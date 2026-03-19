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
import requests

# --- 1. ALAPOK ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

# --- 2. ONLINE ÉTLAP (HIBATŰRŐ) ---
def get_live_menu_data(meta_list):
    menu_map = {}
    if not meta_list: return menu_map
    year, week = None, None
    for m in meta_list:
        if m.get('year') and m.get('week'):
            year, week = m['year'], m['week']; break
    if not year or not week: return menu_map
    url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    try:
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            df = pd.read_excel(BytesIO(resp.content), engine='openpyxl')
            for i in range(len(df)):
                cell = str(df.iloc[i, 0])
                if " - " in cell:
                    parts = cell.split(" - ")
                    code, name = parts[0].strip(), parts[1].strip()
                    price = 0
                    if i + 1 < len(df):
                        for j in range(1, 7):
                            val = re.sub(r'\D', '', str(df.iloc[i+1, j]))
                            if val: price = int(val); break
                    menu_map[code] = {"nev": name, "ar": price}
    except: pass
    return menu_map

# --- 3. A STABIL PDF BEOLVASÓ (VISSZAÁLLÍTVA) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jarat': None}
    # Ez a regex a kulcs, ami az ételeket keresi (pl: 1-E2, 2-R1*)
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            
            # Csak óvatosan keressük a fejlécet, ha nincs meg
            if not metadata['jarat']:
                jm = re.search(r'(\d{4})\.\s*járat', text)
                if jm: metadata['jarat'] = jm.group(1)
            if not metadata['year']:
                ym = re.search(r'Év:\s*(\d{4})', text)
                if ym: metadata['year'] = ym.group(1)
            if not metadata['week']:
                wm = re.search(r'Hét:\s*(\d{1,2})', text)
                if wm: metadata['week'] = wm.group(1)
            if not metadata['day']:
                dm = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű, ]+)', text)
                if dm: metadata['day'] = dm.group(1).split('InterFood')[0].strip()

            table = page.extract_table()
            if not table: continue
            for row in table:
                if not row or len(row) < 5: continue
                # Ügyfél ID keresése (pl: P-123456)
                u_m = re.search(r'([HKSCPZ])-(\d{5,7})', str(row[1]))
                if u_m:
                    pfix, uid = u_m.groups()
                    name = row[2].split('\n')[0] if row[2] else "Ismeretlen"
                    addr = row[1].split('\n')[-1] if row[1] else ""
                    
                    # Rendelések kinyerése - VISSZAÁLLÍTVA A MŰKÖDŐ LOGIKA
                    raw_order_text = str(row[4]) if len(row) > 4 else ""
                    orders = re.findall(order_pat, raw_order_text)
                    
                    # Darabszám összegzése
                    sq = 0
                    for o in orders:
                        try: sq += int(o.split('-')[0])
                        except: pass

                    rows.append({
                        "ID": uid, 
                        "Prefix": pfix, 
                        "Ügyintéző": name, 
                        "Cím": addr, 
                        "Rendelés": ", ".join(orders), 
                        "Pénz": "0 Ft", 
                        "Összesen": sq
                    })
    return rows, metadata

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items and items[0]: # Csak ha van benne kód
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    res = pd.DataFrame(merged)
    res['Sorrend'] = range(1, len(res) + 1)
    return res

