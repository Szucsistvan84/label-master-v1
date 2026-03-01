import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_v13(pdf_file):
    all_customers = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            
            # 1. Sávok kijelölése sorszám alapján
            markers = []
            for w in words:
                if w['x0'] < 40 and re.match(r'^\d+$', w['text']):
                    markers.append({'num': w['text'], 'top': w['top']})
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                
                # A teljes szöveg egy sorban, szóközökkel
                full_text = " ".join([w['text'] for w in block_words])
                
                # --- RÉTEGEZETT BONTÁS ---
                
                # 1. Kód kinyerése és törlése (P-123456)
                kod_m = re.search(r'([PZSC]-\d{6})', full_text)
                kod = kod_m.group(1) if kod_m else ""
                clean_text = full_text.replace(kod, "").strip()

                # 2. Cím kinyerése (Irányítószám + Debrecen + utca/házszám)
                # A minta: 4-jegyű szám + Debrecen + minden a következő vesszőig vagy nagyobb szünetig
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*[^,]+?[\d/A-Z\-]+\.?)', clean_text)
                cim = cim_m.group(1) if cim_m else ""
                
                # Mi van a cím után?
                after_address = clean_text.split(cim)[-1].strip() if cim else clean_text

                # 3. Telefonszám kinyerése (utána jövő adatokhoz kell)
                tel_m = re.search(r'(\d{2}/\d{6,10})', after_address.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else ""
                
                # 4. Ügyintéző: A cím és a telefonszám között lakik
                raw_ugyintezo = ""
                if tel:
                    # Megkeressük a telefon eredeti (szóközös) formáját a szövegben
                    tel_pattern = tel[0:2] + r'\s*/\s*' + tel[2:]
                    parts = re.split(tel_pattern, after_address)
                    raw_ugyintezo = parts[0].strip()
                else:
                    # Ha nincs tel, az első két szó a cím után
                    raw_ugyintezo = " ".join(after_address.split()[:2])

                # 5. Rendelések (X-YYYY)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', after_address)
                rend_str = ", ".join(rendelesek)

                # 6. Beszedendő összeg
                # A rendelések utáni szám, ami előtt ott a darabszám (pl: "2 11 555 Ft")
                osszeg_m = re.search(r'(\d+)\s+(\d[\d\s]*)\s*Ft', after_address)
                osszeg = osszeg_m.group(2).strip() if osszeg_m else "0"

                # 7. Megjegyzés
                # Minden, ami az összeg vagy a rendelés után maradt (pl. "porta", "kapukód")
                megj = ""
                specialis = ["porta", "kapukód", "kcs", "kulcs", "hívni", "új épület"]
                for s in specialis:
                    if s in after_address.lower():
                        m_m = re.search(f'({s}[^,]+)', after_address, re.IGNORECASE)
                        if m_m: megj = m_m.group(1)

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": raw_ugyintezo,
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": rend_str,
                    "Összeg": osszeg + " Ft",
                    "Megjegyzés": megj
                })

    return pd.DataFrame(all_customers)

# --- Felület ---
st.title("Interfood v13 - Tiszta Adat")
uploaded_file = st.file_uploader("PDF feltöltése", type="pdf")

if uploaded_file:
    df = extract_v13(uploaded_file)
    st.write("### Az új, tisztított táblázat:")
    # Itt már nincs a régi felesleges oszlop
    st.dataframe(df)
    
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("CSV Export", csv, "interfood_v13.csv")
