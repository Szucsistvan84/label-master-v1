import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# 1. Függvény az adatok tisztításához
def clean_name_v50(text, address_text):
    # Munkahelyek és zavaró szavak listája
    blacklist = [
        "Richter Gedeon", "Zaza Süteményes", "István csemege", "Gyógyszertár", 
        "Kérlek", "Köszönöm", "Portán", "DKM", "KCS", "Hungary", "Csemege"
    ]
    clean_text = text
    for b in blacklist:
        clean_text = re.sub(re.escape(b), '', clean_text, flags=re.IGNORECASE)
    
    # Utcanév szavak kiszűrése (hogy ne legyen 'Házgyár István')
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    
    # Csak a nagybetűs szavak maradjanak, amik nem Debrecen és nem az utcanév részei
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    final = []
    for w in words:
        if w not in ["Debrecen", "Sorszám"] and w not in addr_words and len(w) > 2:
            if w not in final:
                final.append(w)
    return " ".join(final[:3])

# 2. Függvény a PDF generáláshoz
def create_pdf_v50(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    # Betűtípusok beállítása (Amit feltöltöttél a GitHubra)
    reg_font = "DejaVuSans.ttf"
    bold_font = "DejaVuSans-Bold.ttf"
    
    if os.path.exists(reg_font) and os.path.exists(bold_font):
        pdf.add_font("DejaVu", style="", fname=reg_font)
        pdf.add_font("DejaVu", style="B", fname=bold_font)
        f_name = "DejaVu"
    else:
        st.error("Hiba: A DejaVuSans.ttf fájlok nem találhatók a GitHub mappában!")
        return None

    for i, row in df.iterrows():
        if i % 21 == 0:
            pdf.add_page()
            
        col = i % 3
        line = (i // 3) % 7
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
        
    return pdf.output()

# --- STREAMLIT FELÜLET ---
st.set_page_config(page_title="Etikett Mester v50", layout="wide")
st.title("Interfood Etikett Mester")

uploaded_file = st.file_uploader("Töltsd fel az Interfood PDF-et", type="pdf")

if uploaded_file:
    data = []
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Sorszámok keresése (pl. 1, 2, 3 a bal szélen)
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                
                # Cím kinyerése
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                # Név tisztítása
                name = clean_name_v50(block, cim)
                
                # Rendelés kódok
                rend = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block))
                
                data.append({"Sorszám": markers[i]['num'], "Ügyintéző": name, "Cím": cim, "Rendelés": rend})
    
    df = pd.DataFrame(data)
    st.write("### Ellenőrizd az adatokat:")
    st.dataframe(df, use_container_width=True)
    
    st.divider()
    
    # Itt a gomb, ami a hibát okozta - most már biztosan jó helyen van
    if st.button("PDF ETIKETT GENERÁLÁSA", use_container_width=True):
        with st.spinner("PDF készítése..."):
            pdf_bytes = create_pdf_v50(df)
            if pdf_bytes:
                st.download_button(
                    label="💾 PDF LETÖLTÉSE MOST",
                    data=pdf_bytes,
                    file_name="interfood_etikettek.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
