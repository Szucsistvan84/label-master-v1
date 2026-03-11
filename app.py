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
# Itt volt a hiba: VERZIO vs VER_ZIO
VERZIO = "v203.52-STABLE"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

def register_fonts():
    try:
        # Ha a környezetben elérhető a betűtípus
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
    # Javított pénz-regex: kezeli a negatív előjelet és a pontot/szóközt is
    money_pat = r'(-?\s?\d[\d\s\.]*)\s*Ft'
    
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
                
                # S- prefix keresése az ügyfélkód előtt (Sze: Szerda)
                u_code_m = re.search(r'S-([0-9]{5,7})', text_ws)
                if u_code_m:
                    uid = u_code_m.group(1)
                    # Név kinyerése (a 355-ös x koordináta környékén kezdődnek az ügyintézők)
                    b4 = " ".join([w['text'] for w in line_words if 350 <= w['x0'] < 550])
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                    
                    # Pénzösszeg kinyerése a sorból
                    money_m = re.search(money_pat, text_ws)
                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(0))
                        if val_str: raw_money = int(val_str)
                    
                    # Rendelések kinyerése Sze: prefixszel
                    raw_orders = re.findall(order_pat, text_ws)
                    v_o = [f"Sze: {o}" for o in raw_orders]
                    
                    # Cím kinyerése (gyakran a név előtt vagy után van a PDF-ben)
                    # Egyszerűsített cím-keresés a koordináták alapján
                    addr_part = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 350])
                    
                    rows.append({
                        "ID": uid, "Ügyintéző": clean_name, "Cím": addr_part.strip(),
                        "Telefon": re.search(phone_pat, text_ws.replace(" ", "")).group(0) if re.search(phone_pat, text_ws.replace(" ", "")) else "",
                        "Rendelés": v_o, "Pénz": raw_money, "Össz db": len(v_o)
                    })
    return rows

# --- PDF GENERÁLÁS: ETIKETT ---
def create_label_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    label_w, label_h = 70 * mm, 42.428 * mm
    safe_m = 5 * mm # Felső margó

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
        p.drawString(x + safe_m, y + label_h - safe_m - 5*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 9)
        p.drawRightString(x + label_w - safe_m, y + label_h - safe_m - 5*mm, str(r['Telefon']))
        
        # Rendelés összesítő sor (Sze: 1-R2, ...)
        p.setFont(f_reg, 8)
        rend_txt = ", ".join(r['Rendelés'])
        p.drawString(x + safe_m, y + label_h/2 - 2*mm, rend_txt[:45])
        
        # Alsó sáv: Pénz + Összesen db
        p.setFont(f_bold, 10)
        p.drawString(x + safe_m, y + safe_m + 5*mm, f"FIZET: {int(r['Pénz'])} Ft")
        p.drawRightString(x + label_w - safe_m, y + safe_m + 5*mm, f"Össz: {r['Össz db']} db")
        
        # Futár adatok legalul
        p.setFont(f_reg, 7)
        p.setStrokeColor(colors.lightgrey)
        p.line(x + safe_m, y + safe_m + 3.5*mm, x + label_w - safe_m, y + safe_m + 3.5*mm)
        p.drawString(x + safe_m, y + safe_m, f"Futár: {f_name} | {f_phone}")
        
    p.save(); buf.seek(0); return buf

# --- PDF GENERÁLÁS: MENETTERV ---
def create_manifest_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=10*mm, bottomMargin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName=f_bold, fontSize=14, alignment=1)
    elements.append(Paragraph(f"MENETTERV - {f_name} ({f_phone})", title_style))
    elements.append(Spacer(1, 5*mm))
    
    data = [["SOR", "ÜGYFÉL / ID", "RENDELÉS", "ÖSSZ DB", "PÉNZ"]]
    for _, r in df.iterrows():
        data.append([
            f"#{r['Sorrend']}",
            f"{r['Ügyintéző']}\nID: {r['ID']}",
            "\n".join(r['Rendelés']),
            f"{r['Össz db']} db",
            f"{int(r['Pénz'])} Ft"
        ])
    
    table = Table(data, colWidths=[15*mm, 55*mm, 75*mm, 20*mm, 25*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), f_reg),
        ('FONTNAME', (0, 0), (-1, 0), f_bold),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    elements.append(table)
    
    doc.build(elements)
    buf.seek(0); return buf

# --- FELHASZNÁLÓI FELÜLET ---
st.title(f"Interfood Logisztika {VERZIO}")

c1, c2 = st.columns(2)
with c1:
    f_nev = st.text_input("Futár neve", "Szűcs István")
with c2:
    f_tel = st.text_input("Futár telefonszáma", "+36201234567")

uploaded_files = st.file_uploader("PDF fájlok (Menettervek)", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("📊 ADATOK ÖSSZESÍTÉSE"):
    all_rows = []
    for f in uploaded_files:
        all_rows.extend(parse_interfood_pro(f))
    
    raw_df = pd.DataFrame(all_rows)
    # Összevonás ID alapján
    df = raw_df.groupby('ID').agg({
        'Ügyintéző': 'first',
        'Cím': 'first',
        'Telefon': 'first',
        'Rendelés': lambda x: [item for sublist in x for item in sublist],
        'Pénz': 'sum',
        'Össz db': 'sum'
    }).reset_index()
    
    df['Sorrend'] = range(1, len(df) + 1)
    # Oszloprend beállítása a táblázathoz
    st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Rendelés', 'Össz db', 'Pénz', 'Telefon']]

if 'mdf' in st.session_state:
    st.subheader("Szerkeszthető adatok")
    # Dinamikus táblázat (itt lehet a sorrendet is állítani)
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.session_state.mdf = edited_df

    st.divider()
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        st.download_button(
            "📥 ETIKETTEK LETÖLTÉSE (PDF)", 
            create_label_pdf(st.session_state.mdf, f_nev, f_tel), 
            "etikettek_javitott.pdf", 
            use_container_width=True
        )
    with btn_col2:
        st.download_button(
            "📋 TÁBLÁZATOS MENETTERV LETÖLTÉSE", 
            create_manifest_pdf(st.session_state.mdf, f_nev, f_tel), 
            "menetterv_javitott.pdf", 
            use_container_width=True
        )
