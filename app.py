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
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# --- 1. FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- 2. ÉTLAP KEZELÉSE (CSILLAGOS KERESÉSSEL) ---
def get_live_menu(year, week, day_name):
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    menu_map = {}
    day_to_col = {'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6}
    target_col = day_to_col.get(day_name, 3) 

    try:
        response = requests.get(excel_url, headers=headers, timeout=15)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), engine='openpyxl')
            current_category = "Egyéb"
            for i in range(len(df)):
                row = df.iloc[i]
                col_a = str(row.iloc[0]).strip()
                if col_a and col_a != 'nan' and " - " in col_a:
                    parts = col_a.split(" - ")
                    code = parts[0].strip()
                    current_category = parts[1].strip()
                    name_on_day = str(row.iloc[target_col]).strip()
                    if name_on_day and name_on_day != 'nan' and len(name_on_day) > 2:
                        try:
                            next_row = df.iloc[i+1]
                            p_str = re.sub(r'[^\d]', '', str(next_row.iloc[target_col]))
                            if p_str:
                                menu_map[code] = {'nev': name_on_day[:60], 'ar': int(p_str), 'kategoria': current_category, 'excel_order': i}
                        except: continue
    except: pass
    return menu_map

# --- 3. PDF PARSER (JÁRATSZÁM KINYERÉSSEL) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {'year': None, 'week': None, 'day': None, 'jarat': "????"}
    with pdfplumber.open(pdf_file) as pdf:
        first_txt = pdf.pages[0].extract_text() or ""
        jarat_m = re.search(r'^(\d+)\.', first_txt)
        if jarat_m: meta['jarat'] = jarat_m.group(1)
        y_m = re.search(r'Év:\s*(\d{4})', first_txt); w_m = re.search(r'Hét:\s*(\d{1,2})', first_txt); d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', first_txt)
        if y_m: meta['year'] = y_m.group(1)
        if w_m: meta['week'] = w_m.group(1)
        if d_m: meta['day'] = d_m.group(1)

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
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                uid = str(u_code_m.group(0).split('-')[-1])
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3
                
                # Pénz keresése a sor alatt
                money_val = "0 Ft"
                idx = sorted(lines.keys()).index(y)
                if idx + 1 < len(lines):
                    next_t = " ".join([w['text'] for w in sorted(lines[sorted(lines.keys())[idx+1]], key=lambda x: x['x0'])])
                    m_match = re.search(r'(-?\s?\d[\d\s]*\s*Ft)', next_t)
                    if m_match: money_val = m_match.group(1).strip()
                
                raw_orders = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({"ID": uid, "Járat": meta['jarat'], "Ügyintéző": clean_name, "Cím": address, "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), "Pénz": money_val, "Összesen": sq})
    return rows, meta

# --- 4. ETIKETT GENERÁLÁS (JAVÍTOTT) ---
def create_label_pdf(df, futar_nev, futar_tel):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
    inner_m = 5.5*mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    
    for i in range(math.ceil(len(df) / 21) * 21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{r['Sorrend']}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            
            p.setFont(f_bold, 6.5)
            p.drawCentredString(x + lw/2, y + inner_m - 1.5*mm, f"[{r['Járat']}] Futár: {futar_nev} | {futar_tel}")
            
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            if m_val != "0":
                p.setFont(f_bold, 10); p.drawString(x + inner_m, y + inner_m + 3*mm, f"FIZET: {r['Pénz']}")
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 3*mm, f"{r['Összesen']} db")
    p.save(); buf.seek(0); return buf

# --- 5. RAKODÁSI LISTA (CSILLAGOS ÉTEL FIX-EL) ---
def create_manifest_pdf(df, futar_nev):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=10)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=10, alignment=1)

    all_codes = []
    for r in df['Rendelés_Full']: 
        all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    
    counts = {}
    for c, code in all_codes: counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    last_cat = None
    for code in sorted(counts.keys()):
        lookup_code = code.replace('*', '')
        info = menu.get(lookup_code, {'nev': 'Ismeretlen étel', 'kategoria': 'Egyéb'})
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<b>{info['kategoria']}</b>", cell_s), ""])
            last_cat = info['kategoria']
        sum_rows.append([Paragraph(f"{code} - {info['nev']}", cell_s), Paragraph(str(counts[code]), head_s)])

    p.setFont(f_bold, 14); p.drawString(15*mm, h - 15*mm, f"RAKODÁSI LISTA - {futar_nev}")
    t = Table([[Paragraph("Étel megnevezése", head_s), Paragraph("DB", head_s)]] + sum_rows, colWidths=[140*mm, 30*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    
    tw, th = t.wrap(w - 30*mm, h - 40*mm)
    t.drawOn(p, 15*mm, h - 25*mm - th)
    p.save(); buf.seek(0); return buf

# --- 6. STREAMLIT UI ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'weights' not in st.session_state: st.session_state.weights = {}
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("👤 Futár Adatok")
    f_n = st.text_input("Név", "Szűcs István")
    f_t = st.text_input("Tel", "+36 20 886 8971")
    st.divider()
    csv_in = st.file_uploader("Előző napi CSV (sorrend)", type="csv")
    if csv_in:
        try:
            imp = pd.read_csv(csv_in)
            st.session_state.weights = dict(zip(imp['ID'].astype(str), imp['Sorrend'].astype(float)))
            if 'Megjegyzés' in imp.columns: st.session_state.notes = dict(zip(imp['ID'].astype(str), imp['Megjegyzés'].fillna("")))
            st.success("✅ Sorrend betöltve!")
        except: st.error("Hiba a CSV-vel")
    
    pdfs = st.file_uploader("Napi PDF-ek", accept_multiple_files=True)
    if pdfs and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in pdfs:
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows)
            if meta['year']: st.session_state.live_menu = get_live_menu(meta['year'], meta['week'], meta['day'])
        
        if raw:
            df = pd.DataFrame(raw)
            merged = []
            for uid, group in df.groupby("ID", sort=False):
                base = group.iloc[0].copy().to_dict()
                base['Rendelés_Full'] = ", ".join(group['Rendelés'].astype(str).tolist())
                base['Összesen'] = group['Összesen'].sum()
                m_list = [int(re.sub(r'[^\d-]', '', str(m)) or 0) for m in group['Pénz'].tolist()]
                base['Pénz'] = f"{sum(m_list)} Ft"
                uid_s = str(uid).strip()
                base['Sorrend'] = st.session_state.weights.get(uid_s, 999.0)
                base['Megjegyzés'] = st.session_state.notes.get(uid_s, "")
                merged.append(base)
            st.session_state.mdf = pd.DataFrame(merged).sort_values(['Sorrend', 'Járat'])
            st.rerun()

if st.session_state.mdf is not None:
    st.subheader("📍 Menetlevél és Sorrend")
    cols = ['Sorrend', 'ID', 'Járat', 'Ügyintéző', 'Cím', 'Rendelés_Full', 'Összesen', 'Pénz', 'Megjegyzés']
    edited = st.data_editor(st.session_state.mdf[cols], hide_index=True, use_container_width=True,
                           column_config={"Sorrend": st.column_config.NumberColumn(format="%.1f"), "ID": st.column_config.TextColumn(disabled=True)})
    
    if st.button("✅ MENTÉS ÉS ÚJRASORSZÁMOZÁS"):
        final = edited.sort_values('Sorrend').reset_index(drop=True)
        final['Sorrend'] = range(1, len(final) + 1)
        for _, r in final.iterrows():
            st.session_state.weights[str(r['ID'])] = r['Sorrend']
            st.session_state.notes[str(r['ID'])] = r['Megjegyzés']
        st.session_state.mdf = final
        st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1: st.download_button("📄 ETIKETTEK", create_label_pdf(st.session_state.mdf, f_n, f_t), "etikett.pdf")
    with c2: st.download_button("📋 RAKLISTA", create_manifest_pdf(st.session_state.mdf, f_n), "raklista.pdf")
    with c3: st.download_button("📥 CSV EXPORT", st.session_state.mdf.to_csv(index=False).encode('utf-8-sig'), "mentes.csv")
