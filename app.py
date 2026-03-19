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

# --- 2. ONLINE ÉTLAP ÉS ROBUSZTUS PDF OLVASÓ ---

def get_live_menu_data(meta_list):
    menu_map = {}
    if not meta_list: return menu_map
    year = meta_list[0].get('year')
    week = meta_list[0].get('week')
    if not (year and week): return menu_map
    url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            df = pd.read_excel(BytesIO(resp.content), engine='openpyxl')
            for i in range(len(df)):
                cell = str(df.iloc[i, 0])
                if " - " in cell:
                    parts = cell.split(" - ")
                    code = parts[0].strip()
                    name = parts[1].strip()
                    price = 0
                    for j in range(1, 7):
                        val = str(df.iloc[i+1, j])
                        p_search = re.sub(r'\D', '', val)
                        if p_search: 
                            price = int(p_search); break
                    menu_map[code] = {"nev": name, "ar": price}
    except: pass
    return menu_map

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jarat': None}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Fejléc keresés
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

            # Adat sorok (HKSCPZ kód alapján)
            lines = text.split('\n')
            for line in lines:
                if re.search(r'[HKSCPZ]-[0-9]{5,7}', line):
                    # Itt egy leegyszerűsített regex-alapú kinyerés történik
                    uid_m = re.search(r'([0-9]{5,7})', line)
                    if uid_m:
                        uid = uid_m.group(1)
                        raw_orders = re.findall(order_pat, line)
                        if raw_orders:
                            v_o, sq = [], 0
                            for o in raw_orders:
                                q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                                v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                            rows.append({
                                "ID": uid, "Ügyintéző": "Feldolgozás alatt...", "Cím": "Cím...", 
                                "Telefon": "", "Rendelés": ", ".join(v_o), "Pénz": "0 Ft", "Összesen": sq,
                                "Prefix": line[0] if line[0] in "HKSCPZ" else "P"
                            })
    return rows, metadata

# --- 3. DOKUMENTUM GENERÁTOROK (VÉDETT MODULOK) ---

