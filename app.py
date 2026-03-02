import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v121(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # VÁLTOZATÁS: Ha a 'lines' nem talál semmit, a 'text' stratégiára váltunk
            # Ez segít a 88. sor utáni "vonal nélküli" részeknél
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "text", # Rugalmasabb vízszintes keresés
                "intersection_y_tolerance": 10
            })
            
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                
                # Sorszám kinyerése
                s_raw = str(row[0]).strip()
                sorszam_match = re.search(r'(\d+)', s_raw)
                if not sorszam_match: continue
                sorszam = sorszam_match.group(1)

                # 1. oszlop: Kód
                c1 = str(row[1]).strip()
                kod_match = re.search(r'([HKSC P Z]-\d{6})', c1)
                kod = kod_match.group(1) if kod_match else "Nincs kód"

                # 2. oszlop: Cím (ha üres, megnézzük az 1. oszlop alját, néha odacsúszik)
                valodi_cim = str(row[2]).strip().replace('\n', ' ')
                if (not valodi_cim or valodi_cim == "None") and "Debrecen" in c1:
                    # Mentőöv: ha a cím belecsúszott az ügyfélkód oszlopába
                    for line in c1.split('\n'):
                        if "Debrecen" in line:
                            valodi_cim = line.strip()
                            break
                
                if "Ügyintéző" in valodi_cim or not valodi_cim: 
                    if sorszam == "89": # Speciális debug a kritikus sorhoz
                        pass 
                    else: continue

                # 4. oszlop: Ügyintéző (Név)
                c4 = str(row[3]).strip()
                nev_m = c4.split('\n')[0] if c4 and c4 != "None" else "Nincs név"

                all_rows.append({
                    "Sorszám": sorszam,
                    "Kód": kod,
                    "Cím": valodi_cim,
                    "Ügyintéző": nev_m
                })
    
    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám', 'Kód'])
    return df

st.title("Interfood v121 - A 88. sor utáni javítás")
st.info("Javítás: Rugalmas táblázatkezelés a hiányzó vonalak ellenére.")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v121(f)
    if not data.empty:
        # Rendezés sorszám szerint, hogy lássuk a végét
        data['Sorszám_int'] = pd.to_numeric(data['Sorszám'], errors='coerce')
        data = data.sort_values('Sorszám_int').drop('Sorszám_int', axis=1)
        
        st.write("### Ellenőrző táblázat (88. sor környéke)")
        st.dataframe(data) # Itt most már látnod kell a 89, 90... sorokat is
        
        csv = data.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV letöltése", csv, "interfood_v121.csv", "text/csv")
