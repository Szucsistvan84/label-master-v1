import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_menetterv_v115(pdf_file):
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
                
                # 0. Sorszám kinyerése
                s_raw = str(row[0]).strip()
                s_match = re.search(r'(\d+)', s_raw)
                if not s_match: continue
                sorszam = s_match.group(1)

                # 1. oszlop tartalmának elemzése (Kód és Cím)
                c1 = str(row[1]).strip()
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                kod = kod_m.group(1) if kod_m else "Nincs kód"
                
                # Cím keresése: 4 számjegy + Város
                cim_m = re.search(r'(\d{4}\s+[A-Z][a-z]+,?\s+[^0-9\n]+[^#\n]+)', c1)
                cim = cim_m.group(1).replace('\n', ' ').strip() if cim_m else "Cím a PDF-ben"
                # Ha még mindig nincs cím, keressük meg a "Debrecen" sort
                if cim == "Cím a PDF-ben":
                    for line in c1.split('\n'):
                        if "Debrecen" in line:
                            cim = line.strip()
                            break

                # 2. oszlop: Ügyintéző (Név)
                c2 = str(row[2]).strip()
                nev = "Név hiányzik"
                if c2 and "Ügyintéző" not in c2:
                    nev = c2.split('\n')[0].strip()
                
                # Ha a név még mindig hiányzik, de a c1-ben van valami a kód előtt/után ami nem cím
                if (nev == "Név hiányzik" or len(nev) < 3) and c1:
                    lines = [l.strip() for l in c1.split('\n') if len(l.strip()) > 3 and "Debrecen" not in l and kod not in l]
                    if lines: nev = lines[0]

                # 3. oszlop: Adatok (Tel, Ft, Rendelés)
                c3 = str(row[3]).strip()
                tel_m = re.search(r'(\d{2}/\d{7})', c3)
                tel = tel_m.group(1) if tel_m else "Nincs tel."
                
                penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                penz = penz_m.group(1) if penz_m else "0 Ft"
                
                rend_m = re.findall(r'(\d+-[A-Z0-9]+)', c3)
                rend = ", ".join(rend_m) if rend_m else "Lásd PDF"

                all_rows.append({
                    "Sorszám": sorszam, "Kód": kod, "Ügyintéző": nev,
                    "Cím": cim, "Telefon": tel, "Pénz": penz, "Rendelés": rend
                })
    
    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám', 'Kód'])

def create_pdf_v115(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for i, (_, row) in enumerate(df.iterrows()):
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        # Név és sorszám
        safe_name = str(row['Ügyintéző']).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(60, 5, f"#{row['Sorszám']} {safe_name[:24]}")
        
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

st.title("Interfood v115 - A végső javítás")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v115(f)
    st.write(f"Beolvasott sorok: **{len(data)}**")
    st.dataframe(data)
    
    if not data.empty:
        pdf_bytes = create_pdf_v115(data)
        st.download_button("💾 PDF Letöltése", pdf_bytes, "etikettek.pdf", "application/pdf")
