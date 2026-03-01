import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. A LEGSZIGORÚBB NÉV-TISZTÍTÓ (v56) ---
def final_name_cleaner_v56(text, address_text):
    # Brutális tiltólista (szavak és töredékek)
    blacklist = [
        "Csokimax", "Harro", "Höfliger", "Hungary", "DKM", "Pearl", "Enterprises", "Kft", "Zrt",
        "DEKK", "Kenézy", "KCS", "Fest-É-ker", "RZK", "Triton", "Services", "Lapostetős",
        "Matrackirály", "ZsoZso", "Color", "LGM", "DMJV", "Hiv", "VDK", "Ker Ipark", "Fsz",
        "HARAPÓS", "CICA", "Bolt", "CATL", "Krones", "Globiz", "International", "Ford", "Expert",
        "HKH", "Mister", "Minit", "Pláza", "Optipont", "Richter", "Gedeon", "Zaza", "Süteményes",
        "Portán", "Kérlek", "Köszönöm", "OTP", "Gázkészülék", "Kormányhivatal", "Fodrászat", 
        "Iskola", "Általános", "Medgyessy", "Javítsd", "Magad", "Csemege", "Házgyár", "Határ"
    ]

    # Cím darabjainak eltávolítása (pl. 'Richter Gedeon u.' ne legyen a névben)
    addr_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    
    # Csak nagybetűs szavak kigyűjtése
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', text)
    
    filtered = []
    for w in words:
        is_bad = False
        for bad in blacklist:
            if bad.lower() in w.lower(): is_bad = True; break
        
        if not is_bad and w not in ["Debrecen", "Sorszám", "Összesen"] and w not in addr_parts and len(w) > 2:
            if w not in filtered: filtered.append(w)
    
    # Speciális eset: Ha "Kovácsné" után ott maradt valami szemét
    clean_res = " ".join(filtered[:3]).strip()
    return clean_res if clean_res else "Ismeretlen"

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v56(df):
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
        
        # NÉV
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
        # TELEFON (Kiemelve, ha van)
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
st.title("Interfood Etikett Mester v56")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    all_rows = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            text_full = page.extract_text()
            words = page.extract_words()
            
            # Sorszámok keresése
            markers = [{'num': w['text'], 'top': w['top'], 'bottom': 0} for w in words if w['x0'] < 45 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                # Az adott sorszámhoz tartozó szövegblokk kinyerése
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                block_text = " ".join([w['text'] for w in block_words])
                
                # CÍM KERESÉSE
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                # TELEFON KERESÉSE (Kibővített regex: 06..., +36..., 20/..., 30/..., 70/...)
                tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text)
                tel = tel_m.group(1) if tel_m else "NINCS"
                
                # Ha nem találta meg a blokkban, megnézzük a block_text végét hátha ott van "kopaszon"
                if tel == "NINCS":
                    tel_alt = re.search(r'(\d{2}/\d{3}-?\d{4})', block_text)
                    if tel_alt: tel = tel_alt.group(1)

                # NÉV TISZTÍTÁSA
                name = final_name_cleaner_v56(block_text, cim)
                
                # RENDELÉSEK
                rend_list = sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text))))
                rend_str = ", ".join(rend_list)
                
                all_rows.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": name,
                    "Telefon": tel,
                    "Cím": cim,
                    "Rendelés": rend_str
                })

    df = pd.DataFrame(all_rows)
    st.dataframe(df)
    
    pdf_bytes = create_pdf_v56(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v56)", bytes(pdf_bytes), "etikettek_v56.pdf", "application/pdf")
