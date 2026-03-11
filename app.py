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

# --- FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERŐ MOTOR (v8 - Blokk alapú) ---
def process_interfood_pdf(pdf_file):
    rows = []
    driver_name = "Ismeretlen futár"
    
    with pdfplumber.open(pdf_file) as pdf:
        # Futár nevének kinyerése a fejlécből
        first_page_text = pdf.pages[0].extract_text() or ""
        driver_match = re.search(r"MENETTERV - ([^\n(]+)", first_page_text)
        if driver_match:
            driver_name = driver_match.group(1).strip()
        elif "járat" in first_page_text:
            driver_match = re.search(r"(\d{4})\. járat", first_page_text)
            if driver_match: driver_name = f"{driver_match.group(1)}. járat"

        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split('\n')
            
            current_row = None
            
            for line in lines:
                # 1. Új ügyfél kezdődik? (ID keresés)
                id_match = re.search(r'([HKSCPZ]-[0-9]{5,7})', line)
                if id_match:
                    if current_row: rows.append(current_row)
                    
                    full_id = id_match.group(0)
                    current_row = {
                        "Prefix": full_id.split('-')[0],
                        "ID": full_id.split('-')[1],
                        "Ügyintéző": "", "Cím": "", "Telefon": "",
                        "Rendelés": "", "Pénz": 0, "Megjegyzés": "",
                        "Összesen": 0, "Futár": driver_name
                    }
                    # Név kinyerése az ID utáni részből (ha ott van)
                    remaining = line.replace(full_id, "").strip()
                    if len(remaining) > 3: current_row["Ügyintéző"] = remaining
                    continue

                if current_row:
                    # 2. Telefonszám keresés
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    if tel_m: current_row["Telefon"] = tel_m.group(0)

                    # 3. Pénzösszeg keresés (Ft)
                    money_m = re.search(r'(-?\d[\d\s]*)\s*Ft', line)
                    if money_m:
                        val = re.sub(r'[^-0-9]', '', money_m.group(1))
                        if val: current_row["Pénz"] += int(val)

                    # 4. Rendelés kódok (pl. 1-L2K)
                    order_matches = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', line)
                    if order_matches:
                        current_row["Rendelés"] += ", ".join(order_matches) + " "
                        for om in order_matches:
                            try: current_row["Összesen"] += int(om.split('-')[0])
                            except: pass
                    
                    # 5. Cím és Megjegyzés (Ha nem pénz és nem telefon, és van benne Debrecen vagy utca)
                    elif "Debrecen" in line or " u." in line or " út" in line:
                        current_row["Cím"] = line.strip()
                    elif len(line.strip()) > 5 and "Ft" not in line and not id_match:
                        current_row["Megjegyzés"] += line.strip() + " "

            if current_row: rows.append(current_row)
            
    return rows

# --- ETIKETT GENERÁLÁS (60x32.43mm) ---
def create_labels(df):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 60*mm, 32.43*mm
    m = 5*mm
    
    for i, (_, r) in enumerate(df.iterrows()):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row * lh
        
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.1*mm)
        p.rect(x, y, lw, lh)
        
        p.setFillColor(colors.black)
        p.setFont(f_bold, 8); p.drawString(x+m, y+lh-7*mm, f"#{i+1}")
        p.setFont(f_reg, 6); p.drawRightString(x+lw-m, y+lh-7*mm, f"ID: {r['ID']}")
        
        # Futár neve a fejlécbe
        p.setFont(f_reg, 5); p.drawCentredString(x+lw/2, y+lh-4*mm, str(r['Futár']))

        p.setFont(f_bold, 9); p.drawString(x+m, y+lh-12*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-16*mm, str(r['Cím'])[:40])
        
        # Rendelés és Telefon
        order_txt = f"{r['Rendelés']} | Tel: {r['Telefon']}"
        order_s = ParagraphStyle('Labels', fontName=f_reg, fontSize=7, leading=8)
        para = Paragraph(order_txt, order_s)
        para.wrap(lw-2*m, 8*mm); para.drawOn(p, x+m, y+8*mm)
        
        # Fizetendő és darabszám
        if r['Pénz'] > 0:
            p.setFont(f_bold, 10); p.drawString(x+m, y+m, f"FIZET: {r['Pénz']} Ft")
        
        p.setFont(f_bold, 8); p.drawRightString(x+lw-m, y+m, f"{r['Összesen']} db")
        
    p.save(); buf.seek(0); return buf

# --- MENETTERV GENERÁLÁS ---
def create_manifest(df):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    rows_per_page = 22
    for p_idx in range(math.ceil(len(df)/rows_per_page)):
        p.setFont(f_bold, 12); p.drawString(15*mm, h-15*mm, f"MENETTERV - {df.iloc[0]['Futár']}")
        
        data = [["SOR", "ÜGYFÉL / CÍM / MEGJEGYZÉS", "TEL", "RENDELÉS", "DB", "PÉNZ"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        
        for idx, r in subset.iterrows():
            note = f"<br/><font color='red' size=7><i>{r['Megjegyzés']}</i></font>" if r['Megjegyzés'] else ""
            info = Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}{note}", ParagraphStyle('Cell', fontName=f_reg, fontSize=8))
            data.append([idx+1, info, r['Telefon'], r['Rendelés'], r['Összesen'], f"{r['Pénz']} Ft"])
        
        t = Table(data, colWidths=[10*mm, 75*mm, 25*mm, 45*mm, 10*mm, 25*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('FONTSIZE', (0,0), (-1,0), 10), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        t.wrapOn(p, w, h); t.drawOn(p, 10*mm, 20*mm)
        p.showPage()
        
    p.save(); buf.seek(0); return buf

# --- STREAMLIT UI ---
st.title(f"Interfood Master {VERZIO}")
files = st.file_uploader("PDF-ek feltöltése", accept_multiple_files=True)
if files:
    all_data = []
    for f in files: all_data.extend(process_interfood_pdf(f))
    df = pd.DataFrame(all_data)
    
    if not df.empty:
        st.dataframe(df)
        col1, col2 = st.columns(2)
        with col1: st.download_button("Etikettek", create_labels(df), "etikettek.pdf")
        with col2: st.download_button("Menetterv", create_manifest(df), "menetterv.pdf")
