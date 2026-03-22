import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import requests
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle

# --- ALAPBEÁLLÍTÁSOK ---
PHONE_PAT = r'(\+?\d{1,2}[/\s-]?)?(\d{2}[/\s-]?)?\d{3}[/\s-]?\d{4}'
ORDER_PAT = r'\d+-[A-Z][A-Z0-9*+]*'

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        return 'DejaVu', 'DejaVu-Bold'
    except Exception as e:
        return 'Helvetica', 'Helvetica-Bold'

def get_etlap_dict(year, week, target_day=None):
    """
    Lekéri az Interfood Excel étlapot és kigyűjti a pénteki (5) és szombati (6) oszlopokat.
    A kulcsok prefixet kapnak (P_ vagy Z_), hogy megkülönböztessük a napokat.
    """
    if not year or not week: return {}
    
    url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    etlap_full = {}
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), header=None)
            
            # 5-ös oszlop: Péntek (F), 6-os oszlop: Szombat (G/Zárónap)
            # A PDF-ben a 'P' jelöli a pénteket, a 'Z' a szombatot
            for day_prefix, col_idx in [("P", 5), ("Z", 6)]:
                for i in range(len(df)):
                    val = str(df.iloc[i, 0])
                    if " - " in val:
                        cikkszam = val.split(" - ")[0].strip().upper()
                        try:
                            # Név kinyerése
                            nev = str(df.iloc[i, col_idx]).strip()
                            # Ár kinyerése a név alatti cellából
                            ar_val = df.iloc[i+1, col_idx]
                            
                            if nev != "nan" and nev != "" and "étlap" not in nev.lower():
                                ar = 0
                                if pd.notnull(ar_val):
                                    try:
                                        ar = int(re.sub(r'\D', '', str(ar_val)))
                                    except: ar = 0
                                
                                # Egyedi kulcs: pl. "P_A" vagy "Z_A"
                                etlap_full[f"{day_prefix}_{cikkszam}"] = {'nev': nev, 'ar': ar}
                        except: continue
            return etlap_full
    except Exception as e:
        st.error(f"Étlap letöltési hiba: {e}")
    return {}

def clean_name_field(text):
    if not text: return ""
    text = re.sub(r'\d{2,}/?\d{3,}-?\d{3,}', '', text)
    text = re.sub(r'\d+-[A-Z0-9*+]+', '', text)
    text = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ\s\-]', '', text)
    return " ".join(text.split()).strip()

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jarat': None}
    with pdfplumber.open(pdf_file) as pdf:
        header_text = pdf.pages[0].extract_text()
        if header_text:
            j_m = re.search(r'(\d{4})\.\s*járat', header_text)
            y_m = re.search(r'Év:\s*(\d{4})', header_text)
            w_m = re.search(r'Hét:\s*(\d{1,2})', header_text)
            d_m = re.search(r'Nap:\s*([^I\n]+)', header_text)
            if j_m: metadata['jarat'] = j_m.group(1)
            if y_m: metadata['year'] = y_m.group(1)
            if w_m: metadata['week'] = w_m.group(1)
            if d_m: metadata['day'] = d_m.group(1).strip()

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
                
                # Itt keressük meg a kódot (pl. P-410511 vagy Z-410511)
                u_code_m = re.search(r'([HKSCPZ][.-][0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                # --- JAVÍTOTT RÉSZ ---
                full_code = u_code_m.group(0) # Megtartjuk a teljes kódot (pl. "P-410511")
                prefix = full_code[0].upper() # Kinyerjük az első betűt (P vagy Z)
                uid = re.sub(r'\D', '', full_code) # Csak a számok az azonosításhoz
                # ---------------------

                b4_words = [w['text'] for w in line_words if 360 <= w['x0'] < 520]
                clean_name = clean_name_field(" ".join(b4_words))
                b3_words = [w['text'] for w in line_words if 140 <= w['x0'] < 360]
                b3_full = " ".join(b3_words)
                addr_m = re.search(r'(\d{4})', b3_full)
                address = b3_full[addr_m.start():].strip() if addr_m else b3_full
                tel_m = re.search(PHONE_PAT, text_ws.replace(" ", ""))
                raw_orders = re.findall(ORDER_PAT, text_ws)
                
                v_o, sq = [], 0
                for o in raw_orders:
                    if any(c.isalpha() for c in o.split('-')[-1]):
                        v_o.append(o)
                        try: sq += int(re.sub(r'\D', '', o.split('-')[0]))
                        except: pass
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, # Elmentjük a P/Z jelölést
                        "ID": f"{prefix}-{uid}", # Az ID tartalmazza a napot is!
                        "Ügyintéző": clean_name, 
                        "Cím": address, 
                        "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), 
                        "Pénz": "0 Ft", 
                        "Összesen": sq
                    })
    return rows, metadata

