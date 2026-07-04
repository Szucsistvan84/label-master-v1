# -*- coding: utf-8 -*-
import streamlit as Object
import streamlit as st

# --- 1. STREAMLIT ALAPBEÁLLÍTÁS - Kötelezően mindenen kívül, a legelső sorban! ---
st.set_page_config(page_title="Interfood Label Master", layout="wide")

# --- KÉNYSZERÍTETT MODUL HOT-RELOAD (GARANTÁLT FRISSÍTÉS) ---
import sys
import importlib
import base64
if "nezetek_modul" in sys.modules:
    importlib.reload(sys.modules["nezetek_modul"])

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
import datetime

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

    # URL paraméterek lekérése az ágak eldöntéséhez (Default: mobile ha nincs megadva)
    view = st.query_params.get("view", "mobile")
    url_jarat = st.query_params.get("jarat", "")
    url_teszt = st.query_params.get("test", "false") == "true"
    is_mobile_view = (view == "mobile")

    # --- MOBIL FOLYAMAT JELZŐ ÁLLAPOT INICIALIZÁLÁSA ---
    if 'current_mobile_tab_state' not in st.session_state:
        url_tab_param = st.query_params.get("active_tab", "aruatvetel")
        tab_mapping_init = {"aruatvetel": "1. Áruátvétel 📦", "bepakolas": "2. Címekre szedés 📥", "kiszallitas": "3. Kiszállítás 🚚"}
        st.session_state.current_mobile_tab_state = tab_mapping_init.get(url_tab_param, "1. Áruátvétel 📦")

    # ==============================================================================
    # 🛰️ AUTOMATIKUS VISSZALÉPTETŐ MOTOR BÖNGÉSZŐ FRISSÍTÉS (F5 / LEHÚZÁS) ESETÉN
    # ==============================================================================
    if 'bejelentkezve' not in st.session_state: st.session_state.bejelentkezve = False
    
    if not st.session_state.bejelentkezve and "token_name" in st.query_params:
        st.session_state.bejelentkezve = True
        st.session_state.user_nev = str(st.query_params["token_name"])
        st.session_state.user_szerep = str(st.query_params.get("token_role", "futar"))
        st.session_state.user_jarat_lista = str(st.query_params.get("token_routes", "")).split(",")
        st.session_state.user_tel = str(st.query_params.get("token_tel", ""))
        if "active_tab" in st.query_params:
            tab_param = st.query_params["active_tab"]
            tab_mapping_rev = {"aruatvetel": "1. Áruátvétel 📦", "bepakolas": "2. Címekre szedés 📥", "kiszallitas": "3. Kiszállítás 🚚"}
            st.session_state.current_mobile_tab_state = tab_mapping_rev.get(tab_param, "1. Áruátvétel 📦")

    # ==============================================================================
    # 🛰️ ÉLES ÚTVONAL-RENDEZŐ ENGINE HOOK (JAVÍTOTT TOKEN-MEGŐRZŐS VÁLTOZAT)
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
                    
                    # 💡 FIX: Átsorolás után is kényszerítve visszaírjuk a belépési adatokat az URL-be, így nincs fehér kifagyás!
                    st.query_params.update(
                        view="mobile", 
                        active_tab="kiszallitas",
                        token_name=st.session_state.get('user_nev', ''),
                        token_role=st.session_state.get('user_szerep', 'futar'),
                        token_routes=",".join(st.session_state.get('user_jarat_lista', []))
                    )
                    st.session_state.current_mobile_tab_state = "3. Kiszállítás 🚚"
                    st.rerun()
        except Exception as e:
            st.error(f"Hiba az átsorrendezés során: {e}")

    # --- ATOMBIZTOS PREMIUM CSS DESIGN ÉS INTERFACE FINOMHANGOLÁSOK (ULTRA-KOMPAKT FUTÁR UX) ---
    st.markdown(
        """
        <style>
        /* 1. Teljes Streamlit/GitHub sallangmentesítés */
        footer {visibility: hidden !important; display: none !important;}
        [data-testid="stFooter"] {visibility: hidden !important; display: none !important;}
        [data-testid="stDecoration"] {display: none !important;}
        .stDeployButton {display: none !important;}
        #MainMenu {visibility: hidden !important; display: none !important;}
        [data-testid="stAppDeployButton"] {display: none !important;}
        [data-testid="stHeaderActionElements"] {visibility: hidden !important; display: none !important;}
        
        header, [data-testid="stHeader"] { 
            background-color: transparent !important; 
            z-index: 99999 !important; 
            display: block !important;
            height: 40px !important;
        }

        /* 2. FIXÁLT SIDEBAR COLLAPSE GOMB: Világos, tiszta háttér, jól látható sötét nyilakkal, gyári helyén megtartva */
        [data-testid="stSidebarCollapseButton"] {
            visibility: visible !important; 
            display: inline-flex !important;
            background-color: #E5E7EB !important; /* Világos, tiszta szürke */
            border: 2px solid #139D43 !important; /* Határozott Interfood Zöld keret */
            border-radius: 8px !important; 
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12) !important;
            margin-left: 10px !important; 
            margin-top: 8px !important; 
            z-index: 1000000 !important;
            transition: all 0.2s ease !important;
        }
        [data-testid="stSidebarCollapseButton"] svg {
            fill: #111827 !important; /* Kristálytiszta éjfekete nyilak! */
            color: #111827 !important;
            width: 20px !important;
            height: 20px !important;
        }
        [data-testid="stSidebarCollapseButton"]:hover { background-color: #D1D5DB !important; border-color: #0E7F35 !important; }
        
        [data-testid="manage-app-button"], [data-testid="viewerBadge"], .viewerBadge, #ConnectionStatus { display: none !important; visibility: hidden !important; }
        
        /* 3. Mobil-specifikus kompakt térközök */
        .block-container { 
            padding-top: 0.2rem !important; 
            padding-bottom: 7rem !important; 
            padding-left: 0.7rem !important;
            padding-right: 0.7rem !important;
        }
        h1 { font-size: 1.5rem !important; font-weight: 700 !important; margin-bottom: 0.4rem !important; }
        h2 { font-size: 1.25rem !important; margin-bottom: 0.4rem !important; }
        h3 { font-size: 1.05rem !important; }

        /* 4. Az alsó fix navigációs sáv */
        .fixed-nav-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            width: 100%;
            background-color: #FFFFFF;
            padding: 10px 15px;
            box-shadow: 0px -4px 12px rgba(0,0,0,0.08);
            z-index: 99999;
            border-top: 1.5px solid #E5E7EB;
        }

        /* 5. A Pöttyös Stepper folyamatjelző stílusai */
        .stepper-wrapper {
            display: flex;
            justify-content: space-between;
            margin-bottom: 15px;
            margin-top: 5px;
            padding: 0 5px;
        }
        .step-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
            position: relative;
        }
        .step-item::after {
            content: "";
            position: absolute;
            background: #E5E7EB;
            height: 3px;
            width: 100%;
            top: 14px;
            left: 50%;
            z-index: 1;
        }
        .step-item:last-child::after { content: none; }
        .step-counter {
            position: relative;
            z-index: 5;
            display: flex;
            justify-content: center;
            align-items: center;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            background: #E5E7EB;
            color: #4B5563;
            font-weight: bold;
            font-size: 12px;
        }
        .step-name {
            font-size: 10px;
            margin-top: 5px;
            color: #6B7280;
            font-weight: 600;
            white-space: nowrap;
        }
        .step-item.active .step-counter {
            background: #139D43; 
            color: white;
            box-shadow: 0 0 8px rgba(19, 157, 67, 0.4);
        }
        .step-item.active .step-name { color: #139D43; font-weight: bold; }
        .step-item.completed .step-counter {
            background: #1F2937; 
            color: white;
        }
        .step-item.completed .step-name { color: #1F2937; }
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
    if 'c_n' not in st.session_state: st.session_state.c_n = ""
    if 'c_p' not in st.session_state: st.session_state.c_p = ""
    if 'edited_df' not in st.session_state: st.session_state.edited_df = None

    # --- JAVÍTOTT PIN KÓDOS BELÉPTETŐ RENDSZER ---
    if not st.session_state.bejelentkezve:
        # TŰPONTOS KÖZÉPRE IGAZÍTOTT LOGÓ BASE64 INFÚZIÓVAL
        if os.path.exists("interfood-logo.png"):
            try:
                with open("interfood-logo.png", "rb") as img_f:
                    enc_logo = base64.b64encode(img_f.read()).decode()
                st.markdown(
                    f"""
                    <div style="display: flex; justify-content: center; width: 100%; margin-bottom: 15px; margin-top: 10px;">
                        <img src="data:image/png;base64,{enc_logo}" style="width: 130px; height: auto;">
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
            except:
                st.markdown("<h1 style='text-align: center; color: #139D43; margin-top:10px; margin-bottom:0;'>🟢 INTERFOOD</h1>", unsafe_allow_html=True)
        else:
            st.markdown("<h1 style='text-align: center; color: #139D43; margin-top:10px; margin-bottom:0;'>🟢 INTERFOOD</h1>", unsafe_allow_html=True)
            
        st.markdown("<p style='text-align: center; color: #6B7280; font-size: 14px; margin-top: 5px;'>Biztonságos azonosítás a rendszer használatához</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.warning("🔒 Kérjük, add meg a járatszámodat és az egyedi jelszavadat!")
            jarat_input = st.text_input("JÁRATSZÁM (vagy Admin):", value=url_jarat, key="login_jarat_field", placeholder="Pl. 4002")
            password_input = st.text_input("JELSZÓ / KÓD:", type="password", key="login_password_field", placeholder="••••••••")
            
            # --- INTELLIGENS SZERVEROLDALI ROUTER DIVERZIFIKÁCIÓ ---
            # Megnézzük az aktuális URL paramétert, és annak megfelelően emeljük ki a gombot zölddel!
            m_type = "primary" if view == "mobile" else "secondary"
            d_type = "primary" if view == "desktop" else "secondary"

            st.write("---")
            st.markdown("<p style='font-size:12px; font-weight:bold; color:#4B5563; margin-bottom:2px;'>Válassz munkakörnyezetet:</p>", unsafe_allow_html=True)
            
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                submit_mobile = st.button("📱 Mobil Terminál", type=m_type, use_container_width=True, key="login_as_mobile_trigger")
            with col_b2:
                submit_desktop = st.button("🖥️ Asztali Dashboard", type=d_type, use_container_width=True, key="login_as_desktop_trigger")

            if url_teszt and jarat_input:
                if st.button("🧪 TESZT BELÉPÉS JELSZÓ NÉLKÜL", type="secondary", use_container_width=True):
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = "Teszt Futár"
                    st.session_state.user_jarat_lista = [jarat_input.strip()]
                    st.session_state.user_szerep = "futar"
                    st.query_params.update(view=view, token_name="Teszt Futár", token_role="futar", token_routes=jarat_input.strip())
                    st.rerun()

            if submit_mobile or submit_desktop:
                target_view_mode = "mobile" if submit_mobile else "desktop"
                tisztitott_input_jarat = str(jarat_input).strip().lower()
                tisztitott_input_pass = str(password_input).strip()
                
                if tisztitott_input_jarat == "admin" and tisztitott_input_pass == "admin123":
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = "Rendszergazda"
                    st.session_state.user_jarat_lista = ["4002"]
                    st.session_state.user_szerep = "superadmin"
                    st.query_params.update(view=target_view_mode, token_name="Rendszergazda", token_role="superadmin", token_routes="4002")
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
                    st.session_state.user_tel = str(talalt_futar.get('Telefon', ''))
                    
                    routes_str = ",".join(st.session_state.user_jarat_lista)
                    if not routes_str and 'login_jarat_field' in st.session_state:
                        routes_str = str(st.session_state.login_jarat_field).strip()
                        st.session_state.user_jarat_lista = [routes_str]
                    
                    st.query_params.update(
                        view=target_view_mode, 
                        token_name=st.session_state.user_nev, 
                        token_role=st.session_state.user_szerep, 
                        token_routes=routes_str,
                        token_tel=st.session_state.user_tel
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
    # 📱 MOBIL ÁG (KÉNYSZERÍTETT ÉLŐ MŰSZERFAL ÉS FOLYAMAT-VEZÉRLŐ ENGINE)
    # =========================================================================
    if is_mobile_view:
        with st.sidebar:
            import base64
            
            st.markdown(
                """
                <style>
                div[data-testid="stSidebarUserContent"] { padding-top: 0rem !important; margin-top: -3.8rem !important; }
                [data-testid="stSidebarUserContent"] [data-testid="stMetricValue"] { font-size: 1.05rem !important; font-weight: 800 !important; color: #139D43 !important; }
                [data-testid="stSidebarUserContent"] [data-testid="stMetricLabel"] { font-size: 0.68rem !important; font-weight: 600; }
                </style>
                """,
                unsafe_allow_html=True
            )

            # --- BASE64 LOGÓ INJEKTÁLÁS ---
            if os.path.exists("interfood-logo.png"):
                try:
                    with open("interfood-logo.png", "rb") as img_file:
                        enc_img = base64.b64encode(img_file.read()).decode()
                    st.markdown(f'<div style="display: flex; justify-content: center; width: 100%; margin-bottom: 8px;"><img src="data:image/png;base64,{enc_img}" style="width: 75px; height: auto;"></div>', unsafe_allow_html=True)
                except: st.markdown("<h3 style='text-align: center; color: #139D43; margin-top:0;'>🟢 Interfood</h3>", unsafe_allow_html=True)
            else: st.markdown("<h3 style='text-align: center; color: #139D43; margin-top:0;'>🟢 Interfood</h3>", unsafe_allow_html=True)

            st.markdown("<h2 style='text-align: center; color: #139D43; margin-bottom: 6px; font-size: 1.15rem;'>📊 Mai Műszerfal</h2>", unsafe_allow_html=True)
            
            futar_nev_kiir = st.session_state.get('user_nev', 'Ismeretlen Futár')
            jarat_lista_kiir = st.session_state.get('user_jarat_lista', [])
            jarat_szoveg_kiir = ", ".join(map(str, jarat_lista_kiir)) if jarat_lista_kiir else "Nincs"
            futar_tel_kiir = st.session_state.get('user_tel', '')
            tel_resz = f" | 📞 {futar_tel_kiir}" if futar_tel_kiir else ""
            
            st.write(f"👤 **Futár:** {futar_nev_kiir}{tel_resz}<br>🚚 **Járat:** {jarat_szoveg_kiir}", unsafe_allow_html=True)

            # Mérők alapértékei
            osszes_cim = 0
            osszes_megallo = 0
            osszes_etel = 0
            forgalmi_ertek = 0

            try:
                sh_ugyfelkor = st.session_state.client.open_by_key(SHEET_ID_UGYFELKOR)
                ws_adatok = sh_ugyfelkor.worksheet("Adatok")
                all_rows = ws_adatok.get_all_records()
                
                futar_keresett = str(futar_nev_kiir).strip().lower()
                driver_records = [r for r in all_rows if str(r.get('Futár', r.get('Futar', ''))).strip().lower() == futar_keresett] if all_rows else []

                if driver_records:
                    osszes_cim = len(driver_records)
                    egyedi_cimek = set(str(r.get('Cím', r.get('Cim', ''))).strip() for r in driver_records)
                    osszes_megallo = len(egyedi_cimek)
                    for r in driver_records:
                        try: osszes_etel += int(float(str(r.get('Összesen', 1))))
                        except: osszes_etel += 1
                        try:
                            p_nyers = str(r.get('Pénz', r.get('Penz', '0'))).replace('Ft', '').replace(' ', '').strip()
                            if p_nyers and p_nyers.isdigit(): forgalmi_ertek += int(p_nyers)
                        except: pass
                else:
                    st.warning("⚠️ Nincs kiosztott fuvarod mára!")
            except Exception as e:
                st.error(f"Hiba az adatok betöltésekor: {e}")

            # Élő elszámolás számítása a megállókból
            live_kesz_cimek = sum(1 for k in st.session_state.keys() if k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres")
            live_beszedett_kp = 0
            live_borravalo = 0
            for k in list(st.session_state.keys()):
                if k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres":
                    idx = k.split("_")[-1]
                    try:
                        live_beszedett_kp += int(st.session_state.get(f"atvett_input_{idx}", 0))
                        live_borravalo += int(st.session_state.get(f"borravalo_{idx}", 0))
                    except: pass

            st.markdown("<div style='margin: 18px 0 12px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
            st.subheader("🏁 Kiszállítás Haladás")
            haladas_szazalek = min(1.0, live_kesz_cimek / osszes_cim) if osszes_cim > 0 else 0.0
            st.progress(haladas_szazalek)
            st.caption(f"Teljesítve: {live_kesz_cimek} / {osszes_cim} cím ({int(haladas_szazalek * 100)}%)")
            
            st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
            st.subheader("💰 Pénzügy & Mennyiség")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.metric("📍 Tervezett megállók", f"{osszes_megallo} db")
                st.metric("🏠 Összes cím (vevő)", f"{osszes_cim} db")
            with col_s2:
                st.metric("📦 Összes étel", f"{osszes_etel} adag")
                st.metric("💵 Rakományérték", f"{forgalmi_ertek:,} Ft".replace(",", " "))
                
            st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
            st.subheader("💸 Élő Elszámolás")
            col_l1, col_l2 = st.columns(2)
            with col_l1:
                st.metric("💵 Beszedett KP aznap", f"{live_beszedett_kp:,} Ft".replace(",", " "))
                st.metric("⭐ Várható Jutelék", f"{int(forgalmi_ertek * 0.13):,} Ft".replace(",", " "))
            with col_l2:
                st.metric("💰 Gyűjtött borravaló", f"{live_borravalo:,} Ft".replace(",", " "))

            # --- SÜRGŐS HIBAJELENTŐ ---
            st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
            st.subheader("⚠️ Probléma az úton?")
            with st.expander("🚨 SÜRGŐS HIBAKÜLDÉS"):
                st.info("Ha sérült vagy hiányzó étellel találkozol, használd a főképernyő gyorsgombjait!")

            # --- RENDSZERGAZDA ESZKÖZÖK ---
            if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                st.write("---")
                st.markdown("### 🛠️ Rendszergazda Eszközök")
                if st.button("🧹 RENDSZER CACHE TELJES TÖRLÉSE", type="primary", use_container_width=True, key="admin_global_cache_clear_btn"):
                    st.cache_data.clear()
                    st.cache_resource.clear()
                    for k in list(st.session_state.keys()):
                        if k not in ['bejelentkezve', 'user_nev', 'user_szerep', 'client', 'user_tel']: st.session_state.pop(k, None)
                    st.query_params.clear()
                    st.query_params.update(view="mobile")
                    st.toast("🔥 Minden gyorsítótár és beragadt URL törölve!")
                    time.sleep(0.5)
                    st.rerun()

            st.write("---")
            if st.button("🚪 Kijelentkezés", key="mob_logout", use_container_width=True):
                st.session_state.bejelentkezve = False
                st.query_params.clear()
                st.query_params.update(view="mobile")
                st.toast("👋 Kijelentkezve!")
                time.sleep(0.5)
                st.rerun()

        # --- STEPPER PROCESS VISUALIZER ---
        tab_mapping_inv = {"1. Áruátvétel 📦": "aruatvetel", "2. Címekre szedés 📥": "bepakolas", "3. Kiszállítás 🚚": "kiszallitas"}
        current_state = st.session_state.current_mobile_tab_state
        
        cls1 = "active" if current_state == "1. Áruátvétel 📦" else "completed"
        cls2 = "active" if current_state == "2. Címekre szedés 📥" else ("completed" if current_state == "3. Kiszállítás 🚚" else "")
        cls3 = "active" if current_state == "3. Kiszállítás 🚚" else ""

        st.markdown(f"""
            <div class="stepper-wrapper">
                <div class="step-item {cls1}">
                    <div class="step-counter">1</div>
                    <div class="step-name">Áruátvétel</div>
                </div>
                <div class="step-item {cls2}">
                    <div class="step-counter">2</div>
                    <div class="step-name">Címekre szedés</div>
                </div>
                <div class="step-item {cls3}">
                    <div class="step-counter">3</div>
                    <div class="step-name">Kiszállítás</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<div style='margin-top: -5px; margin-bottom: 15px; border-top: 1px solid #E5E7EB;'></div>", unsafe_allow_html=True)

        # --- AKTÍV FOLYAMAT MODULOK RENDERE ---
        try:
            if current_state == "1. Áruátvétel 📦":
                render_mobil_aruatvetel(st.session_state.client)
            elif current_state == "2. Címekre szedés 📥":
                render_mobil_bepakolas(st.session_state.client, SHEET_ID_UGYFELKOR)
            elif current_state == "3. Kiszállítás 🚚":
                render_mobil_kiszallitas(st.session_state.client, SHEET_ID_UGYFELKOR)
        except Exception as e:
            st.error(f"❌ Hiba a modul futtatása közben: {e}")

        # --- ALSÓ FIX NAVIGÁCIÓS SÁV ---
        st.markdown('<div class="fixed-nav-bar">', unsafe_allow_html=True)
        col_prev, col_spacer, col_next = st.columns([4, 2, 4])
        
        state_order = ["1. Áruátvétel 📦", "2. Címekre szedés 📥", "3. Kiszállítás 🚚"]
        curr_idx = state_order.index(current_state)
        
        with col_prev:
            if curr_idx > 0:
                if st.button("⬅️ Előző", use_container_width=True, key="stepper_prev_btn_action"):
                    new_state = state_order[curr_idx - 1]
                    st.session_state.current_mobile_tab_state = new_state
                    st.query_params.update(
                        active_tab=tab_mapping_inv[new_state],
                        token_name=st.session_state.get('user_nev', ''),
                        token_role=st.session_state.get('user_szerep', 'futar'),
                        token_routes=",".join(st.session_state.get('user_jarat_lista', []))
                    )
                    st.rerun()
                    
        with col_next:
            if curr_idx < 2:
                if st.button("Következő ➡️", type="primary", use_container_width=True, key="stepper_next_btn_action"):
                    new_state = state_order[curr_idx + 1]
                    st.session_state.current_mobile_tab_state = new_state
                    st.query_params.update(
                        active_tab=tab_mapping_inv[new_state],
                        token_name=st.session_state.get('user_nev', ''),
                        token_role=st.session_state.get('user_szerep', 'futar'),
                        token_routes=",".join(st.session_state.get('user_jarat_lista', []))
                    )
                    st.rerun()
            else:
                if st.button("🏁 Lezárás", type="primary", use_container_width=True, key="stepper_close_btn_action"):
                    st.toast("🎉 Szép munka! Minden mai debreceni címet sikeresen teljesítettél!")
        st.markdown('</div>', unsafe_allow_html=True)

    # =========================================================================
    # 🖥️ ASZTALI ÁG
    # =========================================================================
    else:
        is_admin = st.session_state.user_szerep in ["admin", "superadmin"]
        
        with st.sidebar:
            admin_funkcio = render_desktop_sidebar_controls(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, LOG_FILE)
            
        render_desktop_main_content(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, admin_funkcio, is_admin)

if __name__ == "__main__":
    main()
