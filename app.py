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
from reportlab.lib.styles import ParagraphStyle

# --- ALAPBEÁLLÍTÁSOK ---
VERZIO = "v203.48-MOD15-FINAL-GRID"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ADATFELDOLGOZÁS ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*)\s*Ft'
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines_dict = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines_dict:
                    if abs(y - ey) < 3:
                        lines_dict[ey].append(w); break
                else: lines_dict[y] = [w]
            for y in sorted(lines_dict.keys()):
                line_words = sorted(lines_dict[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if u_code_m:
                    uid = u_code_m.group(0).split('-')[-1]
                    b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                    b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                    tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                    money_m = re.search(money_pat, text_ws)
                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(0))
                        if val_str: raw_money = int(val_str)
                    addr_m = re.search(r'(\d{4})', b3)
                    clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                    raw_orders = re.findall(order_pat, text_ws)
                    v_o, sq = [], 0
                    for o in raw_orders:
                        try:
                            q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                            v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                        except: continue
                    if v_o:
                        rows.append({"ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), "Összesen": sq, "Pénz": f"{raw_money} Ft" if raw_money else ""})
    return rows

# --- PDF: MENETTERV ---
def create_manifest_pdf(df, f_nev):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=10, leading=12)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=10)
    
    rows_per_page = 20
    for p_idx in range(math.ceil(len(df)/rows_per_page)):
        p.setFont(f_bold, 12)
        p.drawString(15*mm, h-15*mm, f"MENETTERV - Futár: {f_nev}")
        data = [["SOR", "ÜGYFÉL / CÍM", "OK", "TEL", "RENDELÉS", "DB", "FIZET"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        for _, r in subset.iterrows():
            u_p = Paragraph(f"{r['Ügyintéző']}<br/><font size=7 color='#444444'>{r['Cím']}</font>", name_s)
            data.append([f"#{int(r['Sorrend'])}", u_p, "[ ]", r['Telefon'], Paragraph(r['Rendelés'], cell_s), r['Összesen'], r['Pénz']])
        
        t = Table(data, colWidths=[12*mm, 65*mm, 10*mm, 25*mm, 50*mm, 8*mm, 20*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTNAME', (0,0), (-1,0), f_bold), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        tw, th = t.wrap(w-20*mm, h-40*mm); t.drawOn(p, 10*mm, (h-20*mm)-th); p.showPage()
    p.save(); buf.seek(0); return buf

# --- PDF: ETIKETTEK (PONTOS RÁCS + 5MM BELSŐ MARGÓ) ---
def create_label_pdf(df):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    label_w = 70 * mm
    label_h = 42.428 * mm 
    safe_m = 5 * mm # A kért 5mm-es belső biztonsági zóna
    
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * label_w, row_i * label_h
        
        # Hajszálvékony segédrács a vágáshoz
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.05*mm); p.rect(x, y, label_w, label_h)

        r = df.iloc[i]
        # Tartalom a belső margón (safe_m) belül
        p.setFont(f_bold, 11)
        p.drawString(x + safe_m, y + label_h - safe_m - 4*mm, str(r['Ügyintéző'])[:25])
        
        p.setFont(f_reg, 9)
        p.drawString(x + safe_m, y + label_h - safe_m - 9*mm, str(r['Cím'])[:38])
        p.drawString(x + safe_m, y + label_h - safe_m - 13*mm, f"Tel: {r['Telefon']}")
        
        para = Paragraph(str(r['Rendelés']), order_s)
        para.wrap(label_w - 2*safe_m, 12*mm)
        para.drawOn(p, x + safe_m, y + safe_m + 6*mm)

        if r['Pénz']:
            p.setFont(f_bold, 10)
            p.drawString(x + safe_m, y + safe_m, f"FIZET: {r['Pénz']}")
        
        p.setFont(f_bold, 9)
        p.drawRightString(x + label_w - safe_m, y + safe_m, f"{r['Összesen']} db")
        p.setFont(f_reg, 7)
        p.drawRightString(x + label_w - safe_m, y + label_h - safe_m, f"#{int(r['Sorrend'])} | ID: {r['ID']}")

    p.save(); buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("Beállítások")
    futar_nev = st.text_input("Futár neve", "Ismeretlen futár")
    futar_tel = st.text_input("Futár telefonszáma", "+36")
    
    if st.button("💾 SORREND MENTÉSE") and st.session_state.mdf is not None:
        st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
        st.success("Sorrend elmentve a rendszerbe!")

up = st.file_uploader("Eredeti Interfood PDF feltöltése", type="pdf", accept_multiple_files=True)

if up and st.button("📊 FELDOLGOZÁS"):
    all_r = []
    for f in up: all_r.extend(parse_interfood_pro(f))
    df = pd.DataFrame(all_r)
    if os.path.exists("user_prefs.csv"):
        prefs = pd.read_csv("user_prefs.csv")
        df = df.merge(prefs, on="ID", how="left")
    if 'Sorrend' not in df.columns: df['Sorrend'] = range(1, len(df)+1)
    df['Sorrend'] = df['Sorrend'].fillna(999).astype(float)
    st.session_state.mdf = df.sort_values("Sorrend")

if st.session_state.mdf is not None:
    # Szerkeszthető táblázat a sorrend módosításához
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.session_state.mdf = edited
    
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 ETIKETTEK LETÖLTÉSE", create_label_pdf(st.session_state.mdf), f"etikett_{futar_nev}.pdf")
    with c2:
        st.download_button("📋 MENETTERV LETÖLTÉSE", create_manifest_pdf(st.session_state.mdf, futar_nev), f"menetterv_{futar_nev}.pdf")
