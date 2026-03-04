import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import Counter

st.set_page_config(page_title="Interfood v178.0 - Tiszta Címek", layout="wide")

def clean_address_to_zip(raw_addr):
    """Mindent levág az irányítószám (4 számjegy) elől."""
    if not raw_addr: return ""
    # Megkeressük az első 4 jegyű számot (irányítószám)
    match = re.search(r'(\d{4})', raw_addr)
    if match:
        return raw_addr[match.start():].strip()
    return raw_addr.strip()

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
                
                # Név és Cím kinyerése a PDF koordináták alapján
                raw_addr_block = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                raw_name_block = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                # TISZTÍTÁS: Csak irányítószámmal kezdődhet!
                final_addr = clean_address_to_zip(raw_addr_block)
                final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', raw_name_block).strip()

                # Rendelés kinyerése
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                found_orders = re.findall(order_pat, search_text)
                clean_orders = [o for o in found_orders if int(re.match(r'^(\d+)', o).group(1)) < 50]

                if not clean_orders: continue

                page_data.append({
                    "Járat": pdf_file.name,
                    "Ügyfélkód": u_code_m.group(0),
                    "Ügyintéző": final_name,
                    "Cím": final_addr,
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": sum(int(re.match(r'^(\d+)', o).group(1)) for o in clean_orders)
                })
    return page_data

if 'working_df' not in st.session_state:
    st.session_state.working_df = None

st.title("🛡️ Interfood v178.0 - Tiszta Cím & Gyorsrendező")

# 1. PDF feltöltés és fájl-sorrend
uploaded_files = st.file_uploader("1. PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if uploaded_files:
    file_info = [{"Járat Sorrend": i+1, "Fájlnév": f.name} for i, f in enumerate(uploaded_files)]
    file_order_df = st.data_editor(pd.DataFrame(file_info), hide_index=True)
    
    if st.button("Adatok beolvasása tiszta címekkel"):
        sorted_files = file_order_df.sort_values("Járat Sorrend")
        all_data = []
        for _, row in sorted_files.iterrows():
            f_obj = next(f for f in uploaded_files if f.name == row["Fájlnév"])
            all_data.extend(parse_interfood(f_obj))
        
        df = pd.DataFrame(all_data)
        df.insert(0, "Sorrend", [str(i+1) for i in range(len(df))])
        st.session_state.working_df = df

# 2. Finomhangolás
if st.session_state.working_df is not None:
    st.divider()
    st.subheader("📍 Címek sorrendezése")
    st.caption("Használj tizedesvesszőt (pl. 1.5) a beszúráshoz. A címek most már fixen irányítószámmal kezdődnek.")
    
    edited_df = st.data_editor(st.session_state.working_df, num_rows="fixed", use_container_width=True, hide_index=True)

    def safe_float(x):
        try: return float(str(x).replace(',', '.'))
        except: return 999.0

    if not edited_df.equals(st.session_state.working_df):
        edited_df['sort_key'] = edited_df['Sorrend'].apply(safe_float)
        edited_df = edited_df.sort_values('sort_key').drop(columns=['sort_key'])
        edited_df['Sorrend'] = [str(i+1) for i in range(len(edited_df))]
        st.session_state.working_df = edited_df
        st.rerun()

    # Összesítő és letöltés
    st.divider()
    csv = edited_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("💾 Tiszta CSV letöltése", csv, "interfood_tiszta_terv.csv")
