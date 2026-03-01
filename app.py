import streamlit as st
import pdfplumber
import pandas as pd
import re

def extract_v20(pdf_file):
    all_customers = []
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
                
                # 1. KÓD ÉS CÍM IZOLÁLÁSA
                kod_m = re.search(r'([PZSC]-\d{6})', full_text)
                kod = kod_m.group(1) if kod_m else ""
                
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', full_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else "Nincs tel."

                # 2. ÜGYINTÉZŐ KERESÉSE (Tisztított területen)
                # Töröljük a kódot és a címet a keresési területből, hogy ne zavarjanak
                search_area = full_text.replace(kod, "").replace(cim, "")
                
                # Keressük a neveket (Nagybetűs szavak, kötőjellel is)
                # Kizárjuk a Debrecent és a technikai szavakat
                name_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', search_area)
                filtered = [n for n in name_parts if n.lower() not in 
                            ["debrecen", "utca", "út", "tér", "kft", "zrt", "mo", "hungary"]]
                
                ugyintezo = ""
                if len(filtered) >= 2:
                    # Ha van kötőjeles név, az elsőbbséget élvez
                    hyphenated = [f for f in filtered if "-" in f]
                    if hyphenated:
                        h_idx = filtered.index(hyphenated[0])
                        # Megpróbáljuk összerakni a keresztévvel (ami előtte vagy utána van)
                        if h_idx + 1 < len(filtered): ugyintezo = f"{filtered[h_idx]} {filtered[h_idx+1]}"
                        elif h_idx - 1 >= 0: ugyintezo = f"{filtered[h_idx-1]} {filtered[h_idx]}"
                        else: ugyintezo = filtered[h_idx]
                    else:
                        # Az első két megmaradt nagybetűs szó (pl. Sápi Réka)
                        ugyintezo = f"{filtered[0]} {filtered[1]}"
                elif len(filtered) == 1:
                    ugyintezo = filtered[0]

                # 3. RENDELÉS ÉS PÉNZ (Precíziós javítás)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                
                # Összeg: a Ft előtti utolsó számsor
                money_find = re.findall(r'(\d[\d\s]*)\s*Ft', full_text)
                fizetendo = money_find[-1].replace(" ", "") if money_find else "0"
                
                # Darabszám: az összeg előtti szám a blokkban
                db_m = re.search(r'(\d+)\s+' + re.escape(fizetendo if money_find else "---") + r'\s*Ft', full_text.replace(" ",""))
                db_osszesen = db_m.group(1) if db_m else str(len(rendelesek))

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": ", ".join(rendelesek),
                    "Db": db_osszesen,
                    "Fizetendő": fizetendo + " Ft"
                })
    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v20 - Ügyintéző Mentőakció")
f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = extract_v20(f)
    st.success("Adatok stabilizálva!")
    st.dataframe(df)
    st.download_button("Export v20 CSV", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v20.csv")
