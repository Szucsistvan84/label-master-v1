import streamlit as st
import pdfplumber
import pandas as pd
import re

def extract_v21(pdf_file):
    all_customers = []
    
    # Gyakori cégnevek és tiltott szavak listája
    tiltolista = ["csokimax", "harro", "höfliger", "hungary", "pearl", "enterprises", "kft", "zrt", "expert", "globiz", "ford", "szalon"]
    
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
                full_text = " ".join([w['text'] for w in block_words])
                
                # 1. FIX ADATOK
                kod_m = re.search(r'([PZSC]-\d{6})', full_text)
                kod = kod_m.group(1) if kod_m else ""
                
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', full_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else "Nincs tel."

                # 2. ÜGYINTÉZŐ KERESÉSE (Emberi név logika)
                clean_area = full_text.replace(kod, "").replace(cim, "")
                # Szavak gyűjtése, amik nagybetűsek és nem tiltottak
                raw_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_area)
                
                filtered = []
                for p in raw_parts:
                    if p.lower() not in tiltolista and p.lower() not in ["debrecen", "utca", "út", "tér", "emelet", "ajtó"]:
                        filtered.append(p)
                
                ugyintezo = ""
                if len(filtered) >= 2:
                    # Ha több szó maradt, az utolsó kettőt-hármat vesszük, 
                    # mert a cégnév (ha nem volt a tiltólistán) általában elöl van
                    if "-" in filtered[0] or "-" in filtered[1]: # Kötőjeles név kezelése
                        ugyintezo = " ".join(filtered[:3]) if len(filtered) >= 3 else " ".join(filtered)
                    else:
                        ugyintezo = f"{filtered[-2]} {filtered[-1]}"
                elif len(filtered) == 1:
                    ugyintezo = filtered[0]

                # 3. RENDELÉS, DB ÉS ÖSSZEG
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                
                # Pénzösszeg kinyerése (szóközök nélkül)
                money_m = re.search(r'(\d[\d\s]*)\s*Ft', full_text)
                fizetendo_raw = money_m.group(1).replace(" ", "") if money_m else "0"
                
                # Darabszám tisztítása (az összeg előtti szám)
                db_clean = "0"
                if money_m:
                    text_before_money = full_text[:money_m.start()].strip()
                    db_find = re.findall(r'\b(\d+)\b', text_before_money)
                    if db_find: db_clean = db_find[-1]
                
                if db_clean == "0" or int(db_clean) > 50: # Hibaszűrés
                    db_clean = str(len(rendelesek))

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": ", ".join(rendelesek),
                    "Db": db_clean,
                    "Fizetendő": fizetendo_raw + " Ft"
                })
    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v21 - Emberi Név Tisztító")
f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = extract_v21(f)
    st.success("Adatok beolvasva! Ellenőrizd Tőkés Istvánt!")
    st.dataframe(df)
    st.download_button("Export v21 CSV", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v21.csv")
