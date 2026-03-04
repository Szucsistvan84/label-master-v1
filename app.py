import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v170.0 - Stabil", layout="wide")

def clean_name_final(raw_name):
    # Csak a pontokat és a magányos kisbetűket (pl. ".a ") pucoljuk le az elejéről
    name = re.sub(r'^[ \.\,a-z]+', '', raw_name.strip())
    # Minden egyéb karaktert békén hagyunk, csak a felesleges szóközöket vesszük le
    return name.strip()

def parse_interfood_v170(pdf_file):
    all_data = []
    # A rendelés minta marad a régi, jól bevált: szám-kód
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                found = False
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w)
                        found = True
                        break
                if not found: lines[y] = [w]

            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                # A teljes szöveg a telefonszám és kódok miatt
                full_text = " ".join([w['text'] for w in line_words])
                
                # Sorszám ellenőrzése
                s_match = re.search(r'^(\d+)', full_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                # --- Juliánna és a Telefonszám fix ---
                # Ha a telefonszám hibás/vesszős, nem dobjuk el a sort, csak "nincs szám"-nak jelöljük
                tel_match = re.search(r'(\d{2}/\d{6,7})', full_text.replace(" ", ""))
                final_tel = tel_match.group(0) if tel_match else "nincs tel. szám"

                # Rendelések: ha összeolvadt valami (pl. 011-M), megkeressük benne a valódit
                # Összeragasztjuk a számot és a kódot, ha a PDF szétvágta volna
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_text)
                found_orders = re.findall(order_pat, search_text)
                
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    # Julianna-mentés: Ha a szám 0-val kezdődik (pl 011-M), 
                    # lefejtjük róla a felesleget, hogy csak az 1-M maradjon
                    if o.startswith('0'):
                        parts = o.split('-')
                        m = re.search(r'([1-9]\d*)$', parts[0])
                        if m:
                            o = f"{m.group(1)}-{parts[1]}"
                    
                    qty = int(o.split('-')[0])
                    if 0 < qty < 50: # Észszerű határ
                        clean_orders.append(o)
                        total_qty += qty

                # Név és cím kinyerése pozíció alapján (ez volt a legstabilabb)
                u_nev_raw = " ".join([w['text'] for w in line_words if 330 <= w['x0'] < 480])
                u_cim = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 330])
                
                u_nev = clean_name_final(u_nev_raw)

                # Ügyfélkód
                u_code_m = re.search(r'([HKS]-\d{5,7})', full_text)
                u_code = u_code_m.group(0) if u_code_m else ""

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim.strip(),
                    "Telefon": final_tel,
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": f"{total_qty} db"
                })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v170.0 - Vissza a stabilitáshoz")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood_v170(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_stabil.csv")
