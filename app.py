import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v137(pdf_file):
    all_rows = []
    # Keressük az összes sorszámmal kezdődő sort a teljes PDF-ben
    # Minta: Sorszám + Kód (pl. 1 P-428867)
    line_pattern = re.compile(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})')
    # Összeg minta: számok, opcionális szóközök, majd Ft
    price_pattern = re.compile(r'(\d[\d\s]{0,10}Ft)')
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            lines = text.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                match = line_pattern.search(line)
                
                if match:
                    s_num = int(match.group(1))
                    kod = match.group(2)
                    
                    # Összeg keresése: megnézzük ezt a sort ÉS a következőt is (Tőkés István miatt)
                    search_area = line
                    if i + 1 < len(lines):
                        search_area += " " + lines[i+1]
                    
                    price_match = price_pattern.search(search_area)
                    price = price_match.group(1) if price_match else "0 Ft"
                    
                    # Telefonszám
                    tel_match = re.search(r'(\d{2}/\d{6,7})', search_area)
                    tel = tel_match.group(1) if tel_match else ""
                    
                    # Ha sorszám 1-88 közötti, próbáljuk a táblázatból a nevet/címet (mert ott szebb)
                    # Ha utolsó oldal, marad a szöveges szeletelés
                    all_rows.append({
                        "Sorszám": s_num,
                        "Kód": kod,
                        "Cím": "Feldolgozás alatt...",
                        "Ügyintéző": "Keresés...",
                        "Telefon": tel,
                        "Összeg": price,
                        "Adag": "1" # Ideiglenes
                    })

    # Most a táblázatokból behúzzuk a neveket a sorszámok alapján, hogy ne kelljen a "szeletelővel" bajlódni
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages[:-1]: # Utolsó oldal kivételével
            table = page.extract_table()
            if table:
                for row in table:
                    if not row or not str(row[0]).strip().isdigit(): continue
                    s_idx = int(str(row[0]).strip().split('\n')[0])
                    for r in all_rows:
                        if r["Sorszám"] == s_idx:
                            r["Cím"] = str(row[2]).replace('\n', ' ')
                            r["Ügyintéző"] = str(row[3]).split('\n')[0]
                            if len(row) > 6: r["Adag"] = str(row[6]).split('\n')[0]

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI rész
st.title("Interfood v137 - Szövegbányász Mód")
st.info("Ez a verzió a nyers szövegben keresi az árakat, így Tőkés István 11 555 Ft-ja is meglesz.")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v137(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v137.csv")
