import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. PROFI ADATTISZTÍTÓ (v66) ---
def clean_v66(raw_name, raw_block_text):
    # 1. Név tisztítása
    # Eltávolítjuk a technikai kódokat (P-..., Z-...) és a sorszámokat
    name = re.sub(r'^[A-Z]-\d+\s+', '', raw_name)
    name = re.sub(r'^\d+\s+', '', name).strip()
    
    # Tiltólista (cégek, helyszínek)
    trash = ["Csokimax", "Ford", "Expert", "Globiz", "International", "Kft", "Zrt", "Bt", 
             "Harro", "Höfliger", "Hungary", "Richter", "Gedeon", "Krones", "Mo.kft"]
    
    for t in trash:
        name = re.sub(r'\b' + t + r'\b', '', name, flags=re.IGNORECASE).strip()
    
    # 2. Telefonszám keresése (kibővített regex az Interfood formátumokhoz)
    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', raw_block_text)
    tel = tel_m.group(1) if tel_m else "NINCS"
    
    # 3. Cím keresése (4 jegyű irányítószámmal kezdődő sor)
    addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b.*)', raw_block_text)
    addr = addr_m.group(1).strip() if addr_m else "Cím nem található"
    
    # 4. Rendelés (Ételkódok)
    rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', raw_block_text)))))
    
    return name, tel, addr, rend

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v66(df):
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
        # Multi-cell a címnek, hogy ne vágjuk le
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0)
        
        pdf.set_font(f_name, "", 7)
        pdf.set_xy(x + 5, y + 32)
        pdf.cell(60, 4, f"REND: {row['Rendelés']}", 0, 1)
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v66")
f = st.file_uploader("Feltöltés", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Sorszámok keresése (a PDF-ben ezek a kis számok a blokkok elején)
            markers = [w for w in words if re.match(r'^\d+$', w['text']) and w['x0'] < 550]
            
            # Sorszámok rendezése: először függőlegesen, aztán vízszintesen
            markers.sort(key=lambda x: (x['top'], x['x0']))
            
            for m in markers:
                # Egy "dobozt" képzelünk a sorszám köré (kb. 180 pixel széles, 50 magas)
                # Ez lefedi az adott ügyfél teljes blokkját
                box = (m['x0'] - 2, m['top'] - 2, m['x0'] + 185, m['top'] + 50)
                crop = page.within_bbox(box)
                block_text = crop.extract_text()
                
                if block_text:
                    lines = block_text.split('\n')
                    raw_name = lines[0]
                    name, tel, addr, rend = clean_v66(raw_name, block_text)
                    
                    if len(name) > 2:
                        results.append({
                            "Ügyintéző": name,
                            "Telefon": tel,
                            "Cím": addr,
                            "Rendelés": rend
                        })

    df = pd.DataFrame(results).drop_duplicates().reset_index(drop=True)
    st.dataframe(df)
    
    if not df.empty:
        pdf_bytes = create_pdf_v66(df)
        st.download_button("💾 PDF LETÖLTÉSE (v66)", bytes(pdf_bytes), "etikettek_v66.pdf", "application/pdf")
