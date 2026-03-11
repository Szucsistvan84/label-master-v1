import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Spacer, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

VERZIO = "v203.53-STABLE"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def smart_round(x):
    """5 Ft-os kerekítés szabálya"""
    return int(5 * round(float(x)/5))

# --- ADATFELDOLGOZÁS ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    # Pénz keresése: számok, amik után 'Ft' áll
    money_pat = r'(-?\d[\d\s\.]*)\s*Ft'
    
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
                
                u_code_m = re.search(r'S-([0-9]{5,7})', text_ws)
                if u_code_m:
                    uid = u_code_m.group(1)
                    
                    # NÉV KINYERÉSE: Csak a releváns oszlopból, tisztítva a rendelésektől
                    name_part = " ".join([w['text'] for w in line_words if 340 <= w['x0'] < 520])
                    # Levágjuk a telefonszámokat és rendeléskódokat a névből
                    clean_name = re.split(r'\d{2}/|1-|2-|S-', name_part)[0].strip()
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', clean_name).strip()
                    
                    # PÉNZ: Kinyerés és kerekítés
                    money_m = re.search(money_pat, text_ws)
                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(1))
                        if val_str: raw_money = smart_round(int(val_str))
                    
                    # RENDELÉSEK: Tisztán a kódok
                    v_o = re.findall(order_pat, text_ws)
                    
                    # TELEFON
                    phone_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                    
                    rows.append({
                        "ID": uid, "Ügyintéző": clean_name, 
                        "Telefon": phone_m.group(0) if phone_m else "",
                        "Rendelés": v_o, "Pénz": raw_money, "Össz db": len(v_o)
                    })
    return rows

# --- PDF: ETIKETT ---
def create_label_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    label_w, label_h = 70 * mm, 42.428 * mm
    safe_m = 5 * mm 

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * label_w, row_i * label_h
        r = df.iloc[i]
        
        # Felső margó biztosítása (y + label_h - safe_m)
        curr_y = y + label_h - safe_m
        
        # 1. sor: #Sorszám | ID
        p.setFont(f_reg, 7)
        p.drawString(x + safe_m, curr_y, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - safe_m, curr_y, f"ID: {r['ID']}")
        
        # 2. sor: Név (Kisebb betűvel, hogy ne folyjon össze) | Telefon
        curr_y -= 5*mm
        p.setFont(f_bold, 8.5) # Kisebb betűméret
        p.drawString(x + safe_m, curr_y, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 8)
        p.drawRightString(x + label_w - safe_m, curr_y, str(r['Telefon']))
        
        # Rendelés sor: Sze: kód1, kód2...
        curr_y -= 7*mm
        p.setFont(f_reg, 8)
        rend_text = f"Sze: {', '.join(r['Rendelés'])}"
        p.drawString(x + safe_m, curr_y, rend_text[:50])
        
        # Pénz és darabszám (Csak ha nem 0 Ft)
        curr_y -= 8*mm
        p.setFont(f_bold, 10)
        p_text = f"FIZET: {r['Pénz']} Ft" if r['Pénz'] != 0 else ""
        p.drawString(x + safe_m, curr_y, p_text)
        p.drawRightString(x + label_w - safe_m, curr_y, f"{r['Össz db']} db")
        
        # Futár adatok KÖZÉPRE ZÁRVA
        p.setStrokeColor(colors.lightgrey)
        p.line(x + safe_m, y + safe_m + 3.5*mm, x + label_w - safe_m, y + safe_m + 3.5*mm)
        p.setFont(f_reg, 7)
        futar_info = f"Futár: {f_name} | {f_phone}"
        p.drawCenteredString(x + label_w/2, y + safe_m, futar_info)
        
    p.save(); buf.seek(0); return buf

# --- PDF: MENETTERV ---
def create_manifest_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph(f"<b>MENETTERV - {f_name}</b>", styles['Title']))
    elements.append(Spacer(1, 5*mm))
    
    data = [["SOR", "ÜGYFÉL", "RENDELÉS", "DB", "PÉNZ"]]
    for _, r in df.iterrows():
        # Pénz elrejtése ha 0
        display_money = f"{r['Pénz']} Ft" if r['Pénz'] != 0 else ""
        data.append([
            r['Sorrend'],
            f"{r['Ügyintéző']}\n{r['ID']}",
            f"Sze: {', '.join(r['Rendelés'])}",
            r['Össz db'],
            display_money
        ])
    
    t = Table(data, colWidths=[12*mm, 55*mm, 80*mm, 15*mm, 25*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTNAME', (0, 0), (-1, -1), f_reg),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

c1, c2 = st.columns(2)
with c1: f_nev = st.text_input("Futár neve", "Szűcs István")
with c2: f_tel = st.text_input("Telefonszám", "+36 20 123 4567")

files = st.file_uploader("Menetterv PDF", accept_multiple_files=True)

if files and st.button("Feldolgozás"):
    all_data = []
    for f in files: all_data.extend(parse_interfood_pro(f))
    df = pd.DataFrame(all_data).groupby('ID').agg({
        'Ügyintéző': 'first', 'Telefon': 'first', 
        'Rendelés': lambda x: [i for s in x for i in s],
        'Pénz': 'sum', 'Össz db': 'sum'
    }).reset_index()
    df['Sorrend'] = range(1, len(df)+1)
    st.session_state.mdf = df

if 'mdf' in st.session_state:
    st.data_editor(st.session_state.mdf, use_container_width=True)
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("Etikettek letöltése", create_label_pdf(st.session_state.mdf, f_nev, f_tel), "etikettek.pdf")
    with col2:
        st.download_button("Menetterv letöltése", create_manifest_pdf(st.session_state.mdf, f_nev, f_tel), "menetterv.pdf")
