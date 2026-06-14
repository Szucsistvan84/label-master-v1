# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import logging
import os
import qrcode
from io import BytesIO

# --- 1. STREAMLIT ALAPBEÁLLÍTÁS ---
st.set_page_config(page_title="Interfood Label Master", layout="wide")

# --- Globális konstansok ---
LOG_FILE = "app.log"

# --- SAJÁT MODULOK IMPORTÁLÁSA ---
from geokodolo_modul import get_coordinates, biztonsagos_koordinata_tisztito
from parser_modul import parse_interfood_pdf, extract_all_meta, load_all_names, merge_data
from adatbazis_modul import (
    get_gspread_client, load_sheet_data, save_df_to_sheet, SHEET_ID_MASTER, 
    SHEET_ID_UGYFELKOR, kotelezo_ugyfelkor_formatum_tisztitas, 
    get_latest_week_from_master, load_sheet_data_cached, load_etlap_api_smart, 
    master_lista_szinkron, sync_interfood_etlap, load_etlap_from_sheets,
    load_futar_from_sheets, save_futar_to_sheets, sync_master_database,
    load_master_data, save_to_master, _tiszta_futar_lista_letoltes
)
from stilus_modul import alkalmaz_mobil_status_bar, alkalmaz_tisztitott_felulet_css, alkalmaz_wolt_gomb_stilus, rendereld_wolt_ugyfel_kartya
from vizualizacio import utvonal_terkep
from utils import init_google_sheets, setup_logging, init_test_mode
from mobil_modulok import render_mobil_aruatvetel, render_mobil_bepakolas, render_mobil_kiszallitas
from nezetek_modul import (
    render_mobil_sidebar_dashboard, 
    render_desktop_sidebar_controls, 
    render_desktop_main_content
)
from nyomtatas_modulok import register_fonts

# --- LOGGOLÁS ÉS INICIALIZÁLÁS ---
setup_logging()
init_test_mode()
client = init_google_sheets()

def main():
    # Stílusok alkalmazása
    alkalmaz_tisztitott_felulet_css()
    register_fonts()

    # Session State inicializálása
    if 'bejelentkezve' not in st.session_state: st.session_state.bejelentkezve = False
    if 'user_nev' not in st.session_state: st.session_state.user_nev = ""
    if 'user_szerep' not in st.session_state: st.session_state.user_szerep = "futar"
    if 'user_jarat_lista' not in st.session_state: st.session_state.user_jarat_lista = []

    # URL paraméterek
    view = st.query_params.get("view", None)
    
    # --- BEJELENTKEZŐ KÉPERNYŐ ---
    if not st.session_state.bejelentkezve:
        st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>🎯 Label Master</h1>", unsafe_allow_html=True)
        
        jarat_input = st.text_input("JÁRATSZÁM:", placeholder="Pl. 4002")
        password_input = st.text_input("JELSZÓ:", type="password", placeholder="••••••••")
        
        if st.button("🔑 BIZTONSÁGOS BELÉPÉS"):
            # 1. Admin vészbejárat a teszteléshez
            if jarat_input == "admin" and password_input == "admin123":
                st.session_state.update({'bejelentkezve': True, 'user_nev': "Admin", 'user_szerep': "superadmin", 'user_jarat_lista': ["4002"]})
                st.rerun()
            
            # 2. Google Sheets hitelesítés
            try:
                futarok = _tiszta_futar_lista_letoltes(SHEET_ID_UGYFELKOR)
                talalt = None
                for f in futarok:
                    # Karakterek tisztítása és összehasonlítás
                    db_jarat = str(f.get('Járat', f.get('Jarat', ''))).strip().lower()
                    db_pass = str(f.get('PIN_Kod', '')).replace("'", "").strip()
                    
                    if db_jarat == jarat_input.strip().lower() and db_pass == password_input.strip():
                        talalt = f
                        break
                
                if talalt:
                    st.session_state.update({
                        'bejelentkezve': True, 
                        'user_nev': talalt.get('Név', 'Futár'),
                        'user_szerep': str(talalt.get('Szerep', 'futar')).strip().lower(),
                        'user_jarat_lista': [jarat_input.strip()]
                    })
                    st.rerun()
                else:
                    st.error("❌ Hibás járatszám vagy jelszó!")
            except Exception as e:
                st.error(f"⚠️ Adatbázis hiba: {e}")
        return

    # --- HA BE VAGY JELENTKEZVE ---
    is_mobile_view = (view == "mobile")

    if is_mobile_view:
        st.title("📱 Futár Terminál")
        with st.sidebar:
            render_mobil_sidebar_dashboard(client, SHEET_ID_UGYFELKOR, SHEET_ID_MASTER)
        
        tab1, tab2, tab3 = st.tabs(["1. Áruátvétel 📦", "2. Címekre szedés 📥", "3. Kiszállítás 🚚"])
        with tab1: render_mobil_aruatvetel(client)
        with tab2: render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR)
        with tab3: render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR)
    else:
        # Asztali nézet vezérlők
        admin_funkcio = render_desktop_sidebar_controls(SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, LOG_FILE)
        render_desktop_main_content(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, admin_funkcio, st.session_state.user_szerep in ["admin", "superadmin"])

    # Kijelentkezés
    if st.sidebar.button("🚪 Kijelentkezés"):
        st.session_state.bejelentkezve = False
        st.rerun()

if __name__ == "__main__":
    main()
