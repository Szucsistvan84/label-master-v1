import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_menetterv_v113(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            })
            
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                
                # Sorszám(ok) kezelése (néha "1\n2" van egy cellában)
                sorszam_cell = str(row[0]).strip().split('\n')
                sorszamok = [s.strip() for s in sorszam_cell if s.strip().isdigit()]
                if not sorszamok: continue

                # Ügyfél/Cím (1. oszlop) - Minden sort beolvasunk
                c1 = str(row[1]).strip()
                kodok = re.findall(r'([PZ]-\d{6})', c1)
                cimek = [line.strip() for line in c1.split('\n') if "Debrecen" in line]
                
                # Ügyintéző (2. oszlop) - Itt vannak a nevek
                c2 = str(row[2]).strip().split('\n')
                nevek = [n.strip() for n in c2 if n.strip() and "Ügyintéző" not in n]

                # Telefon/Rendelés (3. oszlop)
                c3 = str(row[3]).strip()
                tel_m = re.findall(r'(\d{2}/\d{7})', c3)
                penz_m = re.findall(r'(\d+[\s\d]*Ft)', c3)
                # Rendelés: minden ami szám-betű kód (pl 1-DKM)
                rend_m = re.findall(r'(\d+-[A-Z0-9]+)', c3)

                # Mivel egy cellában több ügyfél is lehet (pl. 1. és 2. sor együtt)
                # megpróbáljuk szétosztani az adatokat a sorszámok között
                for i, szam in enumerate(sorszamok):
                    all_rows.append({
                        "Sorszám": szam,
                        "Kód": kodok[i] if i < len(kodok) else (kodok[0] if kodok else "Nincs kód"),
                        "Ügyintéző": nevek[i] if i < len(nevek) else (nevek[0] if nevek else "Név hiányzik"),
                        "Cím": cimek[i] if i < len(cimek) else (cimek[0] if cimek else "Cím a PDF-ben"),
                        "Telefon": tel_m[i] if i < len(tel_m) else (tel_m[0] if tel_m else "Nincs tel."),
                        "Pénz": penz_m[i] if i < len(penz_m) else (penz_m[0] if penz_m else "0 Ft"),
                        "Rendelés": rend_m[i] if i < len(rend_m) else (", ".join(rend_m) if rend_m else "Lásd PDF")
                    })
                    
    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám', 'Kód'])
    return df

def create_pdf_v113(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for i, (_, row) in enumerate(df.iterrows()):
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        # Ügyintéző név (Tőkés István stb.)
        name = str(row['Ügyintéző']).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(60, 5, f"#{row['Sorszám']} {name[:25]}")
        
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+10)
        pdf.cell(60, 5, f"{row['Kód']} | {row['Pénz']}")
        
        pdf.set_font("Arial", "B", 8)
        pdf.set_xy(x+5, y+14)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}")
        
        pdf.set_font("Arial", "", 7)
        pdf.set_xy(x+5, y+18)
        addr = str(row['Cím']).encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(60, 3.5, addr)
        
        pdf.set_font("Arial", "", 6)
        pdf.set_xy(x+5, y+30)
        pdf.cell(60, 5, f"REND: {row['Rendelés']}"[:55])
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

st.title("Interfood v113 - Oszlop-fixált verzió")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v113(f)
    st.write(f"Beolvasott sorok: **{len(data)}** (Cél: 101)")
    st.dataframe(data)
    
    if not data.empty:
        pdf_bytes = create_pdf_v113(data)
        st.download_button("💾 PDF Letöltése", pdf_bytes, "etikettek.pdf", "application/pdf")
