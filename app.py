# -*- coding: utf-8 -*-
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

# --- MOBIL NÉZETEK ÉS NYOMTATÁS BEHÚZÁSA (A reload UTÁN!) ---
import mobil_modulok
from mobil_modulok import render_mobil_aruatvetel, render_mobil_bepakolas, render_mobil_kiszallitas

# --- KISZERVEZETT ÚJ NÉZET RENDEREK (nezetek_modul.py) ---
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
    
    # ==============================================================================
    # 🛰️ ÉLES ÚTVONAL-RENDEZŐ ÉS RENDELÉSI SORREND HOOK (MINT A TÉRKÉPEN)
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
                    
                    # Tiszta átsorolás utáni visszaugrás a kiszállítás fülre
                    st.query_params.clear()
                    st.query_params.update(view="mobile", active_tab="kiszallitas")
                    st.session_state.current_mobile_tab_state = "3. Kiszállítás 🚚"
                    st.rerun()
        except Exception as e:
            st.error(f"Hiba az átsorrendezés során: {e}")

    url_jarat = st.query_params.get("jarat", "")
    url_teszt = st.query_params.get("test", "false") == "true"
    is_mobile_view = (view == "mobile")

    # --- ATOMBIZTOS PREMIUM CSS DESIGN ÉS INJEKTÁLT ELEM ELREJTŐK ---
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
        header, [data-testid="stHeader"] { background-color: rgba(0,0,0,0) !important; z-index: 999999 !important; }

        [data-testid="stSidebarCollapseButton"] {
            visibility: visible !important; display: inline-flex !important;
            background-color: #FFFFFF !important; border: 1px solid #E5E7EB !important;
            border-radius: 8px !important; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.08) !important;
            margin-left: 8px !important; margin-top: 6px !important; z-index: 1000000 !important;
        }
        [data-testid="stSidebarCollapseButton"]:hover { border-color: #139D43 !important; }
        [data-testid="manage-app-button"], [data-testid="viewerBadge"], .viewerBadge, #ConnectionStatus { display: none !important; visibility: hidden !important; }
        .block-container { padding-top: 2.5rem !important; padding-bottom: 2rem !important; }

        @media (max-width: 768px) {
            div[data-testid="stAppViewContainer"]::after, .stApp::after {
                content: "" !important; position: fixed !important; bottom: 0 !important; left: 0 !important;
                width: 100% !important; height: 65px !important; background-color: #FFFFFF !important;
                z-index: 999990 !important; border-top: 1.5px solid #F3F4F6 !important; pointer-events: none;
            }
            @media (prefers-color-scheme: dark) {
                div[data-testid="stAppViewContainer"]::after, .stApp::after { background-color: #0E1117 !important; border-top: 1.5px solid #1F2937 !important; }
            }
            .block-container { padding-bottom: 120px !important; }
        }
        </style>

        <script>
            var wakeLock = null;
            async function requestWakeLock() {
                try { if ('wakeLock' in navigator) { if (!wakeLock) { wakeLock = await navigator.wakeLock.request('screen'); } } } catch (err) {}
            }
            function cleanupStreamlitElements() {
                try {
                    var parentDoc = window.parent.document;
                    var manageBtn = parentDoc.querySelector('[data-testid="manage-app-button"]');
                    if (manageBtn) { manageBtn.style.setProperty('display', 'none', 'important'); }
                    var badges = parentDoc.querySelectorAll('[data-testid="viewerBadge"], .viewerBadge');
                    badges.forEach(function(b) { b.style.setProperty('display', 'none', 'important'); });
                    requestWakeLock();
                } catch(e) {}
            }
            document.addEventListener('visibilitychange', async () => { if (document.visibilityState === 'visible') { wakeLock = null; requestWakeLock(); } });
            setTimeout(cleanupStreamlitElements, 300); setTimeout(cleanupStreamlitElements, 1000);
        </script>
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
    if 'bejelentkezve' not in st.session_state: st.session_state.bejelentkezve = False
    if 'user_nev' not in st.session_state: st.session_state.user_nev = ""
    if 'user_szerep' not in st.session_state: st.session_state.user_szerep = "futar"
    if 'nevnapok_df' not in st.session_state: st.session_state.nevnapok_df = pd.DataFrame()
    if 'keresztnevek_df' not in st.session_state: st.session_state.keresztnevek_df = pd.DataFrame()

    # BIZTONSÁGOS REDIRECT
    if view is None:
        if 'edited_df' in st.session_state: view = "desktop"
        else:
            st.markdown("### 📱 Interfood Futár Terminál")
            if st.button("🚀 MOBIL TERMINÁL INDÍTÁSA", use_container_width=True, type="primary"):
                st.query_params.update(view="mobile")
                st.rerun()
            return

    # --- PIN KÓDOS BELÉPTETŐ RENDSZER ---
    if not st.session_state.bejelentkezve:
        if os.path.exists("interfood-logo.png"):
            import base64
            with open("interfood-logo.png", "rb") as img_file:
                b64_string = base64.b64encode(img_file.read()).decode()
            st.markdown(f'<div style="text-align: center; width: 100%; margin-bottom: 15px; margin-top: 10px;"><img src="data:image/png;base64,{b64_string}" style="max-width: 140px; height: auto; display: block; margin: 0 auto;"></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="text-align: center; width: 100%; margin-bottom: 15px; margin-top: 10px;"><img src="https://www.interfood.hu/images/logo.png" style="max-width: 140px; height: auto; display: block; margin: 0 auto;"></div>', unsafe_allow_html=True)
            
        st.markdown("<p style='text-align: center; color: #6B7280; font-size: 14px;'>Biztonságos azonosítás a rendszer használatához</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.warning("🔒 Kérjük, add meg a járatszámodat és az egyedi jelszavadat!")
            jarat_input = st.text_input("JÁRATSZÁM (vagy Admin):", value=url_jarat, key="login_jarat_field", placeholder="Pl. 4002")
            password_input = st.text_input("JELSZÓ / KÓD:", type="password", key="login_password_field", placeholder="••••••••")
            
            if url_teszt and jarat_input:
                if st.button("🧪 TESZT BELÉPÉS JELSZÓ NÉLKÜL", type="primary", use_container_width=True):
                    for k in list(st.session_state.keys()):
                        if any(x in k for x in ["kiszallitva_", "bepak_allapot_", "lada_szam_tarolt_"]): st.session_state.pop(k, None)
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = "Teszt Futár"
                    st.session_state.user_jarat_lista = [jarat_input.strip()]
                    st.session_state.user_szerep = "futar"
                    st.rerun()

            if st.button("🔑 BIZTONSÁGOS BELÉPÉS", use_container_width=True):
                tisztitott_input_jarat = str(jarat_input).strip().lower()
                tisztitott_input_pass = str(password_input).strip()
                
                if tisztitott_input_jarat == "admin" and tisztitott_input_pass == "admin123":
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = "Rendszergazda"
                    st.session_state.user_jarat_lista = ["4002"]
                    st.session_state.user_szerep = "superadmin"
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

    # Globális változók átadása
    global etlap_api_df, etelek_master_df, master_df, ugyfelkor_df, mdf
    etlap_api_df = st.session_state.get('etlap_api_df', pd.DataFrame())
    etelek_master_df = st.session_state.get('etelek_master_df', pd.DataFrame())
    master_df = etelek_master_df

    # =========================================================================
    # 📱 1. ÁG: MOBIL FUTÁR TERMINÁL (SZEGMENTÁLT FÜLVEZÉRLÉSSEL)
    # =========================================================================
    if is_mobile_view:
        st.title("📱 Futár Terminál")
        st.caption(f"Bejelentkezve: {st.session_state.user_nev}")
        
        # --- 🧹 ADMIN GYORSÍTÓTÁR ÉS MEMÓRIA TÖRLŐ GOMB A MOBIL SIDEBARON ---
        with st.sidebar:
            render_mobil_sidebar_dashboard(client, SHEET_ID_UGYFELKOR, SHEET_ID_MASTER)
            if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                st.write("---")
                st.markdown("### 🛠️ Rendszergazda Eszközök")
                if st.button("🧹 RENDZER CACHE TELJES TÖRLÉSE", type="primary", use_container_width=True, key="admin_global_cache_clear_btn"):
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    for k in list(st.session_state.keys()):
                        if k not in ['bejelentkezve', 'user_nev', 'user_szerep', 'client']: st.session_state.pop(k, None)
                    st.query_params.clear()
                    st.query_params.update(view="mobile")
                    st.toast("🔥 Minden gyorsítótár és beragadt URL törölve!")
                    time.sleep(0.5)
                    st.rerun()

        # --- 🔄 OKOS SZINKRONIZÁLT NAVIGÁCIÓS SÁV (JAVÍTOTT, GOMBBIZTOS) ---
        tab_mapping = {
            "aruatvetel": "1. Áruátvétel 📦",
            "bepakolas": "2. Címekre szedés 📥",
            "kiszallitas": "3. Kiszállítás 🚚"
        }
        
        if "current_mobile_tab_state" not in st.session_state:
            url_tab_param = st.query_params.get("active_tab", "aruatvetel")
            st.session_state.current_mobile_tab_state = tab_mapping.get(url_tab_param, "1. Áruátvétel 📦")
            
        # 🔥 FIX: Kényszerítjük a Streamlit belső widget-memóriáját, hogy kövesse a külső állapotot,
        # így ha egy gomb (pl. az Admin panel) átírja a fület, a navigációs sáv nem akad ki!
        st.session_state["mobil_segmented_nav_bar_live"] = st.session_state.current_mobile_tab_state
        
        selected_mobil_tab = st.segmented_control(
            "Navigáció",
            options=list(tab_mapping.values()),
            selection_mode="single",
            label_visibility="collapsed",
            key="mobil_segmented_nav_bar_live"  # Ez a kulcs és a fenti session sor most már tökéletes szinkronban van!
        )
        
        if selected_mobil_tab and selected_mobil_tab != st.session_state.current_mobile_tab_state:
            st.session_state.current_mobile_tab_state = selected_mobil_tab
            inv_map = {v: k for k, v in tab_mapping.items()}
            st.query_params.update(active_tab=inv_map[selected_mobil_tab])
            st.rerun()

        # 🔥 BIZTONSÁGI HÁLÓ: Ha bármelyik modul elhasal, a Kijelentkezés gomb akkor is megmarad alatta!
        try:
            if st.session_state.current_mobile_tab_state == "1. Áruátvétel 📦":
                render_mobil_aruatvetel(client)
            elif st.session_state.current_mobile_tab_state == "2. Címekre szedés 📥":
                render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR)
            elif st.session_state.current_mobile_tab_state == "3. Kiszállítás 🚚":
                render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR)
        except Exception as e:
            st.error(f"❌ Hiba történt a modul futtatása közben: {e}")
                
        # ⭐ ELPUSZTÍTHATATLAN KIJELENTKEZÉS ÉS URL-GYALU
        st.write("---")
        if st.button("🚪 Kijelentkezés", key="mob_logout", use_container_width=True):
            # 1. Kitakarítjuk a lokális memóriát és az elcsúszott állapotokat
            for k in list(st.session_state.keys()):
                if any(x in k for x in ["kiszallitva_", "bepak_allapot_", "lada_szam_tarolt_", "current_mobile_tab_state"]): 
                    st.session_state.pop(k, None)
            st.session_state.bejelentkezve = False
            
            # 2. Letöröljük a beragadt active_tab paramétert az URL-ből, visszaállunk tiszta mobilra
            st.query_params.clear()
            st.query_params.update(view="mobile")
            
            st.toast("👋 Sikeres és biztonságos kijelentkezés!")
            time.sleep(0.5)
            st.rerun()

    # =========================================================================
    # 🖥️ 2. ÁG: TELJES ASZTALI / ADMINISZTRÁCIÓS NÉZET
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

        render_desktop_main_content(
            client=client, SHEET_ID_MASTER=SHEET_ID_MASTER, SHEET_ID_UGYFELKOR=SHEET_ID_UGYFELKOR,
            admin_funkcio=admin_funkcio, is_admin=is_admin
        )

if __name__ == "__main__":
    main()
