import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. PROFI NÉVSZŰRŐ (v64) ---
def clean_name_v64(text):
    # Országos tiltólista (intézmények, kódok, sallangok)
    trash = [
        "Mo.kft", "Kft", "Zrt", "Bt", "Kft.", "Hungary", "International", "Services", "Expert", 
        "Ford", "Szalon", "Richter", "Gedeon", "Harro", "Höfliger", "Krones", "Globiz", "Csokimax",
        "P-", "Z-", "Nem", "Összesítés", "Ifjúsági", "Portán", "Házgyár", "Határ", "Bánki", "Donát"
    ]
    
    # Tisztítás: számok és technikai kódok le az elejéről
    name = re.sub(r'^[A-Z]-\d+\s+', '', text)
    name = re.sub(r'^\d+\s+', '', name)
    
    words = name.split()
    final_name = []
    for w in words:
        # Csak akkor marad, ha nincs a tiltólistán és nem tiszta nagybetűs kód
        if not any(t.lower() in w.lower() for t in trash) and not (w.isupper() and len(w) > 4):
            final_name.append(w)
    
    # Ha túl sok maradt, csak az első 3 szót vesszük (Vezetéknév + Keresztnév + esetleg -né)
    return " ".join(final_name[:3]).strip()

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v64(df):
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
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
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
st.title("Interfood Etikett Mester v64")
f = st.file_uploader("Interfood PDF feltöltése", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # 1. Keressük a sorszámokat (ezek a horgonyok)
            markers = [w for w in words if w['x0'] < 50 and re.match(r'^\d+$', w['text'])]
            
            for m in markers:
                # 2. Definiáljuk a zónát a sorszám körül
                # NÉV: a sorszám mellett közvetlenül
                name_words = [w for w in words if abs(w['top'] - m['top']) < 4 and w['x0'] > m['x1'] and w['x0'] < 250]
                raw_name = " ".join([w['text'] for w in name_words])
                
                # CÍM: a sorszám alatt (kb. 10-25 pixel távolságra)
                addr_words = [w for w in words if m['top'] + 5 < w['top'] < m['top'] + 30 and w['x0'] < 250]
                raw_addr = " ".join([w['text'] for w in addr_words])
                
                # TELEFON ÉS RENDELÉS (a környezetben)
                context_words = [w for w in words if m['top'] - 5 < w['top'] < m['top'] + 50]
                context_text = " ".join([w['text'] for w in context_words])
                
                tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', context_text)
                tel = tel_m.group(1) if tel_m else "NINCS"
                
                rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', context_text)))))
                
                # Tisztítás
                clean_name = clean_name_v64(raw_name)
                # Cím: ha találunk irányítószámot, onnantól vesszük
                cim_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', raw_addr)
                cim = cim_m.group(1).strip() if cim_m else raw_addr
                
                if len(clean_name) > 2:
                    results.append({"Ügyintéző": clean_name, "Telefon": tel, "Cím": cim, "Rendelés": rend})

    df = pd.DataFrame(results).drop_duplicates().reset_index(drop=True)
    st.dataframe(df)
    
    pdf_bytes = create_pdf_v64(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v64)", bytes(pdf_bytes), "etikettek_v64.pdf", "application/pdf")
