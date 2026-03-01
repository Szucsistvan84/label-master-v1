import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. FINOMHANGOLT TISZTÍTÓ LOGIKA (v57) ---
def final_clean_v57(text, address_text):
    # Kibővített tiltólista a legújabb hibák alapján
    blacklist = [
        "Nem", "Ifjúsági", "Összesítés", "Összesen", "Sorszám", "Hiv", "VDK", "DKM", 
        "CICA", "Portán", "Kérlek", "Csokimax", "Gyógyszertár", "Főnix", "Ker Ipark",
        "OTP", "Gázkészülék", "Iskola", "Medgyessy", "Javítsd", "Magad", "Csemege",
        "Kft", "Zrt", "Hungary", "Expert", "Mister", "Minit", "Pláza", "Bolt"
    ]

    # Cím szavai ne zavarjanak be
    addr_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    
    # Szavak kinyerése (Nagybetűs, min 3 karakter, kivéve ha ékezetes rövid név)
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', text)
    
    filtered = []
    for w in words:
        # Ha a szó benne van a blacklistben vagy a cím része, kihagyjuk
        if (w not in blacklist and 
            w not in addr_parts and 
            not any(bad.lower() == w.lower() for bad in blacklist) and
            w != "Debrecen" and len(w) > 2):
            if w not in filtered:
                filtered.append(w)
    
    # Csak az első 2-3 szót tartjuk meg (Név)
    return " ".join(filtered[:3]).strip()

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v57(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    font_reg, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    if os.path.exists(font_reg):
        pdf.add_font("DejaVu", style="", fname=font_reg)
        pdf.add_font("DejaVu", style="B", fname=font_bold)
        f_name = "DejaVu"
    else:
        st.error("Fontok hiányoznak!")
        return None

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        # NÉV
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
        # TELEFON
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "B", 9)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        
        # CÍM
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 8)
        pdf.cell(60, 4, str(row['Cím']), 0, 1)
        
        # RENDELÉS
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 7)
        pdf.multi_cell(60, 3.5, f"REND: {row['Rendelés']}", 0)
        
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v57")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    all_rows = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 45 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                # Szigorúbb blokk-határ (hogy ne nyúljon át a következő sorba vagy az összesítőbe)
                block_words = [w for w in words if top - 1 <= w['top'] < bottom - 3]
                block_text = " ".join([w['text'] for w in block_words])
                
                # Ha a blokkban benne van az "Összesítés" szó, vágjuk le onnantól
                block_text = block_text.split("Összesítés")[0]
                
                # Adatok kinyerése
                cim = (re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text).group(1) if re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text) else "")
                tel = (re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text).group(1) if re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text) else "NINCS")
                
                # Név tisztítása
                name = final_clean_v57(block_text, cim)
                
                # Rendelések
                rend_list = sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text))))
                
                all_rows.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": name,
                    "Telefon": tel,
                    "Cím": cim,
                    "Rendelés": ", ".join(rend_list)
                })

    df = pd.DataFrame(all_rows)
    st.dataframe(df)
    
    pdf_bytes = create_pdf_v57(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v57)", bytes(pdf_bytes), "etikettek_v57.pdf", "application/pdf")
