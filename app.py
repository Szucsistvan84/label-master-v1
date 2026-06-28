# -*- coding: utf-8 -*-
import streamlit as Object
import streamlit as st

# --- 1. STREAMLIT ALAPBEÁLLÍTÁS - Kötelezően mindenen kívül, a legelső sorban! ---
st.set_page_config(page_title="Interfood Label Master", layout="wide")

# --- KÉNYSZERÍTETT MODUL HOT-RELOAD (GARANTÁLT FRISSÍTÉS) ---
import sys
import importlib

modules_to_reload = ["parser_modul", "mobil_modulok", "nezetek_modul", "adatbazis_modul", "geokodolo_modul", "vizualizacio"]
for mod_name in modules_to_reload:
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
# -----------------------------------------------------------------------------------

# --- Standard Python modulok importálása ---
import pandas as pd
import logging
import os
import time

# --- Globális konstansok ---
LOG_FILE = "app.log"

# --- SAJÁT MODULOK IMPORTÁLÁSA ---
from parser_modul import merge_data
from adatbazis_modul import (
    SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, 
    _tiszta_futar_lista_letoltes, load_etlap_api_smart
)
from utils import init_google_sheets, setup_logging, init_test_mode

# --- MOBIL NÉZETEK ÉS NYOMTATÁS BEHÚZÁSA ---
import mobil_modulok
from mobil_modulok import render_mobil_aruatvetel, render_mobil_bepakolas, render_mobil_kiszallitas

# --- KISZERVEZETT ÚJ NÉZET RENDEREK ---
from nezetek_modul import (
    render_mobil_sidebar_dashboard, 
    render_desktop_sidebar_controls, 
    render_desktop_main_content
)

# --- LOGGOLÁS ÉS TESZT ÜZEMMÓD INICIALIZÁLÁSA ---
setup_logging()
logger = logging.getLogger(__name__)
init_test_mode()

# --- GOOGLE SHEETS KLIENS INICIALIZÁLÁSA ---
client = init_google_sheets()
if 'client' not in st.session_state:
    st.session_state['client'] = client