def merge_data(raw_rows):
    if not raw_rows: return None
    L_DAYS = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p, has_weekend = [], False
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items: 
                o_p.append(f"{L_DAYS.get(pfix, pfix)}: {', '.join(items)}")
                if pfix == 'Z': has_weekend = True
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Hétvégi'] = has_weekend 
        base['Megjegyzés'] = ""
        merged.append(base)
    res = pd.DataFrame(merged)
    if 'Sorrend' not in res.columns:
        res['Sorrend'] = range(1, len(res) + 1)
        res['Sorrend'] = res['Sorrend'].astype(float)
    return res

# --- UI ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta_data' not in st.session_state: st.session_state.meta_data = []
if 'etlap' not in st.session_state: st.session_state.etlap = {}

with st.sidebar:
    st.header("⚙️ Kezelés")
    c_n = st.text_input("Futár Neve", "Szűcs István")
    c_p = st.text_input("Telefonszám", "+36 20 886 8971")
    st.divider()
    up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
    
# ... (a kód eleje változatlan) ...

    if up_files and st.button("🚀 FELDOLGOZÁS"):
        all_rows, all_meta = [], []
        for f in up_files:
            rows, meta = parse_interfood_pdf(f)
            all_rows.extend(rows)
            all_meta.append(meta)
        
        mdf = merge_data(all_rows)
        
        # --- AUTOMATIKUS ÉTLAP KEZELÉS (Most már a gombon belül!) ---
        if all_meta and mdf is not None:
            y, w = all_meta[0]['year'], all_meta[0]['week']
            with st.spinner(f"Pénteki és Szombati étlapok betöltése..."):
                # JAVÍTVA: get_etlap_dict-et hívunk, mert így nevezted el fent!
                etlap = get_etlap_dict(y, w) 
                st.session_state.etlap = etlap
                
                if etlap:
                    for idx, row in mdf.iterrows():
                        total_sum = 0
                        # Az ID-ból (pl. P-410511) kinyerjük az első betűt
                        row_id = str(row.get('ID', ''))
                        day_prefix = row_id[0] if row_id else "P"
                        
                        # A rendelés sztringből kiszedjük a kódokat
                        order_string = str(row['Rendelés_Full'])
                        matches = re.findall(r'(\d+)-([A-Z0-9*+]+)', order_string)
                        
                        for qty, code in matches:
                            clean_c = code.replace('*', '').strip().upper()
                            # Keresés: pl. "P_A" vagy "Z_AK"
                            lookup_key = f"{day_prefix}_{clean_c}"
                            
                            if lookup_key in etlap:
                                total_sum += int(qty) * etlap[lookup_key]['ar']
                        
                        if total_sum > 0:
                            mdf.at[idx, 'Pénz'] = f"{total_sum} Ft"
                
                st.session_state.mdf = mdf
                st.session_state.meta_data = all_meta
                st.rerun()

    # --- CSV Visszatöltés (Visszatéve a helyére) ---
    st.divider()
    st.subheader("2. CSV Visszatöltés")
    up_csv = st.file_uploader("Exportált CSV betöltése", type=['csv'])
    if up_csv and st.button("📥 BETÖLTÉS"):
        try:
            loaded_df = pd.read_csv(up_csv)
            # Biztosítjuk, hogy a Sorrend float legyen a rendezéshez
            if 'Sorrend' in loaded_df.columns:
                loaded_df['Sorrend'] = pd.to_numeric(loaded_df['Sorrend'], errors='coerce').astype(float)
            st.session_state.mdf = loaded_df
            st.success("CSV sikeresen betöltve!")
            st.rerun() # Frissítjük az oldalt a betöltött adatokkal
        except Exception as e:
            st.error(f"Hiba a CSV betöltésekor: {e}")

    # --- INFÓ PANEL ---
    if st.session_state.meta_data:
        st.divider()
        m = st.session_state.meta_data[0]
        st.info(f"📅 {m.get('year')}.{m.get('week')}. hét, {m.get('day')}")
        if not st.session_state.etlap:
            st.warning("⚠️ Az étlap üres!")
        else:
            st.success(f"✅ {len(st.session_state.etlap)} étel betöltve.")
    # ----------------------------------------------------------------

