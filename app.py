import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os
from io import BytesIO

# --- 1. TISZTÍTÓ LOGIKA ---
def clean_name_v52(text, address_text):
    blacklist = ["Richter Gedeon", "Zaza Süteményes", "István csemege", "Gyógyszertár", "Kérlek", "Csemege"]
    clean_text = text
    for b in blacklist:
        clean_text = re.sub(re.escape(b), '', clean_text, flags=re.IGNORECASE)
    
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    final = []
    for w in words:
        if w not in ["Debrecen", "Sorszám"] and w not in addr_words and len(w) > 2:
            if w not in final: final.append(w)
    return " ".join(final[:3])

# --- 2. PDF GENERÁLÁS (BytesIO-val a biztos letöltésért) ---
def create_pdf_v52(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    reg_font = "DejaVuSans.ttf"
    bold_font = "DejaVuSans-Bold.ttf"
    
    if os.path.exists(reg_font) and os.path.exists(bold_font):
        pdf.add_font("DejaVu", style="", fname=reg_font)
        pdf.add_font("DejaVu", style="B", fname=bold_font)
        f_name = "DejaVu"
    else:
        st.error("Hiányzó betűtípus fájlok a GitHubon!")
        return None

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        pdf.set_xy(x + 5, y + 10)
        pdf.set_font(f_name, "B", 12)
        pdf.cell(60, 6, str(row['Ügyintéző']), 0, 1)
        
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 9)
        pdf.cell(60, 5, str(row['Cím']), 0, 1)
        
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 7)
        pdf.multi_cell(60, 4, f"Rendelés: {row['Rendelés']}", 0)
        
    # PDF generálása bájtokként
    return pdf.output()

# --- 3. UI ÉS FŐPROGRAM ---
st.set_page_config(page_title="Etikett Mester v52")
st.title("Interfood Etikett Mester")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                cim = (re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block).group(1) if re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block) else "")
                name = clean_name_v52(block, cim)
                rend = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block))
                data.append({"Sorszám": markers[i]['num'], "Ügyintéző": name, "Cím": cim, "Rendelés": rend})
    
    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True)
    
    # Letöltési szekció
    st.divider()
    pdf_bytes = create_pdf_v52(df)
    
    if pdf_bytes:
        st.download_button(
            label="💾 PDF LETÖLTÉSE",
            data=bytes(pdf_bytes), # Biztos bájtokká alakítás
            file_name="interfood_etikettek.pdf",
            mime="application/pdf",
            use_container_width=True
        )
