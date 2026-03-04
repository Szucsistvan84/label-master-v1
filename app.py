import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import Counter

st.set_page_config(page_title="Interfood v175.0 - Nyilacskás Rendező", layout="wide")

# --- ADATKINYERŐ LOGIKA (A már bevált v173+ alapokon) ---
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
                
                # Koordináták alapján név és cím (v167 beállítások)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                # Rendelés kinyerése
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                found_orders = re.findall(order_pat, search_text)
                clean_orders = [o for o in found_orders if int(re.match(r'^(\d+)', o).group(1)) < 50]

                if not clean_orders: continue

                page_data.append({
                    "Járat": pdf_file.name.replace(".pdf", "").replace("menetterv ", ""),
                    "Ügyfélkód": u_code_m.group(0),
                    "Ügyintéző": re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip(),
                    "Cím": b3.strip(),
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": sum(int(re.match(r'^(\d+)', o).group(1)) for o in clean_orders)
                })
    return page_data

# --- SESSION STATE KEZELÉS ---
if 'df' not in st.session_state:
    st.session_state.df = None

# --- FELÜLET ---
st.title("🚚 Interfood v175.0 - Interaktív Útvonaltervező")

files = st.file_uploader("PDF feltöltése", type="pdf", accept_multiple_files=True)
if files and st.button("Beolvasás"):
    data = []
    for f in files:
        data.extend(parse_interfood(f))
    st.session_state.df = pd.DataFrame(data)

if st.session_state.df is not None:
    df = st.session_state.df
    
    st.subheader("📍 Kiszállítási sorrend beállítása")
    st.info("Használd a FEL/LE gombokat a címek rendezéséhez. A lista sorrendje határozza meg a mentett fájlt.")

    # Sorrend módosító gombok logikája
    for i in range(len(df)):
        col_up, col_down, col_info = st.columns([0.05, 0.05, 0.9])
        
        with col_up:
            if st.button("🔼", key=f"up_{i}"):
                if i > 0:
                    # Sorcsere
                    df.iloc[i-1], df.iloc[i] = df.iloc[i].copy(), df.iloc[i-1].copy()
                    st.session_state.df = df
                    st.rerun()
        
        with col_down:
            if st.button("🔽", key=f"down_{i}"):
                if i < len(df) - 1:
                    # Sorcsere
                    df.iloc[i+1], df.iloc[i] = df.iloc[i].copy(), df.iloc[i+1].copy()
                    st.session_state.df = df
                    st.rerun()
        
        with col_info:
            # Kompakt megjelenítés a rendezéshez
            st.write(f"**{i+1}.** {df.iloc[i]['Ügyintéző']} | {df.iloc[i]['Cím']} | ({df.iloc[i]['Rendelés']})")

    # --- ÖSSZESÍTŐ ÉS MENTÉS ---
    st.divider()
    
    # Rakodólista generálása az aktuális sorrend alapján
    all_codes = []
    for r in df['Rendelés']:
        for item in r.split(', '):
            match = re.match(r'(\d+)-(.*)', item)
            if match:
                qty, code = int(match.group(1)), match.group(2)
                all_codes.extend([code] * qty)
    
    counts = Counter(all_codes)
    summary_df = pd.DataFrame.from_dict(counts, orient='index', columns=['db']).reset_index()
    
    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("📦 Napi totál")
        st.dataframe(summary_df.sort_values('db', ascending=False), use_container_width=True)
    with c2:
        st.subheader("💾 Kész lista")
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("Végleges CSV letöltése", csv, "interfood_napi_terv.csv", use_container_width=True)
