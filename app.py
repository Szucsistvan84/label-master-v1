import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_v15(pdf_file):
    all_customers = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = []
            for w in words:
                if w['x0'] < 40 and re.match(r'^\d+$', w['text']):
                    markers.append({'num': w['text'], 'top': w['top']})
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                full_text = " ".join([w['text'] for w in block_words])
                
                # --- 1. FIX ADATOK KINYERÉSE ---
                # Cím
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*[^,]+?[\d/A-Z\-]+\.?)', full_text)
                cim = cim_m.group(1) if cim_m else ""
                
                # Telefon (Horgony a névhez)
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else ""

                # Rendelések
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                
                # Összeg
                osszeg_m = re.search(r'(\d[\d\s]*)\s*Ft', full_text)
                osszeg = osszeg_m.group(1).strip() if osszeg_m else "0"

                # --- 2. ÜGYINTÉZŐ KERESÉSE (A horgonyok között) ---
                ugyintezo = ""
                if cim and tel:
                    # Megkeressük mi van a Cím és a Telefonszám között
                    # Ehhez a telefonszám első pár számjegyét keressük a szövegben
                    tel_start = tel[:2] + "/"
                    pattern = f"{re.escape(cim)}(.*?){tel_start}"
                    name_area = re.search(pattern, full_text)
                    
                    if name_area:
                        raw_name = name_area.group(1).strip()
                        # Tisztítás: levágjuk a cégneveket (amik per jellel vagy kft-vel végződnek)
                        # Csak a valódi nevet tartjuk meg (Nagybetűs szavak a végén)
                        clean_name = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', raw_name)
                        if len(clean_name) >= 2:
                            ugyintezo = " ".join(clean_name[-2:]) # Az utolsó két nagybetűs szó általában a név

                # --- 3. MEGJEGYZÉS ---
                megj = ""
                for kw in ["kapukód", "porta", "kcs", "kulcs", "hívni"]:
                    if kw in full_text.lower():
                        m_m = re.search(f'({kw}[^,]+)', full_text, re.IGNORECASE)
                        if m_m: megj = m_m.group(1)

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo if ugyintezo else "Név nem lelt",
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": ", ".join(rendelesek),
                    "Összeg": osszeg + " Ft",
                    "Megjegyzés": megj
                })

    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v15 - Szikra")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    df = extract_v15(f)
    st.write("### Ellenőrzés: Csak az Ügyintéző és a Cím")
    st.table(df[["Sorszám", "Ügyintéző", "Cím", "Összeg"]].head(10))
    
    st.dataframe(df)
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("Export CSV", csv, "interfood_v15.csv")
