import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_menetterv_v112(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A 'lattice' helyett 'stream' szerű felismerés, hogy ne vesszen el sor
            table = page.extract_table({
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "snap_tolerance": 5,
            })
            
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                
                # 0. oszlop: Sorszám (tisztítás a szeméttől)
                sorszam_raw = str(row[0]).strip()
                sorszam_match = re.search(r'^(\d+)', sorszam_raw)
                if not sorszam_match: continue
                sorszam = sorszam_match.group(1)

                # 1. oszlop: Kód és Cím (összefűzzük az összes sort a cellában)
                c1 = str(row[1]).strip()
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                kod = kod_m.group(1) if kod_m else "Nincs kód"
                
                # Cím keresése: Irányítószám + Város formátumra vadászunk
                cim_m = re.search(r'(\d{4}\s+Debrecen,?[^#\n]+)', c1)
                cim = cim_m.group(1).replace('\n', ' ').strip() if cim_m else "Cím a PDF-ben"

                # 2. oszlop: Ügyintéző (A név általában itt van magában)
                nev = str(row[2]).strip().replace('\n', ' ')
                if "Ügyintéző" in nev: continue

                # 3. oszlop: Adatok (Telefon, Ft, Rendelés)
                c3 = str(row[3]).strip()
                
                tel_m = re.search(r'(\d{2}/\d{7})', c3)
                tel = tel_m.group(1) if tel_m else "Nincs tel."
                
                penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                penz = penz_m.group(1) if penz_m else "0 Ft"
                
                # Rendelés: minden, ami szám-betűkombináció (pl. 1-DKM)
                rend_m = re.findall(r'(\d+-[A-Z0-9]+)', c3)
                rendeles = ", ".join(rend_m) if rend_m else "Adat a PDF-ben"

                all_rows.append({
                    "Sorszám": sorszam,
                    "Kód": kod,
                    "Ügyintéző": nev,
                    "Cím": cim,
                    "Telefon": tel,
                    "Pénz": penz,
                    "Rendelés": rendeles
                })
    
    # Duplikátumok kiszűrése (ha a fejlécet többször elkapná) és sorbarendezés
    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám', 'Kód'])
    df['Sorszám'] = pd.to_numeric(df['Sorszám'])
    return df.sort_values('Sorszám')

def create_pdf_v112(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    # Alap font
    pdf.set_font("Arial", size=10)
    
    for i, (_, row) in enumerate(df.iterrows()):
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        # Név - Félkövér
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        name = str(row['Ügyintéző']).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(60, 5, name[:28])
        
        # Kód és Pénz
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+10)
        pdf.cell(60, 5, f"{row['Kód']} | {row['Pénz']}")
        
        # Telefon
        pdf.set_font("Arial", "B", 8)
        pdf.set_xy(x+5, y+14)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}")
        
        # Cím - Multi-cell a sortöréshez
        pdf.set_font("Arial", "", 7)
        pdf.set_xy(x+5, y+18)
        address = str(row['Cím']).encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(60, 3.5, address)
        
        # Rendelés
        pdf.set_font("Arial", "", 6)
        pdf.set_xy(x+5, y+30)
        pdf.cell(60, 5, f"REND: {row['Rendelés']}"[:55])
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

st.title("Interfood Menetterv v112 - A 101 Soros Megoldás")
f = st.file_uploader("Töltsd fel a PDF-et", type="pdf")

if f:
    data = parse_menetterv_v112(f)
    st.write(f"Beolvasott sorok száma: **{len(data)}**")
    st.dataframe(data)
    
    if not data.empty:
        pdf_bytes = create_pdf_v112(data)
        st.download_button("💾 PDF Etikettek Letöltése", pdf_bytes, "etikettek.pdf", "application/pdf")
