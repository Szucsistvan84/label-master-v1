import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_phone(tel_str):
    if not tel_str or tel_str == "Nincs tel.":
        return tel_str
    # Csak a számokat és a perjelet tartjuk meg
    cleaned = re.sub(r'[^0-9/]', '', tel_str)
    # Ha van benne perjel, de rossz helyen (pl 70/5...)
    if "/" in cleaned:
        parts = cleaned.split("/")
        return f"{parts[0]}/{parts[1]}"
    return cleaned

def extract_v28(pdf_file):
    all_customers = []
    
    stop_words = [
        "csokimax", "harro", "höfliger", "hungary", "pearl", "enterprises", "kft", "zrt", 
        "expert", "globiz", "ford", "szalon", "debrecen", "utca", "út", "tér", "emelet", 
        "ajtó", "porta", "portán", "ft", "db", "tétel", "kérem", "kérlek", "hívni", "kapu", 
        "kód", "csöngessen", "vigye", "fel", "le", "fszt", "tető", "udvar", "bejárat", 
        "mellék", "szám", "vagyok", "süteményes", "gyógyszertár", "fest-é-ker", "bolt", 
        "üzlet", "iroda", "recepció", "műszak", "ügyelet", "raktár", "férfi", "női",
        "gedeon", "richter", "zaza", "főnix", "medgyessy", "iskola", "gimnázium", "matrackirály",
        "color", "zsozso", "ifjúsági", "ház", "hiv", "kormányhivatal", "fodrászat", "ipark",
        "bhs", "international", "pláza", "harapós", "gázkészülék", "gázkészülékbolt", "szállításkor",
        "általános", "javítsd", "magad", "csemege", "triton", "services", "mister", "minit", "lapostetős"
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
                full_text = ""
                for w in block_words:
                    if "Összesen" in w['text'] or "Összesítés" in w['text']:
                        break
                    full_text += w['text'] + " "
                
                kod_m = re.search(r'([PZSC]-\d{6})', full_text)
                kod = kod_m.group(1) if kod_m else ""
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', full_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                # TELEFON TISZTÍTÁS
                tel_m = re.search(r'(\d{2}[^0-9]*\d{6,10})', full_text.replace(" ", ""))
                tel = clean_phone(tel_m.group(1)) if tel_m else "Nincs tel."

                # ÜGYINTÉZŐ KERESÉSE
                search_area = full_text.replace(kod, "").replace(cim, "")
                raw_parts = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]*\b', search_area)
                
                filtered = []
                for p in raw_parts:
                    p_clean = p.strip().lower()
                    if (p_clean not in stop_words and 
                        not re.match(order_code_pattern, p.upper()) and 
                        len(p) > 2):
                        filtered.append(p)
                
                final_parts = []
                for p in filtered:
                    if p not in final_parts:
                        # Részleges egyezés szűrő (Hajós-Szabó típusúaknak)
                        is_sub = False
                        for idx, existing in enumerate(final_parts):
                            if p in existing: is_sub = True; break
                            if existing in p: final_parts[idx] = p; is_sub = True; break
                        if not is_sub: final_parts.append(p)

                # Név összeállítása (visszafelé nézve a legpontosabb)
                if len(final_parts) >= 3:
                    ugyintezo = f"{final_parts[-3]} {final_parts[-2]} {final_parts[-1]}"
                elif len(final_parts) == 2:
                    ugyintezo = f"{final_parts[-2]} {final_parts[-1]}"
                else:
                    ugyintezo = final_parts[0] if final_parts else "Név nem azonosítható"

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
st.title("Interfood v28 - A Tökéletesített Verzió")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v28(f)
    st.write("### Ellenőrzés (92. Nagy Ákos telefon, 43. Asztalos Károlyné):")
    st.dataframe(df)
    st.download_button("Export v28 CSV", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v28.csv")
