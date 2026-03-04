import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v180.0 - Stabil Alap", layout="wide")

def parse_interfood_v180(pdf_file):
    all_data = []
    # Alapvető rendelés minta: szám-kód
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
                full_text = " ".join([w['text'] for w in line_words])
                
                # Sorszám keresése a sor elején
                s_match = re.search(r'^(\d+)', full_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                # Telefonszám (egyszerű keresés)
                tel_match = re.search(r'(\d{2}/\d{6,7})', full_text.replace(" ", ""))
                phone = tel_match.group(0) if tel_match else " - "

                # RENDELÉS FIX (Czinege Juliánna 11-es sorához):
                # Kivesszük a rendeléseket, és ha 011-M szerűséget látunk, levágjuk az elejét
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_text)
                found_orders = re.findall(order_pat, search_text)
                
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    # Ha a darabszám 0-val kezdődik (pl. 011-M), 
                    # de a sorszám (s_id) benne van az elején, lefaragjuk
                    if o.startswith('0') or len(o.split('-')[0]) > 2:
                        parts = o.split('-')
                        # Csak az utolsó 1 vagy 2 számjegyet tartjuk meg
                        m = re.search(r'([1-9]\d?)$', parts[0])
                        if m:
                            o = f"{m.group(1)}-{parts[1]}"
                    
                    try:
                        qty = int(o.split('-')[0])
                        clean_orders.append(o)
                        total_qty += qty
                    except: continue

                # Név és Cím kinyerése (vissza a régi, oszlop alapú módszerhez)
                u_nev = " ".join([w['text'] for w in line_words if 330 <= w['x0'] < 480]).strip()
                u_cim = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 330]).strip()
                
                # Finom névtisztítás (csak a pontokat az elejéről)
                u_nev = re.sub(r'^[ \.]+', '', u_nev)

                # Ügyfélkód
                u_code_m = re.search(r'([HKS]-\d{5,7})', full_text)
                u_code = u_code_m.group(0) if u_code_m else ""

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": phone,
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": f"{total_qty} db"
                })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v180.0 - Stabil Alap")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood_v180(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v180.csv")
