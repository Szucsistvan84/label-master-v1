import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import io
import os

def parse_menetterv(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A menetterv speciális struktúrája miatt soronként olvassuk a szöveget
            text = page.extract_text()
            lines = text.split('\n')
            
            for line in lines:
                # Keressük az ügyfélkódot (P- vagy Z- és 6 szám)
                kod_match = re.search(r'([PZ]-\d{6})', line)
                if kod_match:
                    cid = kod_match.group(1)
                    # Megpróbáljuk kinyerni a nevet (ami általában a kód után vagy előtt van a sorban)
                    # Ebben a PDF-ben a név gyakran a kód mellett van közvetlenül
                    name = "Név hiányzik"
                    parts = line.split(cid)
                    if len(parts) > 1:
                        # A név keresése a sorban
                        potential_name = parts[0].strip()
                        if len(potential_name.split()) >= 2:
                            name = potential_name
                    
                    # Ha nem találtuk meg a sorban, nézzük a környezetet
                    all_rows.append({
                        "Kód": cid,
                        "Ügyintéző": name,
                        "Cím": "Debrecen (beolvasás alatt...)",
                        "Telefon": "NINCS",
                        "Rendelés": "Adat kinyerése...",
                        "Pénz": "0 Ft"
                    })
    return pd.DataFrame(all_rows)

def create_etikett_pdf(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    # HIBAJAVÍTÁS: Betűtípus ellenőrzése
    # Megpróbáljuk betölteni a DejaVu-t, ha nincs meg, marad az Arial
    font_name = "Arial"
    try:
        # Csak akkor próbálja meg, ha a fájlok léteznek a mappában
        if os.path.exists("DejaVuSans.ttf"):
            pdf.add_font("DejaVu", "", "DejaVuSans.ttf", uni=True)
            pdf.add_font("DejaVu", "B", "DejaVuSans-Bold.ttf", uni=True)
            font_name = "DejaVu"
    except:
        font_name = "Arial"

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x = (i % 3) * 70
        y = ((i // 3) % 7) * 42.4
        
        # Ügyintéző név
        pdf.set_xy(x+5, y+5)
        pdf.set_font(font_name, "B", 10)
        # latin-1 kódolás az Arialhoz, hogy ne legyen hiba
        name_text = str(row['Ügyintéző'])[:25].encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(60, 5, name_text)
        
        # Kód és Pénz
        pdf.set_xy(x+5, y+10)
        pdf.set_font(font_name, "", 8)
        pdf.cell(60, 5, f"KOD: {row['Kód']}")
        
        # Cím (Multi-cell a hosszú címekhez)
        pdf.set_xy(x+5, y+15)
        pdf.set_font(font_name, "", 7)
        pdf.multi_cell(60, 3.5, "Debrecen, Házgyár u. 12.") # Teszt adat
        
    return pdf.output(dest='S')

st.title("Interfood Menetterv v107 - Fixált Fontok")
f = st.file_uploader("Eredeti Menetterv PDF", type="pdf")

if f:
    # Elmentjük ideiglenesen
    with open("temp_mt.pdf", "wb") as tmp:
        tmp.write(f.read())
    
    df = parse_menetterv("temp_mt.pdf")
    
    if not df.empty:
        st.write("Beolvasott adatok (Tőkés István ellenőrzése):")
        st.dataframe(df)
        
        pdf_bytes = create_etikett_pdf(df)
        st.download_button("💾 PDF Letöltése", pdf_bytes, "etikettek.pdf")
    else:
        st.error("Nem sikerült adatot találni a PDF-ben.")
