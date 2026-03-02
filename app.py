import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_menetterv_v111(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Finomhangolt táblázatfelismerés
            table = page.extract_table({
                "vertical_strategy": "text",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            })
            
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                
                # Sorszám kinyerése
                sorszam = str(row[0]).strip().split('\n')[0] if row[0] else ""
                if not sorszam.isdigit(): continue # Csak a számmal kezdődő sorok kellenek

                # Oszlop 1: Kód és Cím
                c1 = str(row[1]) if row[1] else ""
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                kod = kod_m.group(1) if kod_m else "Nincs kód"
                # A címet tisztítjuk a kódtól és a felesleges nevektől
                cim = c1.split(kod)[-1].strip().split('\n')[0] if kod_m else c1
                
                # Oszlop 2: Ügyintéző (Itt van a tiszta név!)
                nev = str(row[2]).strip().split('\n')[0] if row[2] else "Név hiányzik"

                # Oszlop 3: Adatok (Tel, Ft, Rendelés)
                c3 = str(row[3]) if row[3] else ""
                
                # Telefonszám keresése
                tel_m = re.search(r'(\d{2}/\d{7})', c3)
                tel = tel_m.group(1) if tel_m else "Nincs tel."
                
                # Pénz (Ft) keresése
                penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                penz = penz_m.group(1) if penz_m else "0 Ft"
                
                # Rendelési kódok (pl. 1-DKM, 1-L1K)
                rend_m = re.findall(r'(\d+-[A-Z0-9]+)', c3)
                rendeles = ", ".join(rend_m) if rend_m else "Nincs adat"

                all_rows.append({
                    "Sorszám": sorszam,
                    "Kód": kod,
                    "Ügyintéző": nev,
                    "Cím": cim,
                    "Telefon": tel,
                    "Pénz": penz,
                    "Rendelés": rendeles
                })
    return pd.DataFrame(all_rows)

def create_pdf_v111(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for i, (_, row) in enumerate(df.iterrows()):
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:25].encode('latin-1', 'replace').decode('latin-1'))
        
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+10)
        pdf.cell(60, 5, f"{row['Kód']} | {row['Pénz']}")
        
        pdf.set_xy(x+5, y+14)
        pdf.set_font("Arial", "B", 8)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}")
        
        pdf.set_font("Arial", "", 7)
        pdf.set_xy(x+5, y+18)
        pdf.multi_cell(60, 3.5, str(row['Cím']).encode('latin-1', 'replace').decode('latin-1'))
        
        pdf.set_xy(x+5, y+30)
        pdf.set_font("Arial", "", 6)
        pdf.cell(60, 5, f"REND: {row['Rendelés']}"[:50])
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

st.title("Interfood v111 - 101 Soros Teszt")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v111(f)
    st.write(f"Talált sorok száma: {len(data)}")
    st.dataframe(data)
    
    if not data.empty:
        pdf_bytes = create_pdf_v111(data)
        st.download_button("💾 PDF Etikettek Letöltése", pdf_bytes, "etikettek.pdf", "application/pdf")
