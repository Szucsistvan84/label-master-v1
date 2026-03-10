import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
import math
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

st.set_page_config(page_title="Interfood Logisztika v203.27", layout="wide")

# --- NAP RÖVIDÍTÉSEK ---
DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
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
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                prefix, uid = u_code_m.group(0).split('-')[0], u_code_m.group(0).split('-')[-1]
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                if v_o: rows.append({"Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), "Összesen": sq})
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        base['HasSaturday'] = any(p == 'Z' for p in group['Prefix'])
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            items = group[group['Prefix'] == pfix]['Rendelés'].tolist()
            if items: o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
        base['Rendelés'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2 + 2*mm, (h - 7*lh)/2 
    style = ParagraphStyle('L', fontName=f_reg, fontSize=7, leading=8)
    for i in range(math.ceil(len(df)/21)*21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        if i < len(df):
            r = df.iloc[i]
            p.setLineWidth(1.8 if r.get('HasSaturday', False) or "Szo:" in str(r['Rendelés']) else 0.8)
            p.rect(x+5*mm, y+4*mm, lw-10*mm, lh-8*mm)
            p.setFont(f_bold, 9); p.drawString(x+8*mm, y+35*mm, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 7); p.drawRightString(x+lw-9*mm, y+35*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 8); p.drawString(x+8*mm, y+28*mm, str(r['Ügyintéző'])[:30])
            p.setFont(f_reg, 7); p.drawRightString(x+lw-9*mm, y+28*mm, str(r['Telefon']))
            p.setFont(f_reg, 7); p.drawString(x+8*mm, y+24.5*mm, str(r['Cím'])[:45])
            Paragraph(str(r['Rendelés']), style).wrapOn(p, lw-16*mm, 15*mm).drawOn(p, x+8*mm, y+13*mm)
            p.setFont(f_reg, 7); p.drawRightString(x+lw-9*mm, y+9*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+5.5*mm, f"Futár: {fn} ({ft})")
    p.save(); buf.seek(0); return buf

# --- UI ---
st.title("🏷️ Interfood Logisztika v203.27")
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("⚙️ Beállítások")
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+3620/886-89-71")
    st.divider()
    if st.button("💾 AKTUÁLIS SORREND MENTÉSE"):
        if st.session_state.mdf is not None:
            st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
            st.success("Sorrend a memóriába mentve!")

up_files = st.file_uploader("PDF feltöltés", accept_multiple_files=True)
if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_pro(f))
    mdf = pd.DataFrame(merge_data_flexible(raw))
    if os.path.exists("user_prefs.csv"):
        prefs = pd.read_csv("user_prefs.csv").set_index('ID')['Sorrend'].to_dict()
        mdf['S'] = mdf['ID'].map(prefs)
        mdf = mdf.sort_values(by=['S', 'ID'], na_position='last').drop(columns=['S'])
    mdf.insert(0, "Sorrend", range(1, len(mdf)+1))
    st.session_state.mdf = mdf.astype({"Sorrend": float, "ID": str})

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, num_rows="dynamic", use_container_width=True, hide_index=True, key="main_editor")
    if st.button("🔄 SORREND ÉS ADATOK FRISSÍTÉSE"):
        st.session_state.mdf = edited_df.sort_values("Sorrend").reset_index(drop=True)
        st.session_state.mdf["Sorrend"] = range(1, len(st.session_state.mdf)+1)
        st.rerun()
    if st.button("📥 ETIKETTEK LETÖLTÉSE"):
        st.download_button("Mentés", create_label_pdf(st.session_state.mdf, fn_in, ft_in), "etikettek.pdf")
