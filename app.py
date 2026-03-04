import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

# --- KONFIGURÁCIÓ ---
st.set_page_config(page_title="Interfood v189.0 - Stabil Rendező", layout="wide")

# --- KÖTELEZŐ MEZŐK ---
st.sidebar.title("🚚 Szállítási adatok")
f_nev = st.sidebar.text_input("Futár neve", key="f_nev_input")
f_tel = st.sidebar.text_input("Futár telefonszáma", key="f_tel_input")

if not f_nev or not f_tel:
    st.warning("👈 Kérlek, add meg a futár nevét és telefonszámát a bal oldalon!")
    st.stop()

# --- SESSION STATE TÁROLÓK ---
if 'master_df' not in st.session_state:
    st.session_state.master_df = None

# --- PARSER FÜGGVÉNY ---
def parse_interfood_row_by_row(pdf_file):
    rows = []
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
                
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text)
                if not u_code_m: continue
                
                # Cím tisztítás (4 jegyű irányítószámtól)
                b3_text = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                addr_match = re.search(r'(\d{4})', b3_text)
                clean_addr = b3_text[addr_match.start():].strip() if addr_match else b3_text

                # Név tisztítás (Czinege-szindróma ellen)
                b4_text = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4_text).split('-')[0].strip()

                # Rendelés
                orders = re.findall(order_pat, text.replace(" ", ""))
                valid_orders = []
                sum_qty = 0
                for o in orders:
                    q = int(o.split('-')[0])
                    if q >= 10: q = int(str(q)[-1])
                    valid_orders.append(f"{q}-{o.split('-')[1]}")
                    sum_qty += q
                
                if sum_qty > 0:
                    rows.append({
                        "Prefix": u_code_m.group(0).split('-')[0],
                        "ID": u_code_m.group(0).split('-')[-1],
                        "Ügyintéző": clean_name,
                        "Cím": clean_addr,
                        "Telefon": re.search(r'(\d{2}/\d{6,7})', text.replace(" ", "")).group(0) if re.search(r'(\d{2}/\d{6,7})', text.replace(" ", "")) else "nincs",
                        "Rendelés": ", ".join(valid_orders),
                        "Összesen": sum_qty
                    })
    return rows

# --- FŐ OLDAL ---
st.title("🏷️ Stabil Hétvégi Rendező")

# 1. LÉPÉS: PDF feltöltés és Fájl-sorrendező
uploaded_files = st.file_uploader("1. PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if uploaded_files:
    st.subheader("2. PDF-ek (járatok) sorrendje")
    file_order_data = [{"Fájl Sorrend": i+1, "Fájlnév": f.name} for i, f in enumerate(uploaded_files)]
    file_order_df = st.data_editor(pd.DataFrame(file_order_data), hide_index=True)

    if st.button("Adatok beolvasása a fenti sorrendben"):
        # Fájlok rendezése a megadott sorszám alapján
        sorted_filenames = file_order_df.sort_values("Fájl Sorrend")["Fájlnév"].tolist()
        
        all_parsed_data = []
        for fname in sorted_filenames:
            f_obj = next(f for f in uploaded_files if f.name == fname)
            all_parsed_data.extend(parse_interfood_row_by_row(f_obj))
        
        final_df = pd.DataFrame(all_parsed_data)
        final_df.insert(0, "Sorrend", [str(i+1) for i in range(len(final_df))])
        st.session_state.master_df = final_df

# 3. LÉPÉS: Címek finomhangolása
if st.session_state.master_df is not None:
    st.divider()
    st.subheader("3. Címek pontos sorrendje")
    st.caption("Írd át a 'Sorrend' oszlopot (pl. 1.1) a beszúráshoz, majd nyomj Entert.")

    edited_df = st.data_editor(
        st.session_state.master_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="main_editor"
    )

    # HA VÁLTOZOTT A TÁBLÁZAT -> ÚJRARANDEZZÜK
    if not edited_df.equals(st.session_state.master_df):
        def safe_float(x):
            try: return float(str(x).replace(',', '.'))
            except: return 9999.0
        
        edited_df['sort_key'] = edited_df['Sorrend'].apply(safe_float)
        # Rendezzük a tizedesvesszős értékek alapján
        new_df = edited_df.sort_values('sort_key').drop(columns=['sort_key'])
        # Kapjanak új, tiszta egész számú sorszámokat (1, 2, 3...)
        new_df['Sorrend'] = [str(i+1) for i in range(len(new_df))]
        
        st.session_state.master_df = new_df
        st.rerun()

    # NYOMTATÁS
    st.button("📥 3x7-es PDF Etikett Letöltése")
