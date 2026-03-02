import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_menetterv_v114(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines"
            })
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                
                # 0. Sorszám
                sorszam_raw = str(row[0]).strip()
                if not any(s.isdigit() for s in sorszam_raw): continue
                sorszam = sorszam_raw.split('\n')[0]

                # 1. Kód és Cím (Itt volt a keveredés)
                c1 = str(row[1]).strip()
                kod_match = re.search(r'([PZ]-\d{6})', c1)
                kod = kod_match.group(1) if kod_match else "Nincs kód"
                
                # Cím: Megkeressük a Debrecen szót és a környezetét
                cim_lines = [l.strip() for l in c1.split('\n') if "Debrecen" in l]
                cim = cim_lines[0] if cim_lines else "Cím a PDF-ben"

                # 2. Ügyintéző (A tiszta név oszlopa)
                nev_raw = str(row[2]).strip()
                # Ha üres, vagy fejléc, átugorjuk
                if not nev_raw or "Ügyintéző" in nev_raw: continue
                nev = nev_raw.split('\n')[0] # Csak az első sor (a név)

                # 3. Adatok (Telefon, Pénz, Rendelés)
                c3 = str(row[3]).strip()
                tel_m = re.search(r'(\d{2}/\d{7})', c3)
                tel = tel_m.group(1) if tel_m else "Nincs tel."
                
                penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                penz = penz_m.group(1) if penz_m else "0 Ft"
                
                # Rendelési kódok kigyűjtése
                rend_m = re.findall(r'(\d+-[A-Z0-9]+)', c3)
                rend = ", ".join(rend_m) if rend_m else "Lásd PDF"

                all_rows.append({
                    "Sorszám": sorszam,
                    "Kód": kod,
                    "Ügyintéző": nev,
                    "Cím": cim,
                    "Telefon": tel,
                    "Pénz": penz,
                    "Rendelés": rend
                })
    
    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám', 'Kód'])
    return df

def create_pdf_v114(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for i, (_, row) in enumerate(df.iterrows()):
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        # Név kiírása
        safe_name = str(row['Ügyintéző']).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(60, 5, f"#{row['Sorszám']} {safe_name[:25]}")
        
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+10)
        pdf.cell(60, 5, f"{row['Kód']} | {row['Pénz']}")
        
        pdf.set_font("Arial", "B", 8)
        pdf.set_xy(x+5, y+14)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}")
        
        pdf.set_font("Arial", "", 7)
        pdf.set_xy(x+5, y+18)
        safe_addr = str(row['Cím']).encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(60, 3.5, safe_addr)
        
        pdf.set_font("Arial", "", 6)
        pdf.set_xy(x+5, y+30)
        pdf.cell(60, 5, f"REND: {row['Rendelés']}"[:55])
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

st.title("Interfood v114 - Stabil Oszlopok")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v114(f)
    st.write(f"Beolvasott sorok: **{len(data)}**")
    st.dataframe(data)
    
    if not data.empty:
        pdf_bytes = create_pdf_v114(data)
        st.download_button("💾 PDF Letöltése", pdf_bytes, "etikettek.pdf", "application/pdf")
