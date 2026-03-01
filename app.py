import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. A LEGFINOMABB NÉVTISZTÍTÓ (v62) ---
def advanced_name_cleaner_v62(text, address_text):
    # 1. Technikai kódok és sorszámok eltávolítása (pl. P-428867, 24, stb.)
    name = re.sub(r'^[A-Z]-\d+\s+', '', text)
    name = re.sub(r'^\d+\s+', '', name)
    
    # 2. Cím szavainak kiszűrése (Hogy ne legyen "Házgyár Tőkés")
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b', address_text)
    
    # 3. Tiltólista (Cégek, helyszínek, utasítások)
    trash = [
        "Csokimax", "Harro", "Höfliger", "Hungary", "Pearl", "Enterprises", "Globiz", "International",
        "Expert", "Ford", "Krones", "Kft", "Zrt", "Bt", "Hiv", "DMJV", "VDK", "DKM", "Campus", "Kenézy",
        "Gyula", "Iskola", "Általános", "Férfi", "Fodrászat", "Gázkészülék", "Süteményes", "Zaza",
        "Services", "LGM", "Javítsd", "Magad", "Nem", "Ifjúsági", "Portán", "Kérlek", "Csemege", "Bolt"
    ]
    
    # Szavakra bontjuk a talált nevet
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', name)
    
    final_parts = []
    for w in words:
        # Csak akkor tartjuk meg, ha:
        # - nincs a tiltólistán
        # - nem a cím része
        # - nem Debrecen
        is_bad = any(t.lower() in w.lower() for t in trash)
        if not is_bad and w not in addr_words and w != "Debrecen":
            if w not in final_parts:
                final_parts.append(w)
    
    # Ha a végén maradt valami felesleg (pl. "Összesítés"), levágjuk
    res = " ".join(final_parts[:3]).strip()
    return res if res else "Ismeretlen"

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v62(df):
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
st.title("Interfood Etikett Mester v62")
f = st.file_uploader("Interfood PDF feltöltése", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Keressük a sorszámokat a bal szélen
            markers = [w for w in words if w['x0'] < 45 and re.match(r'^\d+$', w['text'])]
            
            for i, m in enumerate(markers):
                top = m['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                # A teljes blokk szövege az adatok kinyeréséhez
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                full_text = " ".join([w['text'] for w in block_words])
                
                # 1. Cím (Precízebb keresés országos formátumra)
                cim_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b,?\s+.*?(\d+[\s/]*[A-Z-]*\.?))', full_text)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                # 2. Név (Csak a sorszám melletti szavak)
                name_line_words = [w for w in block_words if abs(w['top'] - top) < 3]
                raw_name_text = " ".join([w['text'] for w in name_line_words])
                clean_name = advanced_name_cleaner_v62(raw_name_text, cim)
                
                # 3. Telefon
                tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', full_text)
                tel = tel_m.group(1) if tel_m else "NINCS"
                
                # 4. Rendelés
                rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', full_text)))))
                
                results.append({"Ügyintéző": clean_name, "Telefon": tel, "Cím": cim, "Rendelés": rend})

    df = pd.DataFrame(results)
    st.dataframe(df)
    pdf_bytes = create_pdf_v62(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v62)", bytes(pdf_bytes), "etikettek_v62.pdf", "application/pdf")
