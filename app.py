import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. TISZTÍTÓ LOGIKA (v74 - Stabilizált) ---
def clean_v74(block_text):
    lines = [l.strip() for l in block_text.split('\n') if l.strip()]
    if not lines:
        return "Névtelen", "NINCS", "Cím nem található", ""

    # NÉV: Technikai kódok és sorszámok levágása
    name = re.sub(r'^[A-Z]-\d+\s+', '', lines[0]).strip()
    name = re.sub(r'^\d+\s+', '', name).strip()
    
    # TELEFON keresése a teljes blokkban
    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text)
    tel = tel_m.group(1) if tel_m else "NINCS"
    
    # CÍM keresése (irányítószám alapján)
    addr = "Cím nem található"
    for line in lines:
        if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line):
            addr = line.strip()
            break
    
    # RENDELÉS gyűjtés
    rend_list = sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text))))
    rend = ", ".join(rend_list) if rend_list else "Nincs kód"
    if len(rend_list) > 25: rend = "ÖSSZESÍTŐ"

    return name, tel, addr, rend

# --- 2. PDF GENERÁLÁS (Fix rács, hibátlan elrendezés) ---
def create_pdf_v74(df):
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
        
        pdf.set_xy(x + 5, y + 4)
        pdf.set_font(f_main, "B", 10)
        pdf.multi_cell(62, 4.5, str(row['Ügyintéző'])[:50], 0, 'L')
        
        pdf.set_xy(x + 5, y + 14)
        pdf.set_font(f_main, "B", 9)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        
        pdf.set_xy(x + 5, y + 19)
        pdf.set_font(f_main, "", 8)
        pdf.multi_cell(62, 3.5, str(row['Cím']), 0, 'L')
        
        pdf.set_xy(x + 5, y + 28) 
        pdf.set_font(f_main, "", 7)
        pdf.multi_cell(62, 3, f"REND: {row['Rendelés']}", 0, 'L')
        
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v74")
f = st.file_uploader("Feltöltés (Eredeti Interfood PDF)", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            for i in range(len(words) - 1):
                # Arany Horgony: Szám + P/Z kód
                if re.match(r'^\d+$', words[i]['text']) and re.match(r'^[A-Z]-\d+$', words[i+1]['text']):
                    # Biztonsági korlátok kiszámítása
                    x0 = max(0, words[i]['x0'] - 2)
                    top = max(0, words[i]['top'] - 2)
                    x1 = min(page.width, x0 + 200)
                    bottom = min(page.height, top + 80)
                    
                    try:
                        # Csak a lapon belüli területet vágjuk ki
                        crop = page.within_bbox((x0, top, x1, bottom))
                        text = crop.extract_text()
                        if text:
                            n, t, a, r = clean_v74(text)
                            if "ÖSSZESÍTŐ" not in r:
                                results.append({"Ügyintéző": n, "Telefon": t, "Cím": a, "Rendelés": r})
                    except Exception:
                        continue

    df = pd.DataFrame(results).drop_duplicates(subset=['Ügyintéző', 'Cím']).reset_index(drop=True)
    st.write(f"Talált ügyfelek száma: {len(df)}")
    st.dataframe(df)
    
    if not df.empty:
        pdf_out = create_pdf_v74(df)
        st.download_button("💾 PDF LETÖLTÉSE (v74)", bytes(pdf_out), "etikettek_v74.pdf", "application/pdf")
