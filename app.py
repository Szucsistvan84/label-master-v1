import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_menetterv_v117(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Szigorú táblázatkezelés - csak a vonalak mentén!
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines"
            })
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                s_raw = str(row[0]).strip()
                if not any(c.isdigit() for c in s_raw): continue
                
                # SORSZÁM
                sorszam = s_raw.split('\n')[0]

                # 1. OSZLOP: KÓD ÉS CÍM (A v110-es nyerő logika)
                c1 = str(row[1]).strip()
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                kod = kod_m.group(1) if kod_m else "Nincs kód"
                # Cím: megkeressük azt a sort, amiben ott a Debrecen
                cim = "Cím hiányzik"
                for line in c1.split('\n'):
                    if "Debrecen" in line:
                        cim = line.strip()
                        break

                # 2. OSZLOP: ÜGYINTÉZŐ (Itt van a tiszta név!)
                nev = str(row[2]).strip().split('\n')[0]
                if "Ügyintéző" in nev: continue

                # 3. OSZLOP: TELEFON ÉS RENDELÉS
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

st.title("Interfood v117 - A Restaurált v110")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    data = parse_menetterv_v117(f)
    st.dataframe(data)
