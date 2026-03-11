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
from reportlab.lib.styles import getSampleStyleSheet

VERZIO = "v203.54-STABLE"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

def register_fonts():
    try:
        # Próbáljuk regisztrálni a betűtípust, ha a fájl ott van a szerveren
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        # Ha nincs meg a fájl, marad a beépített Helvetica (nem tud ékezetet jól, de nem omlik össze)
        return "Helvetica", "Helvetica-Bold"

def smart_round(x):
    """5 Ft-os kerekítés szabálya"""
    try:
        val = float(x)
        return int(5 * round(val/5))
    except:
        return 0

# --- ADATFELDOLGOZÁS ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
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
                    
                    # NÉV KINYERÉSE: Csak az ügyintéző oszlopból (340-520 x coord)
                    name_parts = [w['text'] for w in line_words if 340 <= w['x0'] < 520]
                    full_name_raw = " ".join(name_parts)
                    # Szigorú tisztítás: mindent levágunk, ami nem név (számok, kódok)
                    clean_name = re.split(r'\d{2}/|1-|2-|S-|ID:', full_name_raw)[0].strip()
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', clean_name).strip()
                    
                    # CÍM KINYERÉSE (150-340 x coord)
                    addr_parts = [w['text'] for w in line_words if 150 <= w['x0'] < 340]
                    clean_addr = " ".join(addr_parts).strip()
                    
                    # PÉNZ: Kinyerés és kerekítés
                    money_m = re.search(money_pat, text_ws)
                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(1))
                        if val_str: raw_money = smart_round(val_str)
                    
                    # RENDELÉSEK
                    v_o = re.findall(order_pat, text_ws)
                    
                    # TELEFON
                    phone_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                    
                    rows.append({
                        "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr,
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
    top_margin = 5 * mm 

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * label_w, row_i * label_h
        r = df.iloc[i]
        
        # 1. sor: #Sorszám | ID (Garantált 5mm margó felülről)
        p.setFont(f_reg, 7)
        p.drawString(x + 5*mm, y + label_h - top_margin, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - 5*mm, y + label_h - top_margin, f"ID: {r['ID']}")
        
        # 2. sor: Név | Telefon (Kisebb betűvel az összefolyás ellen)
        p.setFont(f_bold, 8.5)
        p.drawString(x + 5*mm, y + label_h - top_margin - 5*mm, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 8)
        p.drawRightString(x + label_w - 5*mm, y + label_h - top_margin - 5*mm, str(r['Telefon']))
        
        # Rendelés: Sze: kódok...
        p.setFont(f_reg, 8)
        rend_txt = f"Sze: {', '.join(r['Rendelés'])}"
        p.drawString(x + 5*mm, y + label_h/2 - 2*mm, rend_txt[:50])
        
        # Pénz és DB (Csak ha > 0 Ft)
        p.setFont(f_bold, 10)
        p_val = f"FIZET: {r['Pénz']} Ft" if r['Pénz'] > 0 else ""
        p.drawString(x + 5*mm, y + 10*mm, p_val)
        p.drawRightString(x + label_w - 5*mm, y + 10*mm, f"{r['Össz db']} db")
        
        # Futár adatok KÖZÉPRE
        p.setStrokeColor(colors.lightgrey)
        p.setLineWidth(0.1)
        p.line(x + 5*mm, y + 8*mm, x + label_w - 5*mm, y + 8*mm)
        p.setFont(f_reg, 7)
        futar_txt = f"Futár: {f_name} | {f_phone}"
        # A középre záráshoz a drawCenteredString-et használjuk az etikett közepére (x + label_w/2)
        p.drawCenteredString(x + label_w/2, y + 4*mm, futar_txt)
        
    p.save(); buf.seek(0); return buf

# --- PDF: MENETTERV ---
def create_manifest_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph(f"<b>MENETTERV - {f_name} ({f_phone})</b>", styles['Title']))
    elements.append(Spacer(1, 5*mm))
    
    # OSZLOPREND: SOR | ÜGYFÉL | RENDELÉS | DB | PÉNZ
    data = [["SOR", "ÜGYFÉL / ID", "RENDELÉS", "DB", "PÉNZ"]]
    for _, r in df.iterrows():
        p_val = f"{r['Pénz']} Ft" if r['Pénz'] > 0 else ""
        data.append([
            r['Sorrend'],
            f"{r['Ügyintéző']}\n{r['ID']}",
            f"Sze: {', '.join(r['Rendelés'])}",
            r['Össz db'],
            p_val
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

files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True)

if files and st.button("📊 FELDOLGOZÁS"):
    all_data = []
    for f in files: all_data.extend(parse_interfood_pro(f))
    
    df = pd.DataFrame(all_data).groupby('ID').agg({
        'Ügyintéző': 'first', 'Cím': 'first', 'Telefon': 'first',
        'Rendelés': lambda x: [i for s in x for i in s],
        'Pénz': 'sum', 'Össz db': 'sum'
    }).reset_index()
    
    df['Sorrend'] = range(1, len(df)+1)
    # UI oszloprend: Sorrend, ID, Ügyintéző, Cím, Rendelés, Össz db, Pénz, Telefon
    st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Rendelés', 'Össz db', 'Pénz', 'Telefon']]

if 'mdf' in st.session_state:
    st.subheader("Szerkeszthető adatok")
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.session_state.mdf = edited_df

    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 Etikettek (PDF)", create_label_pdf(st.session_state.mdf, f_nev, f_tel), "etikettek.pdf", use_container_width=True)
    with col2:
        st.download_button("📋 Menetterv (PDF)", create_manifest_pdf(st.session_state.mdf, f_nev, f_tel), "menetterv.pdf", use_container_width=True)
