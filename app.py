import streamlit as st
import pdfplumber
import pandas as pd
import re

def extract_v25(pdf_file):
    all_customers = []
    
    stop_words = [
        "csokimax", "harro", "höfliger", "hungary", "pearl", "enterprises", "kft", "zrt", 
        "expert", "globiz", "ford", "szalon", "debrecen", "utca", "út", "tér", "emelet", 
        "ajtó", "porta", "ft", "db", "tétel", "kérem", "hívni", "kapu", "kód", "csöngessen", 
        "vigye", "fel", "le", "fszt", "tető", "udvar", "bejárat", "mellék", "szám", "vagyok"
    ]
    
    order_code_pattern = r'^[A-Z0-9]{1,4}$'

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

                # 2. ÜGYINTÉZŐ KERESÉSE (Duplikáció elleni védelemmel)
                search_area = full_text.replace(kod, "").replace(cim, "")
                raw_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', search_area)
                
                filtered = []
                for p in raw_parts:
                    if (p.lower() not in stop_words and 
                        not re.match(order_code_pattern, p) and 
                        len(p) > 2):
                        # Csak akkor adjuk hozzá, ha még nincs benne (duplikáció szűrés)
                        if p not in filtered:
                            filtered.append(p)
                
                ugyintezo = ""
                if len(filtered) >= 3:
                    # Megnézzük, hogy az utolsó 3 szó egyedi-e
                    ugyintezo = f"{filtered[-3]} {filtered[-2]} {filtered[-1]}"
                elif len(filtered) == 2:
                    ugyintezo = f"{filtered[0]} {filtered[1]}"
                elif len(filtered) == 1:
                    ugyintezo = filtered[0]

                # 3. RENDELÉS ÉS PÉNZ
                money_m = re.search(r'(\d[\d\s]*)\s*Ft', full_text)
                fizetendo = money_m.group(1).replace(" ", "") if money_m else "0"
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": ", ".join(rendelesek),
                    "Db": str(len(rendelesek)),
                    "Fizetendő": fizetendo + " Ft"
                })
    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v25 - Duplikáció Szűrő")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v25(f)
    st.write("### Ellenőrzés: Hajós-Szabó Anett és Nagy Izabella Ilona")
    st.dataframe(df)
    st.download_button("Export v25 CSV", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v25.csv")
