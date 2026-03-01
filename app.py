import streamlit as st
import pdfplumber
import pandas as pd
import re

def absolute_clean_v41(text, address_text):
    # 1. Cégek és fix munkahelyek
    firms = [
        "Harro Höfliger", "Pearl Enterprises", "DEKK", "Kenézy Gyula", "Főnix", 
        "Fest-É-ker", "Medgyessy", "Általános Iskola", "Triton Services", "Javítsd Magad",
        "Matrackirály", "Ford Szalon", "ZsoZso Color", "Kormányhivatal", "Gázkészülék", "Csokimax"
    ]
    for f in firms:
        text = re.sub(re.escape(f), '', text, flags=re.IGNORECASE)

    # 2. Utcanév tiltás
    address_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    address_blacklist = [p for p in address_parts if p not in ["Debrecen"]]

    # 3. KCS, DKM, Portán és társai - KIFEJEZETT TÖRLÉSE
    # Itt most már minden kisbetűs/nagybetűs variációt kigyilkolunk
    micro_trash = ["KCS", "DKM", "Portán", "Porta", "Hungary", "Kft", "Zrt", "Hiv", "Rövid", "LGM", "HKH"]
    
    # 4. Név kinyerése
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰa-záéíóöőúüű-]+\b', text)
    
    final_parts = []
    for w in words:
        # Szűrés: Ne legyen címben, ne legyen a micro_trash listában, és kezdődjön nagybetűvel
        if (w not in ["Debrecen", "Sorszám", "Összesen"] and 
            w not in address_blacklist and 
            w.upper() not in [t.upper() for t in micro_trash] and
            len(w) > 2 and
            w[0].isupper()): # Csak nagybetűvel kezdődő maradhat!
            
            if w not in final_parts:
                is_sub = False
                for idx, existing in enumerate(final_parts):
                    if w in existing: is_sub = True; break
                    if existing in w: final_parts[idx] = w; is_sub = True; break
                if not is_sub:
                    final_parts.append(w)
    
    return " ".join(final_parts[:3])

def extract_v41(pdf_file):
    all_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_text = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                name = absolute_clean_v41(block_text, cim)
                
                all_data.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": name if name else "Név keresése",
                    "Cím": cim,
                    "Rendelés": ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block_text))
                })
    return pd.DataFrame(all_data)

st.title("Interfood v41 - A Makulátlan")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v41(f)
    st.dataframe(df)
    st.download_button("VÉGLEGES CSV LETÖLTÉSE", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v41.csv")
