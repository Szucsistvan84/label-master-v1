import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_text_from_institutions(text):
    # Itt a teljes kifejezéseket irtjuk ki, mielőtt a nevet keresnénk
    blacklist_phrases = [
        r"DEKK Kenézy Gyula\s*.*?Kórház", 
        r"Kenézy Gyula", 
        r"DMJV Önkormányzat",
        r"DMJV",
        r"István úti csemege",
        r"Mister Minit",
        r"Richter Gedeon",
        r"Javítsd Magad",
        r"Ifjúsági Ház",
        r"Kormányhivatal"
    ]
    cleaned = text
    for phrase in blacklist_phrases:
        cleaned = re.sub(phrase, "", cleaned, flags=re.IGNORECASE)
    return cleaned

def extract_v32(pdf_file):
    all_customers = []
    
    # Csak azokat hagytam itt, amik SOHA nem lehetnek nevek
    stop_words = [
        "csokimax", "harro", "höfliger", "kft", "zrt", "debrecen", "utca", "út", "tér", 
        "emelet", "ajtó", "porta", "portán", "ft", "db", "tétel", "kérem", "kérlek", 
        "hívni", "kapu", "kód", "csöngessen", "fszt", "fsz", "otp", "kcs", "dkm", "rzk", 
        "vdk", "lgm", "hkh", "cica", "nem", "szállításkor", "gázkészülék"
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
                raw_block_text = " ".join([w['text'] for w in block_words if "Összesen" not in w['text']])
                
                # 1. LÉPÉS: Kifejezések tisztítása (Gyula marad, ha nem Kenézy)
                clean_block = clean_text_from_institutions(raw_block_text)
                
                kod_m = re.search(r'([PZSC]-\d{6})', clean_block)
                kod = kod_m.group(1) if kod_m else ""
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', clean_block)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                # 2. LÉPÉS: Név keresése a már tisztított szövegben
                search_area = clean_block.replace(kod, "").replace(cim, "")
                raw_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]*\b', search_area)
                
                filtered = []
                for p in raw_parts:
                    if p.lower() not in stop_words and len(p) > 2:
                        # Duplikáció szűrés (Hajós-Szabó fix)
                        if not any(p in f or f in p for f in filtered):
                            filtered.append(p)
                        elif any(f in p for f in filtered): # Ha a hosszabb van meg, cseréljük
                            idx = [i for i, f in enumerate(filtered) if f in p][0]
                            filtered[idx] = p

                if len(filtered) >= 2:
                    # Az első két-három értelmes szó a név
                    ugyintezo = " ".join(filtered[:3]) if len(filtered) >= 3 else " ".join(filtered[:2])
                else:
                    ugyintezo = filtered[0] if filtered else "Név nem azonosítható"

                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', raw_block_text)
                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Rendelés": ", ".join(rendelesek)
                })
    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v32 - Az Intelligens Gyula-szűrő")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v32(f)
    st.write("### Ellenőrizd: Szilágyi Anita (Kenézy nélkül) és Tőkés István")
    st.dataframe(df)