def create_label_pdf(df, fn, ft):
    """Etikett generálás DejaVu fontokkal és marketing szöveggel az üres helyeken"""
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    inner_m = 5.5*mm
    
    # Stílusok az ékezetekhez és a marketing szöveghez
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9, encoding='utf-8')
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1, encoding='utf-8')
    
    # Kiszámoljuk, hány matricahely van összesen (21 matrica / oldal)
    total_slots = math.ceil(len(df) / 21) * 21
    
    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        # 1. HA VAN ÜGYFÉL ADAT (Normál etikett)
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
            if r.get('Hétvégi'):
                p.saveState()
                p.setFillColor(colors.lightgrey)
                p.rect(x + 1*mm, top_y - 8.5*mm, lw - 2*mm, 4.5*mm, fill=1, stroke=0)
                p.restoreState()
            
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{int(r['Sorrend'])}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:28])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm)
            para.drawOn(p, x + inner_m, y + inner_m + 5*mm)
            
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 1*mm, f"{int(r['Összesen'])} db")
            # Vonal rajzolása a futár adatai fölé
            p.line(x + 5*mm, y + 4.5*mm, x + lw - 5*mm, y + 4.5*mm)
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + 2*mm, f"Futár: {fn} | {ft}")

        # 2. HA NINCS TÖBB ÜGYFÉL (Marketing etikett az üres helyekre)
        else:
            # p.setDash(1, 2) # Szaggatott vonal a marketing matrica szélének (opcionális)
            # p.rect(x + 2*mm, y + 2*mm, lw - 4*mm, lh - 4*mm, stroke=1, fill=0)
            p.setDash(1, 0) # Vissza sima vonalra
            
            m_text = (
                f"<font size='10.5' name='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető<br/>területi képviselőnk által</b></font>"
            )
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw - 6*mm, lh - 6*mm)
            # Középre igazítva rajzoljuk ki
            para.drawOn(p, x + (lw - pw) / 2, y + (lh - ph) / 2)
            
    p.save(); buf.seek(0); return buf

# --- 3. RÉSZ: PDF GENERÁLÓK ÉS ADATSZERKESZTŐ ---

