import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. ADATTISZTÍTÓ LOGIKA (A legfrissebb szűrőkkel) ---
def final_clean_v47(text, address_text):
    blacklist_phrases = [
        "Richter Gedeon", "Zaza Süteményes", "István úti csemege", "István csemege",
        "Pearl Enterprises", "DEKK Kenézy Gyula", "Főnix Gyógyszertár", "Főnix Állatorvosi",
        "Harro Höfliger", "Javítsd Magad", "Ford Szalon", "ZsoZso Color", "Kormányhivatal"
    ]
    blacklist_words = [
        "Richter", "Gedeon", "Zaza", "Süteményes", "Gyógyszertár", "Csemege", "Kérlek", 
        "Köszönöm", "Matrackirály", "Triton", "Services", "Gázkészülék", "Bolt", "Iskola",
        "Általános", "Micskey", "Ügyvédi", "Portán", "Porta", "KCS", "DKM", "Hungary", "Kft", "Zrt"
    ]
    
    clean_text = text
    for phrase in blacklist_phrases:
        clean_text = re.sub(re.escape(phrase), '', clean_text, flags=re.IGNORECASE)
    
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    final_parts = []
    for w in words:
        if (w not in ["Debrecen", "Sorszám", "Összesen"] and 
            w not in addr_words and 
            w.upper() not in [bw.upper() for bw in blacklist_words] and
            len(w) > 2):
            if w not in final_parts:
                is_sub = False
                for idx, existing in enumerate(final_parts):
                    if w in existing: is_sub = True; break
                    if existing in w: final_parts[idx] = w; is_sub = True; break
                if not is_sub:
                    final_parts.append(w)
    return " ".join(final_parts[:3])

# --- 2. PDF GENERÁLÁS (3x7 Etikett ív) ---
def create_pdf_v47(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    # Betűtípusok betöltése a GitHubról
    font_reg = "DejaVuSans.ttf"
    font_bold = "DejaVuSans-Bold.ttf"
    
    if os.path.exists(font_reg) and os.path.exists(font_bold):
        pdf.add_font("DejaVu", style="", fname=font_reg)
        pdf.add_font("DejaVu", style="B", fname=font_bold)
        use_font = "DejaVu"
    else:
        st.error("HIBA: A betűtípus fájlok nem találhatók a mappában!")
        return None

    # Méretek (A4: 210x297mm)
    label_w = 70
    label_h = 42.4
    
    for i, row in df.iterrows():
        if i % 21 == 0:
            pdf.add_page()
            
        col = i % 3
        line = (i // 3) % 7
        x, y = col * label_w, line * label_h
        
        # Név (Félkövér)
        pdf.set_xy(x + 5, y + 10)
        pdf.set_font(use_font, "B", 12)
        pdf.cell(60, 6, str(row['Ügyintéző']), 0, 1)
        
        # Cím (Normál)
        pdf.set_x(x + 5)
        pdf.set_font(use_font, "", 9)
        pdf.cell(60, 5, str(row['Cím']), 0, 1)
        
        # Rendelés (Normál, kisebb)
        pdf.set_x(x + 5)
        pdf.set_font(use_font, "", 7)
        pdf.multi_cell(60, 4, f"Rendelés: {row['Rendelés']}", 0)
        
    return pdf.output()

# --- 3. STREAMLIT FELÜLET ---
st.set_page_config(page_title="Interfood Etikett Mester", layout="wide")
st.title("Interfood Etikett Mester v47")

uploaded_file = st.file_uploader("Válaszd ki az Interfood PDF fájlt", type="pdf")

if uploaded_file:
    with st.spinner("Adatok feldolgozása..."):
        all_data = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                words = page.extract_words()
