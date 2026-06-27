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
    # --- SORREND MÓDOSÍTÓ HOOK AZ APP INDULÁSAKOR ---
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
                    
                    # URL tisztítás és tiszta reload
                    st.query_params.clear()
                    st.query_params.update(view="mobile")
                    st.rerun()
        except Exception as e:
            st.error(f"Hiba az átsorrendezés során: {e}")
    url_jarat = st.query_params.get("jarat", "")
    url_teszt = st.query_params.get("test", "false") == "true"
    is_mobile_view = (view == "mobile")

    # --- ATOMBIZTOS CSS ÉS JS TRÜKKÖK (MÁRKAHŰ ÉS PREMIUM MOBIL ELRENDEZÉSEK) ---
    st.markdown(
        """
        <style>
        /* 1. A Streamlit Cloud belső lábléc és felesleges dekorációk elrejtése */
        footer {visibility: hidden !important; display: none !important;}
        [data-testid="stFooter"] {visibility: hidden !important; display: none !important;}
        [data-testid="stDecoration"] {display: none !important;}
        
        /* 2. Szigorúan CSAK a jobb oldali fejléc gombokat (Deploy, Share, Github, Három pont) rejtjük el */
        .stDeployButton {display: none !important;}
        #MainMenu {visibility: hidden !important; display: none !important;}
        [data-testid="stAppDeployButton"] {display: none !important;}
        [data-testid="stHeaderActionElements"] {visibility: hidden !important; display: none !important;}
        [data-testid="stToolbarActions"] {visibility: hidden !important; display: none !important;}
        .stToolbarActions {visibility: hidden !important; display: none !important;}
        div[class*="stAppHeader"] > div[class*="stHeaderActionElements"] { display: none !important; }
        
        /* 3. Fejléc átlátszóvá tétele, hogy ne takarjon ki semmit és ne foglaljon helyet feleslegesen */
        header, [data-testid="stHeader"] {
            background-color: rgba(0,0,0,0) !important;
            z-index: 999999 !important;
        }

        /* 4. A bal oldali menü/sidebar-nyitó gombot (Collapse) megvédjük, stílusosabbá és könnyen nyithatóvá tesszük */
        [data-testid="stSidebarCollapseButton"] {
            visibility: visible !important;
            display: inline-flex !important;
            background-color: #FFFFFF !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 8px !important;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.08) !important;
            margin-left: 8px !important;
            margin-top: 6px !important;
            z-index: 1000000 !important;
            transition: all 0.2s ease !important;
        }
        [data-testid="stSidebarCollapseButton"]:hover {
            transform: scale(1.08) !important;
            border-color: #139D43 !important; /* Kijelöléskor Interfood Zöld keretet kap! */
        }

        /* 5. Golyóálló szelektorok a lebegő belső Streamlit elemekre */
        [data-testid="manage-app-button"] {
            display: none !important;
            visibility: hidden !important;
        }
        button[data-testid="manage-app-button"] {
            display: none !important;
            visibility: hidden !important;
        }
        [data-testid="viewerBadge"] {
            display: none !important;
            visibility: hidden !important;
        }
        .viewerBadge {
            display: none !important;
            visibility: hidden !important;
        }
        div[class*="viewerBadge"] {
            display: none !important;
            visibility: hidden !important;
        }
        #ConnectionStatus {
            display: none !important;
            visibility: hidden !important;
        }
        button[class*="terminalButton"], button[class*="ManageApp"], div[class*="viewerBadge"] {
            display: none !important;
            visibility: hidden !important;
        }
        
        /* Wildcard osztály elrejtések a belső iframe-hez is a profilkép és linkek ellen */
        div[class*="profilePreview"], span[class*="profilePreview"], [class*="profilePreview"] {
            display: none !important;
            visibility: hidden !important;
        }
        a[class*="link"], [class*="link"] {
            display: none !important;
            visibility: hidden !important;
        }
        
        .block-container {
            padding-top: 2.5rem !important;
            padding-bottom: 2rem !important;
        }

        /* 📱 6. AUTOMATIKUS MOBIL BIZTONSÁGI SÁV ÉS SPÁCIÓS EMELÉS (MEDIA QUERY ALAPON) */
        @media (max-width: 768px) {
            /* Létrehozunk egy fix biztonsági sávot a legfelső szintű Streamlit ablakra, ami kikerüli a transform-okat */
            div[data-testid="stAppViewContainer"]::after, .stApp::after {
                content: "" !important;
                position: fixed !important;
                bottom: 0 !important;
                left: 0 !important;
                width: 100% !important;
                height: 65px !important; /* Biztonságos magasság az ikonok és linkek elfedéséhez */
                background-color: #FFFFFF !important; /* Világos mód alapértelmezett háttér */
                z-index: 999990 !important; /* Maximális prioritás a belső elemek felett */
                border-top: 1.5px solid #F3F4F6 !important; /* Finom modern elválasztó vonal */
                pointer-events: none; /* Átengedjük a gombok melletti érintéseket a stabilitásért */
            }
            
            /* 🌙 SÖTÉT / ÉJSZAKAI ÜZEMMÓD AUTOMATIKUS ÉRZÉKELÉSE A MOBILON */
            @media (prefers-color-scheme: dark) {
                div[data-testid="stAppViewContainer"]::after, .stApp::after {
                    background-color: #0E1117 !important; /* Tökéletesen simul a Streamlit gyári sötét hátterébe */
                    border-top: 1.5px solid #1F2937 !important; /* Elegáns sötétszürke elválasztó */
                }
            }
            
            /* Megemeljük a teljes tartalom alsó margóját, hogy a gombok kényelmesen a biztonsági sáv felett lebegjenek */
            .block-container {
                padding-bottom: 120px !important; /* Bőséges spárció az átlapolások és elnyelések ellen */
            }
        }
        </style>

        <!-- 7. INTELLIGENS SZÜLŐABLAK-ÁTTÖRŐ JAVASCRIPT A MAKACS SALLANGOK ELLEN -->
        <script>
            var wakeLock = null;
        
            async function requestWakeLock() {
                try {
                    if ('wakeLock' in navigator) {
                        // Csak akkor kérjük le, ha még nem fut aktívan
                        if (!wakeLock) {
                            wakeLock = await navigator.wakeLock.request('screen');
                            console.log('✨ Label Master Kijelző Ébrentartás AKTÍV - Nincs alvó mód!');
                        }
                    }
                } catch (err) {
                    console.log('Kijelző ébrentartási hiba: ' + err.message);
                }
            }
        
            function cleanupStreamlitElements() {
                try {
                    // Átnyúlunk a szülő ablak dokumentumába (CORS-barát módon)
                    var parentDoc = window.parent.document;
                    
                    // Megkeressük és kíméletlenül elrejtjük a fekete 'Manage app' gombot
                    var manageBtn = parentDoc.querySelector('[data-testid="manage-app-button"]');
                    if (manageBtn) {
                        manageBtn.style.setProperty('display', 'none', 'important');
                        manageBtn.style.setProperty('visibility', 'hidden', 'important');
                    }
                    
                    // Elrejtjük a szülő ablak egyéb felesleges Streamlit logóit, a "Made with Streamlit" és "Fork" gombokat is!
                    var badges = parentDoc.querySelectorAll('[data-testid="viewerBadge"], .viewerBadge, div[class*="viewerBadge"]');
                    badges.forEach(function(badge) {
                        badge.style.setProperty('display', 'none', 'important');
                        badge.style.setProperty('visibility', 'hidden', 'important');
                    });
                    
                    // Elrejtjük a lebegő hálózati státusz panelt is
                    var connStatus = parentDoc.querySelector('#ConnectionStatus, [id*="ConnectionStatus"]');
                    if (connStatus) {
                        connStatus.style.setProperty('display', 'none', 'important');
                        connStatus.style.setProperty('visibility', 'hidden', 'important');
                    }
                    
                    // Kijelentkezett módban megjelenő profil előnézet és a böszme nagy linkek megsemmisítése
                    var profilePreviews = parentDoc.querySelectorAll('[class*="profilePreview"], [class*="link"], a[href*="streamlit"]');
                    profilePreviews.forEach(function(el) {
                        el.style.setProperty('display', 'none', 'important');
                        el.style.setProperty('visibility', 'hidden', 'important');
                    });
        
                    // --- WAKE LOCK API INDÍTÁSA ---
                    requestWakeLock();
        
                } catch(e) {
                    console.log("CORS korlát vagy egyéb hiba a takarítás/ébrentartás során.");
                }
            }
            
            // Figyeljük, ha a futár visszalép az appba (pl. hívás után), azonnal ébresszük fel újra a kijelzőt
            document.addEventListener('visibilitychange', async () => {
                if (document.visibilityState === 'visible') {
                    wakeLock = null; // Reseteljük az előzőt
                    requestWakeLock();
                }
            });
            
            // Futtatás többször is, hogy a késleltetett betöltések után is biztosan kisöpörjük őket
            setTimeout(cleanupStreamlitElements, 300);
            setTimeout(cleanupStreamlitElements, 1000);
            setTimeout(cleanupStreamlitElements, 2500);
        </script>
        """,
        unsafe_allow_html=True
    )

    # Fontok registerelése a PDF-nyomtatáshoz
    from nyomtatas_modulok import register_fonts
    register_fonts()

    # Session State alapértékek biztonságos beállítása
    if 'mdf' not in st.session_state: st.session_state.mdf = None
    if 'meta_data' not in st.session_state: st.session_state.meta_data = {}
    if 'weights' not in st.session_state: st.session_state.weights = {}
    if 'editor_key' not in st.session_state: st.session_state.editor_key = 0
    if 'c_n' not in st.session_state: st.session_state.c_n = "Szűcs István"
    if 'c_p' not in st.session_state: st.session_state.c_p = "+36 20 886 8971"
    if 'bejelentkezve' not in st.session_state: st.session_state.bejelentkezve = False
    if 'user_nev' not in st.session_state: st.session_state.user_nev = ""
    if 'user_jarat' not in st.session_state: st.session_state.user_jarat = ""
    if 'user_szerep' not in st.session_state: st.session_state.user_szerep = "futar"
    if 'nevnapok_df' not in st.session_state: st.session_state.nevnapok_df = pd.DataFrame()
    if 'keresztnevek_df' not in st.session_state: st.session_state.keresztnevek_df = pd.DataFrame()

    # BIZTONSÁGOS REDIRECT: Ha a parancsikon miatt nincs 'view' paraméter a linkben
    if view is None:
        if 'edited_df' in st.session_state:
            view = "desktop"
        else:
            st.markdown("### 📱 Interfood Futár Terminál")
            st.info("A parancsikonról indítottad az alkalmazást. Kattints az alábbi gombra a folytatáshoz:")
            
            if st.button("🚀 MOBIL TERMINÁL INDÍTÁSA", use_container_width=True, type="primary"):
                st.query_params.update(view="mobile")
                st.rerun()
                
            st.write("---")
            with st.expander("💻 Adminisztrátori belépés (Asztali nézet)"):
                if st.button("Asztali verzió megnyitása"):
                    st.query_params.update(view="desktop")
                    st.rerun()
            return

    # --- PIN KÓDOS BELÉPTETŐ RENDSZER ---
    if not st.session_state.bejelentkezve:
        # Fallback védelem a logó hiányára
        if os.path.exists("interfood-logo.png"):
            # HTML/CSS konténer: mobilon és asztalin is FIXEN max 140px széles, és középre zárt!
            st.markdown(
                """
                <div style="text-align: center; width: 100%; margin-bottom: 15px; margin-top: 10px;">
                    <img src="app/static/interfood-logo.png" style="max-width: 140px; height: auto; display: block; margin: 0 auto;" onerror="this.onerror=null; this.src='https://www.interfood.hu/images/logo.png';">
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown("<h1 style='text-align: center; color: #139D43;'>💚 Interfood Label Master</h1>", unsafe_allow_html=True)
            
        st.markdown("<p style='text-align: center; color: #6B7280; font-size: 14px;'>Biztonságos azonosítás a rendszer használatához</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.warning("🔒 Kérjük, add meg a járatszámodat és az egyedi jelszavadat!")
            
            jarat_input = st.text_input("JÁRATSZÁM (vagy Admin):", value=url_jarat, key="login_jarat_field", placeholder="Pl. 4002 vagy admin")
            password_input = st.text_input("JELSZÓ / KÓD:", type="password", key="login_password_field", placeholder="••••••••")
            
            # Teszt belépés jelszó nélkül (ha a linkben szerepel a test=true)
            if url_teszt and jarat_input:
                st.info(f"🧪 Szimulált belépés észlelve a(z) {jarat_input} járathoz.")
                if st.button("🧪 TESZT BELÉPÉS JELSZÓ NÉLKÜL", type="primary", use_container_width=True):
                    # --- TISZTA LAP: Korábbi session kulcsok kisöprése ---
                    for k in list(st.session_state.keys()):
                        if any(x in k for x in ["kiszallitva_", "kiszallitott_statusz_", "bepak_allapot_", "lada_szam_tarolt_", "borravalo_", "atvett_input_", "chk_"]):
                            st.session_state.pop(k, None)
                            
                    st.session_state.bejelentkezve = True
                    st.session_state.user_nev = "Teszt Futár"
                    st.session_state.user_jarat_lista = [j.strip() for j in str(jarat_input).split(",") if j.strip()]
                    st.session_state.user_szerep = "futar"
                    st.session_state.c_n = "Teszt Futár"
                    st.session_state.c_p = "+36 20 886 8971"
                    st.rerun()

            if st.button("🔑 BIZTONSÁGOS BELÉPÉS", use_container_width=True):
                if not jarat_input or not password_input:
                    st.error("❌ Mindkét mező kitöltése kötelező!")
                else:
                    tisztitott_input_jarat = str(jarat_input).strip().lower()
                    tisztitott_input_pass = str(password_input).strip()
                    
                    # --- FEJLESZTŐI VÉSZBEJÁRAT ---
                    if tisztitott_input_jarat == "admin" and tisztitott_input_pass == "admin123":
                        # --- TISZTA LAP: Korábbi session kulcsok kisöprése ---
                        for k in list(st.session_state.keys()):
                            if any(x in k for x in ["kiszallitva_", "kiszallitott_statusz_", "bepak_allapot_", "lada_szam_tarolt_", "borravalo_", "atvett_input_", "chk_"]):
                                st.session_state.pop(k, None)
                        st.session_state.bejelentkezve = True
                        st.session_state.user_nev = "Rendszergazda (Vészbejárat)"
                        st.session_state.user_jarat_lista = ["4002"]
                        st.session_state.user_szerep = "superadmin"
                        st.session_state.c_n = "Szűcs István"
                        st.session_state.c_p = "+36 20 886 8971"
                        st.success("🔓 Sikeres rendszergazda belépés!")
                        st.rerun()
                    
                    # Google Sheets alapú éles ellenőrzés
                    with st.spinner("⏳ Kapcsolódás a biztonsági szerverhez..."):
                        try:
                            futar_adatok = _tiszta_futar_lista_letoltes(SHEET_ID_UGYFELKOR)
                        except Exception as auth_err:
                            st.error(f"⚠️ Nem sikerült a hitelesítő adatok letöltése: {auth_err}")
                            st.info("Tipp: Használhatod a beépített vészbejáratot is (Járatszám: admin, Jelszó: admin123)")
                            st.stop()
                    
                    talalt_futar = None
                    for f in futar_adatok:
                        sheet_jarat = str(f.get('Járat', f.get('Jarat', ''))).strip().lower()
                        sheet_pass = str(f.get('PIN_Kod', '')).replace("'", "").strip()
                        if sheet_pass.endswith('.0'):
                            sheet_pass = sheet_pass[:-2]
                        
                        if sheet_jarat == tisztitott_input_jarat and sheet_pass == tisztitott_input_pass:
                            talalt_futar = f
                            break
                    
                    if talalt_futar:
                        # --- TISZTA LAP: Korábbi session kulcsok kisöprése ---
                        for k in list(st.session_state.keys()):
                            if any(x in k for x in ["kiszallitva_", "kiszallitott_statusz_", "bepak_allapot_", "lada_szam_tarolt_", "borravalo_", "atvett_input_", "chk_"]):
                                st.session_state.pop(k, None)
                        st.session_state.bejelentkezve = True
                        st.session_state.user_nev = talalt_futar.get('Név', 'Ismeretlen felhasznaló')
                        raw_jarat = str(talalt_futar.get('Járat', talalt_futar.get('Jarat', ''))).strip()
                        st.session_state.user_jarat_lista = [j.strip() for j in raw_jarat.split(",") if j.strip()]
                        st.session_state.user_szerep = str(talalt_futar.get('Szerep', 'futar'))
                        
                        # --- AUTOMATIKUS FUTÁR ADATSZINKRON ---
                        st.session_state.c_n = talalt_futar.get('Név', 'Szűcs István')
                        st.session_state.c_p = str(talalt_futar.get('Telefon', '+36 20 886 8971')).strip()
                        
                        st.rerun()
                    else:
                        st.error("❌ Hibás járatszám vagy jelszó!")
        return

    # --- IDŐUTAZÁS FIGYELŐ ÉS ADATBÁZIS-INICIALIZÁLÓ MOTOR ---
    try:
        sheet = client.open_by_key(SHEET_ID_MASTER)
        ws_etlap = sheet.worksheet("Etlap_API")
        nyers_fejlec = ws_etlap.row_values(1) 
        jelenlegi_het_trigger = "-".join(nyers_fejlec)
        
        if 'etlap_trigger_state' in st.session_state and st.session_state.etlap_trigger_state != jelenlegi_het_trigger:
            if 'etlap_api_df' in st.session_state: del st.session_state['etlap_api_df']
            if 'master_df' in st.session_state: del st.session_state['master_df']
            if 'etelek_master_df' in st.session_state: del st.session_state['etelek_master_df']
            if 'nevnapok_df' in st.session_state: del st.session_state['nevnapok_df']
            if 'keresztnevek_df' in st.session_state: del st.session_state['keresztnevek_df']
        st.session_state.etlap_trigger_state = jelenlegi_het_trigger
    except:
        jelenlegi_het_trigger = "INITIAL"

    if 'master_df' not in st.session_state or 'etlap_api_df' not in st.session_state or st.session_state.nevnapok_df.empty or st.session_state.keresztnevek_df.empty:
        with st.spinner("⏳ A Label Master adatbázisok inicializálása..."):
            try:
                # 1. Master Étlap Adatbázis betöltése
                m_df = pd.DataFrame(sheet.worksheet("Master_Adatbazis").get_all_records())
                m_df.columns = [col.strip().replace('\ufeff', '') for col in m_df.columns]
                st.session_state.etelek_master_df = m_df  
                st.session_state.master_df = m_df 
                
                # 2. Éles NÉVNAPOK Adatbázis betöltése
                try:
                    nevnap_df = pd.DataFrame(sheet.worksheet("Nevnapok").get_all_records())
                    nevnap_df.columns = [col.strip().replace('\ufeff', '') for col in nevnap_df.columns]
                    st.session_state.nevnapok_df = nevnap_df
                    logger.info("Névnapok adatbázis sikeresen betöltve a felhőből.")
                except Exception as e_nev:
                    logger.warning(f"Nevnapok betöltési hiba: {e_nev}")
                
                # 3. Éles KERESZTNEVEK Adatbázis betöltése (Szigorú elsőnév-szűréshez)
                try:
                    kereszt_df = pd.DataFrame(sheet.worksheet("Keresztnevek").get_all_records())
                    kereszt_df.columns = [col.strip().replace('\ufeff', '') for col in kereszt_df.columns]
                    st.session_state.keresztnevek_df = kereszt_df
                    logger.info("Keresztnevek adatbázis sikeresen betöltve a felhőből.")
                except Exception as e_ker:
                    logger.warning(f"Keresztnevek betöltési hiba: {e_ker}")
                
                # 4. Étlap API betöltése
                api_df = load_etlap_api_smart(client, SHEET_ID_MASTER, columns_trigger=jelenlegi_het_trigger)
                if api_df is not None:
                    st.session_state.etlap_api_df = api_df
            except Exception as e:
                st.warning(f"⚠️ Adatbázis hiba: {e}")
                st.session_state.master_df = pd.DataFrame()
                st.session_state.etlap_api_df = pd.DataFrame()

    # Biztosítjuk a globális láthatóságot
    global etlap_api_df, etelek_master_df, master_df, ugyfelkor_df, mdf, nevnapok_df, keresztnevek_df
    etlap_api_df = st.session_state.get('etlap_api_df', pd.DataFrame())
    etelek_master_df = st.session_state.get('etelek_master_df', pd.DataFrame())
    master_df = etelek_master_df
    nevnapok_df = st.session_state.get('nevnapok_df', pd.DataFrame())
    keresztnevek_df = st.session_state.get('keresztnevek_df', pd.DataFrame())
    ugyfelkor_df = st.session_state.get('ugyfelkor_df', pd.DataFrame())
    mdf = st.session_state.get('mdf', pd.DataFrame())

    # =========================================================================
    # 📱 1. ÁG: QR-KÓDOS MOBIL NÉZET
    # =========================================================================
    if is_mobile_view:
        st.title("📱 Futár Terminál")
        st.caption(f"Bejelentkezve: {st.session_state.user_nev}")
        
        with st.sidebar:
            render_mobil_sidebar_dashboard(client, SHEET_ID_UGYFELKOR, SHEET_ID_MASTER)
            
        tab1, tab2, tab3 = st.tabs(["1. Áruátvétel 📦", "2. Címekre szedés 📥", "3. Kiszállítás 🚚"])
        with tab1:
            render_mobil_aruatvetel(client)
        with tab2:
            render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR)
        with tab3:
            render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR)
                
        if st.button("🚪 Kijelentkezés", key="mob_logout"):
            # --- TISZTA LAP KIJELENTKEZÉSKOR ---
            for k in list(st.session_state.keys()):
                if any(x in k for x in ["kiszallitva_", "kiszallitott_statusz_", "bepak_allapot_", "lada_szam_tarolt_", "borravalo_", "atvett_input_", "chk_"]):
                    st.session_state.pop(k, None)
            st.session_state.bejelentkezve = False
            st.rerun()

    # =========================================================================
    # 🖥️ 2. ÁG: TELJES ASZTALI / ADMINISZTRÁCIÓS NÉZET
    # =========================================================================
    else:
        st.sidebar.markdown(f"### 👤 {st.session_state.user_nev}")
        is_admin = st.session_state.user_szerep in ["admin", "superadmin"]
        
        if is_admin:
            st.sidebar.success("⭐ Adminisztrátor Mód")
        else:
            if 'user_jarat_lista' in st.session_state and st.session_state.user_jarat_lista:
                st.sidebar.caption(f"🚚 Aktív járatok: {', '.join(st.session_state.user_jarat_lista)}")
            
        if st.sidebar.button("🚪 Kijelentkezés", key="desktop_logout"):
            # --- TISZTA LAP KIJELENTKEZÉSKOR ---
            for k in list(st.session_state.keys()):
                if any(x in k for x in ["kiszallitva_", "kiszallitott_statusz_", "bepak_allapot_", "lada_szam_tarolt_", "borravalo_", "atvett_input_", "chk_"]):
                    st.session_state.pop(k, None)
            st.session_state.bejelentkezve = False
            if 'user_jarat_lista' in st.session_state: del st.session_state.user_jarat_lista
            st.rerun()
            
        # Oldalsáv kezelőszervek kirajzolása és az aktív funkció lekérése
        with st.sidebar:
            admin_funkcio = render_desktop_sidebar_controls(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, LOG_FILE)

        # Főképernyő renderelése a választott menüpont alapján
        render_desktop_main_content(
            client=client,
            SHEET_ID_MASTER=SHEET_ID_MASTER,
            SHEET_ID_UGYFELKOR=SHEET_ID_UGYFELKOR,
            admin_funkcio=admin_funkcio,
            is_admin=is_admin
        )

if __name__ == "__main__":
    main()
