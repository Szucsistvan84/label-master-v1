import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_name_final(text):
    # 1. Minden olyan kifejezés, ami MUNKAHELY vagy CÉG (A te listád alapján)
    workplace_blacklist = [
        "Kft", "Zrt", "Bt", "Csokimax", "Harro Höfliger", "Hungary", "Pearl Enterprises",
        "Gyógyszertár", "Főnix", "Fest-É-ker", "Medgyessy", "Általános Iskola", "Iskola",
        "Javítsd Magad", "István Csemege", "Triton Services", "Lapostetős", "Matrackirály",
        "Ifjúsági Ház", "Ifjúsági", "Kormányhivatal", "Kormány", "Harapós", "Bolt",
        "Gázkészülékbolt", "Gázkészülék", "Optipont", "Pláza", "Ford Szalon", "Ford",
        "ZsoZso Color", "LGM", "DEKK", "Kenézy Gyula", "DMJV", "Micskey Ügyvédi",
        "Tűzoltósági", "HKH", "Krones", "Globiz", "International", "Medvés Nagyker",
        "Otthon Centrum", "Önkiszolgáló", "Portán", "Rövid", "Hiv", "Üzlet"
    ]
    
    cleaned = text
    # Teljes szavakat/kifejezéseket törlünk, nem vágunk bele a közepébe
    for phrase in workplace_blacklist:
        cleaned = re.sub(r'\b' + re.escape(phrase) + r'\b', '', cleaned, flags=re.IGNORECASE)
    
    # 2. Tisztítás a felesleges karakterektől
    cleaned = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ\s-]', ' ', cleaned)
    
    # 3. Duplikációk kiszűrése (pl. Móricz Móricz-Nagy -> Móricz-Nagy)
    parts = cleaned.split()
    final_parts = []
    for p in parts:
        # Csak akkor adjuk hozzá, ha még nincs benne, és nem Debrecen vagy Sorszám
        if p.lower() not in [x.lower() for x in final_parts] and p.lower() not in ["debrecen", "sorszám"]:
            if len(p) > 2 or p.isupper(): # Rövidítések (pl. M.) maradhatnak ha nagybetűsek
                final_parts.append(p)
    
    # 4. Ha a vezetéknév része a kötőjeles névnek, csak a hosszabbat tartsuk meg
    # (Juhász Juhász-Takács -> Juhász-Takács)
    result_name = " ".join(final_parts)
    for p1 in final_parts:
        for p2 in final_parts:
            if p1 != p2 and p1 in p2 and "-" in p2:
                result_name = result_name.replace(p1, "").strip()

    return " ".join(result_name.split()) # Dupla szóközök ellen

def extract_v37(pdf_file):
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
                
                # Adatok kinyerése
                kod_m = re.search(r'([PZSC]-\d{6})', raw_text)
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', raw_text)
                
                # NÉV TISZTÍTÁSA
                ugyintezo = clean_name_final(raw_text.replace(kod_m.group(0) if kod_m else "", "").replace(cim_m.group(0) if cim_m else "", ""))
                
                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo if ugyintezo else "Név nem található",
                    "Cím": cim_m.group(1).strip() if cim_m else "Cím hiba",
                    "Rendelés": ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', raw_text))
                })
    return pd.DataFrame(all_customers)

st.title("Interfood v37 - A Végleges Névtisztító")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v37(f)
    st.dataframe(df)
    st.download_button("v37 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v37.csv")
