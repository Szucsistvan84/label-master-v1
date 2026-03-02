import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v118(pdf_file):
    all_rows = []
    napok_szotar = {
        'H': 'Hétfő', 'K': 'Kedd', 'S': 'Szerda', 
        'C': 'Csütörtök', 'P': 'Péntek', 'Z': 'Szombat'
    }
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Szigorúan a v110-es táblázatkezelés
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines"
            })
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                
                # 0. Sorszám
                s_raw = str(row[0]).strip()
                sorszamok = [s.strip() for s in s_raw.split('\n') if s.strip().isdigit()]
                if not sorszamok: continue
                
                # 1. Kód kinyerése
                c1 = str(row[1]).strip()
                kod_match = re.findall(r'([HKSC P Z])-\d{6}', c1) # Nap kódja
                teljes_kod = re.findall(r'([HKSC P Z]-\d{6})', c1)
                
                # Nap meghatározása
                if len(set(kod_match)) > 1:
                    nap = "Péntek+Szombat" # Vagy bármilyen összevont nap
                elif kod_match:
                    nap = napok_szotar.get(kod_match[0], kod_match[0])
                else:
                    nap = "Ismeretlen"

                # 2. Ügyintéző (A v110-ben ez a 'Rendelés' helyén volt)
                # Itt a nevek vannak a PDF 2. oszlopában
                ugyintezo = str(row[2]).strip().split('\n')[0]
                if "Ügyintéző" in ugyintezo: continue

                # 3. Cím (A v110-ben ez az 'Ügyintéző' helyén volt)
                # Itt a címek vannak a PDF 1. oszlopában a Debrecen sorban
                cim = "Nincs cím"
                for line in c1.split('\n'):
                    if "Debrecen" in line:
                        cim = line.strip()
                        break

                all_rows.append({
                    "Sorszám": sorszamok[0],
                    "Ügyfélkód": teljes_kod[0] if teljes_kod else "Nincs kód",
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Nap": nap
                })
    
    # Duplikátum szűrés (Összevonás kezelése)
    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám', 'Ügyfélkód'])
    return df

st.title("Interfood v118 - Lépésről lépésre")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v118(f)
    st.write("### Ellenőrző táblázat")
    # Megjelenítés a kért sorrendben
    st.dataframe(data[["Sorszám", "Ügyfélkód", "Ügyintéző", "Cím", "Nap"]])
    
    csv = data.to_csv(index=False).encode('utf-8-sig')
    st.download_button("CSV letöltése", csv, "interfood_v118.csv", "text/csv")
