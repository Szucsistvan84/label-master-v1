import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. RADIKÁLIS TISZTÍTÓ LOGIKA (v53) ---
def super_clean_v53(text, address_text):
    # Tiltólista az általad küldött példák alapján
    blacklist = [
        "Csokimax", "Harro Höfliger", "Hungary", "DKM", "Pearl Enterprises", "Kft", "Zrt",
        "DEKK Kenézy Gyula", "KCS", "Fest-É-ker", "RZK", "Triton Services", "Lapostetős",
        "Matrackirály", "ZsoZso Color", "LGM", "DMJV Hiv", "VDK", "Ker Ipark", "Fsz",
        "HARAPÓS", "Bolt", "CATL", "Krones", "Globiz", "International", "Ford", "Expert",
        "HKH", "Mister Minit", "Pláza", "Optipont", "Richter Gedeon", "Zaza", "Süteményes"
    ]
    
    # 1. Lépés: Teljes kifejezések törlése
    clean_text = text
    for item in blacklist:
        clean_text = re.sub(re.escape(item), '', clean_text, flags=re.IGNORECASE)
    
    # 2. Lépés: Utcanév szavak kiszűrése a címből
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    
    # 3. Lépés: Nevek kinyerése (Nagybetűvel kezdődő, legalább 3 betűs szavak)
    # Kizárjuk a Debrecen, Sorszám és a fenti blacklist szavait
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    final_name_parts = []
    for w in words:
        upper_w = w.upper()
        if (w not in ["Debrecen", "Sorszám", "Összesen"] and 
            w not in addr_words and 
            upper_w not in [b.upper() for b in blacklist] and
            len(w) > 2):
            if w not in final_name_parts:
                final_name_parts.append(w)
    
    # Csak az első 2-3 szót tartjuk meg (Vezetéknév + Keresztnév + esetleg jelző)
    return " ".join(final_name_parts[:3]).strip()

# --- 2. PDF GENERÁLÁS (Telefonszámmal és Összesítővel) ---
def create_pdf_v53(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    # Fontok ellenőrzése
    font_reg, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    if os.path.exists(font_reg):
        pdf.add_font("DejaVu", style="", fname=font_reg)
        pdf.add_font("DejaVu", style="B", fname=font_bold)
        f_name = "DejaVu"
    else:
        st.error("Fontok hiányoznak!")
        return None

    label_w, label_h = 70, 42.4
    
    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * label_w, line * label_h
        
        # NÉV
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
        # TELEFON (Ha van)
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 9)
        pdf.cell(60, 5, f"Tel: {row['Telefon']}", 0, 1)
        
        # CÍM
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 9)
        pdf.cell(60, 5, str(row['Cím']), 0, 1)
        
        # RENDELÉS (Összesítve)
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "B", 8)
        pdf.multi_cell(60, 4, f"Rendelés: {row['Rendelés']}", 0)
        
    return pdf.output()

# --- 3. UI ÉS ADATKINYERÉS ---
st.title("Interfood Etikett Mester v53")
f = st.file_uploader("Interfood PDF", type="pdf")

if f:
    extracted_data = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Sorszám markerek
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                
                # Cím
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                # Telefon (06 vagy +36 formátum keresése)
                tel_m = re.search(r'((?:\+36|06)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block)
                tel = tel_m.group(1) if tel_m else "Nincs megadva"
                
                # Név tisztítása a v53 logikával
                name = super_clean_v53(block, cim)
                
                # Rendelés kódok (pl. 1-A, 2-D12)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', block)
                rend_text = ", ".join(rendelesek)
                
                extracted_data.append({
                    "Sorszám": markers[i]['num'], 
                    "Ügyintéző": name, 
                    "Telefon": tel,
                    "Cím": cim, 
                    "Rendelés": rend_text
                })
    
    df = pd.DataFrame(extracted_data)
    st.dataframe(df)
    
    pdf_bytes = create_pdf_v53(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE", bytes(pdf_bytes), "etikettek_v53.pdf", "application/pdf")
