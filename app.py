import streamlit as st
import pdfplumber
import pandas as pd
import re

def extract_v26(pdf_file):
    all_customers = []
    
    # Drasztikusan bővített tiltólista
    stop_words = [
        "csokimax", "harro", "höfliger", "hungary", "pearl", "enterprises", "kft", "zrt", 
        "expert", "globiz", "ford", "szalon", "debrecen", "utca", "út", "tér", "emelet", 
        "ajtó", "porta", "portán", "ft", "db", "tétel", "kérem", "kérlek", "hívni", "kapu", 
        "kód", "csöngessen", "vigye", "fel", "le", "fszt", "tető", "udvar", "bejárat", 
        "mellék", "szám", "vagyok", "süteményes", "gyógyszertár", "fest-é-ker", "bolt", 
        "üzlet", "iroda", "recepció", "műszak", "ügyelet", "raktár", "emelet", "férfi", "női"
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
                
                kod_m = re.search(r'([PZSC]-\d{6})', full_text)
                kod = kod_m.group(1) if kod_m else ""
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', full_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else "Nincs tel."

                # ÜGYINTÉZŐ KERESÉSE
                search_area = full_text.replace(kod, "").replace(cim, "")
                raw_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', search_area)
                
                # 1. Alapszűrés (tiltólista + hossz)
                base_filtered = []
                for p in raw_parts:
                    if (p.lower() not in stop_words and 
                        not re.match(order_code_pattern, p) and 
                        len(p) > 2):
                        base_filtered.append(p)
                
                # 2. Duplikáció és részleges egyezés szűrése (pl. Hajós vs Hajós-Szabó)
                final_parts = []
                for p in base_filtered:
                    is_duplicate = False
                    for existing in final_parts:
                        # Ha a szó már benne van egy másikban, vagy fordítva
                        if p in existing or existing in p:
                            is_duplicate = True
                            # Ha az új szó hosszabb (pl. kötőjeles), cseréljük le a rövidebbet
                            if len(p) > len(existing):
                                final_parts[final_parts.index(existing)] = p
                            break
                    if not is_duplicate:
                        final_parts.append(p)

                ugyintezo = ""
                if len(final_parts) >= 3:
                    ugyintezo = f"{final_parts[-3]} {final_parts[-2]} {final_parts[-1]}"
                elif len(final_parts) == 2:
                    ugyintezo = f"{final_parts[0]} {final_parts[1]}"
                elif len(final_parts) == 1:
                    ugyintezo = final_parts[0]

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
st.title("Interfood v26 - Az Okos Szűrő")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v26(f)
    st.write("### Ellenőrzés: Hajós-Szabó Anett, Süteményes, Fest-É-ker...")
    st.dataframe(df)
    st.download_button("Export v26 CSV", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v26.csv")
