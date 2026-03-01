import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import io

def parse_final_v109(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A menetterv táblázatos szerkezetének kinyerése
            table = page.extract_table()
            if not table: continue
            for row in table:
                if not row or "Ügyfél" in str(row[1]) or "Sor" in str(row[0]): continue
                
                # Oszlopok: 0: Sor, 1: Kód+Cím, 2: Ügyintéző, 3: Telefon/Rendelés
                c1 = str(row[1]) if row[1] else ""
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                if kod_m:
                    kod = kod_m.group(1)
                    # Tőkés István és a cím szétválasztása
                    cim = c1.split(kod)[-1].strip().replace('\n', ' ')
                    nev = str(row[2]).strip().replace('\n', ' ')
                    
                    # Adatok a 3. oszlopból (Tel, Pénz, Rendelés)
                    c3 = str(row[3]) if row[3] else ""
                    tel_m = re.search(r'(\d{2}/\d{7})', c3)
                    tel = tel_m.group(1) if tel_m else "NINCS"
                    
                    penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                    penz = penz_m.group(1) if penz_m else "0 Ft"
                    
                    all_rows.append({
                        "Kód": kod, "Ügyintéző": nev, "Cím": cim,
                        "Telefon": tel, "Pénz": penz, "Rend": c3.split('\n')[-1]
                    })
    return pd.DataFrame(all_rows)

def create_pdf_v109(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        # Karakterkódolás javítása a fagyás ellen
        safe_name = str(row['Ügyintéző']).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(60, 5, safe_name)
        
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+10)
        pdf.cell(60, 5, f"KOD: {row['Kód']} | {row['Pénz']}")
        
        pdf.set_xy(x+5, y+15)
        pdf.multi_cell(60, 4, str(row['Cím']).encode('latin-1', 'replace').decode('latin-1'))
    
    # Ez a rész javítja a Streamlit download_button hibát!
    return pdf.output(dest='S').encode('latin-1', 'replace')

st.title("Interfood - Végső Megoldás v109")
uploaded = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if uploaded:
    data = parse_final_v109(uploaded)
    st.dataframe(data) # Itt látni fogod Tőkés Istvánt!
    
    pdf_bytes = create_pdf_v109(data)
    st.download_button("💾 PDF Letöltése", data=pdf_bytes, file_name="etikettek.pdf", mime="application/pdf")
