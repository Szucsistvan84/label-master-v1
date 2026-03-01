import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. TISZTÍTÓ LOGIKA (v73 - Finomhangolt verzió) ---
def clean_v73(block_text):
    lines = [l.strip() for l in block_text.split('\n') if l.strip()]
    if not lines:
        return "Névtelen", "NINCS", "Cím nem található", ""

    # NÉV: Az első sorból csak a technikai kódot vágjuk le (pl. P-123456)
    name = re.sub(r'^[A-Z]-\d+\s+', '', lines[0]).strip()
    # Ha maradt még sorszám az elején, azt is levágjuk
    name = re.sub(r'^\d+\s+', '', name).strip()
    
    # TELEFON: Bárhol keressük a blokkban
    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text)
    tel = tel_m.group(1) if tel_m else "NINCS"
    
    # CÍM: Megkeressük az irányítószámot (4 számjegy)
    addr = "Cím nem található"
    for line in lines:
        if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line):
            addr = line.strip()
            break
    
    # RENDELÉS: Minden kódot kigyűjtünk (pl. 1-DK)
    rend_list = sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text))))
    rend = ", ".join(rend_list) if rend_list else "Nincs kód"
    if len(rend_list) > 20: rend = "ÖSSZESÍTŐ"

    return name, tel, addr, rend

# --- 2. PDF GENERÁLÁS (A JÓL BEVÁLT FIX RÁCS) ---
def create_pdf_v73(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path = "DejaVuSans.ttf" 
    f_main = "DejaVu" if os.path.exists(font_path) else "Arial"
    if f_main == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=font_path)
        pdf.add_font("DejaVu", style="B", fname="DejaVuSans-Bold.ttf")

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        # Név
        pdf.set_xy(x + 5, y + 4)
        pdf.set_font(f_main, "B", 10)
        pdf.multi_cell(60, 4.5, str(row['Ügyintéző'])[:50], 0, 'L')
        
        # Telefon
        pdf.set_xy(x + 5, y + 14)
        pdf.set_font(f_main, "B", 9)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        
        # Cím
        pdf.set_xy(x + 5, y + 19)
        pdf.set_font(f_main, "", 8)
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        
        # Rendelés
        pdf.set_xy(x + 5, y + 28) 
        pdf.set_font(f_main, "", 7)
        pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
        
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v73")
f = st.file_uploader("Feltöltés (PDF)", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Horgony keresése: szám, amit P- vagy Z- kód követ
            for i in range(len(words) - 1):
                if re.match(r'^\d+$', words[i]['text']) and re.match(r'^[A-Z]-\d+$', words[i+1]['text']):
                    x0, top = words[i]['x0'] - 2, words[i]['top'] - 2
                    crop = page.within_bbox((x0, top, x0 + 200, top + 80))
                    text = crop.extract_text()
                    if text:
                        n, t, a, r = clean_v73(text)
                        if "ÖSSZESÍTŐ" not in r:
                            results.append({"Ügyintéző": n, "Telefon": t, "Cím": a, "Rendelés": r})

    df = pd.DataFrame(results).drop_duplicates(subset=['Ügyintéző', 'Cím']).reset_index(drop=True)
    st.dataframe(df)
    if not df.empty:
        pdf_out = create_pdf_v73(df)
        st.download_button("💾 PDF LETÖLTÉSE (v73)", bytes(pdf_out), "etikettek_v73.pdf", "application/pdf")
