import streamlit as st
import pdfplumber
import pandas as pd
import re

def final_clean_v40(text, address_text):
    # 1. Brutális cég és munkahely törlés
    firms = [
        "Harro Höfliger", "Pearl Enterprises", "DEKK", "Kenézy Gyula", "Főnix", 
        "Fest-É-ker", "Medgyessy", "Általános Iskola", "Triton Services", "Javítsd Magad",
        "Matrackirály", "Ford Szalon", "ZsoZso Color", "Kormányhivatal", "Gázkészülék", "Csokimax"
    ]
    for f in firms:
        text = re.sub(re.escape(f), '', text, flags=re.IGNORECASE)

    # 2. Utcanév szavak kigyűjtése a címből (hogy tiltsuk őket a névben)
    # Ha a cím: "4031 Debrecen, Határ út 1/C", akkor a tiltott szavak: ["Határ", "út"]
    address_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    address_blacklist = [p for p in address_parts if p not in ["Debrecen"]]

    # 3. Általános tiltólista
    trash = ["Hungary", "Kft", "Zrt", "Porta", "Hiv", "Rövid", "LGM", "HKH", "Krones", "Bolt"]
    
    # 4. Név kinyerése
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', text)
    
    final_parts = []
    for w in words:
        # CSAK AKKOR kerülhet be, ha:
        # - Nem Debrecen
        # - Nincs benne az utcanévben
        # - Nincs a tiltólistán
        if (w not in ["Debrecen", "Sorszám", "Összesen"] and 
            w not in address_blacklist and 
            w.lower() not in [t.lower() for t in trash] and
            len(w) > 2):
            
            if w not in final_parts:
                # Duplikáció szűrés (Hajós-Szabó vs Hajós)
                is_sub = False
                for idx, existing in enumerate(final_parts):
                    if w in existing: is_sub = True; break
                    if existing in w: final_parts[idx] = w; is_sub = True; break
                if not is_sub:
                    final_parts.append(w)
    
    return " ".join(final_parts[:3])

def extract_v40(pdf_file):
    all_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                block_text = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                
                # Cím kinyerése ELŐRE
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block_text)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                # NÉV TISZTÍTÁSA a címet ismerve
                name = final_clean_v40(block_text, cim)
                
                all_data.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": name if name else "Név nem azonosítható",
                    "Cím": cim if cim else "Cím hiba",
                    "Rendelés": ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block_text))
                })
    return pd.DataFrame(all_data)

st.title("Interfood v40 - Az Utolsó Bástya")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v40(f)
    st.dataframe(df.head(30))
    st.download_button("CSV LETÖLTÉSE", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v40.csv")
