import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. A LEGEGYSZERŰBB, DE LEGBIZTOSABB TISZTÍTÓ (v63) ---
def clean_row_v63(raw_name, raw_address):
    # Csak a legszükségesebb vágások:
    # 1. Levágjuk a technikai kódokat az elejéről (P-428867 vagy Z-410511)
    name = re.sub(r'^[A-Z]-\d+\s+', '', raw_name).strip()
    # 2. Levágjuk a sorszámot, ha még ott van
    name = re.sub(r'^\d+\s+', '', name).strip()
    # 3. Levágjuk a "Nem", "Összesítés", "Ifjúsági" szavakat a végéről, ha ott vannak
    name = re.sub(r'\s(Nem|Összesítés|Ifjúsági|Portán)$', '', name).strip()
    
    # Cím tisztítása (csak a felesleges szóközök)
    address = raw_address.strip()
    
    return name, address

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v63(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_reg, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    if os.path.exists(font_reg):
        pdf.add_font("DejaVu", style="", fname=font_reg); pdf.add_font("DejaVu", style="B", fname=font_bold)
        f_name = "DejaVu"
    else: return None

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 10) # Kicsit kisebb betű, hogy beférjen minden
        pdf.cell(60, 5, str(row['Ügyintéző'])[:35], 0, 1) # Max 35 karakter
        
        pdf.set_font(f_name, "B", 9)
        pdf.set_x(x + 5)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        
        pdf.set_font(f_name, "", 8)
        pdf.set_x(x + 5)
        pdf.multi_cell(60, 4, str(row['Cím']), 0)
        
        pdf.set_font(f_name, "", 7)
        pdf.set_x(x + 5)
        pdf.cell(60, 4, f"REND: {row['Rendelés']}", 0, 1)
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v63")
f = st.file_uploader("Interfood PDF feltöltése", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            # Sorokra bontjuk a szöveget, megőrizve a sorrendet
            lines = page.extract_text().split('\n')
            
            for i in range(len(lines)):
                # Keressük a sort, ami sorszámmal kezdődik (pl. "24 Kovács János")
                if re.match(r'^\d+\s+', lines[i]) or re.match(r'^[A-Z]-\d+', lines[i]):
                    raw_name_line = lines[i]
                    
                    # A cím általában a következő sorban van, ami irányítószámmal kezdődik
                    raw_addr_line = ""
                    if i + 1 < len(lines):
                        raw_addr_line = lines[i+1]
                    
                    # Telefonszám és Rendelés keresése a környező sorokban
                    # (Megnézzük a következő 3 sort)
                    context = " ".join(lines[i:i+4])
                    tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', context)
                    tel = tel_m.group(1) if tel_m else "NINCS"
                    
                    rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', context)))))
                    
                    # Tisztítás
                    name, addr = clean_row_v63(raw_name_line, raw_addr_line)
                    
                    # Csak akkor adjuk hozzá, ha a cím tényleg címnek néz ki (van benne 4 számjegy)
                    if re.search(r'\d{4}', addr):
                        results.append({"Ügyintéző": name, "Telefon": tel, "Cím": addr, "Rendelés": rend})

    df = pd.DataFrame(results)
    # Duplikátumok szűrése (ha egy embert többször talált meg a sorok miatt)
    df = df.drop_duplicates(subset=['Ügyintéző', 'Cím']).reset_index(drop=True)
    st.dataframe(df)
    
    pdf_bytes = create_pdf_v63(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v63)", bytes(pdf_bytes), "etikettek_v63.pdf", "application/pdf")
