import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. PROFI TISZTÍTÓ (v70) ---
def clean_v70(name_text, block_text):
    # Név alapozás
    name = re.sub(r'^[A-Z]-\d+\s+', '', name_text)
    name = re.sub(r'^\d+\s+', '', name).strip()
    
    # Judit és Tímea szétválasztása (cím alapján)
    if "Judit" in name and "Tímea" in name:
        if "Richter" in block_text:
            name = "Szabó-Salák Tímea"
        elif "Kígyóhagyma" in block_text:
            name = "Földi-Michnyóczki Judit"

    # Tiltólista (Optipont, Ford, Expert, stb. levágása)
    trash = ["Csokimax", "Ford", "Expert", "Globiz", "International", "Kft", "Zrt", "Bt", 
             "Harro", "Höfliger", "Hungary", "Richter", "Gedeon", "Portán", "Optipont", "üzlet"]
    
    for t in trash:
        name = re.sub(r'\b' + t + r'\b', '', name, flags=re.IGNORECASE).strip()
    
    name = name.strip("/- ").strip()

    # Telefonszám
    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text)
    tel = tel_m.group(1) if tel_m else "NINCS"
    
    # Cím (Irányítószám horgony)
    addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b.*)', block_text)
    addr = addr_m.group(1).strip() if addr_m else "Cím nem található"
    
    # RENDELÉS - Itt a lényeg: 50 felett vágunk csak!
    rend_list = sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text))))
    if len(rend_list) >= 50: 
        rend = "ÖSSZESÍTŐ LISTA (Kihagyva)"
    else:
        rend = ", ".join(rend_list)
        
    return name, tel, addr, rend

# --- 2. PDF GENERÁLÁS (Optimalizált helykihasználás) ---
def create_pdf_v70(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path = "DejaVuSans.ttf" 
    if os.path.exists(font_path):
        pdf.add_font("DejaVu", style="", fname=font_path)
        pdf.add_font("DejaVu", style="B", fname="DejaVuSans-Bold.ttf")
        f_main = "DejaVu"
    else:
        f_main = "Arial"

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        # NÉV
        pdf.set_xy(x + 5, y + 7)
        pdf.set_font(f_main, "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:38], 0, 1)
        
        # TEL
        pdf.set_font(f_main, "B", 9)
        pdf.set_x(x + 5)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        
        # CÍM (kicsit feljebb tolva)
        pdf.set_font(f_main, "", 8)
        pdf.set_x(x + 5)
        pdf.multi_cell(60, 3.2, str(row['Cím']), 0)
        
        # RENDELÉS (Apróbb betű a sok kódhoz)
        pdf.set_xy(x + 5, y + 26) 
        pdf.set_font(f_main, "", 6)
        pdf.multi_cell(60, 2.5, f"REND: {row['Rendelés']}", 0)
        
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v70")
f = st.file_uploader("Feltöltés (PDF)", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [w for w in words if re.match(r'^\d+$', w['text']) and w['x0'] < 550]
            markers.sort(key=lambda x: (x['top'], x['x0']))
            
            for m in markers:
                # Dinamikus ablak a sorszám körül
                x0, top = max(0, m['x0'] - 2), max(0, m['top'] - 2)
                x1, bottom = min(page.width, x0 + 195), min(page.height, top + 70)
                
                crop = page.within_bbox((x0, top, x1, bottom))
                block_text = crop.extract_text()
                
                if block_text:
                    lines = block_text.split('\n')
                    raw_name = lines[0]
                    
                    name, tel, addr, rend = clean_v70(raw_name, block_text)
                    
                    # Ha a név helyén csak egy irányítószám van, az hibás találat
                    if not re.match(r'^\d{4}', name) and len(name) > 2:
                        # Varga Ibolya összesítő szűrése
                        if "ÖSSZESÍTŐ" not in rend:
                            results.append({"Ügyintéző": name, "Telefon": tel, "Cím": addr, "Rendelés": rend})

    df = pd.DataFrame(results).drop_duplicates(subset=['Ügyintéző', 'Cím']).reset_index(drop=True)
    st.dataframe(df)
    
    if not df.empty:
        pdf_out = create_pdf_v70(df)
        st.download_button("💾 PDF LETÖLTÉSE (v70)", bytes(pdf_out), "etikettek_v70.pdf", "application/pdf")
