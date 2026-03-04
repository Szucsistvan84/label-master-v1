import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v192.0 - Fix Sorrendező", layout="wide")

# --- 1. SIDEBAR: FUTÁR ADATOK ---
with st.sidebar.form("futar_form"):
    st.title("🚚 Szállítási adatok")
    f_nev_in = st.text_input("Futár neve", value=st.session_state.get('f_nev', ""))
    f_tel_in = st.text_input("Futár telefonszáma", value=st.session_state.get('f_tel', ""))
    if st.form_submit_button("ADATOK MENTÉSE"):
        st.session_state.f_nev = f_nev_in
        st.session_state.f_tel = f_tel_in
        st.rerun()

# Ellenőrzés
if not st.session_state.get('f_nev') or not st.session_state.get('f_tel'):
    st.warning("👈 Kérlek, add meg a futár adatait bal oldalt és nyomj a Mentésre!")
    st.stop()

# --- 2. FŐOLDAL: FÁJL FELTÖLTÉS ---
st.title("🏷️ Interfood Rendező és Etikett")
uploaded_files = st.file_uploader("1. PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if uploaded_files:
    # FÁJL SORRENDEZŐ TÁBLÁZAT
    st.subheader("2. PDF-ek (járatok) sorrendje")
    if 'file_order_df' not in st.session_state or len(st.session_state.file_order_df) != len(uploaded_files):
        init_data = [{"Járat Sorszám": i+1, "Fájlnév": f.name} for i, f in enumerate(uploaded_files)]
        st.session_state.file_order_df = pd.DataFrame(init_data)

    # Szerkeszthető fájl-lista
    current_file_order = st.data_editor(st.session_state.file_order_df, hide_index=True, use_container_width=True)
    
    if st.button("ADATOK BEOLVASÁSA A FENTI SORRENDBEN"):
        # Itt történik a PDF-ek feldolgozása a megadott sorrendben
        sorted_files = current_file_order.sort_values("Járat Sorszám")["Fájlnév"].tolist()
        
        all_rows = []
        for fname in sorted_files:
            # Megkeressük az eredeti file objektumot a név alapján
            f_obj = next(f for f in uploaded_files if f.name == fname)
            # Itt hívjuk a korábban tökéletesített parser-t (P/Z prefixszel)
            # all_rows.extend(parse_logic(f_obj))
            pass 
        
        # Eredmény mentése a session-be
        st.session_state.master_df = pd.DataFrame(all_rows) # Példa
        st.session_state.master_df.insert(0, "Sorrend", [str(i+1) for i in range(len(all_rows))])
        st.rerun()

# --- 3. CÍMEK SORRENDEZÉSE ---
if st.session_state.get('master_df') is not None:
    st.divider()
    st.subheader("3. Címek pontos sorrendje")
    
    edited_master = st.data_editor(
        st.session_state.master_df,
        use_container_width=True,
        hide_index=True,
        key="main_label_editor"
    )

    # Tizedesvesszős újrarendezés figyelése
    if not edited_master.equals(st.session_state.master_df):
        # ... (a korábbi safe_float rendező logikád) ...
        st.session_state.master_df = edited_master # Frissítés
        st.rerun()

    st.button("📥 3x7-es PDF Generálása")
