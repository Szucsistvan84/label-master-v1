import streamlit as st
import pdfplumber
import pandas as pd
import re

def extract_v19(pdf_file):
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
                
                # --- 1. CÍM ÉS TELEFON ---
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', full_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else "Nincs tel."

                # --- 2. ÜGYINTÉZŐ KERESÉSE (Szuper-Mágnes) ---
                # Kivesszük az irányítószámot és a Debrecent, hogy ne zavarjanak
                clean_text = full_text.replace("Debrecen", "").replace("4031", "").replace("4002", "").replace("4030", "")
                
                # Minden szót megvizsgálunk, ami nagybetűvel kezdődik és nem kód/cím
                names = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
                # Szűrjük a tipikus nem-neveket
                filtered_names = [n for n in names if n.lower() not in ["utca", "út", "tér", "kft", "zrt", "fszt", "emelet", "ajtó", "porta"]]
                
                ugyintezo = ""
                if filtered_names:
                    # Ha van kötőjeles (Szabó-Salák), az legyen az alap
                    hyphens = [n for n in filtered_names if "-" in n]
                    if hyphens:
                        idx = filtered_names.index(hyphens[0])
                        if idx + 1 < len(filtered_names): ugyintezo = f"{hyphens[0]} {filtered_names[idx+1]}"
                        elif idx - 1 >= 0: ugyintezo = f"{filtered_names[idx-1]} {hyphens[0]}"
                        else: ugyintezo = hyphens[0]
                    else:
                        # Sápi Réka, Nagy Ákos stb. esetén az utolsó két értelmes nagybetűs szó
                        if len(filtered_names) >= 2:
                            ugyintezo = f"{filtered_names[-2]} {filtered_names[-1]}"
                        else:
                            ugyintezo = filtered_names[0]

                # --- 3. RENDELÉS ÉS PÉNZ ---
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                # Összesítő db (pl. "2 tétel" vagy "2 11 555 Ft" mintából a 2-es)
                db_m = re.search(r'(\d+)\s+\d[\d\s]*\s*Ft', full_text)
                db_osszesen = db_m.group(1) if db_m else str(len(rendelesek))
                
                # Fizetendő (csak a számok a Ft előtt)
                money_m = re.search(r'(\d[\d\s]*)\s*Ft', full_text)
                fizetendo = money_m.group(1).replace(" ", "") if money_m else "0"

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
st.title("Interfood v19 - Szuper-Mágnes")
f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = extract_v19(f)
    st.success("Adatok feldolgozva!")
    st.dataframe(df)
    st.download_button("CSV letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v19.csv")
