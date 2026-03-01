import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_v38(raw_text):
    # 1. Brutális tiltólista (csak teljes szavakra!)
    blacklist = [
        "Kft", "Zrt", "Bt", "Csokimax", "Harro", "Höfliger", "Hungary", "Richter", "Gedeon",
        "Főnix", "Gyógyszertár", "Állatorvosi", "Fest-É-ker", "Medgyessy", "Iskola", "Általános",
        "Javítsd", "Magad", "Triton", "Services", "Matrackirály", "Gázkészülék", "Bolt",
        "Micskey", "Ügyvédi", "Tűzoltósági", "Kormányhivatal", "Hivatal", "Kormány",
        "Porta", "Portán", "Teherporta", "Épület", "Lapostetős", "Rövid", "LGM", "HKH", "Krones"
    ]
    
    # 2. Vegyük ki a kódokat (P-123456) és a Debrecen... részt
    text_no_code = re.sub(r'[PZSC]-\d{6}', '', raw_text)
    text_no_address = re.sub(r'\d{4}\s+Debrecen.*', '', text_no_code)
    
    # 3. Csak a nagybetűs szavakat gyűjtsük ki, amik nem tiltottak
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]*\b', text_no_address)
    
    final_name_parts = []
    for w in words:
        low_w = w.lower()
        # Ne legyen tiltott, ne legyen "Debrecen", és ne legyen duplikáció
        if low_w not in [b.lower() for b in blacklist] and low_w != "debrecen":
            # Duplikáció szűrés: ha a "Móricz-Nagy" már benne van, a "Móricz" ne kerüljön be
            is_duplicate = False
            for existing in final_name_parts:
                if low_w in existing.lower() or existing.lower() in low_w:
                    is_duplicate = True
                    # Ha a mostani szó hosszabb (pl. kötőjeles), cseréljük le a rövidet
                    if len(w) > len(existing):
                        final_name_parts[final_name_parts.index(existing)] = w
                    break
            if not is_duplicate:
                final_name_parts.append(w)

    return " ".join(final_name_parts[:3]) # Max 3 szó a névnek

def extract_v38(pdf_file):
    data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Itt a sorszámok alapján blokkolunk, ahogy eddig
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_text = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                
                # Cím kinyerése (ez kell az etikettre)
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text)
                
                # Név tisztítása
                name = clean_v38(block_text)
                
                data.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": name,
                    "Cím": cim_m.group(1).strip() if cim_m else "Cím hiba",
                    "Rendelés": ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block_text))
                })
    return pd.DataFrame(data)

# --- UI ---
st.title("Interfood v38 - A Tisztasági Teszt")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v38(f)
    st.table(df.head(20)) # Táblázatban mutatjuk az első 20-at az ellenőrzéshez
