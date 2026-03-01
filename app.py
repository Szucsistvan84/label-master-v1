import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. AZ ORSZÁGOS NÉV-TISZTÍTÓ (v65) ---
def clean_name_v65(text):
    # 1. Technikai sallangok törlése (P-123456, Z-123456 és sorszámok)
    name = re.sub(r'^[A-Z]-\d+\s+', '', text)
    name = re.sub(r'^\d+\s+', '', name)
    
    # 2. Gyakori cégjelzések, amik nem részei a névnek
    trash = ["Kft", "Zrt", "Bt", "Kft.", "Hungary", "International", "Services", "Expert", 
             "Ford", "Richter", "Gedeon", "Harro", "Höfliger", "Krones", "Globiz", "Csokimax",
             "Portán", "Házgyár", "Határ", "Campus", "Klinika", "Kormányhivatal"]
    
    for t in trash:
        # Csak ha különálló szóként szerepel
        name = re.sub(r'\b' + t + r'\b', '', name, flags=re.IGNORECASE).strip()
    
    # 3. Tisztítás az írásjelektől
    name = name.replace("/", "").replace("- ", "-").strip()
    
    # 4. Ha a név még mindig túl hosszú (pl. cég maradt benne), 
    # megpróbáljuk az első 2-3 nagybetűs szót megtartani
    parts = name.split()
    if len(parts) > 3:
        return " ".join(parts[-3:]) # Általában a név a sor végén van
    return name

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v65(df):
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
        pdf.set_font(f_name, "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:35], 0, 1)
        
        pdf.set_font(f_name, "B", 9)
        pdf.set_x(x + 5)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        
        pdf.set_font(f_name, "", 8)
        pdf.set_x(x + 5)
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0)
        
        pdf.set_font(f_name, "", 7)
        pdf.set_x(x + 5)
        pdf.cell(60, 4, f"REND: {row['Rendelés']}", 0, 1)
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v65 - Hasáb-Bontó")
f = st.file_uploader("Eredeti Interfood PDF", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            # AZ OLDAL FELBONTÁSA 3 FÜGGŐLEGES HASÁBRA
            # (Az Interfood PDF szélessége kb. 595 pont)
            width = page.width
            col_width = width / 3
            
            for c in range(3):
                # Kivágjuk az adott oszlopot
                bbox = (c * col_width, 0, (c + 1) * col_width, page.height)
                column = page.within_bbox(bbox)
                
                # Oszlopon belüli blokkok keresése sorszám alapján
                words = column.extract_words()
                markers = [w for w in words if w['x0'] < (c * col_width + 40) and re.match(r'^\d+$', w['text'])]
                
                for i, m in enumerate(markers):
                    top = m['top']
                    bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                    
                    # Csak a két sorszám közötti területet nézzük
                    block = column.within_bbox((c * col_width, top - 2, (c + 1) * col_width, bottom - 2))
                    block_text = block.extract_text()
                    
                    if not block_text: continue
                    lines = block_text.split('\n')
                    
                    # NÉV: Az első sor (kivéve ha az csak egy magányos szám)
                    raw_name = lines[0]
                    # CÍM: Keressük az irányítószámot (4 számjegy)
                    cim = ""
                    for line in lines:
                        if re.search(r'\d{4}\s+', line):
                            cim = line.strip()
                            break
                    
                    # TEL & REND
                    tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text)
                    tel = tel_m.group(1) if tel_m else "NINCS"
                    rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text)))))
                    
                    results.append({
                        "Ügyintéző": clean_name_v65(raw_name),
                        "Telefon": tel,
                        "Cím": cim if cim else "Cím nem található",
                        "Rendelés": rend
                    })

    df = pd.DataFrame(results)
    st.dataframe(df)
    
    pdf_bytes = create_pdf_v65(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v65)", bytes(pdf_bytes), "etikettek_v65.pdf", "application/pdf")
