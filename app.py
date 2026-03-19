import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Spacer, Paragraph, Table, TableStyle

# --- 1. ALAPFUNKCIÓK & BETŰTÍPUSOK ---

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def clean_addr(addr):
    if not addr: return ""
    return str(addr).strip().lower().replace('.', '').replace('  ', ' ')

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

# --- 2. PDF PARSER ---

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jarat': None}
    
    with pdfplumber.open(pdf_file) as pdf:
        # FEJLÉC KERESÉSE - Csak az első oldal tetejét nézzük
        first_page = pdf.pages[0]
        header_text = first_page.extract_text()
        
        if header_text:
            # Minták: "4002. járat", "Év: 2026", "Hét: 12", "Nap: Péntek, Szombat"
            j_m = re.search(r'(\d{4})\.\s*járat', header_text)
            y_m = re.search(r'Év:\s*(\d{4})', header_text)
            w_m = re.search(r'Hét:\s*(\d{1,2})', header_text)
            # A napot az "InterFood" szóig olvassuk ki, hogy ne vigyen be szemetet
            d_m = re.search(r'Nap:\s*([^I\n]+)', header_text)
            
            if j_m: metadata['jarat'] = j_m.group(1)
            if y_m: metadata['year'] = y_m.group(1)
            if w_m: metadata['week'] = w_m.group(1)
            if d_m: metadata['day'] = d_m.group(1).strip()

        # Innentől jön a többi kódod (words, lines, stb.), ami változatlan marad...

        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines:
                    if abs(y - ey) < 3: lines[ey].append(w); break
                else: lines[y] = [w]
            
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ][.-][0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                uid = re.sub(r'\D', '', u_code_m.group(0))
                prefix = u_code_m.group(0)[0]
                b3 = " ".join([w['text'] for w in line_words if 140 <= w['x0'] < 360])
                b4 = " ".join([w['text'] for w in line_words if 360 <= w['x0'] < 500])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0]))
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": address, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": "0 Ft", "Összesen": sq
                    })
    return rows, metadata

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p, has_weekend = [], False
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items: 
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
                if pfix == 'Z': has_weekend = True
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Hétvégi'] = has_weekend 
        base['Megjegyzés'] = ""
        merged.append(base)
    res = pd.DataFrame(merged)
    res['Sorrend'] = range(1, len(res) + 1)
    res['Sorrend'] = res['Sorrend'].astype(float)
    return res

# --- 3. PDF GENERÁLÓK (ETIKETT, MENETTERV, RAKLISTA) ---
# (Ezek a függvények a korábbival megegyeznek, de a kód teljessége miatt itt vannak)

