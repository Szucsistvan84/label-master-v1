import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import Counter

st.set_page_config(page_title="Interfood v176.0 - Gyors Rendező", layout="wide")

def parse_interfood(pdf_file):
    page_data = []
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
                full_line_text = " ".join([w['text'] for w in line_words])
                if any(x in full_line_text for x in ["Nyomtatta", "Oldal:", "Összesen"]): continue
                u_code_m = re.search(r'([HKSCPZ]-\d{5,7})', full_line_text)
                if not u_code_m: continue
                
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                found_orders = re.findall(order_pat, search_text)
                clean_orders = [o for o in found_orders if int(re.match(r'^(\d+)', o).group(1)) < 50]

                if not clean_orders: continue

                page_data.append({
                    "Ügyfélkód": u_code_m.group(0),
                    "Ügyintéző": re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip(),
                    "Cím": b3.strip(),
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": sum(int(re.match(r'^(\d+)', o).group(1)) for o in clean_orders)
                })
    return page_data

# --- SESSION STATE ---
if 'working_df' not in st.session_state:
    st.session_state.working_df = None

st.title("🚀 Interfood v176.0 - Tizedesvesszős Gyorsrendező")

files = st.file_uploader("PDF-ek feltöltése", type="pdf", accept_multiple_files=True)
if files and st.button("Adatok beolvasása"):
    data = []
    for f in files:
        data.extend(parse_interfood(f))
    df = pd.DataFrame(data)
    # A sorszámot szövegként tároljuk, hogy engedje a vesszőt/pontot
    df.insert(0, "Sorrend", [str(i+1) for i in range(len(df))])
    st.session_state.working_df = df

if st.session_state.working_df is not None:
    st.subheader("📍 Sorrend módosítása")
    st.info("Írd át a 'Sorrend' oszlopban a számot (pl. 1.5 vagy 2,2) és a lista azonnal átrendeződik!")

    # Szerkeszthető táblázat - A Sorrend oszlop szöveges marad a bevitel alatt
    edited_df = st.data_editor(
        st.session_state.working_df,
        num_rows="fixed",
        use_container_width=True,
        hide_index=True
    )

    # Rendezési logika: Vesszőt pontra cseréljük, számmá alakítjuk és rendezzük
    def safe_float(x):
        try: return float(str(x).replace(',', '.'))
        except: return 999.0

    # Ha változott a Sorrend oszlop, rendezzük újra
    if not edited_df.equals(st.session_state.working_df):
        edited_df['sort_key'] = edited_df['Sorrend'].apply(safe_float)
        edited_df = edited_df.sort_values('sort_key').drop(columns=['sort_key'])
        # Újrageneráljuk a szép sorszámokat, de szö
