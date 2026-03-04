import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v165.0 - Final Logic", layout="wide")

def clean_name(raw_name):
    # Eltávolítja a nevek elejéről a pontokat, magányos kisbetűket és szóközöket
    name = re.sub(r'^[ \.\,a-z0-9]+', '', raw_name.strip())
    # Csak a betűket, kötőjelet és szóközöket tartja meg
    name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', name)
    return name.strip()

def parse_interfood_v165(pdf_file):
    all_data = []
    # Rendelés: Szám-Kód (opcionális extrákkal mint * vagy +)
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
                text = " ".join([w['text'] for w in line_words])
                
                # Sorszám keresése (csak a sor elején)
                s_match = re.match(r'^\s*(\d+)', text)
                if not s_match: continue
                s_id = int(s_match.group(1))

                # Telefonszám
                tel_match = re.search(r'(\d{2}/\d{6,7})', text.replace(" ", ""))
                phone = tel_match.group(0) if tel_match else "nincs tel. szám"

                # Rendelések kinyerése és tisztítása (pl. 011-M -> 1-M)
                raw_orders = re.findall(order_pat, text.replace(" ", ""))
                clean_orders = []
                total_qty = 0
                for ro in raw_orders:
                    # Ha a darabszám 0-val kezdődik vagy túl hosszú, levágjuk a felesleget az elejéről
                    # pl. 011-M esetén keressük az utolsó értelmes darabszámot
                    parts = ro.split('-')
                    qty_str = parts[0]
                    # Csak az utolsó 1-2 számjegyet tartjuk meg, ami nem 0-val kezdődik, ha lehet
                    m = re.search(r'([1-9]\d?)$', qty_str)
                    if m:
                        qty = int(m.group(1))
                        if qty < 25: # Reális darabszám limit
                            clean_orders.append(f"{qty}-{parts[1]}")
                            total_qty += qty

                # Név és Cím (oszlopok alapján megbízhatóbb)
                # Ügyintéző (B4 zóna), Cím (B3 zóna)
                u_nev_raw = " ".join([w['text'] for w in line_words if 330 <= w['x0'] < 480])
                u_cim_raw = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 330])
                
                u_nev = clean_name(u_nev_raw)
                
                # Ügyfélkód
                u_code_m = re.search(r'([HKS]-\d{5,7})', text)
                u_code = u_code_m.group(0) if u_code_m else ""

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim_raw.strip(),
                    "Telefon": phone,
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": f"{total_qty} db"
                })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v165.0 - The Final Logic")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood_v165(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_javitott.csv")
