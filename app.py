import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- TISZTÍTÓ LOGIKA (v48) ---
def clean_name_v48(text, address_text):
    blacklist = ["Richter Gedeon", "Zaza Süteményes", "István csemege", "Gyógyszertár", "Kérlek", "Portán", "DKM", "KCS"]
    clean_text = text
    for b in blacklist:
        clean_text = re.sub(re.escape(b), '', clean_text, flags=re.IGNORECASE)
    
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    final = []
    for w in words:
        if w not in ["Debrecen"] and w not in addr_words and len(w) > 2:
            if w not in final: final.append(w)
    return " ".join(final[:3])

# --- PDF GENERÁLÁS HIBAKEZELÉSSEL ---
def create_pdf_v48(df):
    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=False)
        
        # Ellenőrizzük, látja-e a fájlokat
        reg_font = "DejaVuSans.ttf"
        bold_font = "DejaVuSans-Bold.ttf"
        
        if not os.path.exists(reg_font):
            st.error(f"Hiányzik a fájl: {reg_font}. Jelenlegi fájlok: {os.listdir('.')}")
            return None

        pdf.add_font("DejaVu", style="", fname=reg_font)
        pdf.add_font("DejaVu", style="B", fname=bold_font)
        
        for i, row in df.iterrows():
            if i % 21 == 0: pdf.add_page()
            col, line = i % 3, (i // 3) % 7
            x, y = col * 70, line * 42.4
            
            pdf.set_xy(x + 5, y + 10)
            pdf.set_font("DejaVu", "B", 12)
            pdf.cell(60, 6, str(row['Ügyintéző']), 0, 1)
            
            pdf.set_x(x + 5)
            pdf.set_font("DejaVu", "", 9)
            pdf.cell(60, 5, str(row['Cím']), 0, 1)
            
            pdf.set_x(x + 5)
            pdf.set_font("DejaVu", "", 7)
            pdf.multi_cell(60, 4, f"Rend: {row['Rendelés']}", 0)
            
        return pdf.output()
    except Exception as e:
        st.error(f"Belső hiba a PDF generálásakor: {e}")
        st.exception(e)
        return None

# --- UI ---
st.title("Interfood Etikett v48")

# Ellenőrző panel
with st.expander("Rendszerellenőrzés"):
    st.write("Jelenlegi mappa tartalma:", os.listdir('.'))
    if 'fpdf' in str(FPDF): st.write("✅ fpdf2 betöltve")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    all_data = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            for i in range(len(markers)):
                top, bottom = markers[i]['top'], (markers[i+1]['top'] if i+1 < len(markers) else page.height)
                block = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                cim = (re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block).group(1) if re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block) else "")
                name = clean_name_v48(block, cim)
                all_data.append({"Sorszám": markers[i]['num'], "Ügyintéző": name, "Cím": cim, "Rendelés": ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block))})
    
    df = pd.DataFrame(all_data)
    st.dataframe(df)
    
    if st.button("PDF ELŐÁLLÍTÁSA"):
        pdf_bytes = create_pdf_v48(df)
        if pdf_bytes:
            st.download_button("LETÖLTÉS MOST", pdf_bytes, "etikettek.pdf", "application/pdf")
