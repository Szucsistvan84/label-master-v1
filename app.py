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
VERZIO = "v203.50-FINAL-CONTROL"
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
    
    is_sat = any(x in pdf_file.name.lower() for x in ["szombat", "sat", "szo"])
    nap_prefix = "Szo" if is_sat else "Pén"

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
                    
                    money_m = re.search(money_pat, text_ws)
                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(0))
                        if val_str: raw_money = int(val_str)
                    
                    addr_m = re.search(r'(\d{4})', b3)
                    clean_addr = b3[addr_m.start():].strip() if addr_m else b3

                    raw_orders = re.findall(order_pat, text_ws)
                    v_o = []
                    for o in raw_orders:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        item = f"{nap_prefix}: {q}-{o.split('-')[1]}"
                        v_o.append(f"<b>[{item}]</b>" if is_sat else item)
                    
                    rows.append({
                        "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, 
                        "Telefon": re.search(phone_pat, text_ws.replace(" ", "")).group(0) if re.search(phone_pat, text_ws.replace(" ", "")) else "",
                        "Rendelés": v_o, "Pénz": raw_money
                    })
    return rows

# --- PDF: ETIKETT (RÁCS NÉLKÜL, ÚJ ELRENDEZÉS) ---
def create_label_pdf(df):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    label_w, label_h = 70 * mm, 42.428 * mm
    safe_m = 5 * mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * label_w, row_i * label_h
        
        r = df.iloc[i]
        
        # 1. sor: #Sorszám (bal) | ID (jobb)
        p.setFont(f_reg, 7)
        p.drawString(x + safe_m, y + label_h - safe_m, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - safe_m, y + label_h - safe_m, f"ID: {r['ID']}")
        
        # 2. sor: Név (bal) | Telefon (jobb)
        p.setFont(f_bold, 10)
        p.drawString(x + safe_m, y + label_h - safe_m - 5*mm, str(r['Ügyintéző'])[:22])
        p.setFont(f_reg, 9)
        p.drawRightString(x + label_w - safe_m, y + label_h - safe_m - 5*mm, str(r['Telefon']))
        
        # 3. sor: Cím
        p.setFont(f_reg, 8)
        p.drawString(x + safe_m, y + label_h - safe_m - 10*mm, str(r['Cím'])[:40])
        
        # Rendelések
        rend_txt = ", ".join(r['Rendelés']) if isinstance(r['Rendelés'], list) else str(r['Rendelés'])
        para = Paragraph(rend_txt, order_s)
        para.wrap(label_w - 2*safe_m, 12*mm)
        para.drawOn(p, x + safe_m, y + safe_m + 6*mm)

        # Alsó sor: Pénz és darabszám
        if r['Pénz'] and int(r['Pénz']) != 0:
            p.setFont(f_bold, 10)
            p.drawString(x + safe_m, y + safe_m, f"FIZET: {int(r['Pénz'])} Ft")
            
    p.save(); buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

with st.sidebar:
    st.header("Beállítások")
    f_nev = st.text_input("Futár neve", "Futár")
    f_tel = st.text_input("Futár tel.", "+36")
    if st.button("💾 SORREND MENTÉSE") and 'mdf' in st.session_state:
        st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
        st.success("Mentve!")

up = st.file_uploader("PDF fájlok feltöltése", type="pdf", accept_multiple_files=True)

if up and st.button("📊 ADATOK FELDOLGOZÁSA"):
    all_data = []
    for f in up: all_data.extend(parse_interfood_pro(f))
    
    # Összevonás ID alapján
    merged = {}
    for item in all_data:
        uid = item['ID']
        if uid not in merged: merged[uid] = item
        else:
            merged[uid]['Rendelés'].extend(item['Rendelés'])
            merged[uid]['Pénz'] += item['Pénz']
    
    df = pd.DataFrame(list(merged.values()))
    if os.path.exists("user_prefs.csv"):
        prefs = pd.read_csv("user_prefs.csv")
        df = df.merge(prefs, on="ID", how="left")
    
    df['Sorrend'] = df.get('Sorrend', pd.Series(range(1, len(df)+1))).fillna(999).astype(int)
    # Fix oszloprend: Sorrend az első
    st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Pénz', 'Rendelés']].sort_values("Sorrend")

if 'mdf' in st.session_state and st.session_state.mdf is not None:
    # Táblázat manuális szerkesztéssel és új sor opcióval
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True, num_rows="dynamic")
    st.session_state.mdf = edited_df

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 ETIKETTEK LETÖLTÉSE (PDF)", create_label_pdf(st.session_state.mdf), f"etikett_{f_nev}.pdf", use_container_width=True)
    with col2:
        # Itt a menetterv generáló, amit hiányoltál
        from reportlab.lib.pagesizes import A4
        def quick_manifest(df):
            buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
            p.drawString(20*mm, 280*mm, f"MENETTERV - Futár: {f_nev} ({f_tel})")
            # Egyszerűsített lista a menettervhez
            y = 270*mm
            for _, r in df.iterrows():
                p.setFont("Helvetica", 9)
                p.drawString(20*mm, y, f"#{r['Sorrend']} - {r['Ügyintéző']} - {r['Cím']} - {r['Pénz']} Ft")
                y -= 10*mm
                if y < 20*mm: p.showPage(); y = 280*mm
            p.save(); buf.seek(0); return buf
            
        st.download_button("📋 MENETTERV LETÖLTÉSE (PDF)", quick_manifest(st.session_state.mdf), f"menetterv_{f_nev}.pdf", use_container_width=True)
