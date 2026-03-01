import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_interfood_table_v9(pdf_file):
    extracted_data = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A titok nyitja: a 'text' stratégia a szóközök és igazítások alapján 
            # találja ki a cellákat, nem a vonalak alapján.
            table_settings = {
                "vertical_strategy": "text", 
                "horizontal_strategy": "text",
                "snap_tolerance": 5,
                "intersection_x_tolerance": 15,
            }
            
            # Először kinyerjük a nyers táblázatot
            table = page.extract_table(table_settings)
            
            if not table:
                # Ha a text stratégia nem válik be, próbáljuk meg a soronkénti elemzést
                text = page.extract_text()
                # (Itt egy fallback logikát is tarthatunk, de nézzük a táblázatot)
                continue

            for row in table:
                # Tisztítjuk a cellákat a felesleges sortörésektől
                clean_row = [str(cell).strip() if cell else "" for cell in row]
                
                # Keressük a sorszámot (az Interfoodnál ez az első oszlopban van)
                # Gyakran több sorszám is egy cellába kerül, ha nincs elválasztó
                sorszam_match = re.search(r'^(\d+)', clean_row[0])
                if not sorszam_match:
                    continue
                
                sorszam = sorszam_match.group(1)
                
                # Az adatok kinyerése az oszlopokból
                # 0: Sorszám, 1: Ügyfél/Cím, 2: Ügyintéző, 3: Telefon/Rendelés
                ugyfel_info = clean_row[1] if len(clean_row) > 1 else ""
                rendeles_info = clean_row[3] if len(clean_row) > 3 else ""
                
                # Cím keresése (Irányítószám alapú keresés)
                cim_match = re.search(r'(\d{4}\s+Debrecen[^\n]*)', ugyfel_info, re.IGNORECASE)
                cim = cim_match.group(1) if cim_match else "Cím nem azonosítható"
                
                # Név (A cella eleje a cím előtt)
                nev = ugyfel_info.split('\n')[0].replace(cim, "").strip()
                
                # Telefonszám
                tel = re.search(r'(\d{2}/\d{6,})', rendeles_info)
                
                # Rendelések kinyerése (pl. 1-L1K)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', rendeles_info)

                if sorszam:
                    extracted_data.append({
                        "Sorszám": sorszam,
                        "Név": nev[:30],
                        "Cím": cim,
                        "Telefon": tel.group(1) if tel else "",
                        "Rendelés": ", ".join(rendelesek),
                        "Db": len(rendelesek)
                    })
                    
    return pd.DataFrame(extracted_data)

# Streamlit felület az ellenőrzéshez
st.title("Interfood Táblázat Analizátor v9")
uploaded_file = st.file_uploader("PDF feltöltése", type="pdf")

if uploaded_file:
    df = extract_interfood_table_v9(uploaded_file)
    if not df.empty:
        st.success(f"Beolvasva: {len(df)} sor")
        st.dataframe(df) # Ez egy interaktív táblázat lesz
    else:
        st.error("Nem sikerült felismerni a táblázat szerkezetét.")
