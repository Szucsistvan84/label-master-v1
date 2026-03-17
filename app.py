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
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# --- FONT ÉS ALAPOK ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

# --- PDF PARSER ---
def parse_interfood_pdf(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*\s*Ft)' 
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w); break
                else: lines[y] = [w]
            
            sorted_y = sorted(lines.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                prefix = u_code_m.group(0).split('-')[0]
                uid = u_code_m.group(0).split('-')[-1]
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                
                money_val = "0 Ft"
                if i + 1 < len(sorted_y):
                    next_line_text = " ".join([w['text'] for w in sorted(lines[sorted_y[i+1]], key=lambda x: x['x0'])])
                    m_match = re.search(money_pat, next_line_text)
                    if m_match: money_val = m_match.group(1).strip()

                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": money_val, "Összesen": sq
                    })
    return rows

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        has_weekend = False
        m_list = []

        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items: 
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
                if pfix == 'Z': has_weekend = True
            
            for m_str in day_group['Pénz']:
                num = int(re.sub(r'[^\d-]', '', str(m_str)) or 0)
                if num != 0: m_list.append(num)

        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Hétvégi'] = has_weekend 

        if not m_list:
            total_m = 0
        elif len(set(m_list)) == 1:
            total_m = m_list[0]
        else:
            total_m = sum(m_list)
        
        base['Pénz'] = f"{total_m} Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base) # <--- Fontos, hogy ez a ciklus végén legyen, de a groupby-on belül!
    
    res = pd.DataFrame(merged)
    # Csak azokat tartsuk meg, ahol van rendes ID, hogy ne legyenek "None" sorok
    res = res.dropna(subset=['ID'])

    if 'weights' in st.session_state and st.session_state.weights:
        res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999.0).astype(float)
    else:
        res['Sorrend'] = range(1, len(res) + 1)
        res['Sorrend'] = res['Sorrend'].astype(float)
    
    cols = ['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Megjegyzés', 'Pénz', 'Rendelés_Full', 'Összesen', 'Hétvégi']
    existing_cols = [c for c in cols if c in res.columns]
    return res[existing_cols].sort_values('Sorrend')
    
# --- PDF GENERÁLÁS FÜGGVÉNYEK ---
def create_label_pdf(df, fn, ft):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
    inner_m = 5.5*mm
    
    # Stílusok
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    note_s = ParagraphStyle('Note', fontName=f_bold, fontSize=7, leading=8, textColor=colors.red)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1) # Középre zárt a reklámnak

    # Kiszámoljuk, összesen hány matricahely van (hogy az ív végéig menjen a reklám)
    total_slots = math.ceil(len(df) / 21) * 21
    
    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: 
            p.showPage()
            
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        # --- 1. ESET: VAN ÜGYFÉL ADAT ---
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
            # Szürke fejléc szombatiaknak
            if r.get('Hétvégi', False):
                p.setFillColorRGB(0.9, 0.9, 0.9)
                p.rect(x + 1*mm, top_y - 4*mm, lw - 2*mm, 5*mm, fill=1, stroke=0)
                p.setFillColor(colors.black)

            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{i+1}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            if str(r['Megjegyzés']).strip() and str(r['Megjegyzés']) != 'None':
                pn = Paragraph(f"<b>INFÓ: {r['Megjegyzés']}</b>", note_s)
                pn.wrap(lw - 2*inner_m, 5*mm); pn.drawOn(p, x + inner_m, top_y - 16*mm)

            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 8*mm)
            
            base_y = y + inner_m 
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            if m_val != "0" and m_val != "":
                p.setFont(f_bold, 10); p.drawString(x + inner_m, base_y + 4*mm, f"FIZET: {r['Pénz']}")
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, base_y + 4*mm, f"{r['Összesen']} db")
            
            p.setStrokeColor(colors.black); p.setLineWidth(0.2)
            p.line(x + inner_m, base_y + 2.5*mm, x + lw - inner_m, base_y + 2.5*mm)
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, base_y - 1*mm, f"Futár: {fn} | {ft}")

        # --- 2. ESET: ÜRES HELY (MARKETING) ---
        else:
            m_text = (f"<font size='11'><b>15% kedvezmény* 3 hétig</b></font><br/>"
                      f"Új Ügyfeleinknek!<br/><br/>"
                      f"<b>Rendelés leadás:</b><br/>"
                      f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                      f"<font size='5.5'><b>* a kedvezmény területi képviselőnk által érvényesíthető telefonon leadott rendelésekre</b></font>")
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw - 2*inner_m, lh - 2*inner_m)
            para.drawOn(p, x + (lw - pw) / 2, y + (lh - ph) / 2)

    p.save(); buf.seek(0); return buf
    
# (A create_manifest_pdf-et is hasonlóan kiegészítettem a Megjegyzéssel)
import datetime