# --- 4. PDF GENERÁTOROK ---
def create_manifest_pdf(df, fn, meta_list):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    j_str = ", ".join(list(set([str(m['jarat']) for m in meta_list if m.get('jarat')])))
    dat = meta_list[0].get('day', "") if meta_list else ""
    
    rows_p_p = 25
    pages = math.ceil(len(df) / rows_p_p)
    # Javított stíluskezelés
    head_s = ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)
    cell_s = ParagraphStyle('C', fontName=f_reg, fontSize=7, leading=8)

    for p_idx in range(pages):
        p.setFont(f_bold, 10); p.drawString(10*mm, h-10*mm, f"MENETTERV - Járat: {j_str} | {dat}")
        p.setFont(f_reg, 8); p.drawRightString(w-10*mm, h-10*mm, f"Futár: {fn} | {p_idx+1}/{pages}")
        
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM</b>", head_s), Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        subset = df.iloc[p_idx*rows_p_p : (p_idx+1)*rows_p_p]
        for _, r in subset.iterrows():
            p_disp = "" if str(r['Pénz']).strip().lower() in ["0 ft", "0", "nan", ""] else str(r['Pénz'])
            data.append([str(int(r['Sorrend'])), Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", cell_s), "[ ]", Paragraph(f"<b>{p_disp}</b>", head_s), Paragraph(str(r.get('Rendelés_Full','')), cell_s), str(r['Összesen'])])
        
        t = Table(data, colWidths=[10*mm, 70*mm, 8*mm, 22*mm, 70*mm, 10*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.3, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        t.wrapOn(p, 10*mm, 15*mm); t.drawOn(p, 10*mm, h - 20*mm - (len(data)*9*mm))
        p.showPage()
    p.save(); buf.seek(0); return buf

def create_raklista_pdf(df, jarat, menu):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    # Kritikus javítás: Stílus objektumok explicit definiálása
    h_style = ParagraphStyle(name='RakHead', fontName=f_bold, fontSize=10, alignment=1)
    c_style = ParagraphStyle(name='RakCell', fontName=f_reg, fontSize=9)
    
    items = []
    col = 'Rendelés_Full' if 'Rendelés_Full' in df.columns else 'Rendelés'
    for r in df[col]: items.extend(re.findall(r'(\d+)-([A-Z][A-Z0-9*+]*)', str(r)))
    
    counts = {}; rev = 0
    for c, code in items: counts[code] = counts.get(code, 0) + int(c)
    
    data_rows = [[Paragraph("<b>KÓD</b>", h_style), Paragraph("<b>NÉV</b>", h_style), Paragraph("<b>DB</b>", h_style), Paragraph("<b>ÁR</b>", h_style), Paragraph("<b>ÖSSZ</b>", h_style)]]
    for code in sorted(counts.keys()):
        db = counts[code]
        info = menu.get(code, {"nev": "Ismeretlen étel", "ar": 0})
        sub = db * info['ar']; rev += sub
        data_rows.append([
            Paragraph(code, c_style), 
            Paragraph(info['nev'][:45], c_style), 
            Paragraph(f"{db} db", h_style), 
            Paragraph(f"{info['ar']} Ft", c_style), 
            Paragraph(f"{sub} Ft", h_style)
        ])
    
    rows_p_p = 30
    for i in range(0, len(data_rows), rows_p_p):
        p.setFont(f_bold, 12); p.drawString(10*mm, h-15*mm, f"RAKODÁSI LISTA - Járat: {jarat}")
        subset = data_rows[i:i+rows_p_p]
        if i > 0: subset = [data_rows[0]] + subset
        t = Table(subset, colWidths=[20*mm, 80*mm, 20*mm, 30*mm, 35*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        t.wrapOn(p, 10*mm, 30*mm); t.drawOn(p, 10*mm, h - 30*mm - (len(subset)*8*mm))
        if i + rows_p_p >= len(data_rows):
            curr_y = h - 45*mm - (len(subset)*8*mm)
            p.setFont(f_bold, 11); p.drawString(120*mm, curr_y, f"NAPI FORGALOM: {rev} Ft")
        p.showPage()
    p.save(); buf.seek(0); return buf

# --- 5. STREAMLIT UI ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta' not in st.session_state: st.session_state.meta = []

with st.sidebar:
    st.header("📥 Adatok")
    pdf_files = st.file_uploader("1. PDF feltöltés", accept_multiple_files=True, type=['pdf'])
    if pdf_files and st.button("🚀 Feldolgozás"):
        raw, meta = [], []
        for f in pdf_files:
            r, m = parse_interfood_pdf(f)
            raw.extend(r); meta.append(m)
        if raw:
            st.session_state.mdf = merge_data(raw)
            st.session_state.meta = meta
            st.rerun()
    st.divider()
    csv_file = st.file_uploader("2. CSV betöltés", type=['csv'])
    if csv_file: st.session_state.mdf = pd.read_csv(csv_file)
    st.divider()
    fn = st.text_input("Futár", "Szűcs István")

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    if st.button("💾 Mentés"):
        new_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
        new_df['Sorrend'] = range(1, len(new_df)+1)
        st.session_state.mdf = new_df; st.rerun()
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    j_str = ", ".join(list(set([str(m.get('jarat','?')) for m in st.session_state.meta])))
    menu = get_live_menu_data(st.session_state.meta)
    
    c1.download_button("📋 MENETTERV", create_manifest_pdf(edited_df, fn, st.session_state.meta), "menetterv.pdf")
    c2.download_button("📦 RAKLISTA", create_raklista_pdf(edited_df, j_str, menu), "raklista.pdf")
    c3.download_button("📊 CSV EXPORT", edited_df.to_csv(index=False).encode('utf-8-sig'), "adatok.csv")
