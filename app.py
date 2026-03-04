import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import Counter

st.set_page_config(page_title="Interfood v177.0 - Járat-Rendező", layout="wide")

# --- ADATKINYERŐ FÜGGVÉNY (Változatlanul a stabil v173+ alapokon) ---
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
                    "Járat": pdf_file.name,
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

st.title("🚀 Interfood v177.0 - Járat és Cím Rendező")

# 1. LÉPÉS: PDF-ek feltöltése
uploaded_files = st.file_uploader("1. Húzd be a PDF-eket", type="pdf", accept_multiple_files=True)

if uploaded_files:
    st.subheader("2. Állítsd be a járatok sorrendjét")
    # Létrehozunk egy kis táblázatot a fájloknak
    file_info = [{"Fájlnév": f.name, "Sorszám": i+1, "file_obj": f} for i, f in enumerate(uploaded_files)]
    file_df = pd.DataFrame(file_info)
    
    # Itt a felhasználó átírhatja a sorszámokat a fájlok mellett
    edited_file_df = st.data_editor(file_df[["Sorszám", "Fájlnév"]], hide_index=True, use_container_width=False)
    
    if st.button("Adatok beolvasása a megadott sorrendben"):
        # Fájlok rendezése a megadott sorszám szerint
        sorted_files_info = edited_file_df.sort_values("Sorszám")
        
        all_data = []
        for _, row in sorted_files_info.iterrows():
            # Megkeressük az eredeti fájl objektumot
            original_file = next(f for f in uploaded_files if f.name == row["Fájlnév"])
            all_data.extend(parse_interfood(original_file))
        
        df = pd.DataFrame(all_data)
        df.insert(0, "Sorrend", [str(i+1) for i in range(len(df))])
        st.session_state.working_df = df

# 3. LÉPÉS: Címek finomhangolása (Tizedesvesszős módszer)
if st.session_state.working_df is not None:
    st.divider()
    st.subheader("3. Címek pontos sorrendezése")
    st.info("Járatok összefűzve! Most már módosíthatod az egyes címeket (pl. 1.5).")

    edited_df = st.data_editor(
        st.session_state.working_df,
        num_rows="fixed",
        use_container_width=True,
        hide_index=True
    )

    # Automatikus újrarendezés, ha a Sorrend oszlop változik
    def safe_float(x):
        try: return float(str(x).replace(',', '.'))
        except: return 999.0

    if not edited_df.equals(st.session_state.working_df):
        edited_df['sort_key'] = edited_df['Sorrend'].apply(safe_float)
        edited_df = edited_df.sort_values('sort_key').drop(columns=['sort_key'])
        edited_df['Sorrend'] = [str(i+1) for i in range(len(edited_df))]
        st.session_state.working_df = edited_df
        st.rerun()

    # --- EXPORT ÉS ÖSSZESÍTŐ ---
    st.divider()
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("📦 Napi totál")
        # Összesítés kódok szerint
        all_items = []
        for r in edited_df['Rendelés']:
            for item in r.split(', '):
                m = re.match(r'(\d+)-(.*)', item)
                if m: all_items.extend([m.group(2)] * int(m.group(1)))
        st.dataframe(pd.DataFrame.from_dict(Counter(all_items), orient='index', columns=['db']), use_container_width=True)
    
    with col2:
        st.subheader("💾 Mentés")
        st.download_button("Végleges CSV letöltése", edited_df.to_csv(index=False).encode('utf-8-sig'), "interfood_napi_terv.csv")