def main():
    global client  
    if 'client' not in st.session_state or st.session_state['client'] is None:
        st.session_state['client'] = client

    # URL paraméterek lekérése az ágak eldöntéséhez
    view = st.query_params.get("view", None)
    url_jarat = st.query_params.get("jarat", "")
    url_teszt = st.query_params.get("test", "false") == "true"
    is_mobile_view = (view == "mobile")

    # ==============================================================================
    # 🛰️ 2. PONT FIX: AUTOMATIKUS VISSZALÉPTETŐ MOTOR BÖNGÉSZŐ FRISSÍTÉS (F5) ESETÉN
    # ==============================================================================
    if 'bejelentkezve' not in st.session_state: st.session_state.bejelentkezve = False
    
    # Ha a memóriából kiesett a belépés, de az URL-ben ott vannak a futár adatai, visszaléptetjük!
    if not st.session_state.bejelentkezve and "token_name" in st.query_params:
        st.session_state.bejelentkezve = True
        st.session_state.user_nev = str(st.query_params["token_name"])
        st.session_state.user_szerep = str(st.query_params.get("token_role", "futar"))
        st.session_state.user_jarat_lista = str(st.query_params.get("token_routes", "")).split(",")
        if "active_tab" in st.query_params:
            tab_param = st.query_params["active_tab"]
            tab_mapping_rev = {"aruatvetel": "1. Áruátvétel 📦", "bepakolas": "2. Címekre szedés 📥", "kiszallitas": "3. Kiszállítás 🚚"}
            st.session_state.current_mobile_tab_state = tab_mapping_rev.get(tab_param, "1. Áruátvétel 📦")

    # ==============================================================================
    # 🛰️ ÉLES ÚTVONAL-RENDEZŐ ENGINE HOOK
    # ==============================================================================
    if "action" in st.query_params and "target_id" in st.query_params:
        action = st.query_params["action"]
        target_id = str(st.query_params["target_id"]).strip()
        
        try:
            sh = st.session_state.client.open_by_key(SHEET_ID_UGYFELKOR)
            ws_adatok = sh.worksheet("Adatok")
            adatok_rows = ws_adatok.get_all_values()
            
            if adatok_rows and len(adatok_rows) > 1:
                header_adatok = adatok_rows[0]
                df_sheets = pd.DataFrame(adatok_rows[1:], columns=header_adatok)
                df_sheets['Sorrend'] = pd.to_numeric(df_sheets['Sorrend'], errors='coerce').fillna(999).astype(int)
                df_sheets = df_sheets.sort_values(by='Sorrend').reset_index(drop=True)
                target_idx = df_sheets[df_sheets['ID'].astype(str).str.strip() == target_id].index
                
                if not target_idx.empty:
                    t_idx = target_idx[0]
                    target_row = df_sheets.loc[t_idx].copy()
                    if action == "move_end":
                        max_sorrend = df_sheets['Sorrend'].max()
                        df_sheets = df_sheets.drop(t_idx).reset_index(drop=True)
                        target_row['Sorrend'] = max_sorrend + 1
                        df_sheets = pd.concat([df_sheets, pd.DataFrame([target_row])], ignore_index=True)
                    elif action == "move_to" and "pos" in st.query_params:
                        target_pos = max(1, int(st.query_params["pos"]))
                        df_sheets = df_sheets.drop(t_idx).reset_index(drop=True)
                        insert_idx = min(len(df_sheets), target_pos - 1)
                        df_left = df_sheets.iloc[:insert_idx]
                        df_right = df_sheets.iloc[insert_idx:]
                        df_sheets = pd.concat([df_left, pd.DataFrame([target_row]), df_right], ignore_index=True)
                    
                    df_sheets['Sorrend'] = range(1, len(df_sheets) + 1)
                    ws_adatok.clear()
                    ws_adatok.update('A1', [header_adatok] + df_sheets.values.tolist(), value_input_option='USER_ENTERED')
                    st.session_state.mdf = df_sheets
                    st.cache_data.clear()
                    
                    st.query_params.update(view="mobile", active_tab="kiszallitas")
                    st.session_state.current_mobile_tab_state = "3. Kiszállítás 🚚"
                    st.rerun()
        except Exception as e:
            st.error(f"Hiba az átsorrendezés során: {e}")

    # --- ATOMBIZTOS PREMIUM CSS DESIGN ÉS INJEKTÁLT ELEM ELREJTŐK (ULTRA-KOMPAKT FUTÁR UX) ---
    st.markdown(
        """
        <style>
        footer {visibility: hidden !important; display: none !important;}
        [data-testid="stFooter"] {visibility: hidden !important; display: none !important;}
        [data-testid="stDecoration"] {display: none !important;}
        .stDeployButton {display: none !important;}
        #MainMenu {visibility: hidden !important; display: none !important;}
        [data-testid="stAppDeployButton"] {display: none !important;}
        [data-testid="stHeaderActionElements"] {visibility: hidden !important; display: none !important;}
        
        header, [data-testid="stHeader"] { 
            background-color: transparent !important; 
            z-index: 999999 !important; 
            display: block !important;
            height: 45px !important;
        }

        /* Sidebar megnyitó gomb állandó, stabil szürke dizájnja - BEBETONOZVA */
        [data-testid="stSidebarCollapseButton"] {
            visibility: visible !important; 
            display: inline-flex !important;
            background-color: #E5E7EB !important; 
            border: 1.5px solid #9CA3AF !important;
            border-radius: 8px !important; 
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08) !important;
            margin-left: 8px !important; 
            margin-top: 6px !important; 
            z-index: 1000000 !important;
            color: #374151 !important;
        }
        [data-testid="stSidebarCollapseButton"]:hover { border-color: #139D43 !important; background-color: #D1D5DB !important; }
        
        [data-testid="manage-app-button"], [data-testid="viewerBadge"], .viewerBadge, #ConnectionStatus { display: none !important; visibility: hidden !important; }
        .block-container { padding-top: 0.5rem !important; padding-bottom: 2rem !important; }

        /* 5. PONT KÉNYSZERÍTETT RESZPONZÍV JAVÍTÁS: A gombok SOHA nem törnek két sorba! */
        div[data-testid="stSegmentedControl"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            width: 100% !important;
        }
        div[data-testid="stSegmentedControl"] button {
            flex: 1 1 0% !important;
            min-width: 0 !important;
            padding: 4px 1px !important;
        }
        div[data-testid="stSegmentedControl"] button div p {
            font-size: 11px !important;
            white-space: nowrap !important; /* Nem engedjük a sortörést a gombon belül */
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            text-align: center !important;
            font-weight: bold !important;
        }

        @media (max-width: 768px) {
            div[data-testid="stAppViewContainer"]::after, .stApp::after {
                content: "" !important; position: fixed !important; bottom: 0 !important; left: 0 !important;
                width: 100% !important; height: 65px !important; background-color: #FFFFFF !important;
                z-index: 999990 !important; border-top: 1.5px solid #F3F4F6 !important; pointer-events: none;
            }
            .block-container { padding-bottom: 120px !important; }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Fontok regisztrálása
    from nyomtatas_modulok import register_fonts
    register_fonts()

    # Session State alapértékek biztonságos beállítása
    if 'mdf' not in st.session_state: st.session_state.mdf = None
    if 'meta_data' not in st.session_state: st.session_state.meta_data = {}
    if 'weights' not in st.session_state: st.session_state.weights = {}
    if 'user_nev' not in st.session_state: st.session_state.user_nev = ""
    if 'user_szerep' not in st.session_state: st.session_state.user_szerep = "futar"
    if 'nevnapok_df' not in st.session_state: st.session_state.nevnapok_df = pd.DataFrame()
    if 'keresztnevek_df' not in st.session_state: st.session_state.keresztnevek_df = pd.DataFrame()

    # Golyóálló fixek a járatmentes induláshoz és a nyomtatási modulokhoz
    if 'c_n' not in st.session_state: st.session_state.c_n = ""
    if 'c_p' not in st.session_state: st.session_state.c_p = ""
    if 'edited_df' not in st.session_state: st.session_state.edited_df = None
    
    # 💡 Ikonok és betűtípusok kényszerített fixálása a generáláshoz:
    from nyomtatas_modulok import register_fonts
    register_fonts()

    # ==============================================================================
    # 🚨 VISSZAÁLLÍTOTT SZABAD ASZTALI/MOBILKAPCSOLÓ (MINDENKINEK JÁR A DESKTOP)
    # ==============================================================================
    if view is None:
        if 'edited_df' in st.session_state: 
            view = "desktop"
        else:
            # Ha tiszta URL-lel érkezik be a futár az asztali gépen, asztali módot kap!
            view = "desktop"
            st.query_params.update(view="desktop")
            st.rerun()

    # --- PIN KÓDOS BELÉPTETŐ RENDSZER ---
    if not st.session_state.bejelentkezve:
        st.markdown('<div style="text-align: center; width: 100%; margin-bottom: 15px; margin-top: 10px;"><img src="https://www.interfood.hu/images/logo.png" style="max-width: 140px; height: auto; display: block; margin: 0 auto;"></div>', unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #6B7280; font-size: 14px;'>Biztonságos azonosítás a rendszer használatához</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.warning("🔒 Kérjük, add meg a járatszámodat és az egyedi jelszavadat!")
            jarat_input = st.text_input("JÁRATSZÁM (vagy Admin):", value=url_jarat, key="login_jarat_field", placeholder="Pl. 4002")
            password_input = st.text_input("JELSZÓ / KÓD:", type="password", key="login_password_field", placeholder="••••••••")
            
            if url_teszt and jarat_input:
                if st.button("🧪 TESZT BELÉPÉS JELSZÓ NÉLKÜL", type="primary", use_container_width=True):
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = "Teszt Futár"
                    st.session_state.user_jarat_lista = [jarat_input.strip()]
                    st.session_state.user_szerep = "futar"
                    # Rögzítjük az URL-be az auto-login tokeneket!
                    st.query_params.update(view="mobile", token_name="Teszt Futár", token_role="futar", token_routes=jarat_input.strip())
                    st.rerun()

            if st.button("🔑 BIZTONSÁGOS BELÉPÉS", use_container_width=True):
                tisztitott_input_jarat = str(jarat_input).strip().lower()
                tisztitott_input_pass = str(password_input).strip()
                
                if tisztitott_input_jarat == "admin" and tisztitott_input_pass == "admin123":
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = "Rendszergazda"
                    st.session_state.user_jarat_lista = ["4002"]
                    st.session_state.user_szerep = "superadmin"
                    st.query_params.update(view="mobile", token_name="Rendszergazda", token_role="superadmin", token_routes="4002")
                    st.rerun()
                
                with st.spinner("⏳ Hitelesítés..."):
                    try: futar_adatok = _tiszta_futar_lista_letoltes(SHEET_ID_UGYFELKOR)
                    except: st.stop()
                
                talalt_futar = None
                for f in futar_adatok:
                    sheet_jarat = str(f.get('Járat', f.get('Jarat', ''))).strip().lower()
                    sheet_pass = str(f.get('PIN_Kod', '')).replace("'", "").strip().split('.')[0]
                    if sheet_jarat == tisztitott_input_jarat and sheet_pass == tisztitott_input_pass:
                        talalt_futar = f
                        break
                
                if talalt_futar:
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = talalt_futar.get('Név', 'Futár')
                    st.session_state.user_jarat_lista = [j.strip() for j in str(talalt_futar.get('Járat', '')).split(",") if j.strip()]
                    st.session_state.user_szerep = str(talalt_futar.get('Szerep', 'futar'))
                    
                    # 💡 MODOSÍTÁS: Elmentjük a telefonszámot és a járatokat is fixen a session_state-be a Google Sheetből!
                    st.session_state.user_tel = str(talalt_futar.get('Telefon', ''))
                    
                    routes_str = ",".join(st.session_state.user_jarat_lista)
                    
                    # Ha üres lenne a routes_str, az asztali feldolgozáshoz a beírt járatot használjuk fallbackként
                    if not routes_str and 'login_jarat_field' in st.session_state:
                        routes_str = str(st.session_state.login_jarat_field).strip()
                        st.session_state.user_jarat_lista = [routes_str]
                    
                    # 💡 INTELLIGENS JAVÍTÁS: Megtartjuk a nézetet, és átadjuk a tokeneket
                    current_view = view if view else "desktop"
                    st.query_params.update(
                        view=current_view, 
                        token_name=st.session_state.user_nev, 
                        token_role=st.session_state.user_szerep, 
                        token_routes=routes_str
                    )
                    st.rerun()
                else:
                    st.error("❌ Hibás járatszám vagy jelszó!")
        return

    # --- ÉTLAP ÉS ADATBÁZIS-INICIALIZÁLÓ MOTOR ---
    if 'master_df' not in st.session_state or st.session_state.nevnapok_df.empty:
        with st.spinner("⏳ Inicializálás..."):
            try:
                sheet = client.open_by_key(SHEET_ID_MASTER)
                m_df = pd.DataFrame(sheet.worksheet("Master_Adatbazis").get_all_records())
                st.session_state.etelek_master_df = m_df  
                st.session_state.master_df = m_df 
                st.session_state.nevnapok_df = pd.DataFrame(sheet.worksheet("Nevnapok").get_all_records())
                st.session_state.keresztnevek_df = pd.DataFrame(sheet.worksheet("Keresztnevek").get_all_records())
                st.session_state.etlap_api_df = load_etlap_api_smart(client, SHEET_ID_MASTER, "INITIAL")
            except: pass

    global etlap_api_df, etelek_master_df, master_df
    etlap_api_df = st.session_state.get('etlap_api_df', pd.DataFrame())
    etelek_master_df = st.session_state.get('etelek_master_df', pd.DataFrame())
    master_df = etelek_master_df

    # =========================================================================
    # 📱 MOBIL ÁG
    # =========================================================================
    if is_mobile_view:
        # 1. PONT FIX: ELTÜNTETTÜK A DUPLA LOGÓT! CSAK A RENDER ENGEDÉLYEZETT
        with st.sidebar:
            render_mobil_sidebar_dashboard(client, SHEET_ID_UGYFELKOR, SHEET_ID_MASTER)
            if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                st.write("---")
                st.markdown("### 🛠️ Rendszergazda Eszközök")
                if st.button("🧹 RENDSZER CACHE TELJES TÖRLÉSE", type="primary", use_container_width=True, key="admin_global_cache_clear_btn"):
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    for k in list(st.session_state.keys()):
                        if k not in ['bejelentkezve', 'user_nev', 'user_szerep', 'client']: st.session_state.pop(k, None)
                    st.query_params.clear()
                    st.query_params.update(view="mobile")
                    st.toast("🔥 Minden gyorsítótár és beragadt URL törölve!")
                    time.sleep(0.5)
                    st.rerun()

            # 3. PONT FIX: KIJELENTKEZÉS BEBETONOZVA A SIDEBAR ALJÁRA
            st.write("---")
            if st.button("🚪 Kijelentkezés", key="mob_logout", use_container_width=True):
                st.session_state.bejelentkezve = False
                st.query_params.clear()
                st.query_params.update(view="mobile")
                st.toast("👋 Kijelentkezve!")
                time.sleep(0.5)
                st.rerun()

        # --- 🔄 NAVIGÁCIÓS SÁV ---
        tab_mapping = {
            "aruatvetel": "1. Áruátvétel 📦",
            "bepakolas": "2. Címekre szedés 📥",
            "kiszallitas": "3. Kiszállítás 🚚"
        }
        
        if "current_mobile_tab_state" not in st.session_state:
            url_tab_param = st.query_params.get("active_tab", "aruatvetel")
            st.session_state.current_mobile_tab_state = tab_mapping.get(url_tab_param, "1. Áruátvétel 📦")
            
        st.session_state["mobil_segmented_nav_bar_live"] = st.session_state.current_mobile_tab_state
        
        selected_mobil_tab = st.segmented_control(
            "Navigáció", options=list(tab_mapping.values()), selection_mode="single", label_visibility="collapsed", key="mobil_segmented_nav_bar_live"
        )
        
        if selected_mobil_tab and selected_mobil_tab != st.session_state.current_mobile_tab_state:
            st.session_state.current_mobile_tab_state = selected_mobil_tab
            inv_map = {v: k for k, v in tab_mapping.items()}
            st.query_params.update(active_tab=inv_map[selected_mobil_tab])
            st.rerun()

        try:
            if st.session_state.current_mobile_tab_state == "1. Áruátvétel 📦":
                render_mobil_aruatvetel(client)
            elif st.session_state.current_mobile_tab_state == "2. Címekre szedés 📥":
                render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR)
            elif st.session_state.current_mobile_tab_state == "3. Kiszállítás 🚚":
                render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR)
        except Exception as e:
            st.error(f"❌ Hiba: {e}")

    # =========================================================================
    # 🖥️ ASZTALI ÁG
    # =========================================================================
    else:
        st.sidebar.markdown(f"### 👤 {st.session_state.user_nev}")
        is_admin = st.session_state.user_szerep in ["admin", "superadmin"]
        if is_admin: st.sidebar.success("⭐ Adminisztrátor Mód")
        if st.sidebar.button("🚪 Kijelentkezés", key="desktop_logout"):
            st.session_state.bejelentkezve = False
            st.rerun()
        with st.sidebar:
            admin_funkcio = render_desktop_sidebar_controls(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, LOG_FILE)
        render_desktop_main_content(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, admin_funkcio, is_admin)

if __name__ == "__main__":
    main()