def create_manifest_pdf(df, fn):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    date_header = f"{tomorrow.strftime('%Y-%m-%d')}" 
    
    def clean_addr(addr):
        return str(addr).strip().lower().replace('.', '').replace('  ', ' ')

    cleaned_addresses = [clean_addr(a) for a in df['Cím'].tolist()]
    
    rows_per_page = 25 
    total_p = math.ceil(len(df) / rows_per_page)
    
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=9, leading=10)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=7, leading=8)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=8, alignment=1)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 11)
        p.drawString(10*mm, h - 12*mm, f"MENETTERV - {fn}")
        p.drawRightString(w - 10*mm, h - 12*mm, f"{p_idx + 1}/{total_p}. oldal")
        
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM / INFÓ</b>", head_s), 
                  Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>TEL</b>", head_s), 
                  Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), 
                  Paragraph("<b>DB</b>", head_s)]]
        
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        t_style = [('GRID', (0,0), (-1,-1), 0.5, colors.black), 
                   ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                   ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]

        for i, (_, r) in enumerate(subset.iterrows()):
            curr_cleaned = clean_addr(r['Cím'])
            group_count = cleaned_addresses.count(curr_cleaned)
            is_group = group_count > 1
            
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            m_disp = f"<b>{r['Pénz']}</b>" if m_val != "0" and m_val != "" else ""
            
            warning = f"▲ <b>CSOPORT ({group_count})</b><br/>" if is_group else ""
            
            data.append([f"#{p_idx*rows_per_page+i+1}", 
                         Paragraph(f"{warning}{r['Ügyintéző']}<br/><font size='7'>{r['Cím']}</font>", name_s),
                         "[ ]", Paragraph(str(r['Telefon']), cell_s), Paragraph(m_disp, cell_s),
                         Paragraph(str(r['Rendelés_Full']), cell_s), r['Összesen']])
            
            if is_group:
                t_style.append(('BACKGROUND', (1, i+1), (1, i+1), colors.Color(0.92, 0.92, 0.92)))
                t_style.append(('BOX', (1, i+1), (1, i+1), 1.2, colors.black))
        
        # MÓDOSÍTOTT SZÉLESSÉGEK: Az első oszlop 11mm, a második 64mm lett
        t = Table(data, colWidths=[11*mm, 64*mm, 9*mm, 25*mm, 22*mm, 54*mm, 10*mm])
        t.setStyle(TableStyle(t_style))
        t.wrapOn(p, 7*mm, 20*mm); w_t, h_t = t.wrap(w - 14*mm, h - 35*mm)
        t.drawOn(p, 7*mm, h - 22*mm - h_t)
        p.showPage()

    p.save(); buf.seek(0)
    return buf

# --- UI ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'weights' not in st.session_state: st.session_state.weights = {}
if 'notes' not in st.session_state: st.session_state.notes = {}

with st.sidebar:
    st.header("👤 Futár Adatok")
    c_n = st.text_input("Futár neve", "Szűcs István")
    c_p = st.text_input("Telefonszáma", "+36 20 886 8971")
    st.divider()
    st.header("💾 1. Súlyozás & Megjegyzések")
    old_csv = st.file_uploader("CSV Betöltése", type="csv")
    if old_csv:
        db_df = pd.read_csv(old_csv)
        st.session_state.weights = dict(zip(db_df['ID'].astype(str), db_df['Sorrend'].astype(float)))
        if 'Megjegyzés' in db_df.columns:
            st.session_state.notes = dict(zip(db_df['ID'].astype(str), db_df['Megjegyzés'].fillna("")))
        st.success("Adatok betöltve!")

    st.header("📄 2. Napi PDF-ek")
    up_files = st.file_uploader("Feltöltés", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in up_files: raw.extend(parse_interfood_pdf(f))
        if raw:
            st.session_state.mdf = merge_data(raw)
            st.rerun()

if st.session_state.mdf is not None:
    st.header("🚛 Sorrend és Megjegyzések")
    edited_df = st.data_editor(
        st.session_state.mdf, 
        hide_index=True, 
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Sorrend": st.column_config.NumberColumn(
                "Sorrend",
                help="Használj tizedespontot (pl. 1.5) a sorok közé szúráshoz!",
                min_value=0,
                step=0.1,  # Ez engedélyezi a tizedeseket!
                format="%.1f"
            ),
            "ID": st.column_config.TextColumn("ID", disabled=True),
            "Hétvégi": None  # Elrejtjük a technikai oszlopot
        }
    )
    
    if st.button("✅ RÖGZÍTÉS ÉS ÚJRARAKÁS"):
        temp_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
        temp_df['Sorrend'] = range(1, len(temp_df) + 1)
        st.session_state.weights = dict(zip(temp_df['ID'].astype(str), temp_df['Sorrend']))
        st.session_state.notes = dict(zip(temp_df['ID'].astype(str), temp_df['Megjegyzés'].fillna("")))
        st.session_state.mdf = temp_df
        st.rerun()
            
    csv_data = edited_df[['ID', 'Sorrend', 'Megjegyzés']].to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 ADATOK MENTÉSE (CSV)", csv_data, "interfood_adatok.csv", use_container_width=True)

    st.divider()
    cp1, cp2 = st.columns(2)
    with cp1: st.download_button("📥 ETIKETTEK", create_label_pdf(st.session_state.mdf, c_n, c_p), "etikettek.pdf", use_container_width=True)
    with cp2: st.download_button("📋 MENETTERV", create_manifest_pdf(st.session_state.mdf, c_n), "menetterv.pdf", use_container_width=True)










