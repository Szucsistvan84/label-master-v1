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
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

# --- ALAPBEÁLLÍTÁSOK ---
VERZIO = "v203.48-MOD14-PRECISION-GRID"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ADATFELDOLGOZÁS (STABIL MOD3 LOGIKA) ---
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

# --- PDF GENERÁLÁS: ETIKETTEK (TÖKÉLETES 3x7 RÁCS) ---
def create_label_pdf(df):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    # A4: 210 x 297 mm. 3 oszlop x 7 sor esetén:
    label_w = 70 * mm
    label_h = 42.428 * mm # 297 / 7
    
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col = idx % 3
        row = 6 - (idx // 3)
        
        x = col * label_w
        y = row * label_h
        
        # Keret (csak ellenőrzéshez, hajszálvékony)
        p.setStrokeColor(colors.lightgrey)
        p.setLineWidth(0.05*mm)
        p.rect(x, y, label_w, label_h)

        # Tartalom elhelyezése (itt már hagyunk egy kis belső védőtávolságot, hogy ne vágja le a gép)
        r = df.iloc[i]
        margin = 4*mm
        
        p.setFont(f_bold, 11)
        p.drawString(x + margin, y + label_h - 8*mm, str(r['Ügyintéző'])[:25])
        
        p.setFont(f_reg, 9)
        p.drawString(x + margin, y + label_h - 13*mm, str(r['Cím'])[:40])
        p.drawString(x + margin, y + label_h - 17*mm, f"Tel: {r['Telefon']}")
        
        # Rendelés Paragraph-ként a tördelés miatt
        para = Paragraph(str(r['Rendelés']), order_s)
        para.wrap(label_w - 2*margin, 15*mm)
        para.drawOn(p, x + margin, y + 10*mm)

        # Alsó sor
        if r['Pénz']:
            p.setFont(f_bold, 10)
            p.drawString(x + margin, y + 4*mm, f"FIZETENDŐ: {r['Pénz']}")
        
        p.setFont(f_bold, 9)
        p.drawRightString(x + label_w - margin, y + 4*mm, f"Össz: {r['Összesen']} db")
        
        p.setFont(f_reg, 7)
        p.drawRightString(x + label_w - margin, y + label_h - 6*mm, f"#{int(r['Sorrend'])} | ID: {r['ID']}")

    p.save()
    buf.seek(0)
    return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    if st.button("💾 SORREND MENTÉSE") and st.session_state.mdf is not None:
        st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
        st.success("Mentve!")

up = st.file_uploader("Menetterv PDF feltöltése", type="pdf", accept_multiple_files=True)
if up and st.button("📊 FELDOLGOZÁS"):
    all_rows = []
    for f in up: all_rows.extend(parse_interfood_pro(f))
    df = pd.DataFrame(all_rows)
    if os.path.exists("user_prefs.csv"):
        prefs = pd.read_csv("user_prefs.csv")
        df = df.merge(prefs, on="ID", how="left")
    if 'Sorrend' not in df.columns: df['Sorrend'] = range(1, len(df)+1)
    df['Sorrend'] = df['Sorrend'].fillna(999).astype(float)
    st.session_state.mdf = df.sort_values("Sorrend")

if st.session_state.mdf is not None:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.session_state.mdf = edited
    st.download_button("📥 PONTOS ETIKETTEK LETÖLTÉSE", create_label_pdf(st.session_state.mdf), "etikettek_javitott.pdf")