def create_manifest_pdf(df, fn, meta_list):
    """Menetterv készítése csoportosítással, oldalszámozással és DejaVu fontokkal"""
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts() # Itt már a DejaVu-t fogja adni
    buf = BytesIO()
    
    # Alsó margót kicsit megnöveljük az oldalszámnak (20mm)
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=20*mm, bottomMargin=20*mm)
    
    # Címek kigyűjtése a csoportosítás ellenőrzéséhez
    all_addresses = df['Cím'].tolist()
    
    jaratok = ", ".join(sorted(list(set([str(m['jarat']) for m in meta_list if m['jarat']]))))
    ev = meta_list[0].get('year', '') if meta_list else ""
    het = meta_list[0].get('week', '') if meta_list else ""
    nap = meta_list[0].get('day', '') if meta_list else ""
    fejlec_text = f"MENETTERV - Járat: {jaratok} | {ev}. év, {het}. hét | {nap}"

    elements = []
    
    # Stílusok definiálása ékezet-kezeléssel
    s_normal = ParagraphStyle('L', fontName=f_reg, fontSize=8, encoding='utf-8')
    s_bold_center = ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1, encoding='utf-8')
    s_order = ParagraphStyle('O', fontName=f_reg, fontSize=7, encoding='utf-8')

    data = [[
        Paragraph("<b>#</b>", s_bold_center),
        Paragraph("<b>NÉV / CÍM / INFÓ</b>", s_bold_center),
        Paragraph("<b>[ ]</b>", s_bold_center),
        Paragraph("<b>PÉNZ</b>", s_bold_center),
        Paragraph("<b>TEL</b>", s_bold_center),
        Paragraph("<b>RENDELÉS</b>", s_bold_center),
        Paragraph("<b>DB</b>", s_bold_center)
    ]]
    
    t_style = [
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
    ]

    for i, (_, r) in enumerate(df.iterrows()):
        # CSOPORTOSÍTÁS: Megnézzük, hányszor szerepel a cím
        is_group = all_addresses.count(r['Cím']) > 1
        group_tag = "<b><font color='blue'>▲ CSOPORT </font></b>" if is_group else ""
        
        note = str(r.get('Megjegyzés', ''))
        note_html = f"<br/><font color='red'><b>{note}</b></font>" if note and note.lower() != 'nan' and note.strip() != "" else ""
        penz = "" if str(r['Pénz']).lower() in ["0 ft", "0", "nan"] else str(r['Pénz'])
        
        data.append([
            f"{int(r['Sorrend'])}",
            Paragraph(f"{group_tag}<b>{r['Ügyintéző']}</b><br/><font size='7'>{r['Cím']}</font>{note_html}", s_normal),
            "[ ]",
            Paragraph(f"<b>{penz}</b>", s_bold_center),
            str(r['Telefon']),
            Paragraph(str(r['Rendelés_Full']), s_order),
            f"{int(r['Összesen'])}"
        ])
        
        # Ha csoport, kap egy nagyon halvány háttérszínt a sor
        if is_group:
            t_style.append(('BACKGROUND', (0, i+1), (-1, i+1), colors.whitesmoke))

    t = Table(data, colWidths=[10*mm, 60*mm, 10*mm, 20*mm, 25*mm, 55*mm, 10*mm], repeatRows=1)
    t.setStyle(TableStyle(t_style))
    elements.append(t)

    # OLDALSZÁMOZÁS ÉS FEJLÉC FUNKCIÓ
    def add_header_footer(canvas, doc):
        canvas.saveState()
        # Fejléc (minden oldalon)
        canvas.setFont(f_bold, 11)
        canvas.drawString(10*mm, A4[1] - 12*mm, fejlec_text)
        canvas.setFont(f_reg, 9)
        canvas.drawRightString(A4[0] - 10*mm, A4[1] - 12*mm, f"Futár: {fn}")
        
        # Oldalszám (minden oldalon alul középen)
        page_num = f"{canvas.getPageNumber()}. oldal"
        canvas.setFont(f_reg, 8)
        canvas.drawCentredString(A4[0]/2, 10*mm, page_num)
        canvas.restoreState()

    # Build indítása a fejléc/lábléc funkcióval
    doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    buf.seek(0); return buf
    