def create_label_pdf(df, fn, ft):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    inner_m = 5.5*mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    # Piros, feltűnő stílus a megjegyzésnek
    note_s = ParagraphStyle('Note', fontName=f_bold, fontSize=7, leading=8, textColor=colors.red)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1)
    
    total_labels = math.ceil(len(df) / 21) * 21
    for i in range(total_labels):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
            # Hétvégi jelzés (szürke háttér a név alatt)
            if r.get('Hétvégi') == True:
                p.saveState()
                p.setFillColor(colors.lightgrey)
                p.rect(x + 1*mm, top_y - 8.5*mm, lw - 2*mm, 4.5*mm, fill=1, stroke=0)
                p.restoreState()
            
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{int(r['Sorrend'])}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            # --- JAVÍTOTT MEGJEGYZÉS RÉSZ ---
            msg = str(r.get('Megjegyzés', ''))
            # Csak akkor írjuk ki, ha nem üres, nem 'nan' és nem csak szóköz
            if msg.lower() != 'nan' and msg.strip() != '':
                pn = Paragraph(f"<b>INFÓ: {msg}</b>", note_s)
                pn.wrap(lw - 2*inner_m, 5*mm)
                pn.drawOn(p, x + inner_m, top_y - 17*mm)
            # -------------------------------

            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm)
            para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 3*mm, f"{r['Összesen']} db")
            p.setLineWidth(0.2); p.line(x + inner_m, y + inner_m + 2*mm, x + lw - inner_m, y + inner_m + 2*mm)
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + inner_m - 1.5*mm, f"Futár: {fn} | {ft}")
        else:
            # Üres etikettek (reklámhely)
            m_text = f"<font size='10.5'><b>15% kedvezmény* 3 hétig</b></font><br/><b>Rendelés: {fn}</b>, <b>{ft}</b>"
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw - 6*mm, lh - 6*mm)
            para.drawOn(p, x + (lw - pw)/2, y + (lh - ph)/2)
            
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn, meta_list):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    
    # topMargin csökkentve 15mm-re, hogy közelebb legyen a fejléchez a táblázat
    doc = SimpleDocTemplate(buf, pagesize=A4, 
                            rightMargin=10*mm, leftMargin=10*mm, 
                            topMargin=15*mm, bottomMargin=15*mm)
    
    # Fejléc adatok összeállítása
    jaratok = ", ".join(sorted(list(set([str(m['jarat']) for m in meta_list if m['jarat']]))))
    ev = meta_list[0].get('year', '') if meta_list else ""
    het = meta_list[0].get('week', '') if meta_list else ""
    nap = meta_list[0].get('day', '') if meta_list else ""
    fejlec_szoveg = f"MENETTERV - Járat: {jaratok} | {ev}. év, {het}. hét | {nap}"

    cleaned_addrs = [clean_addr(a) for a in df['Cím'].tolist()]
    
    # Stílusok
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=8, alignment=1)
    name_s = ParagraphStyle('Name', fontName=f_reg, fontSize=8, leading=10)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=7, leading=9)

    elements = []

    # Táblázat adatainak előkészítése
    data = [[
        Paragraph("<b>#</b>", head_s), 
        Paragraph("<b>NÉV / CÍM / INFÓ</b>", head_s), 
        Paragraph("<b>[ ]</b>", head_s), 
        Paragraph("<b>PÉNZ</b>", head_s), 
        Paragraph("<b>TEL</b>", head_s), 
        Paragraph("<b>RENDELÉS</b>", head_s), 
        Paragraph("<b>DB</b>", head_s)
    ]]
    
    t_style = [
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
    ]

    for i, (_, r) in enumerate(df.iterrows()):
        curr_addr = clean_addr(r['Cím'])
        g_count = cleaned_addrs.count(curr_addr)
        is_group = g_count > 1
        
        # Üres adatok kezelése
        raw_note = str(r.get('Megjegyzés', ''))
        note_text = f"<br/><font color='red'><b>{raw_note}</b></font>" if raw_note.lower() != 'nan' and raw_note.strip() != '' else ""
        penz = "" if str(r['Pénz']).strip().lower() in ["0 ft", "0", "0ft", "nan"] else str(r['Pénz'])
        tel = str(r.get('Telefon', '')) if str(r.get('Telefon', '')).lower() != 'nan' else ""
        
        # NÉV FÉLKÖVÉRRE ÁLLÍTÁSA
        warn = "▲ CSOPORT " if is_group else ""
        ugyfel_sor = f"<b>{warn}{r['Ügyintéző']}</b>"
        
        data.append([
            f"{int(r['Sorrend'])}", 
            Paragraph(f"{ugyfel_sor}<br/><font size='7'>{r['Cím']}</font>{note_text}", name_s), 
            "[ ]", 
            Paragraph(f"<b>{penz}</b>", head_s),
            Paragraph(tel, cell_s), 
            Paragraph(str(r['Rendelés_Full']), cell_s), 
            f"{int(r['Összesen'])}"
        ])
        
        if is_group:
            idx = i + 1
            t_style.append(('BACKGROUND', (0, idx), (-1, idx), colors.lightgrey))
            t_style.append(('LINEABOVE', (0, idx), (-1, idx), 1.2, colors.black))
            t_style.append(('LINEBELOW', (0, idx), (-1, idx), 1.2, colors.black))

    # Táblázat létrehozása tördeléssel
    t = Table(data, colWidths=[10*mm, 60*mm, 10*mm, 20*mm, 25*mm, 55*mm, 10*mm], repeatRows=1)
    t.setStyle(TableStyle(t_style))
    elements.append(t)

    # Fejléc és oldalszám rajzolása minden lapra
    def on_page(canvas, doc):
        canvas.saveState()
        # Fejléc - feljebb tolva a margóhoz képest
        canvas.setFont(f_bold, 11)
        canvas.drawString(10*mm, A4[1] - 10*mm, fejlec_szoveg)
        canvas.setFont(f_reg, 9)
        canvas.drawRightString(A4[0] - 10*mm, A4[1] - 10*mm, f"Futár: {fn}")
        
        # Oldalszám - fix pozíció alul
        canvas.setFont(f_reg, 8)
        page_num = canvas.getPageNumber()
        canvas.drawCentredString(A4[0]/2, 8*mm, f"{page_num}. oldal")
        canvas.restoreState()

    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    return buf

