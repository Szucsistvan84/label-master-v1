import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. A LEGSZIGORÚBB TISZTÍTÓ (v58) ---
def ultra_clean_v58(text, address_text):
    # Minden olyan szó, ami NEM emberi név része az Interfood PDF-ben
    trash = [
        "Harro", "Höfliger", "Hungary", "Richter", "Gedeon", "Csokimax", "Globiz", 
        "International", "Expert", "Krones", "Kft", "Zrt", "DKM", "VDK", "Hiv", 
        "DMJV", "Móricz", "Medgyessy", "Iskola", "Általános", "Gyógyszertár", "Főnix",
        "OTP", "Gázkészülék", "Fodrászat", "CATL", "Wallau", "Mister", "Minit", "Pláza",
        "Nem", "Ifjúsági", "Összesítés", "Összesen", "Sorszám", "Portán", "Kérlek",
        "Csemege", "Javítsd", "Magad", "KCS", "RZK", "DEKK", "Kenézy", "Triton"
    ]

    # Cím darabjai
    addr_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    
    # Szavak kinyerése a blokkból
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', text)
    
    clean_parts = []
    for w in words:
        # Csak akkor tartjuk meg, ha nincs a tiltólistán, nem a cím része és nem Debrecen
        is_trash = any(t.lower() == w.lower() for t in trash)
        if not is_trash and w not in addr_parts and w != "Debrecen" and len(w) > 2:
            if w not in clean_parts:
                clean_parts.append(w)
    
    # Ha a név végén maradt egy magányos 'Kft' vagy 'Nem', levágjuk
    if clean_parts and clean_parts[-1] in ["Kft", "Nem", "Hiv"]:
        clean_parts.pop()

    return " ".join(clean_parts[:3]).strip()

# --- 2. PDF GENERÁLÁS (A megszokott 3x7 elrendezés) ---
def create_pdf_v58(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    font_reg, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    if os.path.exists(font_reg):
        pdf.add_font("DejaVu", style="", fname=font_reg)
        pdf.add_font("DejaVu", style="B", fname=font_bold)
        f_name = "DejaVu"
    else:
        st.error("Hiányzó fontok!")
        return None

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "B", 9)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 8)
        pdf.cell(60, 4, str(row['Cím']), 0, 1)
        
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 7)
        pdf.multi_cell(60, 3.5, f"REND: {row['Rendelés']}", 0)
        
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v58")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    extracted = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Sorszámok (a bal szélen)
            markers = [{'num': w['text'], 'top': w['top'], 'x1': w['x1']} for w in words if w['x0'] < 45 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                # CSAK a sorszámtól jobbra lévő szavakat nézzük a blokkon belül!
                # Ezzel kiejtjük a sorszám felett lévő cégneveket.
                block_words = [w for w in words if (top - 1.5 <= w['top'] < bottom - 2) and (w['x0'] >= markers[i]['x1'])]
                block_text = " ".join([w['text'] for w in block_words])
                
                # Összesítés levágása
                block_text = block_text.split("Összesítés")[0]
                
                # Adat kinyerés
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text)
                tel = tel_m.group(1) if tel_m else "NINCS"
                
                name = ultra_clean_v58(block_text, cim)
                
                rend_list = sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text))))
                
                extracted.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": name,
                    "Telefon": tel,
                    "Cím": cim,
                    "Rendelés": ", ".join(rend_list)
                })

    df = pd.DataFrame(extracted)
    st.dataframe(df)
    
    pdf_bytes = create_pdf_v58(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v58)", bytes(pdf_bytes), "etikettek_v58.pdf", "application/pdf")
