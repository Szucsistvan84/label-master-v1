import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_v36(text):
    # 1. Nagytakarítás: Cégek, helyszínek, intézmények
    blacklist = [
        r"Optipont", r"Pláza", r"Ford\s*Szalon", r"Ford", r"ZsoZso\s*Color", 
        r"LGM", r"Harro\s*Höfliger", r"Richter\s*Gedeon", r"Micskey\s*Ügyvédi",
        r"DEKK", r"Kenézy\s*Gyula", r"DMJV", r"Hiv", r"Portán", r"Tűzoltósági",
        r"HKH", r"Krones", r"Globiz", r"Pearl\s*Enterprises"
    ]
    cleaned = text
    for p in blacklist:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE)
    
    # 2. Technikai kódok és szemét törlése
    trash = ["DKM", "RZK", "VDK", "KCS", "OTP", "FSZ", "FSZT", "CICA", "NEM"]
    for t in trash:
        cleaned = re.sub(r'\b' + t + r'\b', "", cleaned, flags=re.IGNORECASE)
        
    return cleaned.strip()

def extract_v36(pdf_file):
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
                
                # Sterilizálás
                clean_text = clean_v36(raw_text)
                
                # Cím és kód
                kod_m = re.search(r'([PZSC]-\d{6})', raw_text)
                kod = kod_m.group(1) if kod_m else ""
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', raw_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                # NÉVÉPÍTÉS - DUPLIKÁCIÓ ELLENI VÉDELEMMEL
                search_area = clean_text.replace(kod, "").replace(cim, "")
                potential = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]*\b', search_area)
                
                name_parts = []
                for p in potential:
                    # Csak ha nem tiltott, nem Debrecen, és MÉG NINCS BENNE a listában
                    if p not in ["Debrecen", "Sorszám"] and len(p) > 2:
                        # Ez a sor akadályozza meg a Batiz Batiz-t:
                        if p not in name_parts:
                            name_parts.append(p)

                # Összeállítás (Vezetéknév + Keresztnév)
                ugyintezo = " ".join(name_parts[:3]) if len(name_parts) >= 2 else (name_parts[0] if name_parts else "Név hiba")

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Rendelés": ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', raw_text))
                })
    return pd.DataFrame(all_customers)

st.title("Interfood v36 - A Duplikáció-gyilkos")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v36(f)
    st.dataframe(df)
