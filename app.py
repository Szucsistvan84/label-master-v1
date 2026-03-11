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

# --- KONFIGURÁCIÓ ---
VERZIO = "v203.48-MOD10-STABIL"

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def custom_round(amount):
    return 5 * round(amount / 5)

# --- ADATKINYERÉS (A tegnapi kifinomult motor) ---
def parse_interfood_source(pdf_file):
    rows = []
    driver_name = "Ismeretlen"
    
    with pdfplumber.open(pdf_file) as pdf:
        # Futár neve az első oldal tetejéről
        first_page_text = pdf.pages[0].extract_text() or ""
        driver_match = re.search(r"MENETTERV\s*-\s*([^\n(]+)", first_page_text)
        if driver_match: driver_name = driver_match.group(1).strip()
        
        for page in pdf.pages:
            tables = page.extract_table()
            if not tables: continue
            
            for row in tables:
                if not row or len(row) < 5 or row[0] == "Sor": continue
                
                # Ügyfélkód kinyerése (pl. S-123456)
                u_match = re.search(r'([HKSCPZ]-[0-9]{5,7})', str(row[1]))
                if u_match:
                    u_code = u_match.group(0)
                    
                    # Pénzösszeg kinyerése a Telefon/Rendelés oszlopból (row[4])
                    money_val = 0
                    money_match = re.search(r'(-?\d[\d\s]*)\s*Ft', str(row[4]))
                    if money_match:
                        money_val = int(re.sub(r'[^-0-9]', '', money_match.group(1)))
                    
                    # Megjegyzés kinyerése (gyakran az ügyfélkód utáni perjel után van)
                    note = ""
                    if "/" in str(row[1]):
                        note = str(row[1]).split("/", 1)[1].replace("\n", " ").strip()

                    rows.append({
                        "ID": u_code.split('-')[1],
                        "Prefix": u_code.split('-')[0],
                        "Ügyintéző": str(row[3]).split('\n')[0].strip(),
                        "Cím": str(row[2]).replace('\n', ' ').strip(),
                        "Telefon": re.search(r'(\d{2}/\d{6,7})', str(row[4])).group(0) if re.search(r'(\d{2}/\d{6,7})', str(row[4])) else "",
                        "Rendelés": str(row[4]).split('\n')[-1].strip(),
                        "Pénz": custom_round(money_val),
                        "Megjegyzés": note,
                        "Futár": driver_name,
                        "Összesen": row[5] if len(row) > 5 else "1"
                    })
    return rows

# --- ETIKETT (A tegnapi precíziós stílus) ---
def create_label_pdf(df):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 60*mm, 32.43*mm
    m = 4*mm
    
    for i, (_, r) in enumerate(df.iterrows()):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row * lh
        
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.1*mm)
        p.rect(x, y, lw, lh)
        
        p.setFillColor(colors.black)
        # Fejléc: Sorrend, Futár és ID
        p.setFont(f_bold, 8); p.drawString(x+m, y+lh-7*mm, f"#{i+1}")
        p.setFont(f_reg, 5); p.drawCentredString(x+lw/2, y+lh-4*mm, str(r['Futár'])[:30])
        p.setFont(f_reg, 6); p.drawRightString(x+lw-m, y+lh-7*mm, f"ID: {r['ID']}")
        
        # Név és Cím
        p.setFont(f_bold, 9); p.drawString(x+m, y+lh-12*mm, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-16*mm, str(r['Cím'])[:45])
        
        # Rendelés és Megjegyzés
        order_style = ParagraphStyle('LabelOrder', fontName=f_reg, fontSize=7, leading=8)
        note_text = f"<br/><font color='red' size=6>{r['Megjegyzés']}</font>" if r['Megjegyzés'] else ""
        para = Paragraph(f"{r['Rendelés']}{note_text}", order_style)
        para.wrap(lw-2*m, 10*mm); para.drawOn(p, x+m, y+8*mm)
        
        # Alsó sor: Pénz és darabszám
        if r['Pénz'] > 0:
            p.setFont(f_bold, 10); p.drawString(x+m, y+m, f"FIZET: {r['Pénz']} Ft")
        p.setFont(f_bold, 8); p.drawRightString(x+lw-m, y+m, f"{r['Összesen']} db")
        
    p.save(); buf.seek(0); return buf

# --- STREAMLIT UI ---
def main():
    st.set_page_config(page_title="Interfood Label Master", layout="wide")
    st.title(f"🚚 Interfood Label Master {VERZIO}")
    
    files = st.file_uploader("Menetterv PDF-ek feltöltése", accept_multiple_files=True)
    
    if files:
        all_data = []
        for f in files:
            all_data.extend(parse_interfood_source(f))
            
        if all_data:
            df = pd.DataFrame(all_data)
            st.success(f"Sikeres beolvasás: {len(df)} tétel.")
            st.dataframe(df)
            
            col1, _ = st.columns([1, 3])
            with col1:
                pdf_output = create_label_pdf(df)
                st.download_button(
                    label="Etikettek Letöltése (PDF)",
                    data=pdf_output,
                    file_name=f"etikettek_{VERZIO}.pdf",
                    mime="application/pdf"
                )

if __name__ == "__main__":
    main()
