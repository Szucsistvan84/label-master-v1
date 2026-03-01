import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. PROFI ADATTISZTÍTÓ (v67) ---
def clean_v67(raw_name, raw_block_text):
    # 1. Név tisztítása
    name = re.sub(r'^[A-Z]-\d+\s+', '', raw_name) # P-123456 le
    name = re.sub(r'^\d+\s+', '', name).strip()    # Sorszám le
    
    # Tiltólista (cégek, amik bekavarhatnak)
    trash = ["Csokimax", "Ford", "Expert", "Globiz", "International", "Kft", "Zrt", "Bt", 
             "Harro", "Höfliger", "Hungary", "Richter", "Gedeon", "Krones", "Mo.kft", "üzlet"]
    
    for t in trash:
        name = re.sub(r'\b' + t + r'\b', '', name, flags=re.IGNORECASE).strip()
    
    # Ha maradt benne perjel vagy kötőjel a szélén, levágjuk
    name = name.strip("/- ").strip()
    
    # 2. Telefonszám (Intenzívebb keresés)
    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', raw_block_text)
    tel = tel_m.group(1) if tel_m else "NINCS"
    
    # 3. Cím (4 jegyű irányítószám keresése)
    addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b.*)', raw_block_text)
    addr = addr_m.group(1).strip() if addr_m else "Cím nem található"
    
    # 4. Rendelés
    rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', raw_block_text)))))
    
    return name, tel, addr, rend

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v67(df):
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
        
        pdf.set_xy(x + 5, y + 32)
        pdf.set_font(f_name, "", 7)
        pdf.cell(60, 4, f"REND: {row['Rendelés']}", 0, 1)
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v67")
f = st.file_uploader("Interfood PDF feltöltése", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Keressük a sorszámokat
            markers = [w for w in words if re.match(r'^\d+$', w['text']) and w['x0'] < 550]
            markers.sort(key=lambda x: (x['top'], x['x0']))
            
            for m in markers:
                # --- A HIBA JAVÍTÁSA: BIZTONSÁGI HATÁROK ---
                x0 = max(0, m['x0'] - 2)
                top = max(0, m['top'] - 2)
                x1 = min(page.width, x0 + 190)   # Nem mehet túl a lap szélén
                bottom = min(page.height, top + 55) # Nem mehet le a lapról
                
                box = (x0, top, x1, bottom)
                
                try:
                    crop = page.within_bbox(box)
                    block_text = crop.extract_text()
                    
                    if block_text:
                        lines = block_text.split('\n')
                        raw_name = lines[0]
                        name, tel, addr, rend = clean_v67(raw_name, block_text)
                        
                        if len(name) > 2:
                            results.append({
                                "Ügyintéző": name,
                                "Telefon": tel,
                                "Cím": addr,
                                "Rendelés": rend
                            })
                except Exception:
                    continue # Ha mégis hiba lenne, ugorja át ezt a rekordot

    df = pd.DataFrame(results).drop_duplicates(subset=['Ügyintéző', 'Cím']).reset_index(drop=True)
    st.dataframe(df)
    
    if not df.empty:
        pdf_bytes = create_pdf_v67(df)
        if pdf_bytes:
            st.download_button("💾 PDF LETÖLTÉSE (v67)", bytes(pdf_bytes), "etikettek_v67.pdf", "application/pdf")
