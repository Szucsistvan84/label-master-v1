import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import io
import os

def parse_menetterv_v108(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A Menetterv táblázatos, de a cellákban több sor van
            table = page.extract_table({
                "vertical_strategy": "text", 
                "horizontal_strategy": "text",
                "snap_tolerance": 4,
            })
            
            if not table: continue

            for row in table:
                # Tisztítás
                c0 = str(row[0]) if row[0] else ""
                c1 = str(row[1]) if row[1] else "" # Kód + Cím
                c2 = str(row[2]) if row[2] else "" # Ügyintéző
                c3 = str(row[3]) if row[3] else "" # Tel + Rendelés + Pénz
                
                if "Ügyfél" in c1 or "Sor" in c0: continue

                # Ügyfélkód kinyerése
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                if kod_m:
                    kod = kod_m.group(1)
                    # Cím: Minden, ami a kód után van a cellában
                    cim = c1.split(kod)[-1].strip().replace('\n', ' ')
                    
                    # Név: A 2. oszlop (Ügyintéző)
                    nev = c2.strip().replace('\n', ' ')
                    if not nev or len(nev) < 3: nev = "Név hiányzik"

                    # Telefon: 06/ vagy 20/ stb.
                    tel_m = re.search(r'(\d{2}/\d{7})', c3)
                    tel = tel_m.group(1) if tel_m else "NINCS"

                    # Pénz: "X Ft" formátum
                    penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                    penz = penz_m.group(1) if penz_m else "0 Ft"

                    # Rendelés: A cella alja
                    rend = c3.split(penz)[-1].strip().replace('\n', ', ') if penz != "0 Ft" else c3.strip()

                    all_rows.append({
                        "Kód": kod, "Ügyintéző": nev, "Cím": cim,
                        "Telefon": tel, "Rendelés": rend, "Pénz": penz
                    })
    return pd.DataFrame(all_rows)

def create_etikett_pdf_v108(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    # Alapértelmezett font, hogy ne legyen hiba
    pdf.set_font("Arial", size=10)

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x = (i % 3) * 70
        y = ((i // 3) % 7) * 42.4
        
        # NÉV (Félkövér)
        pdf.set_xy(x+5, y+5)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:25].encode('latin-1', 'replace').decode('latin-1'))
        
        # KÓD + PÉNZ
        pdf.set_xy(x+5, y+11)
        pdf.set_font("Arial", "", 8)
        pdf.cell(60, 4, f"KOD: {row['Kód']} | {row['Pénz']}".encode('latin-1', 'replace').decode('latin-1'))
        
        # TELEFON (Kiemelve)
        pdf.set_xy(x+5, y+16)
        pdf.set_font("Arial", "B", 9)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}")
        
        # CÍM
        pdf.set_xy(x+5, y+21)
        pdf.set_font("Arial", "", 8)
        pdf.multi_cell(60, 3.5, str(row['Cím']).encode('latin-1', 'replace').decode('latin-1'))
        
        # RENDELÉS (Alul kicsiben)
        pdf.set_xy(x+5, y+33)
        pdf.set_font("Arial", "", 7)
        pdf.cell(60, 4, f"REND: {str(row['Rendelés'])[:40]}".encode('latin-1', 'replace').decode('latin-1'))
        
    # FONTOS: Bájtokká alakítjuk a kimenetet a Streamlit számára
    return bytes(pdf.output(dest='S'))

st.title("Interfood Menetterv v108")
f = st.file_uploader("Válaszd ki a Menetterv PDF-et", type="pdf")

if f:
    df = parse_menetterv_v108(f)
    if not df.empty:
        st.success(f"Beolvasva: {len(df)} ügyfél")
        st.dataframe(df)
        
        # PDF Generálás
        pdf_data = create_etikett_pdf_v108(df)
        st.download_button(
            label="💾 PDF Letöltése",
            data=pdf_data,
            file_name="interfood_etikettek.pdf",
            mime="application/pdf"
        )
