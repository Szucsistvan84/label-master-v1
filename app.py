import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_v12(pdf_file):
    all_customers = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            
            # 1. Sorszámok keresése (Sávok kijelölése)
            markers = []
            for w in words:
                if w['x0'] < 40 and re.match(r'^\d+$', w['text']):
                    markers.append({'num': w['text'], 'top': w['top']})
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                full_text = " ".join([w['text'] for w in block_words])
                
                # --- ADATKINYERÉS ---
                
                # 1. Kód (P-123456)
                kod_m = re.search(r'([PZSC]-\d{6})', full_text)
                kod = kod_m.group(1) if kod_m else ""

                # 2. Beszedendő összeg (Pl: 11 555 Ft)
                # Olyan számot keresünk, ami után közvetlenül ott a "Ft"
                osszeg_m = re.search(r'(\d[\d\s]*)\s*Ft', full_text)
                osszeg = osszeg_m.group(1).strip() if osszeg_m else "0"

                # 3. Rendelések és darabszám
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                db = len(rendelesek)

                # 4. Telefonszám
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else ""

                # 5. CÍM ÉS ÜGYINTÉZŐ SZÉTVÁLASZTÁSA
                # A cím általában a "40xx Debrecen,"-el kezdődik és a házszámig tart
                cim = ""
                ugyintezo = ""
                
                # Megkeressük a címet a "Debrecen," kulcsszó és az azt követő utca/szám alapján
                addr_m = re.search(r'(\d{4}\s+Debrecen,\s*[^,]+(?:utca|u\.|út|útja|tér|sor|krt\.|lakótelep|ltp\.)?\s*[\d\w/.\-\s]+(?=,?\s))', full_text, re.IGNORECASE)
                
                if addr_m:
                    cim = addr_m.group(1).strip()
                    # Ami a cím után van, de a telefonszám/rendelés előtt, az lesz az ügyintéző
                    # Ezt gyakran nehéz pontosan megfogni, ezért a maradék szövegből tisztítjuk
                    maradek = full_text.replace(kod, "").replace(cim, "").replace(osszeg + " Ft", "")
                    # Kiszűrjük belőle a rendeléseket és a telefonszámot is
                    for r in rendelesek: maradek = maradek.replace(r, "")
                    if tel: maradek = maradek.replace(tel, "")
                    
                    # Ami marad, abból az első 2-3 szó az ügyintéző (ha nem sorszám)
                    m_parts = [p for p in maradek.split() if not p.isdigit() and len(p) > 2]
                    ugyintezo = " ".join(m_parts[:2]) # Pl. "Tőkés István"
                
                # Megjegyzés (kapukód stb.)
                megj = ""
                if "kapukód" in full_text.lower() or "porta" in full_text.lower():
                    m_m = re.search(r'((?:kapukód|porta|kcs|kulcs)[^,]+)', full_text, re.IGNORECASE)
                    megj = m_m.group(1) if m_m else ""

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Kód": kod,
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": ", ".join(rendelesek),
                    "Összeg": osszeg + " Ft",
                    "Db": db,
                    "Megjegyzés": megj
                })

    return pd.DataFrame(all_customers)

# --- Streamlit Felület ---
st.title("Interfood Etikett v12 - Precíziós vágás")
f = st.file_uploader("Menetterv PDF", type="pdf")

if f:
    df = extract_v12(f)
    st.write("### Beolvasott adatok")
    # Megjelenítésnél csak a futárnak fontos oszlopokat mutatjuk
    st.dataframe(df[["Sorszám", "Ügyintéző", "Cím", "Telefon", "Rendelés", "Összeg", "Megjegyzés"]])
    
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("Adatok mentése (CSV)", csv, "interfood_v12.csv")
