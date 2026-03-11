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

# --- FONTOS VÁLTOZÓK ---
VERZIO = "v203.48-MOD9"

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERŐ (Megerősített telefon, pénz és futár felismerés) ---
def process_interfood_pdf(pdf_file):
    rows = []
    driver_name = "Ismeretlen futár"
    
    with pdfplumber.open(pdf_file) as pdf:
        # Futár és járatszám kinyerése
        first_page = pdf.pages[0].extract_text() or ""
        driver_m = re.search(r"MENETTERV\s*-\s*([^\n(]+)", first_page)
        if driver_m:
            driver_name = driver_m.group(1).strip()
        jarat_m = re.search(r"(\d{4})\.\s*járat", first_page)
        if jarat_m:
            driver_name = f"{jarat_m.group(1)} - {driver_name}"

        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split('\n')
            
            current_row = None
            for line in lines:
                # Ügyfélkód (pl. S-123456) - Ez a horgonypont
                id_match = re.search(r'([HKSCPZ]-[0-9]{5,7})', line)
                if id_match:
                    if current_row: rows.append(current_row)
                    full_id = id_match.group(0)
                    current_row = {
                        "ID": full_id.split('-')[1],
                        "Prefix": full_id.split('-')[0],
                        "Ügyintéző": line.replace(full_id, "").strip(),
                        "Cím": "", "Telefon": "", "Rendelés": "", 
                        "Pénz": 0, "Megjegyzés": "", "Összesen": 0, "Futár": driver_name
                    }
                    continue

                if current_row:
                    # Telefonszám
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    if tel_m: current_row["Telefon"] = tel_m.group(0)

                    # Pénzösszeg (Ft)
                    money_m = re.search(r'(-?\d[\d\s]*)\s*Ft', line)
                    if money_m:
                        val = re.sub(r'[^-0-9]', '', money_m.group(1))
                        if val: current_row["Pénz"] += int(val)

                    # Rendelés (pl. 1-L2K)
                    orders = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', line)
                    if orders:
                        current_row["Rendelés"] += ", ".join(orders) + " "
                        for o in orders:
                            try: current_row["Összesen"] += int(o.split('-')[0])
                            except: pass
                    
                    # Cím és Megjegyzés szétválasztása
                    elif any(x in line for x in ["Debrecen", " u.", " út", " tér"]):
                        current_row["Cím"] = line.strip()
                    elif len(line.strip()) > 3 and "Ft" not in line:
                        current_row["Megjegyzés"] += line.strip() + " "

            if current_row: rows.append(current_row)
    return rows

# --- ETIKETT (60x32,43mm, Precíziós rács) ---
def create_labels(df):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 60*mm, 32.43*mm
    m = 4*mm # Margó
    
    for i, (_, r) in enumerate(df.iterrows()):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row * lh
        
        # Halvány keret a vágáshoz
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.1*mm)
        p.rect(x, y, lw, lh)
        
        p.setFillColor(colors.black)
        p.setFont(f_bold, 8); p.drawString(x+m, y+lh-7*mm, f"#{i+1}")
        p.setFont(f_reg, 6); p.drawRightString(x+lw-m, y+lh-7*mm, f"ID: {r['ID']}")
        
        # Futár neve pici betűvel legfelül
        p.setFont(f_reg, 5); p.drawCentredString(x+lw/2, y+lh-3*mm, str(r['Futár']))

        p.setFont(f_bold, 9); p.drawString(x+m, y+lh-11*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-15*mm, str(r['Cím'])[:40])
        
        # Rendelés és Telefon középre
        p.setFont(f_reg, 7)
        order_text = f"{r['Rendelés']} | {r['Telefon']}"
        p.drawString(x+m, y+10*mm, order_text[:45])
        
        # Megjegyzés (ha van)
        if r['Megjegyzés']:
            p.setFont(f_reg, 6); p.setFillColor(colors.red)
            p.drawString(x+m, y+7*mm, str(r['Megjegyzés'])[:45])
            p.setFillColor(colors.black)

        # Alsó sor: Pénz és darabszám
        if r['Pénz'] > 0:
            p.setFont(f_bold, 10); p.drawString(x+m, y+m, f"FIZET: {r['Pénz']} Ft")
        p.setFont(f_bold, 8); p.drawRightString(x+lw-m, y+m, f"{r['Összesen']} db")
        
    p.save(); buf.seek(0); return buf

# --- STREAMLIT FELÜLET ---
def main():
    st.title(f"🚚 Interfood Master {VERZIO}")
    files = st.file_uploader("PDF menettervek feltöltése", accept_multiple_files=True)
    
    if files:
        all_data = []
        for f in files:
            all_data.extend(process_interfood_pdf(f))
        
        if all_data:
            df = pd.DataFrame(all_data)
            st.success(f"{len(df)} ügyfél feldolgozva.")
            st.dataframe(df[['ID', 'Ügyintéző', 'Cím', 'Telefon', 'Pénz', 'Megjegyzés']])
            
            col1, col2 = st.columns(2)
            with col1:
                st.download_button("Etikettek Letöltése", create_labels(df), "etikettek.pdf")
            with col2:
                # Itt a menetterv generátor is hívható (a korábbi MOD8-as kódból)
                pass

if __name__ == "__main__":
    main()
