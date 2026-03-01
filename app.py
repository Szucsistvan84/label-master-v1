import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. AZ ULTIMATE TISZTÍTÓ LOGIKA (v54) ---
def ultra_clean_v54(text, address_text):
    # Brutális tiltólista a beküldött adatok alapján
    hard_blacklist = [
        "Portán", "Kérlek", "CICA", "HARAPÓS", "OTP", "Gázkészülék", "Gázkészülékbolt",
        "Hiv", "DMJV", "Móricz", "Kormányhivatal", "Férfi", "Fodrászat", "Ker Ipark",
        "Javítsd Magad", "Csemege", "Gyógyszertár", "Általános", "Iskola", "Kft", "Zrt",
        "Hungary", "DKM", "KCS", "CATL", "Globiz", "International", "Ford", "Pearl",
        "Expert", "Mister Minit", "Pláza", "Optipont", "Richter", "Gedeon", "Zaza",
        "Süteményes", "Fsz", "VDK", "LGM", "RZK", "DEKK", "Kenézy", "Triton"
    ]
    
    clean_text = text
    # 1. Töröljük a cím szavait a szövegből (hogy ne legyen 'Házgyár István')
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    
    # 2. Szavakra bontás és szűrés
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    final_name_parts = []
    for w in words:
        # Tisztítás: csak akkor tartjuk meg, ha nincs a tiltólistán és nem a város neve
        if (w not in ["Debrecen", "Sorszám", "Összesen", "Rendelés", "Telefon"] and 
            w not in addr_words and 
            w not in hard_blacklist and
            not any(x.upper() in w.upper() for x in hard_blacklist) and
            len(w) > 2):
            
            if w not in final_name_parts:
                final_name_parts.append(w)
    
    # Különleges eset: "Asztalos Károlyné Nem" -> "Nem" törlése ha a név után van
    if len(final_name_parts) > 1 and final_name_parts[-1] in ["Nem", "Vagyok", "Itthon"]:
        final_name_parts.pop()

    return " ".join(final_name_parts[:3]).strip()

# --- 2. PDF GENERÁLÁS (A kért tartalommal) ---
def create_pdf_v54(df):
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
        
        # Ügyintéző Neve
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
        # Telefonszám
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 9)
        pdf.cell(60, 5, f"Tel: {row['Telefon']}", 0, 1)
        
        # Cím
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 8)
        pdf.cell(60, 5, str(row['Cím']), 0, 1)
        
        # Rendelés összesítő
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "B", 8)
        pdf.multi_cell(60, 4, f"Rend: {row['Rendelés']}", 0)
        
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v54")
f = st.file_uploader("Interfood PDF feltöltése", type="pdf")

if f:
    extracted = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top, bottom = markers[i]['top'], (markers[i+1]['top'] if i+1 < len(markers) else page.height)
                block = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                
                # Cím, Telefon, Rendelés kinyerése
                cim = (re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block).group(1) if re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block) else "")
                tel = (re.search(r'((?:\+36|06)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block).group(1) if re.search(r'((?:\+36|06)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block) else "Nincs megadva")
                rend_codes = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block))
                
                # A NÉV TISZTÍTÁSA
                name = ultra_clean_v54(block, cim)
                
                extracted.append({"Sorszám": markers[i]['num'], "Ügyintéző": name, "Telefon": tel, "Cím": cim, "Rendelés": rend_codes})
    
    df = pd.DataFrame(extracted)
    st.dataframe(df)
    
    pdf_out = create_pdf_v54(df)
    if pdf_out:
        st.download_button("💾 PDF LETÖLTÉSE (v54)", bytes(pdf_out), "etikettek_v54.pdf", "application/pdf")