def create_raklista_pdf(df, jarat_info, meta_list=None):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    
    # A raklista általában rövidebb, de használjunk itt is Template-et a biztonság kedvéért
    doc = SimpleDocTemplate(buf, pagesize=A4, 
                            rightMargin=20*mm, leftMargin=20*mm, 
                            topMargin=20*mm, bottomMargin=15*mm)
    
    # Adatok a fejléchez
    ev = meta_list[0].get('year', '') if meta_list else ""
    het = meta_list[0].get('week', '') if meta_list else ""
    nap = meta_list[0].get('day', '') if meta_list else ""
    
    title_text = f"RAKODÁSI LISTA - Járat: {jarat_info}"
    sub_title = f"{ev}. év, {het}. hét | {nap}"

    # Összesítés készítése
    all_codes = []
    # Végigmegyünk a Rendelés_Full oszlopon és kinyerjük a "szám-kód" párosokat
    for r in df['Rendelés_Full']:
        # Keresünk minden "1-R2K" vagy "2-L3" típusú mintát
        found = re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r))
        all_codes.extend(found)
    
    counts = {}
    for count, code in all_codes:
        counts[code] = counts.get(code, 0) + int(count)
    
    # Táblázat adatok összeállítása (ABC sorrendben a kódok szerint)
    data = [[Paragraph("<b>ÉTEL KÓD</b>", ParagraphStyle('H', fontName=f_bold, fontSize=12, alignment=1)), 
             Paragraph("<b>ÖSSZESEN</b>", ParagraphStyle('H', fontName=f_bold, fontSize=12, alignment=1))]]
    
    total_items = 0
    for code in sorted(counts.keys()):
        qty = counts[code]
        total_items += qty
        data.append([
            Paragraph(code, ParagraphStyle('C', fontName=f_bold, fontSize=11, alignment=1)), 
            Paragraph(f"<b>{qty} db</b>", ParagraphStyle('Q', fontName=f_bold, fontSize=12, alignment=1))
        ])
    
    # Összesítő sor a végére
    data.append([
        Paragraph("<b>MINDÖSSZESEN:</b>", ParagraphStyle('T', fontName=f_bold, fontSize=12, alignment=2)),
        Paragraph(f"<b>{total_items} db</b>", ParagraphStyle('T', fontName=f_bold, fontSize=12, alignment=1))
    ])

    t = Table(data, colWidths=[60*mm, 40*mm])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('BACKGROUND', (0,-1), (-1,-1), colors.lightgrey), # Utolsó sor is szürke
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 5*mm),
        ('RIGHTPADDING', (0,0), (-1,-1), 5*mm),
        ('TOPPADDING', (0,0), (-1,-1), 3*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3*mm),
    ]))

    elements = [t]

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_bold, 14)
        canvas.drawString(20*mm, A4[1] - 15*mm, title_text)
        canvas.setFont(f_reg, 10)
        canvas.drawString(20*mm, A4[1] - 20*mm, sub_title)
        canvas.restoreState()

    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    return buf

# --- 4. UI ---

st.set_page_config(page_title="Interfood Logisztika Pro", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta_data' not in st.session_state: st.session_state.meta_data = []

with st.sidebar:
    st.header("⚙️ Beállítások")
    c_n = st.text_input("Futár Neve", "Szűcs István")
    c_p = st.text_input("Telefonszám", "+36 20 886 8971")
    
    st.divider()
    st.subheader("1. Új PDF-ek feldolgozása")
    up_files = st.file_uploader("PDF menettervek feltöltése", accept_multiple_files=True, type=['pdf'])
    if up_files and st.button("📊 ADATOK BEOLVASÁSA"):
        raw, metas = [], []
        for f in up_files: 
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows); metas.append(meta)
        if raw:
            st.session_state.mdf = merge_data(raw)
            st.session_state.meta_data = metas
            st.rerun()

    st.divider()
    st.subheader("2. Mentett sorrend visszatöltése")
    up_csv = st.file_uploader("Korábbi export.csv visszatöltése", type=['csv'])
    if up_csv and st.button("📥 SORREND HELYREÁLLÍTÁSA"):
        try:
            restored_df = pd.read_csv(up_csv)
            if 'Sorrend' in restored_df.columns:
                restored_df['Sorrend'] = restored_df['Sorrend'].astype(float)
                restored_df = restored_df.sort_values('Sorrend')
            st.session_state.mdf = restored_df
            st.success("Sorrend sikeresen visszatöltve!")
            st.rerun()
        except Exception as e:
            st.error(f"Hiba: {e}")

if st.session_state.mdf is not None:
    st.session_state.mdf = st.session_state.mdf.sort_values('Sorrend')
    edited_df = st.data_editor(
        st.session_state.mdf, hide_index=True, use_container_width=True,
        column_config={
            "Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f", step=0.1),
            "Pénz": st.column_config.TextColumn("Beszedendő Pénz")
        }
    )
    if st.button("💾 SORREND ÉS MÓDOSÍTÁSOK MENTÉSE"):
        new_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
        new_df['Sorrend'] = range(1, len(new_df) + 1)
        new_df['Sorrend'] = new_df['Sorrend'].astype(float)
        st.session_state.mdf = new_df
        st.success("Minden módosítás elmentve!")
        st.rerun()
    
    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    jarat_str = ", ".join(sorted(list(set([m['jarat'] for m in st.session_state.meta_data if m['jarat']]))))
    c1.download_button("📄 ETIKETTEK (PDF)", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf")
    c2.download_button("📋 MENETTERV (PDF)", create_manifest_pdf(edited_df, c_n, st.session_state.meta_data), "menetterv.pdf")
    c3.download_button("📦 RAKLISTA (PDF)", create_raklista_pdf(edited_df, jarat_str), "raklista.pdf")
    c4.download_button("📊 CSV EXPORT", edited_df.to_csv(index=False).encode('utf-8-sig'), "export.csv", "text/csv")