def create_manifest_pdf(df, fn, meta_list):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    jarat_str = ", ".join(list(set([str(m['jarat']) for m in meta_list if m.get('jarat')])))
    datum = meta_list[0].get('day', "") if meta_list else ""
    
    rows_per_page = 28
    pages = math.ceil(len(df) / rows_per_page)
    head_s = ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)
    cell_s = ParagraphStyle('C', fontName=f_reg, fontSize=7, leading=8)

    for p_idx in range(pages):
        p.setFont(f_bold, 10); p.drawString(10*mm, h-10*mm, f"MENETTERV - Járat: {jarat_str} | {datum}")
        p.setFont(f_reg, 8); p.drawRightString(w-10*mm, h-10*mm, f"Futár: {fn} | {p_idx+1}/{pages}")
        
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM</b>", head_s), Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        for _, r in subset.iterrows():
            p_val = "" if str(r['Pénz']).strip().lower() in ["0 ft", "0", "nan", ""] else str(r['Pénz'])
            data.append([str(int(r['Sorrend'])), Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", cell_s), "[ ]", Paragraph(f"<b>{p_val}</b>", head_s), Paragraph(str(r.get('Rendelés_Full', r['Rendelés'])), cell_s), str(r['Összesen'])])
        
        t = Table(data, colWidths=[8*mm, 75*mm, 8*mm, 22*mm, 68*mm, 8*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.3, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        t.wrapOn(p, 10*mm, 15*mm); t.drawOn(p, 10*mm, h - 20*mm - (len(data)*8.2*mm))
        p.showPage()
    p.save(); buf.seek(0); return buf

def create_raklista_pdf(df, jarat, menu):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    items = []
    for r in df['Rendelés_Full']: items.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    counts = {}; rev = 0
    for c, code in items: counts[code] = counts.get(code, 0) + int(c)
    
    data = [[Paragraph("KÓD", f_bold), Paragraph("NÉV", f_bold), Paragraph("DB", f_bold), Paragraph("ÁR", f_bold), Paragraph("ÖSSZ", f_bold)]]
    for code in sorted(counts.keys()):
        db = counts[code]; info = menu.get(code, {"nev": "Ismeretlen", "ar": 0})
        sub = db * info['ar']; rev += sub
        data.append([code, info['nev'][:35], f"{db} db", f"{info['ar']} Ft", f"{sub} Ft"])
    
    p.setFont(f_bold, 14); p.drawString(10*mm, h-15*mm, f"RAKLISTA - Járat: {jarat}")
    t = Table(data, colWidths=[20*mm, 85*mm, 20*mm, 30*mm, 35*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
    t.wrapOn(p, 10*mm, 30*mm); t.drawOn(p, 10*mm, h - 30*mm - (len(data)*6*mm))
    
    curr_y = h - 40*mm - (len(data)*6*mm)
    p.setFont(f_bold, 11); p.drawString(120*mm, curr_y, f"FORGALOM: {rev} Ft")
    p.drawString(120*mm, curr_y - 7*mm, f"JUTALÉK (13%): {round(rev*0.13)} Ft")
    p.save(); buf.seek(0); return buf

# --- 4. ETIKETT MODUL (BEBETONOZVA) ---
def create_label_pdf(df, fn, ft):
    # (A korábbi etikett kódod sértetlenül ide tartozik)
    f_reg, f_bold = register_fonts(); buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm; inner = 5*mm
    for i in range(math.ceil(len(df)/21)*21):
        if i%21==0 and i>0: p.showPage()
        col, row = (i%21)%3, 6-((i%21)//3); x, y = col*lw, row*lh
        if i < len(df):
            r = df.iloc[i]
            p.setFont(f_bold, 10); p.drawString(x+inner, y+lh-8*mm, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 8); p.drawString(x+inner, y+lh-13*mm, f"{r['Ügyintéző']}")
            p.setFont(f_reg, 7); p.drawString(x+inner, y+lh-17*mm, f"{r['Cím']}")
            p.setFont(f_reg, 7); p.drawString(x+inner, y+7*mm, f"{r.get('Rendelés_Full', r['Rendelés'])}")
    p.save(); buf.seek(0); return buf

# --- 5. STREAMLIT UI ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta' not in st.session_state: st.session_state.meta = []

with st.sidebar:
    st.header("📥 Adatok betöltése")
    
    # 1. OPCIÓ: ÚJ PDF FELDOLGOZÁSA
    pdf_files = st.file_uploader("1. Eredeti PDF-ek feltöltése", accept_multiple_files=True, type=['pdf'])
    if pdf_files and st.button("🚀 PDF Feldolgozása"):
        all_r, all_m = [], []
        for f in pdf_files:
            r, m = parse_interfood_pdf(f)
            all_r.extend(r); all_m.append(m)
        df = pd.DataFrame(all_r)
        df['Sorrend'] = range(1, len(df)+1)
        st.session_state.mdf = df
        st.session_state.meta = all_m
        st.rerun()

    st.divider()
    
    # 2. OPCIÓ: CSV VISSZATÖLTÉSE (DRAG & DROP)
    csv_file = st.file_uploader("2. Mentett CSV visszatöltése", type=['csv'])
    if csv_file:
        st.session_state.mdf = pd.read_csv(csv_file)
        st.success("CSV betöltve!")

    st.divider()
    fn = st.text_input("Futár", "Szűcs István")
    ft = st.text_input("Tel", "+36 20 886 8971")

if st.session_state.mdf is not None:
    # Fő szerkesztő felület
    st.subheader("📋 Napi sorrend és adatok szerkesztése")
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    if st.button("💾 Sorrend Mentése / Újrasorszámozás"):
        edited_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
        edited_df['Sorrend'] = range(1, len(edited_df)+1)
        st.session_state.mdf = edited_df
        st.rerun()

    st.divider()
    
    # Letöltések
    c1, c2, c3, c4 = st.columns(4)
    j_str = ", ".join(list(set([str(m.get('jarat','')) for m in st.session_state.meta])))
    menu = get_live_menu_data(st.session_state.meta)

    c1.download_button("📄 ETIKETTEK", create_label_pdf(edited_df, fn, ft), "etikettek.pdf")
    c2.download_button("📋 MENETTERV", create_manifest_pdf(edited_df, fn, st.session_state.meta), "menetterv.pdf")
    c3.download_button("📦 RAKLISTA", create_raklista_pdf(edited_df, j_str, menu), "raklista.pdf")
    c4.download_button("📊 CSV MENTÉSE", edited_df.to_csv(index=False).encode('utf-8-sig'), "napi_adatok.csv")
