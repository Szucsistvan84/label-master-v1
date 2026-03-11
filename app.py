import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle, SimpleDocTemplate, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- KONFIGURÁCIÓ ---
VERZIO = "v203.51-STABLE"
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
    # Minták a PDF-ből való kinyeréshez
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    # Pénz minta: számok, közte szóköz vagy pont, majd 'Ft'
    money_pat = r'(-?\s?\d[\d\s\.]*)\s*Ft'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            words = page.extract_words()
            
            # Sorok csoportosítása Y koordináta alapján
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
                
                # S- prefix keresése az ügyfélkód előtt (Szerda)
                u_code_m = re.search(r'S-([0-9]{5,7})', text_ws)
                if u_code_m:
                    uid = u_code_m.group(1)
                    # Név és cím kinyerése koordináták alapján (becsült)
                    b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 550])
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                    
                    # Pénzösszeg kinyerése
                    money_m = re.search(money_pat, text_ws)
                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(1))
                        if val_str: raw_money = int(val_str)
                    
                    # Rendelések gyűjtése (Sze: prefixszel)
                    raw_orders = re.findall(order_pat, text_ws)
                    v_o = [f"Sze: {o}" for o in raw_orders]
                    
                    rows.append({
                        "ID": uid, "Ügyintéző": clean_name, 
                        "Telefon": re.search(phone_pat, text_ws.replace(" ", "")).group(0) if re.search(phone_pat, text_ws.replace(" ", "")) else "",
                        "Rendelés": v_o, "Pénz": raw_money, "Össz db": len(v_o)
                    })
    return rows

# --- PDF: ETIKETT (ÚJ ELRENDEZÉS + FUTÁR ADATOK) ---
def create_label_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    label_w, label_h = 70 * mm, 42.428 * mm
    safe_m = 5 * mm # FIX 5mm margó

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * label_w, row_i * label_h
        r = df.iloc[i]
        
        # 1. sor: #Sorszám | ID
        p.setFont(f_reg, 7)
        p.drawString(x + safe_m, y + label_h - safe_m, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - safe_m, y + label_h - safe_m, f"ID: {r['ID']}")
        
        # 2. sor: Név | Telefon
        p.setFont(f_bold, 10)
        p.drawString(x + safe_m, y + label_h - safe_m - 5*mm, str(r['Ügyintéző'])[:22])
        p.setFont(f_reg, 9)
        p.drawRightString(x + label_w - safe_m, y + label_h - safe_m - 5*mm, str(r['Telefon']))
        
        # Rendelések listája
        p.setFont(f_reg, 8)
        rend_txt = ", ".join(r['Rendelés'])
        p.drawString(x + safe_m, y + label_h/2, rend_txt[:45])
        
        # Alsó sor: Pénz, Darabszám és Futár infó
        p.setFont(f_bold, 9)
        p.drawString(x + safe_m, y + safe_m + 4*mm, f"FIZET: {int(r['Pénz'])} Ft | {r['Össz db']} db")
        p.setFont(f_reg, 7)
        p.setStrokeColor(colors.lightgrey)
        p.line(x+safe_m, y+safe_m+3*mm, x+label_w-safe_m, y+safe_m+3*mm)
        p.drawString(x + safe_m, y + safe_m, f"Futár: {f_name} ({f_phone})")
        
    p.save(); buf.seek(0); return buf

# --- PDF: TÁBLÁZATOS MENETTERV ---
def create_manifest_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    header = Paragraph(f"<b>MENETTERV - {f_name} ({f_phone})</b>", styles['Title'])
    elements.append(header)
    elements.append(Spacer(1, 5*mm))
    
    # Táblázat adatok
    data = [["Sor", "Név / ID", "Rendelés", "Pénz", "Db"]]
    for _, r in df.iterrows():
        data.append([
            r['Sorrend'],
            f"{r['Ügyintéző']}\nID: {r['ID']}",
            "\n".join(r['Rendelés']),
            f"{int(r['Pénz'])} Ft",
            r['Össz db']
        ])
    
    t = Table(data, colWidths=[12*mm, 50*mm, 80*mm, 25*mm, 15*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), f_bold),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(t)
    
    doc.build(elements)
    buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VER_ZIO}")

col_cfg1, col_cfg2 = st.columns(2)
with col_cfg1:
    f_nev = st.text_input("Futár neve", "Szűcs István")
with col_cfg2:
    f_tel = st.text_input("Futár telefonszáma", "+36201234567")

up = st.file_uploader("PDF feltöltése", type="pdf", accept_multiple_files=True)

if up and st.button("📊 ADATOK FELDOLGOZÁSA"):
    all_data = []
    for f in up: all_data.extend(parse_interfood_pro(f))
    
    df = pd.DataFrame(all_data)
    # Csoportosítás ID alapján (összevonás)
    df = df.groupby('ID').agg({
        'Ügyintéző': 'first',
        'Telefon': 'first',
        'Rendelés': lambda x: [item for sublist in x for item in sublist],
        'Pénz': 'sum',
        'Össz db': 'sum'
    }).reset_index()
    
    df['Sorrend'] = range(1, len(df) + 1)
    st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Rendelés', 'Pénz', 'Össz db', 'Telefon']]

if 'mdf' in st.session_state:
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.session_state.mdf = edited_df

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 ETIKETTEK (PDF)", create_label_pdf(st.session_state.mdf, f_nev, f_tel), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 TÁBLÁZATOS MENETTERV (PDF)", create_manifest_pdf(st.session_state.mdf, f_nev, f_tel), "menetterv.pdf", use_container_width=True)
