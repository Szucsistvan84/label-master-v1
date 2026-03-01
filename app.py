import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_v17(pdf_file):
    all_customers = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = []
            for w in words:
                # Sorszám keresése a bal oldalon
                if w['x0'] < 40 and re.match(r'^\d+$', w['text']):
                    markers.append({'num': w['text'], 'top': w['top']})
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                full_text = " ".join([w['text'] for w in block_words])
                
                # --- 1. CÍM KERESÉSE (Bővített minta) ---
                # Keressük az irányítószámot, Debrecent, és mindent, ami házszámnak tűnik a végén
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', full_text)
                cim = cim_m.group(1) if cim_m else ""
                
                # --- 2. TELEFON KERESÉSE ---
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else ""

                # --- 3. ÜGYINTÉZŐ KERESÉSE (Kötőjel barát) ---
                ugyintezo = ""
                if cim and tel:
                    tel_start = tel[:2] + "/"
                    pattern = f"{re.escape(cim)}(.*?){tel_start}"
                    name_area = re.search(pattern, full_text)
                    if name_area:
                        # Olyan szavakat keresünk, amik nagybetűvel kezdődnek ÉS lehet bennük kötőjel
                        names = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', name_area.group(1))
                        # Kiszűrjük a "Debrecen" szót és a cégneveket ha tudjuk
                        names = [n for n in names if n.lower() != "debrecen" and len(n) > 2]
                        if len(names) >= 2:
                            ugyintezo = " ".join(names[-2:])

                # --- 4. RENDELÉS ÖSSZESÍTŐ ÉS ÖSSZEG SZÉTVÁLASZTÁSA ---
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                
                # Keressük a mintát: [Összesítő szám] [Összeg] Ft
                # Példa: "2 11 555 Ft" -> Darab: 2, Összeg: 11 555
                osszesito_m = re.search(r'(\d+)\s+(\d[\d\s]*)\s*Ft', full_text)
                
                db_osszesen = osszesito_m.group(1) if osszesito_m else str(len(rendelesek))
                fizetendo = osszeg_m.group(1).strip() if (osszeg_m := re.search(r'(\d[\d\s]*)\s*Ft', full_text)) else "0"

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": ", ".join(rendelesek),
                    "Összesen (db)": db_osszesen,
                    "Fizetendő": fizetendo + " Ft"
                })
    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v17 - Hibajavító Verzió")
uploaded_file = st.file_uploader("Menetterv PDF", type="pdf")

if uploaded_file:
    df = extract_v17(uploaded_file)
    st.write("### Ellenőrizzük a javított adatokat:")
    # Itt most már látnod kellene a teljes neveket és címeket
    st.dataframe(df)
    
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("Export CSV", csv, "interfood_v17.csv")
