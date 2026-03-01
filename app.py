import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_institutions_and_firms_v34(text):
    # A legfrissebb visszajelzéseid alapján bővített "irtólista"
    blacklist = [
        r"Micskey\s*Ügyvédi", r"Otthon\s*Centrum", r"Medvés\s*Nagyker",
        r"DMJV\s*Hiv", r"Főnix\s*Állatorvosi", r"Önkiszolgáló",
        r"Tűzoltósági", r"István\s*Csemege", r"Kenézy\s*Gyula",
        r"Harro\s*Höfliger\s*Hungary", r"Pearl\s*Enterprises", r"DEKK",
        r"Zaza\s*Süteményes", r"Főnix\s*Gyógyszertár", r"Fest-É-ker",
        r"Medgyessy\s*Gimnázium", r"Általános\s*Iskola", r"Triton\s*Services",
        r"Globiz", r"Krones", r"HKH", r"Mister\s*Minit"
    ]
    cleaned = text
    for phrase in blacklist:
        cleaned = re.sub(phrase, "", cleaned, flags=re.IGNORECASE)
    return cleaned

def extract_v34(pdf_file):
    all_customers = []
    
    # Megjegyzés-szerű szavak, amik sosem részei a névnek
    stop_words = [
        "portán", "lapostetős", "gyógyszertár", "rövid", "hiv", "csokimax", 
        "kft", "zrt", "debrecen", "utca", "út", "tér", "fszt", "fsz",
        "dkm", "rzk", "vdk", "kcs", "otp", "cica", "nem", "számlát"
    ]

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
                raw_text = " ".join([w['text'] for w in block_words if "Összesen" not in w['text']])
                
                # 1. SZÖVEG TISZTÍTÁSA
                cleaned_text = clean_institutions_and_firms_v34(raw_text)
                
                kod_m = re.search(r'([PZSC]-\d{6})', cleaned_text)
                kod = kod_m.group(1) if kod_m else ""
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', cleaned_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                # 2. NÉV KERESÉSE
                search_area = cleaned_text.replace(kod, "").replace(cim, "")
                potential_names = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]*\b', search_area)
                
                name_parts = []
                for p in potential_names:
                    if p.lower() not in stop_words and len(p) > 2:
                        if p not in name_parts:
                            is_sub = False
                            for idx, existing in enumerate(name_parts):
                                if p in existing: is_sub = True; break
                                if existing in p: name_parts[idx] = p; is_sub = True; break
                            if not is_sub:
                                name_parts.append(p)

                # Név összerakása (első 2-3 szó)
                ugyintezo = " ".join(name_parts[:3]) if len(name_parts) >= 3 else " ".join(name_parts[:2])
                if not name_parts: ugyintezo = "Név nem azonosítható"

                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', raw_text)
                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Rendelés": ", ".join(rendelesek)
                })
    return pd.DataFrame(all_customers)

st.title("Interfood v34 - Páncélterem Üzemmód")
f = st.file_uploader("PDF feltöltése (Bármelyik havi!)", type="pdf")
if f:
    df = extract_v34(f)
    st.write("### Teszt: Móricz-Nagy Krisztina, Bereczky Bence, Sztalos Károlyné")
    st.dataframe(df)
    st.download_button("v34 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v34.csv")
