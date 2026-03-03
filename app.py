import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v139(pdf_file):
    all_rows = []
    # Az összeg keresése: számok és szóközök, amiket a "Ft" zár le
    price_regex = re.compile(r'(\d[\d\s]*Ft)')
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            lines = text.split('\n')
            for i, line in enumerate(lines):
                # Sorszám és Kód azonosítása
                match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                if match:
                    s_num = int(match.group(1))
                    kod = match.group(2)
                    
                    # 1. LÉPÉS: Megkeressük a Ft-ot és levágunk mindent, ami UTÁNA van
                    search_area = line
                    if i + 1 < len(lines): search_area += " " + lines[i+1]
                    
                    if "Ft" in search_area:
                        # Levágjuk a Ft utáni részt, hogy a darabszám ne kavarjon be
                        clean_area = search_area[:search_area.find("Ft") + 2]
                        price_match = price_regex.search(clean_area)
                        price = price_match.group(1) if price_match else "0 Ft"
                    else:
                        price = "0 Ft"

                    # 2. LÉPÉS: Adagszám kiszámolása a kódokból (pl. 1-L1K -> 1)
                    # Megkeressük a "szám-betűkód" mintákat
                    adag_talalatok = re.findall(r'(\d+)-[A-Z0-9]+', search_area)
                    kalkulalt_adag = sum(int(a) for a in adag_talalatok) if adag_talalatok else 1

                    all_rows.append({
                        "Sorszám": s_num,
                        "Kód": kod,
                        "Összeg": price.strip(),
                        "Számolt Adag": kalkulalt_adag,
                        "Eredeti sor": line[:40] # Csak ellenőrzéshez
                    })

    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám'])
    return df.sort_values("Sorszám")

# Streamlit interfész
st.title("Interfood v139 - Ft-Stop & Adagszám Számító")
st.info("Ez a verzió a 'Ft' után mindent levág, az adagszámot pedig a rendelési kódokból számolja ki.")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v139(f)
    st.dataframe(df, use_container_width=True)
    st.metric("Összesített adagszám (számolt)", int(df['Számolt Adag'].sum()))
    st.download_button("💾 CSV Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v139.csv")