def create_raklista_pdf(df, jarat_info, meta_list):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm)
    etlap = st.session_state.get('etlap', {}) # Ez tartalmazza az Excel sorrendet is
    
    # 1. Összesítés a táblázatból (Rendelés_Full oszlop alapján)
    counts = {}
    for _, r in df.iterrows():
        order_str = str(r.get('Rendelés_Full', ''))
        # Keresünk minden "szám-kód" formátumot (pl. 1-A, 2-BK)
        found = re.findall(r'(\d+)\s*-\s*([A-Z0-9*+]+)', order_str)
        for qty, code in found:
            code = code.strip().upper()
            counts[code] = counts.get(code, 0) + int(qty)
    
    # 2. Táblázat adatok összeállítása az EXCEL SORRENDBEN
    data = [[
        Paragraph("<b>KÓD</b>", ParagraphStyle('C', fontName=f_bold, fontSize=10, alignment=1)), 
        Paragraph("<b>MEGNEVEZÉS</b>", ParagraphStyle('C', fontName=f_bold, fontSize=10, alignment=1)),
        Paragraph("<b>DB</b>", ParagraphStyle('C', fontName=f_bold, fontSize=10, alignment=1))
    ]]
    
    # Az étlap szótár kulcsai az Excel sorrendjében vannak (P_A, P_B, stb.)
    # Végigmegyünk az étlapon, és ha a kód szerepel a PDF-ből kigyűjtött rendelésekben, hozzáadjuk
    processed_codes = set()
    
    for full_key in etlap.keys():
        # A kulcsból (pl. "P_A") kiszedjük a tiszta kódot ("A")
        code_only = full_key.split('_')[1] if '_' in full_key else full_key
        
        if code_only in counts and code_only not in processed_codes:
            nev = etlap[full_key].get('nev', "---")
            darab = counts[code_only]
            
            data.append([
                code_only, 
                Paragraph(nev, ParagraphStyle('L', fontName=f_reg, fontSize=9)), 
                f"{darab} db"
            ])
            processed_codes.add(code_only)

    # 3. Kézi kódok kezelése (amik nincsenek az étlapon, de a PDF-ben benne voltak)
    for code, darab in counts.items():
        if code not in processed_codes:
            data.append([
                code, 
                Paragraph("--- NINCS AZ ÉTLAPON / KÉZI ---", ParagraphStyle('L', fontName=f_reg, fontSize=9)), 
                f"{darab} db"
            ])

    # 4. PDF felépítése
    if len(data) == 1: # Csak a fejléc van benne
        data.append(["-", "Nincs megjeleníthető adat", "0"])

    t = Table(data, colWidths=[30*mm, 125*mm, 25*mm])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,-1), f_reg)
    ]))
    
    elements = []
    elements.append(Paragraph(f"<b>ÖSSZESÍTETT RAKLISTA</b> - {jarat_info}", 
                               ParagraphStyle('Title', fontName=f_bold, fontSize=14, spaceAfter=10)))
    elements.append(t)
    
    doc.build(elements)
    buf.seek(0)
    return buf
    
# --- FŐ PROGRAMFUTÁS ---

if st.session_state.mdf is not None:
    st.subheader("📦 Adatok ellenőrzése")
    
    # A num_rows="dynamic" engedélyezi az új sorok hozzáadását és a törlést
    edited_df = st.data_editor(
        st.session_state.mdf, 
        hide_index=True, 
        use_container_width=True,
        num_rows="dynamic"  # <--- EZT ADD HOZZÁ
    )
    
    if st.button("💾 MÓDOSÍTÁSOK MENTÉSE"):
        st.session_state.mdf = edited_df
        st.success("Mentve! Most már letöltheted a friss PDF-eket.")

    st.divider()
    c1, c2, c3 = st.columns(3)
    j_info = ", ".join(list(set([str(m['jarat']) for m in st.session_state.meta_data if m['jarat']])))
    
    # Letöltések szekció
    c1, c2, c3, c4 = st.columns(4)
    
    j_info = ", ".join(list(set([str(m['jarat']) for m in st.session_state.meta_data if m['jarat']])))
    
    # ETIKETTEK LETÖLTÉSE (create_label_pdf függvényt az előző blokkból használja)
    c1.download_button("📄 ETIKETTEK (PDF)", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf")
    
    # MENETTERV LETÖLTÉSE
    c2.download_button("📋 MENETTERV (PDF)", create_manifest_pdf(edited_df, c_n, st.session_state.meta_data), "menetterv.pdf")
    
    # RAKLISTA LETÖLTÉSE
    c3.download_button(
        label="📦 RAKLISTA (PDF)", 
        data=create_raklista_pdf(edited_df, j_info, st.session_state.meta_data), 
        file_name=f"raklista_{j_info.replace(', ','_')}.pdf"
    )
    
    # CSV EXPORT (hogy később visszatölthető legyen)
    csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
    c4.download_button("📊 CSV EXPORT", csv_data, "szallitasi_lista.csv", "text/csv")

