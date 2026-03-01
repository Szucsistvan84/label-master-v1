import streamlit as st
import pdfplumber
import pandas as pd
import re

def super_clean_v39(text):
    # 1. Töröljük a cégneveket TELJES kifejezésként, hogy ne maradjon belőlük roncs
    firms = [
        "Harro Höfliger Hungary", "Harro Höfliger", "Pearl Enterprises", "DEKK Kenézy Gyula",
        "Kenézy Gyula", "DEKK", "Főnix Gyógyszertár", "Főnix Állatorvosi", "Fest-É-ker",
        "Medgyessy Gimnázium", "Általános Iskola", "Triton Services", "Javítsd Magad",
        "Matrackirály", "Ford Szalon", "ZsoZso Color", "Kormányhivatal", "Gázkészülékbolt"
    ]
    for f in firms:
        text = re.sub(re.escape(f), '', text, flags=re.IGNORECASE)

    # 2. Töröljük a maradék szemetet
    trash = [
        "Hungary", "Kft", "Zrt", "Porta", "Portán", "Teherporta", "Hiv", "Rövid", 
        "LGM", "HKH", "Krones", "Csokimax", "Mo ", "Expert", "Bolt"
    ]
    for t in trash:
        text = re.sub(r'\b' + re.escape(t) + r'\b', '', text, flags=re.IGNORECASE)

    # 3. Név kinyerése: Csak nagybetűvel kezdődő, legalább 3 betűs szavak
    # Kizárjuk a "Debrecen" szót és a technikai kódokat
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', text)
    
    clean_parts = []
    for w in words:
        if w not in ["Debrecen", "Sorszám", "Összesen"] and len(w) > 2:
            if w not in clean_parts:
                # Duplikáció szűrés (Hajós Hajós-Szabó -> Hajós-Szabó)
                is_sub = False
                for idx, existing in enumerate(clean_parts):
                    if w in existing: is_sub = True; break
                    if existing in w: clean_parts[idx] = w; is_sub = True; break
                if not is_sub:
                    clean_parts.append(w)
    
    return " ".join(clean_parts[:3])

def extract_v39(pdf_file):
    all_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_text = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                
                # Cím és Rendelés kódok
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', block_text)
                
                # NÉV TISZTÍTÁS
                name = super_clean_v39(block_text)
                
                all_data.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": name if name else "Név keresése...",
                    "Cím": cim_m.group(1).strip() if cim_m else "Cím hiba",
                    "Rendelés": ", ".join(rendelesek)
                })
    return pd.DataFrame(all_data)

st.title("Interfood v39 - A Végső Exportőr")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v39(f)
    st.write("### Az elkészült lista (Első 20 sor):")
    st.dataframe(df.head(20))
    # Itt az export gomb, ami az egészet letölti!
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("TELJES LISTA LETÖLTÉSE (CSV)", csv, "interfood_final_v39.csv")
