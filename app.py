import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v120(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Szigorúan a v110-es bevált táblázatkezelés a vonalak mentén
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines"
            })
            if not table: continue

            for row in table:
                if not row or len(row) < 4: continue
                
                # Sorszám kinyerése (v110 logika)
                s_raw = str(row[0]).strip()
                sorszamok = [s.strip() for s in s_raw.split('\n') if s.strip().isdigit()]
                if not sorszamok: continue
                
                # 1. oszlop: Kód kinyerése
                c1 = str(row[1]).strip()
                kod_match = re.search(r'([HKSC P Z]-\d{6})', c1)
                kod = kod_match.group(1) if kod_match else "Nincs kód"

                # 2. oszlop: Itt vannak a CÍMEK (A v110-ben ez volt az Ügyintéző fejléc alatt)
                # Ezt nevezzük át Cím-re
                valodi_cim = str(row[2]).strip().replace('\n', ' ')
                if "Ügyintéző" in valodi_cim: continue

                # 3. oszlop: Ez volt a 'Cím' fejléc, ezt a kérésedre most KIHAGYJUK/TÖRÖLJÜK.

                # 4. oszlop: Ebben van a NÉV (Ügyintéző) legfelül
                c4 = str(row[3]).strip()
                nev_m = c4.split('\n')[0] # A név az első sor ebben a cellában

                all_rows.append({
                    "Sorszám": sorszamok[0],
                    "Kód": kod,
                    "Cím": valodi_cim,   # A 2. oszlopból jön
                    "Ügyintéző": nev_m    # A 4. oszlop tetejéről jön
                })
    
    return pd.DataFrame(all_rows)

st.title("Interfood v120 - Tisztított Adatok")
st.info("Logika: 2. oszlop -> Cím | 4. oszlop teteje -> Ügyintéző | 3. oszlop törölve")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v120(f)
    
    if not data.empty:
        st.write("### Ellenőrző táblázat")
        # Megjelenítés: Sorszám, Kód, Cím, Ügyintéző
        final_df = data[["Sorszám", "Kód", "Cím", "Ügyintéző"]]
        st.dataframe(final_df)
        
        csv = final_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV letöltése", csv, "interfood_v120.csv", "text/csv")
    else:
        st.warning("Nem sikerült adatot kinyerni. Ellenőrizd a PDF-et!")
