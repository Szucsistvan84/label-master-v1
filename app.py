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

# --- 1. ALAPOK ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

# --- 2. JAVÍTOTT PDF PARSER (STABILABB) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Év/Hét/Nap kinyerése ha még nincs meg
            if not metadata['year']:
                ym = re.search(r'Év:\s*(\d{4})', text)
                if ym: metadata['year'] = ym.group(1)
            
            table = page.extract_table()
            if not table: continue
            
            for row in table:
                clean_row = [str(c) if c else "" for c in row]
                if len(clean_row) < 5: continue
                
                # ID keresése (pl P-123456)
                id_m = re.search(r'([HKSCPZ])-(\d{5,7})', clean_row[1])
                if id_m:
                    prefix, uid = id_m.groups()
                    name = clean_row[2].split('\n')[0]
                    addr = clean_row[1].split('\n')[-1]
                    
                    # Rendelések keresése a sorban bárhol
                    full_line = " ".join(clean_row)
                    orders = re.findall(order_pat, full_line)
                    
                    sq = 0
                    v_o = []
                    for o in orders:
                        try:
                            q = int(o.split('-')[0])
                            v_o.append(o)
                            sq += q
                        except: pass
                    
                    if v_o:
                        rows.append({
                            "Prefix": prefix, "ID": uid, "Ügyintéző": name,
                            "Cím": addr, "Telefon": "", # Telefon kinyerése opcionális
                            "Rendelés": ", ".join(v_o), "Összesen": sq
                        })
    return rows, metadata

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    # Inicializáljuk a notes-t ha nincs
    if 'notes' not in st.session_state: st.session_state.notes = {}
    
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        has_weekend = False
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items:
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
                if pfix == 'Z': has_weekend = True
        
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Hétvégi'] = has_weekend
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
    
    res = pd.DataFrame(merged)
    res['Sorrend'] = range(1, len(res) + 1)
    res['Sorrend'] = res['Sorrend'].astype(float)
    return res

# --- 3. ETIKETT GENERÁLÁS (JAVÍTVA) ---
def create_label_pdf(df, fn, ft):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm # 3x7 etikett egy lapon
    inner_m = 5*mm
    
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=7, leading=8)
    
    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col = idx % 3
        row_idx = 6 - (idx // 3) # Fentről lefelé töltés
        x = col * lw
        y = row_idx * lh
        
        r = df.iloc[i]
        
        # Keret (opcionális, segít látni a vágást)
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.1)
        p.rect(x, y, lw, lh)
        
        # Adatok rajzolása
        p.setFont(f_bold, 10); p.drawString(x + inner_m, y + lh - 8*mm, f"#{int(r['Sorrend'])}")
        p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, y + lh - 8*mm, f"ID: {r['ID']}")
        p.setFont(f_bold, 9); p.drawString(x + inner_m, y + lh - 13*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 7); p.drawString(x + inner_m, y + lh - 17*mm, str(r['Cím'])[:40])
        
        # Rendelések Paragraph-ként (hogy törje a sort)
        para = Paragraph(r['Rendelés_Full'], order_s)
        para.wrap(lw - 2*inner_m, 15*mm)
        para.drawOn(p, x + inner_m, y + 10*mm)
        
        p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + 5*mm, f"{r['Összesen']} db")
        p.setFont(f_reg, 6); p.drawString(x + inner_m, y + 3*mm, f"Futár: {fn}")

    p.save(); buf.seek(0); return buf

# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="Logisztika Fix", layout="wide")

if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'notes' not in st.session_state: st.session_state.notes = {}

with st.sidebar:
    c_n = st.text_input("Futár Neve", "Szűcs István")
    c_p = st.text_input("Telefon", "+36 20 886 8971")
    files = st.file_uploader("PDF-ek feltöltése", accept_multiple_files=True)
    if files and st.button("Beolvasás"):
        all_raw = []
        for f in files:
            all_raw.extend(parse_interfood_pdf(f))
        st.session_state.mdf = merge_data(all_raw)
        st.rerun()

if st.session_state.mdf is not None:
    # A táblázat szerkesztése
    edited = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    if st.button("Sorrend mentése"):
        st.session_state.mdf = edited.sort_values('Sorrend').reset_index(drop=True)
        st.session_state.mdf['Sorrend'] = range(1, len(st.session_state.mdf) + 1)
        st.rerun()
        
    c1, c2 = st.columns(2)
    c1.download_button("🏷️ ETIKETTEK LETÖLTÉSE", create_label_pdf(edited, c_n, c_p), "etikettek.pdf")
    c2.download_button("📊 CSV MENTÉSE", edited.to_csv(index=False).encode('utf-8-sig'), "adatok.csv")
