import streamlit as st
import pdfplumber
import pandas as pd
import re

def final_clean_logic(text):
    # 1. TELJES KIFEJEZÉSEK IRTÁSA (Mielőtt bármi mást tennénk)
    # Ez a lista tartalmazza az összes céget és intézményt, amit eddig megbeszéltünk.
    major_blacklist = [
        "Harro Höfliger Hungary", "Harro Höfliger", "Richter Gedeon", "Mister Minit", 
        "Pearl Enterprises", "Zaza Süteményes", "Főnix Gyógyszertár", "Főnix Állatorvosi",
        "Fest-É-ker", "Medgyessy Ferenc Gimnázium", "Medgyessy Gimnázium", "Általános Iskola",
        "Triton Services", "Globiz International", "Globiz", "Otthon Centrum", 
        "Micskey Ügyvédi", "Tűzoltósági", "István Csemege", "István úti csemege",
        "Kenézy Gyula Kórház", "Kenézy Gyula", "DEKK", "DMJV Hiv", "DMJV", "Krones", "HKH",
        "Medvés Nagyker", "Javítsd Magad", "Matrackirály", "Gázkészülékbolt", "Gázkészülék"
    ]
    
    cleaned = text
    for phrase in major_blacklist:
        cleaned = re.sub(phrase, "", cleaned, flags=re.IGNORECASE)
    
    # 2. MARADÉK SZEMÉT SZAVAK (Amik nem nevek)
    trash_words = [
        "Portán", "Lapostetős", "Rövid", "Hiv", "Kcs", "Dkm", "Rzk", "Vdk", "Otp", "Fsz", 
        "Fszt", "Hungary", "Cica", "Harapós", "Nem kér számlát", "Nem", "Kft", "Zrt", "Bt"
    ]
    
    for word in trash_words:
        cleaned = re.sub(r'\b' + word + r'\b', "", cleaned, flags=re.IGNORECASE)
        
    return cleaned.strip()

def extract_v35(pdf_file):
    all_customers = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                raw_text = " ".join([w['text'] for w in block_words if "Összesen" not in w['text']])
                
                # Futtatjuk a mindent elsöprő tisztítást
                sterile_text = final_clean_logic(raw_text)
                
                # Kód és Cím (ezek stabilak)
                kod_m = re.search(r'([PZSC]-\d{6})', raw_text)
                kod = kod_m.group(1) if kod_m else ""
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', raw_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                # NÉV KINYERÉSE a már sterilizált szövegből
                search_area = sterile_text.replace(kod, "").replace(cim, "")
                # Csak a nagybetűs, 2 betűnél hosszabb szavak
                name_candidates = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]*\b', search_area)
                
                # Speciális szűrés: ne legyen benne Debrecen vagy az utca neve
                final_name_parts = [p for p in name_candidates if p not in ["Debrecen", "Sorszám"] and len(p) > 2]
                
                # Név összerakása (Vezetéknév + Keresztnév + esetleg harmadik név)
                if len(final_name_parts) >= 2:
                    ugyintezo = " ".join(final_name_parts[:3]) if len(final_name_parts) >= 3 else " ".join(final_name_parts[:2])
                else:
                    ugyintezo = final_name_parts[0] if final_name_parts else "Név nem azonosítható"

                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', raw_text)
                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Rendelés": ", ".join(rendelesek)
                })
    return pd.DataFrame(all_customers)

st.title("Interfood v35 - A Végső Megoldás")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v35(f)
    st.dataframe(df)
    st.download_button("v35 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v35.csv")
