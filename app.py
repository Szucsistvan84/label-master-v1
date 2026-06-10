import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import requests
import openpyxl
import os
import gspread
import folium
import logging
import time
import unicodedata
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from streamlit_folium import st_folium
from datetime import datetime
from gspread_dataframe import set_with_dataframe
from google.oauth2 import service_account
from google.oauth2.service_account import Credentials
from io import BytesIO
from mobil_modulok import render_mobil_aruatvetel, render_mobil_bepakolas, render_mobil_kiszallitas
from nyomtatas_modulok import create_label_pdf, create_manifest_pdf, create_raklista_pdf

# ==============================================================================
# 1. GLOBÁLIS KONFIGURÁCIÓK, MINTÁK ÉS BEÁLLÍTÁSOK
# ==============================================================================

# --- LOGGOLÁS BEÁLLÍTÁSA ---
LOG_FILE = "utvonaltervezo.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 🧪 URL PARAMÉTEREK ÉS TESZT MÓD INICIALIZÁLÁSA
# ==============================================================================
if 'teszt_uzemmod' not in st.session_state:
    st.session_state.teszt_uzemmod = False

# Ha a mobilos vagy asztali URL-ből jön a teszt jelzés, kényszerítjük a teszt módot
if "test" in st.query_params and st.query_params["test"] == "true":
    st.session_state.teszt_uzemmod = True
# ==============================================================================

# --- GEOCODING (CÍMKERESŐ) SETUP ---
geolocator = Nominatim(user_agent="futarszoli_app")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.5)

# --- GLOBÁLIS REGEX MINTÁK (PDF FELDOLGOZÁSHOZ) ---
PHONE_PAT = r'(\d{2}/\d[\d\s,]*\d)'
# Frissített minta: felismeri a sima (-), az en-dash (–) és az em-dash (—) jeleket is
ORDER_PAT = r'(\d+)\s*[-\u2013\u2014\u2212]\s*([A-Z][A-Z0-9*+]*)'
# Frissített, "szóköz-toleráns" regex
MONEY_PAT = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

# --- GOOGLE SHEETS ALAPHELYZET ---
client = None 


# ==============================================================================
# 2. GLOBÁLIS SEGÉDFÜGGVÉNYEK
# ==============================================================================

def check_user_role():
    """Visszaadja a felhasználó szerepkörét."""
    role = st.session_state.get('user_szerep', 'futar')
    if st.session_state.get('user_nev') == "SajátNeved": 
        return "superadmin"
    return role

def biztonsagos_koordinata_tisztito(val):
    """Minden létező koordináta formátumot tiszta float számmá alakít."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() == "none" or s == "0" or s == "0.0":
        return None
        
    s = s.replace("'", "").replace('"', '').replace('`', '')
    s = s.replace(",", ".")
    
    try:
        f = float(s)
        if abs(f) > 1000:
            if str(abs(int(f))).startswith(('46', '47', '48')):
                f = f / 10000000 if len(str(int(f))) >= 9 else f / 1000000
            elif str(abs(int(f))).startswith(('16', '17', '18', '19', '20', '21', '22')):
                f = f / 10000000 if len(str(int(f))) >= 9 else f / 1000000
        
        if 45.5 <= f <= 48.8 or 16.0 <= f <= 23.0:
            return round(f, 7)
        else:
            return None
    except:
        return None

def kotelezo_ugyfelkor_formatum_tisztitas(df):
    """
    Szigorú típusbiztos szűrő az Ugyfelkor DataFrame-re.
    Garantálja, hogy a Google Sheets-be csak tiszta, számolható adatok kerüljenek.
    A koordinátákat átfuttatja a biztonsagos_koordinata_tisztito-n, és stringként 
    menti, hogy a Google Sheets ne nyelje le a tizedesvesszőket.
    """
    if df.empty:
        return df
        
    df_clean = df.copy()
    
    # 1. ID kényszerítése tiszta 6 jegyű szöveggé (levágva a .0-át ha float lenne)
    if 'ID' in df_clean.columns:
        df_clean['ID'] = df_clean['ID'].astype(str).apply(
            lambda x: "".join(filter(str.isdigit, x.split('.')[0])).strip()
        )
        
    # 2. Nevek és Címek tisztítása a felesleges szóközöktől
    if 'Név' in df_clean.columns:
        df_clean['Név'] = df_clean['Név'].astype(str).str.strip()
    if 'Cím' in df_clean.columns:
        df_clean['Cím'] = df_clean['Cím'].astype(str).str.strip()
        
    # =========================================================================
    # 🔥 JAVÍTOTT 3. PONT: Koordináták precíziós tisztítása és mentése
    # =========================================================================
    for col in ['Lat', 'Lon']:
        if col in df_clean.columns:
            # Első lépés: átengedjük a te okos, levágás-biztos tisztító függvényeden
            df_clean[col] = df_clean[col].apply(biztonsagos_koordinata_tisztito)
            
            # Második lépés (Google Sheets trükk): Szöveggé alakítjuk a kapott tiszta float számot.
            # Így a gspread tizedespontos stringként küldi be, és a Sheets nem fogja eltüntetni a pontot!
            df_clean[col] = df_clean[col].apply(lambda x: f"{x}" if x is not None and not pd.isna(x) else "")
            
    # 4. Telefon, Csoport, Megjegyzés, Utolso_Rendeles tisztítása stringgé (nan-ok eltávolítása)
    for col in ['Telefon', 'Csoport', 'Megjegyzés', 'Utolso_Rendeles']:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].astype(str).str.strip().replace(['nan', 'None', '<NA>', 'NaN'], '')
            
    # 5. Összérték és Rendelésszám szigorúan EGÉSZ SZÁM (Integer)
    if 'Osszertek' in df_clean.columns:
        df_clean['Osszertek'] = df_clean['Osszertek'].astype(str).str.replace(r'[^0-9-]', '', regex=True)
        df_clean['Osszertek'] = pd.to_numeric(df_clean['Osszertek'], errors='coerce').fillna(0).astype(int)
        
    if 'Rendeles_Szam' in df_clean.columns:
        df_clean['Rendeles_Szam'] = df_clean['Rendeles_Szam'].astype(str).str.replace(r'[^0-9-]', '', regex=True)
        df_clean['Rendeles_Szam'] = pd.to_numeric(df_clean['Rendeles_Szam'], errors='coerce').fillna(0).astype(int)
        
    # Minden üres/hiányzó értéket üres stringre cserélünk a Sheets kompatibilitás miatt
    df_clean = df_clean.fillna("")

    # 🔥 EZT A KÉT SORT ADD HOZZÁ A RETURN ELŐTT:
    if 'Lat' in df_clean.columns:
        df_clean['Lat'] = df_clean['Lat'].astype(str)
    if 'Lon' in df_clean.columns:
        df_clean['Lon'] = df_clean['Lon'].astype(str)
    
    return df_clean

def get_google_sheets_creds():
    """Összeállítja és visszaadja a Google Credentials objektumot a Secrets-ből."""
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
    else:
        creds_dict = dict(st.secrets)
        
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
    return Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])

def get_latest_week_from_master(sheet_id):
    """Kinyeri a legnagyobb hetet a 'wXX' formátumú szövegekből."""
    try:
        global client
        if client is None:
            client = gspread.authorize(get_google_sheets_creds())
        sheet = client.open_by_key(sheet_id).worksheet("Master_Adatbazis")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        oszlop_nev = "Kódok és Árak" 
        if oszlop_nev not in df.columns:
            st.error(f"Hiba: Az oszlop '{oszlop_nev}' nem található.")
            return 2026, 0

        all_weeks = []
        for cell_content in df[oszlop_nev].astype(str):
            weeks = re.findall(r'w(\d+)', cell_content)
            all_weeks.extend([int(w) for w in weeks])
            
        if not all_weeks:
            return 2026, 0
            
        return 2026, max(all_weeks)
    except Exception as e:
        st.error(f"Hiba történt a hét lekérésekor: {e}")
        return 2026, 0

def get_coordinates(address):
    """Lekéri a megadott cím koordinátáit."""
    try:
        location = geocode(address) 
        if location:
            str_lat = f"'{location.latitude:.7f}"
            str_lon = f"'{location.longitude:.7f}"
            return str_lat, str_lon
        else:
            return None, None
    except Exception as e:
        logger.error(f"Váratlan hiba a geocoding során ({address}): {e}")
        return None, None

def tisztitott_cim_lekerese(nyers_szoveg):
    if not nyers_szoveg:
        return ""
    szoveg = nyers_szoveg.replace('$', '').strip()
    minta = r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-áéíóöőúüű]+\s*,\s*[^,]+?\s\d+[a-zA-Z0-9\/\-\.]*)'
    match = re.search(minta, szoveg)
    if match:
        return match.group(1).strip()
    tisztitott = szoveg.split('. fsz')[0].split('. fszt')[0].split(', fsz')[0]
    return tisztitott.strip()

@st.cache_data(ttl=300)
def _tiszta_futar_lista_letoltes(sheet_id):
    try:
        local_client = gspread.authorize(get_google_sheets_creds())
        sh = local_client.open_by_key(sheet_id)
        ws_futarok = sh.worksheet("Futárok")
        return ws_futarok.get_all_records()
    except Exception as e:
        return []

@st.cache_data(ttl=600)
def _tiszta_ugyfelkor_letoltes(sheet_id):
    try:
        local_client = gspread.authorize(get_google_sheets_creds())
        sh = local_client.open_by_key(sheet_id)  
        ws_ugyfel = sh.worksheet("Ugyfelkor")
        try:
            return ws_ugyfel.get_all_records(value_render_option='UNFORMATTED_VALUE')
        except:
            return ws_ugyfel.get_all_records()
    except Exception as e:
        return []

# ==============================================================================
# 🔥 EZ LEGYEN AZ ÚJ, OKOSÍTOTT ÉTLAP FIGYELŐ (GOOGLE SHEETS VERZIÓ):
# ==============================================================================
@st.cache_data(show_spinner="Étlap API frissítése a felhőből...")
def load_etlap_api_smart(sheet_id, columns_trigger=None):
    """
    Letölti az Etlap_API munkalapot a Google Sheets-ből. 
    Ha a 'columns_trigger' (a felhőben lévő oszlopnevek összeragasztva) megváltozik 
    egy időutazás miatt, a Streamlit azonnal törli a régi cache-t és újra letölti!
    """
    try:
        import gspread
        # Hitelesítés és a táblázat megnyitása
        local_client = gspread.authorize(get_google_sheets_creds())
        sh = local_client.open_by_key(sheet_id)
        ws_api = sh.worksheet("Etlap_API")
        
        # Teljes adattábla letöltése DataFrame-be
        df = pd.DataFrame(ws_api.get_all_records())
        
        # Megtisztítjuk az oszlopneveket a felesleges szóközöktől (a \n karaktereket meghagyjuk!)
        df.columns = [str(col).strip().replace('\ufeff', '') for col in df.columns]
        return df
    except Exception as e:
        st.error(f"❌ Smart Cache hiba az Etlap_API letöltésekor: {e}")
        return None
        
# ==============================================================================
# 🟢 2. A JAVÍTOTT, TELJES MESTER LISTA SZINKRONIZÁLÓ FÜGGVÉNY (GOLYÓÁLLÓ VERZIÓ)
# ==============================================================================
def master_lista_szinkron(df_napi, sheet_id, client, jarat_szam=None):
    """
    Összefésüli a napi listát a törzslistával (Ugyfelkor) szigorúan 6 jegyű ID alapján.
    Kevesebb API hívást használ, megelőzve a Google Sheets 429-es kvótahibáját.
    1. Az 'Ugyfelkor' fület CSAK BŐVÍTI az új ügyfelekkel (nem törli!).
    2. Az 'Adatok' fület kiüríti és feltölti a pontos aznapi 15 oszlopos menetrenddel.
    """
    import pandas as pd
    import streamlit as st
    import logging
    import time  # <--- Szükséges a rövid szünetekhez
    from gspread_dataframe import set_with_dataframe
    
    logger = logging.getLogger(__name__)
    logger.info("🧬 Master lista szinkronizálása elindult az új struktúra alapján (Kvótavédelemmel)...")
    master_df = pd.DataFrame()

    # Golyóálló ID tisztító függvény
    def tiszta_id_konverzio(x):
        if pd.isna(x) or x == "":
            return ""
        s = str(x).replace("'", "").replace(' ', '').strip()
        if '-' in s:
            s = s.split('-')[-1]
        tisztitott = "".join(filter(str.isdigit, s))
        return tisztitott if len(tisztitott) > 0 else ""

    # Biztonságos float konvertáló helyi szinten is
    def biztonsagos_float(val):
        if val is None or str(val).strip() in ["", "None", "nan", "NaN", "-", "'"]:
            return ""
        try:
            val_clean = str(val).replace(",", ".").replace("'", "").strip()
            return float(val_clean)
        except ValueError:
            return ""

    # --- 1. LÉPÉS: TÖRZSLISTA BEOLVASÁSA ÉS TISZTÍTÁSA ---
    try:
        sh = client.open_by_key(sheet_id)
        ws_ugyfel = sh.worksheet("Ugyfelkor")
        
        # A Google-től csak akkor kérünk adatot, ha a 10 perc letelt, különben memóriából rántja elő!
        records = _tiszta_ugyfelkor_letoltes(sheet_id)
        
        if records:
            master_df = pd.DataFrame(records)
        else:
            master_df = pd.DataFrame(columns=['ID', 'Név', 'Cím', 'Lat', 'Lon', 'Telefon', 'Csoport', 'Megjegyzés', 'Utolso_Rendeles', 'Osszertek', 'Rendeles_Szam'])
            
        master_df.columns = [c.strip() for c in master_df.columns]
        
        if 'ID' in master_df.columns:
            master_df['ID'] = master_df['ID'].astype(str).str.strip().apply(lambda x: x.split('.')[0] if x.endswith('.0') else x)
            master_df['ID'] = master_df['ID'].apply(tiszta_id_konverzio)
            
        # Tisztítás a globális koordináta tisztítóval
        if 'Lat' in master_df.columns:
            master_df['Lat'] = master_df['Lat'].apply(biztonsagos_koordinata_tisztito)
        if 'Lon' in master_df.columns:
            master_df['Lon'] = master_df['Lon'].apply(biztonsagos_koordinata_tisztito)
            
        st.session_state.ugyfelkor_df = master_df.copy()
        st.session_state.mdf = master_df.copy()
            
        logger.info(f"Mesterlista sikeresen beolvasva CACHE módban és letisztítva, {len(master_df)} meglévő ügyfél.")

    except Exception as e:
        logger.error(f"Hiba a törzslista (Ugyfelkor) megnyitásakor: {e}")
        st.error(f"Nem sikerült elérni az 'Ugyfelkor' táblázatot! Hiba: {e}")
        return df_napi, pd.DataFrame()

    # --- 2. LÉPÉS: NAPI IMPORTÁLT LISTA FEJLÉC ÉS ID TISZTÍTÁSA ---
    df_napi.columns = [c.strip() for c in df_napi.columns]
    
    if 'Preferált Sorrend' in df_napi.columns:
        df_napi = df_napi.drop(columns=['Preferált Sorrend'], errors='ignore')

    df_napi['ID'] = df_napi['ID'].apply(tiszta_id_konverzio)

    # --- 3. LÉPÉS: ÚJ ÜGYFELEK ÉSZLELÉSE, GEOMAPOLÁS ÉS ADATBÁZIS ÖSSZEFÉSÜLÉS ---
    st.info("🔄 Ügyfélkör adatbázis aktualizálása és koordináták ellenőrzése...")
    
    # Előkészítjük a master_df-et biztonsági okokból az try blokkon kívül
    master_df = pd.DataFrame()

    try:
        # 1. Betöltjük a Google Sheets aktuális teljes 'Ugyfelkor' tartalmát egy DataFrame-be
        ugyfelkor_adatok = ws_ugyfel.get_all_records()
        df_ugyfelkor_teljes = pd.DataFrame(ugyfelkor_adatok)
        
        # 🔥 AZONNALI TISZTÍTÁS: Kigyomláljuk az összes létező hibát (pl. idézőjelek, vesszők) a felhőből letöltött adatokból
        if not df_ugyfelkor_teljes.empty:
            df_ugyfelkor_teljes = kotelezo_ugyfelkor_formatum_tisztitas(df_ugyfelkor_teljes)
        
        # Kinyerjük a szállítás VALÓDI dátumát a session_state-ből vagy fallbackként a mai napot
        meta_forras = st.session_state.get('meta_data', {})
        szallitas_napja = meta_forras.get('datum_iso', datetime.now().strftime("%Y-%m-%d"))
        
        új_koordináta_számláló = 0
        
        # 2. Végigmegyünk a PDF-ből most beolvasott napi megrendeléseken
        for idx, row in df_napi.iterrows():
            u_id = str(row['ID']).strip()
            if not u_id or u_id == "" or u_id == "nan": 
                continue
                
            # Megkeressük a mai rendelés értékét a Fizetendő oszlopból
            mai_rendeles_erteke = 0
            if 'Fizetendő' in row and pd.notna(row['Fizetendő']):
                tisztitott_ar = str(row['Fizetendő']).replace('Ft', '').replace(' ', '').strip()
                if tisztitott_ar.isdigit() or (tisztitott_ar.startswith('-') and tisztitott_ar[1:].isdigit()):
                    mai_rendeles_erteke = int(tisztitott_ar)
            
            # ELLENŐRIZZÜK A KOORDINÁTÁKAT
            van_koordinata = False
            lat_clean, lon_clean = "", ""
            
            if not df_ugyfelkor_teljes.empty and 'ID' in df_ugyfelkor_teljes.columns:
                if u_id in df_ugyfelkor_teljes['ID'].values:
                    talalat = df_ugyfelkor_teljes[df_ugyfelkor_teljes['ID'] == u_id]
                    lat_val = talalat.iloc[0].get('Lat')
                    lon_val = talalat.iloc[0].get('Lon')
                    
                    if pd.notna(lat_val) and pd.notna(lon_val):
                        lat_str = str(lat_val).replace("'", "").replace('"', '').replace(',', '.').strip()
                        lon_str = str(lon_val).replace("'", "").replace('"', '').replace(',', '.').strip()
                        
                        if lat_str not in ["", "None", "nan", "NaN", "0", "0.0"]:
                            try:
                                lat_clean = float(lat_str)
                                lon_clean = float(lon_str)
                                van_koordinata = True
                            except ValueError:
                                van_koordinata = False
            
            # Ha nincs meg a koordináta, akkor lekérjük a Geocoder API-n keresztül
            if not van_koordinata:
                nev = row.get('Ügyintéző', row.get('Név', row.get('Nev', 'Ismeretlen név')))
                eredeti_cim = str(row.get('Cím', row.get('Cim', '')))
                
                try:
                    keresesi_cim = tisztitott_cim_lekerese(eredeti_cim)
                except NameError:
                    keresesi_cim = eredeti_cim
                    
                logger.info(f"✨ Koordináta keresése/pótlása: {nev} ({u_id})...")
                st.info(f"📍 GPS koordináta keresése: {nev}...")
                
                try:
                    lat, lon = get_coordinates(keresesi_cim)
                    time.sleep(0.2) # API kímélése
                except Exception as e:
                    logger.error(f"Hiba a geocoding során ({nev}): {e}")
                    lat, lon = None, None
                    
                if lat is not None and lon is not None:
                    try:
                        lat_clean = round(float(str(lat).replace("'", "").replace('"', '').replace(',', '.').strip()), 6)
                        lon_clean = round(float(str(lon).replace("'", "").replace('"', '').replace(',', '.').strip()), 6)
                        st.success(f"🎯 GPS sikeresen megvan: {nev}")
                        új_koordináta_számláló += 1
                    except Exception as e_conv:
                        logger.error(f"Konverziós hiba új koordinátánál ({nev}): {e_conv}")
                        lat_clean, lon_clean = "", ""
                else:
                    st.warning(f"⚠️ Nem találtam koordinátát: {nev}")
                    lat_clean, lon_clean = "", ""

            # --- INTEGRÁCIÓ: FRISSÍTÉS VAGY ÚJ HOZZÁADÁS A MEMÓRIÁBAN ---
            if not df_ugyfelkor_teljes.empty and u_id in df_ugyfelkor_teljes['ID'].values:
                # MEGLÉVŐ ÜGYFÉL: Módosítunk és biztonságosan kumulálunk (Numeric cast)
                idx_ugyfel = df_ugyfelkor_teljes[df_ugyfelkor_teljes['ID'] == u_id].index[0]
                
                try:
                    jelenlegi_ertek = int(float(str(df_ugyfelkor_teljes.at[idx_ugyfel, 'Osszertek']).strip() or 0))
                    jelenlegi_szam = int(float(str(df_ugyfelkor_teljes.at[idx_ugyfel, 'Rendeles_Szam']).strip() or 0))
                except (ValueError, TypeError):
                    jelenlegi_ertek = 0
                    jelenlegi_szam = 0

                df_ugyfelkor_teljes.at[idx_ugyfel, 'Osszertek'] = jelenlegi_ertek + mai_rendeles_erteke
                df_ugyfelkor_teljes.at[idx_ugyfel, 'Rendeles_Szam'] = jelenlegi_szam + 1
                df_ugyfelkor_teljes.at[idx_ugyfel, 'Utolso_Rendeles'] = szallitas_napja
                df_ugyfelkor_teljes.at[idx_ugyfel, 'Lat'] = str(lat_clean) if lat_clean else ""
                df_ugyfelkor_teljes.at[idx_ugyfel, 'Lon'] = str(lon_clean) if lon_clean else ""
            else:
                # TELJESEN ÚJ ÜGYFÉL: Új sort építünk tiszta típusokkal
                uj_sor = {
                    'ID': u_id,
                    'Név': row.get('Név', row.get('Ügyintéző', 'Ismeretlen Ügyfél')),
                    'Cím': row.get('Cím', row.get('Cim', '')),
                    'Lat': lat_clean,
                    'Lon': lon_clean,
                    'Telefon': str(row.get('Telefon', '')),
                    'Csoport': str(row.get('Csoport', '')),
                    'Megjegyzés': str(row.get('Megjegyzés', row.get('Megjegyzes', ''))),
                    'Utolso_Rendeles': szallitas_napja,
                    'Osszertek': mai_rendeles_erteke,
                    'Rendeles_Szam': 1
                }
                df_ugyfelkor_teljes = pd.concat([df_ugyfelkor_teljes, pd.DataFrame([uj_sor])], ignore_index=True)

        # 3. Az összefésült teljes állományt még egyszer átfuttatjuk a szigorú formázón a biztonság kedvéért
        df_ugyfelkor_vegleges = kotelezo_ugyfelkor_formatum_tisztitas(df_ugyfelkor_teljes)
        
        # 4. 🔥 JAVÍTOTT MENTÉS: Indexek nélkül, pontos cellameghatározással írjuk felül a Sheets-et
        set_with_dataframe(ws_ugyfel, df_ugyfelkor_vegleges, row=1, col=1, include_index=False, resize=True)
        st.success(f"🎉 Ügyfélkör adatbázis sikeresen szűrve és elmentve! Új koordináták pótolva: {új_koordináta_számláló} db.")
        
        # A lokális master_df frissítése a merge-höz
        master_df = df_ugyfelkor_vegleges.copy()
        
        if 'google_data_loaded' in st.session_state:
            del st.session_state['google_data_loaded']
            
    except Exception as e_full_process:
        logger.error(f"Súlyos hiba az ügyfélkör PDF alapú frissítése során: {e_full_process}")
        st.error(f"❌ Nem sikerült az ügyfélkör automatikus frissítése: {e_full_process}")

    # --- 4. LÉPÉS: SZIGORÚ ÖSSZEFÉSÜLÉS (Koordináták áthúzása a napi listába) ---
    if not master_df.empty:
        df_napi = df_napi.drop(columns=['Lat', 'Lon'], errors='ignore')
        b_cols = ['ID', 'Lat', 'Lon']
        for c in ['Csoport', 'Megjegyzés']:
            if c in master_df.columns and c not in df_napi.columns:
                b_cols.append(c)
                
        df_napi = df_napi.merge(master_df[b_cols], on='ID', how='left')
    else:
        if 'Lat' not in df_napi.columns: df_napi['Lat'] = None
        if 'Lon' not in df_napi.columns: df_napi['Lon'] = None

    # Végül átfuttatjuk a biztonságos tisztítón a napi DataFrame koordinátáit is
    df_napi['Lat'] = df_napi['Lat'].apply(biztonsagos_koordinata_tisztito)
    df_napi['Lon'] = df_napi['Lon'].apply(biztonsagos_koordinata_tisztito)

    # --- 5. LÉPÉS: DINAMIKUS NAPI SORSZÁM GENERÁLÁSA ---
    df_napi['Sorrend'] = range(1, len(df_napi) + 1)

    # --- 6. LÉPÉS: HIÁNYZÓ MOBILOS OSZLOPOK OKOS KITÖLTÉSE ---
    if 'Név' not in df_napi.columns:
        if 'Ügyintéző' in df_napi.columns:
            df_napi['Név'] = df_napi['Ügyintéző']
        elif 'Nev' in df_napi.columns:
            df_napi['Név'] = df_napi['Nev']
        else:
            df_napi['Név'] = "Ismeretlen"

    if 'Fizetendő' not in df_napi.columns and 'Pénz' in df_napi.columns:
        df_napi['Fizetendő'] = df_napi['Pénz']

    # 🟢 JAVÍTOTT TÖBBJÁRATOS LOGIKA: 
    # Ha a merge_data már sikeresen beletette a soronkénti egyedi járatokat, akkor NEM bántjuk!
    # Csak akkor használjuk a jarat_szam-ot, ha a sorban az érték üres vagy teljesen hiányzik.
    if 'Járat' not in df_napi.columns:
        df_napi['Járat'] = jarat_szam if jarat_szam else ""
    else:
        df_napi['Járat'] = df_napi['Járat'].fillna("")
        if jarat_szam:
            df_napi['Járat'] = df_napi['Járat'].apply(lambda x: jarat_szam if str(x).strip() == "" else x)

    # Az összes többi hiányzó oszlop alapértelmezése (a Járatot és Fizetendőt kivettük a ciklusból, mert fent lekezeltük)
    for col in ['Rendelés', 'Megjegyzés', 'Fizetési Mód', 'Státusz', 'Időbélyeg', 'Telefon', 'Csoport']:
        if col not in df_napi.columns:
            if col == 'Státusz':
                df_napi[col] = "Kiszállítás alatt"
            else:
                df_napi[col] = ""

    # --- 7. LÉPÉS: FRISSÍTÉS AZ "ADATOK" FÜLRE (SZIGORÚ HIERARCHIA - TÖBBFELHASZNÁLÓS MÓD) ---
    try:
        time.sleep(1.0)
        ws_adatok = sh.worksheet("Adatok")
        
        # 1. Beolvassuk a Google Sheets-ben AKTUALISAN bent lévő összes adatot
        existing_records = ws_adatok.get_all_records()
        if existing_records:
            df_existing = pd.DataFrame(existing_records)
            df_existing.columns = [c.strip() for c in df_existing.columns]
        else:
            df_existing = pd.DataFrame()

        # 🟢 JAVÍTÁS ÜNNEPI / ÖSSZEVONT RENDELÉSEKHEZ:
        if 'Rendelés_Full' in df_napi.columns:
            df_napi['Rendelés'] = df_napi.apply(
                lambda row: str(row['Rendelés_Full']).strip() if str(row.get('Rendelés_Full', '')).strip() != "" else row['Rendelés'], 
                axis=1
            )
        
        # 🔒 AUTOMATIKUS FUTÁR PECSÉT GENERÁLÁSA
        aktualis_futar_nev = st.session_state.get('user_nev', 'Ismeretlen_Feltölto')
        df_napi['Feldolgozó Futár'] = aktualis_futar_nev
        
        # Ez a hivatalos, kért 16 oszlopos séma
        export_cols = [
            'ID', 'Név', 'Cím', 'Telefon', 'Csoport', 'Sorrend', 'Lat', 'Lon', 
            'Rendelés', 'Megjegyzés', 'Járat', 'Fizetendő', 'Fizetési Mód', 'Státusz', 'Időbélyeg',
            'Feldolgozó Futár'
        ]
        
        # Előkészítjük az új adatokat tartalmazó DataFrame-et
        df_uj_adatok = df_napi[export_cols].copy()
        
        # 🔄 ÖSSZEFÉSÜLÉS (ANTI-ADATVESZTÉS ÉS IDŐBÉLYEG-VÉDELEM LOGIKA):
        if not df_existing.empty and 'Feldolgozó Futár' in df_existing.columns:
            # 1. Megtartjuk a MÁSOK által feltöltött sorokat
            df_mások_adatai = df_existing[df_existing['Feldolgozó Futár'] != aktualis_futar_nev]
            
            # 2. Megtartjuk a SAJÁT, de már IDŐBÉLYEGGEL ELLÁTOTT (lezárt) sorainkat!
            # (Feltételezzük, hogy az 'Időbélyeg' oszlopba kerül a lezárás a futár appból. 
            # Ha a 'Státusz' oszlop jelzi a lezárást, pl. 'Kiszállítva', akkor arra is szűrhetünk.)
            df_saját_lezárt_adatai = df_existing[
                (df_existing['Feldolgozó Futár'] == aktualis_futar_nev) & 
                (df_existing['Időbélyeg'].astype(str).str.strip() != "")
            ]
            
            # Összegyúrjuk a védett adatokat (másoké + saját lezártunk) az én friss, új PDF adataimmal
            save_df = pd.concat([df_mások_adatai, df_saját_lezárt_adatai, df_uj_adatok], ignore_index=True)
        else:
            # Ha teljesen üres a táblázat, akkor csak az új adatokat mentjük
            save_df = df_uj_adatok

        # Típusbiztonsági takarítás a mentés előtt
        save_df['Lat'] = save_df['Lat'].apply(biztonsagos_float)
        save_df['Lon'] = save_df['Lon'].apply(biztonsagos_float)
        save_df['ID'] = save_df['ID'].astype(str)
        
        for col in save_df.columns:
            save_df[col] = save_df[col].astype(object)
        save_df = save_df.fillna('')
        
        # 🚨 A TELJES TÖRLÉS HELYETT: Csak felülírjuk a táblázatot az összefésült, biztonságos adattal!
        ws_adatok.clear() # Most már kiüríthetjük egy tizedmásodpercre, mert a 'save_df'-ben benne van a pesti kolléga adata is!
        set_with_dataframe(ws_adatok, save_df, include_index=False, include_column_header=True)
        logger.info("🚀 Biztonságos, többfelhasználós szinkronizáció kész! Minden kolléga adata megőrizve.")
        
    except Exception as e:
        logger.warning(f"A térkép elkészült, de az 'Adatok' fül frissítése megszakadt: {e}")

    logger.info("Szinkronizáció teljesen kész.")
    return df_napi, master_df

# --- VIZUALIZÁCIÓ ---
def utvonal_terkep(df_napi, sheet_id=None, client=None):
    """
    Kiszállítási útvonal térképes megjelenítése Folium-mal.
    KIZÁRÓLAG a hajszálpontosan egyező koordinátájú (társasház/cég) ügyfeleket vonja össze.
    """
    import folium
    import folium.plugins
    
    st.subheader("🗺️ Tervezett Kiszállítási Útvonal")
    
    # Session state és kliens ellenőrzése
    actual_client = st.session_state.get('client') if 'client' in st.session_state else client
    actual_sheet_id = st.session_state.get('sheet_id') if 'sheet_id' in st.session_state else sheet_id

    if not actual_client or isinstance(actual_client, str):
        st.error("❌ A Google Sheets kliens nincs inicializálva!")
        return
    if not actual_sheet_id:
        st.error("❌ A Google Sheets ID hiányzik!")
        return

    # 1. Google Sheets törzslista beolvasása
    try:
        sh = actual_client.open_by_key(actual_sheet_id)
        ws = sh.worksheet("Ugyfelkor")
        df_torzs = pd.DataFrame(ws.get_all_records())
    except Exception as e:
        st.error(f"Nem sikerült beolvasni az Ugyfelkor törzslistát: {e}")
        return

    # 2. Adatok összefésülése
    df_valid_gps = df_napi.copy()
    if 'ID' in df_valid_gps.columns and 'ID' in df_torzs.columns:
        df_valid_gps['ID'] = df_valid_gps['ID'].astype(str).str.strip()
        df_torzs['ID'] = df_torzs['ID'].astype(str).str.strip()
        
        cols_to_drop = [c for c in ['Lat', 'Lon', 'Név', 'Cím'] if c in df_valid_gps.columns]
        df_megtisztitott = df_valid_gps.drop(columns=cols_to_drop)
        df_valid_gps = pd.merge(df_megtisztitott, df_torzs[['ID', 'Név', 'Cím', 'Lat', 'Lon']], on='ID', how='left')

    # Koordináták tisztítása és számmá alakítása
    for col in ['Lat', 'Lon']:
        if col in df_valid_gps.columns:
            df_valid_gps[col] = df_valid_gps[col].astype(str).str.replace("'", "").str.replace('"', '').str.replace(",", ".").str.strip()
            df_valid_gps[col] = pd.to_numeric(df_valid_gps[col], errors='coerce')

    # Csak a valós, jó koordináták megtartása
    df_jo_gps = df_valid_gps[df_valid_gps['Lat'].notna() & df_valid_gps['Lon'].notna()].copy()
    df_jo_gps = df_jo_gps[(df_jo_gps['Lat'] >= -90) & (df_jo_gps['Lat'] <= 90) & (df_jo_gps['Lon'] >= -180) & (df_jo_gps['Lon'] <= 180)]

    if df_jo_gps.empty:
        st.info("💡 Nincs megjeleníthető koordináta a térképen.")
        m = folium.Map(location=[47.5316, 21.6273], zoom_start=12)
    else:
        # Sorrend meghatározása
        if 'Sorrend' in df_jo_gps.columns:
            df_jo_gps['Kijelzendo_Sorrend'] = pd.to_numeric(df_jo_gps['Sorrend'], errors='coerce')
        else:
            df_jo_gps['Kijelzendo_Sorrend'] = range(1, len(df_jo_gps) + 1)
            
        df_jo_gps = df_jo_gps.sort_values(by='Kijelzendo_Sorrend')

        # Térkép középpontja
        m = folium.Map(location=[df_jo_gps.iloc[0]['Lat'], df_jo_gps.iloc[0]['Lon']], zoom_start=14)

        # --- SEBÉSZI PONTOSSÁGÚ TÖMBHÁZ CSOPORTOSÍTÁS (SZÖVEGES KOORDINÁTA-PÁR ALAPJÁN) ---
        # Létrehozunk egy kulcsot a nyers, módosítatlan karakterekből, így csak a 100%-ban azonos pontok olvadnak össze
        df_jo_gps['Coord_Key'] = df_jo_gps['Lat'].astype(str) + "_" + df_jo_gps['Lon'].astype(str)
        
        vonal_pontok = []
        utolso_pont = None
        megallok = []
        
        # Csoportosítás a szigorú szöveges kulcs alapján, az útvonal sorrendjét megtartva
        for coord_key, group in df_jo_gps.groupby('Coord_Key', sort=False):
            group = group.sort_values(by='Kijelzendo_Sorrend')
            sorszamok = group['Kijelzendo_Sorrend'].astype(int).tolist()
            
            if len(sorszamok) > 1:
                tol_ig_szoveg = f"{min(sorszamok)}-{max(sorszamok)}"
            else:
                tol_ig_szoveg = str(sorszamok[0])
                
            megallok.append({
                'lat': group.iloc[0]['Lat'],
                'lon': group.iloc[0]['Lon'],
                'tol_ig': tol_ig_szoveg,
                'ugyfelek': group.to_dict('records'),
                'elso_sorszam': min(sorszamok)
            })
            
        # Megállók végső sorrendbe rendezése a menetterv szerint
        megallok = sorted(megallok, key=lambda x: x['elso_sorszam'])
        
        for megallo in megallok:
            aktualis_pont = [megallo['lat'], megallo['lon']]
            if utolso_pont is None or utolso_pont != aktualis_pont:
                vonal_pontok.append(aktualis_pont)
                utolso_pont = aktualis_pont

        # Útvonalvonal (AntPath)
        if len(vonal_pontok) >= 2:
            try:
                folium.plugins.AntPath(
                    locations=vonal_pontok, dash_array=[10, 20], delay=1000,
                    color='#0072ff', pulse_color='#ffffff', weight=5, opacity=0.8
                ).add_to(m)
            except:
                folium.PolyLine(vonal_pontok, color="#0072ff", weight=4, opacity=0.7).add_to(m)

        # Márkerek elhelyezése
        for megallo in megallok:
            cím = megallo['ugyfelek'][0].get('Cím', megallo['ugyfelek'][0].get('Cim', 'Nincs cím'))
            
            popup_html = f"""
            <div style="font-family: Arial, sans-serif; min-width: 210px;">
                <h4 style="margin:0 0 5px 0; color:#0072ff;">📭 Megállópont: {megallo['tol_ig']}</h4>
                <p style="margin:0 0 10px 0; font-size:12px; color:#555;"><b>Cím:</b> {cím}</p>
                <table style="width:100%; border-collapse: collapse; font-size:12px;">
                    <tr style="background:#f0f0f0; font-weight:bold;">
                        <th style="padding:3px; border:1px solid #ddd;">Sor.</th>
                        <th style="padding:3px; border:1px solid #ddd;">Név</th>
                        <th style="padding:3px; border:1px solid #ddd;">ID</th>
                    </tr>
            """
            for u in megallo['ugyfelek']:
                u_nev = u.get('Név', u.get('Nev', u.get('Ügyintéző', 'Ismeretlen')))
                u_sor = int(u['Kijelzendo_Sorrend'])
                popup_html += f"""
                    <tr>
                        <td style="padding:3px; border:1px solid #ddd; text-align:center; font-weight:bold;">{u_sor}</td>
                        <td style="padding:3px; border:1px solid #ddd;">{u_nev}</td>
                        <td style="padding:3px; border:1px solid #ddd; text-align:center; color:#777;">{u['ID']}</td>
                    </tr>
                """
            popup_html += "</table></div>"

            # Dinamikus méretezés a szöveg hosszától függően (ha pl "15-18", szélesebb legyen)
            doboz_szelesseg = "38px" if "-" in megallo['tol_ig'] else "26px"
            
            folium.Marker(
                location=[megallo['lat'], megallo['lon']],
                popup=folium.Popup(popup_html, max_width=350),
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        position: relative;
                        background-color: #0072ff;
                        color: white;
                        border: 2px solid white;
                        border-radius: 13px;
                        width: {doboz_szelesseg};
                        height: 26px;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        font-weight: bold;
                        font-size: 11px;
                        white-space: nowrap;
                        padding: 0 4px;
                        box-shadow: 0px 2px 5px rgba(0,0,0,0.4);
                        transform: translate(-50%, -50%);
                    ">{megallo['tol_ig']}</div>
                    """
                )
            ).add_to(m)

    # Térkép kirajzolása
    from streamlit_folium import st_folium
    st_folium(m, width=700, height=500, returned_objects=[])

    # --- ÁLLANDÓ KOORDINÁTA KARBANTARTÓ PANEL ---
    st.markdown("---")
    st.subheader("🛠️ Ügyfél Koordináták Karbantartása / Javítása")
    
    # 🔴 EGYSZERI ADATBÁZIS NAGYTAKARÍTÓ GOMB (API-KÍMÉLŐ, BATCH UPDATE VERZIÓ)
    with st.expander("⚠️ VESZÉLYES ZÓNA: Google Sheets Adatbázis Formátum Javítása"):
        st.write("Ez a gomb végigmegy a teljes Google Sheets táblázatodon, és az összes elrontott dupla aposztrófos (''47...) koordinátát átalakítja szép, egységes, szóló aposztrófos formátumra – mindezt EGYETLEN API hívással.")
        
        if st.button("🚨 FUTTASD A GOOGLE SHEETS NAGYTAKARÍTÁST"):
            try:
                with st.spinner("⏳ Adatbázis letöltése és elemzése..."):
                    if "gcp_service_account" in st.secrets:
                        creds_dict = dict(st.secrets["gcp_service_account"])
                    else:
                        creds_dict = dict(st.secrets)

                    if "private_key" in creds_dict: 
                        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
                        
                    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                    client = gspread.authorize(creds)

                    sheet = client.open_by_key(SHEET_ID_UGYFELKOR)
                    worksheet = sheet.worksheet("Ugyfelkor")

                    # 1. Beolvassuk az egészet egy nagy listába (1 olvasási API hívás)
                    rows = worksheet.get_all_values()

                    if not rows:
                        st.warning("A táblázat üres!")
                    else:
                        header = rows[0]
                        lat_idx = header.index("Lat") if "Lat" in header else -1
                        lon_idx = header.index("Lon") if "Lon" in header else -1

                        if lat_idx == -1 or lon_idx == -1:
                            st.error("❌ Nem találom a 'Lat' vagy 'Lon' oszlopot a táblázatban!")
                        else:
                            javitott_db = 0
                            frissitando_cellak = []
                            
                            # 2. Végigmegyünk a memóriában lévő adatokon (0 API hívás)
                            for idx, row_data in enumerate(rows[1:], start=2):
                                if len(row_data) <= max(lat_idx, lon_idx):
                                    continue
                                    
                                nyers_lat = str(row_data[lat_idx]).strip()
                                nyers_lon = str(row_data[lon_idx]).strip()
                                
                                uj_lat = None
                                uj_lon = None
                                
                                # Tisztítás meghívása (mivel az app.py tetejére betetted, itt már látni fogja!)
                                tiszta_lat = biztonsagos_koordinata_tisztito(nyers_lat)
                                if tiszta_lat is not None:
                                    uj_lat = f"'{str(tiszta_lat).replace('.', ',')}"
                                        
                                tiszta_lon = biztonsagos_koordinata_tisztito(nyers_lon)
                                if tiszta_lon is not None:
                                    uj_lon = f"'{str(tiszta_lon).replace('.', ',')}"

                                # Ha változott az adat, betesszük a gyűjtőbe a cellát az új értékkel
                                valtozott = False
                                if uj_lat and uj_lat != nyers_lat:
                                    frissitando_cellak.append(gspread.Cell(row=idx, col=lat_idx + 1, value=uj_lat))
                                    valtozott = True
                                if uj_lon and uj_lon != nyers_lon:
                                    frissitando_cellak.append(gspread.Cell(row=idx, col=lon_idx + 1, value=uj_lon))
                                    valtozott = True
                                    
                                if valtozott:
                                    javitott_db += 1

                            # 3. KÖTEGELT FELTÖLTÉS (Összesen 1 darab API hívás!)
                            if frissitando_cellak:
                                with st.spinner(f"⏳ {len(frissitando_cellak)} cella egységesítése a felhőben..."):
                                    worksheet.update_cells(frissitando_cellak, value_input_option='USER_ENTERED')
                                st.success(f"🎉 SIKER! Összesen {javitott_db} ügyfél koordinátája lett javítva és szinkronizálva!")
                            else:
                                st.info("✨ Az adatbázis már teljesen tiszta, nem volt mit javítani!")
                            
                            # Cache törlése, hogy kényszerítsük a friss adatot
                            if 'ugyfelkor_df' in st.session_state:
                                del st.session_state['ugyfelkor_df']
                                
                            # Kis szünet, majd tiszta lappal újraindul az oldal
                            st.rerun()
                            
            except Exception as e:
                st.error(f"Hiba a takarítás során: {e}")
    
    # 🟢 ÚJ LUSTA BETÖLTÉS PAJZS: Ha üres az ügyfélkör (mert még nem olvastunk be PDF-et),
    # akkor közvetlenül a Google Sheets-ből rántjuk le a teljes listát a karbantartáshoz.
    if 'ugyfelkor_df' not in st.session_state or st.session_state.ugyfelkor_df.empty:
        with st.spinner("🔄 Teljes ügyfélkör betöltése a Google Sheets-ből a karbantartáshoz..."):
            try:
                if "gcp_service_account" in st.secrets:
                    creds_dict = dict(st.secrets["gcp_service_account"])
                else:
                    creds_dict = dict(st.secrets)
                if "private_key" in creds_dict: 
                    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
                creds = Credentials.from_service_account_info(creds_dict, scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
                client = gspread.authorize(creds)
                
                sh_ugyfel = client.open_by_key(SHEET_ID_UGYFELKOR)
                ws_ugyfelkor = sh_ugyfel.worksheet("Ugyfelkor")
                
                # 🟢 JAVÍTÁS ITT IS: Kompatibilis beolvasás numeric_mode nélkül
                try:
                    records = ws_ugyfelkor.get_all_records(value_render_option='UNFORMATTED_VALUE')
                except:
                    records = ws_ugyfelkor.get_all_records()
                if records:
                    tisztitott_master = pd.DataFrame(records)
                    tisztitott_master.columns = [c.strip() for c in tisztitott_master.columns]
                    
                    # Alkalmazzuk a golyóálló koordináta tisztítót az Ugyfelkor adatokra
                    if 'Lat' in tisztitott_master.columns:
                        tisztitott_master['Lat'] = tisztitott_master['Lat'].apply(biztonsagos_koordinata_tisztito)
                    if 'Lon' in tisztitott_master.columns:
                        tisztitott_master['Lon'] = tisztitott_master['Lon'].apply(biztonsagos_koordinata_tisztito)
                    
                    st.session_state.ugyfelkor_df = tisztitott_master
            except Exception as e:
                st.error(f"Nem sikerült közvetlenül elérni a Google Sheets ügyfélkört: {e}")

    # Biztosítjuk, hogy a panel az éppen aktuálisan elérhető legnagyobb ügyféllistából dolgozzon
    # (Ha futott PDF, akkor abból, ha nem, akkor a fent letöltött teljes listából)
    if 'ugyfelkor_df' in st.session_state and not st.session_state.ugyfelkor_df.empty:
        df_karbantartas_forras = st.session_state.ugyfelkor_df
    else:
        df_karbantartas_forras = df_valid_gps

    # 🟡 INNENTŐL FOLYTATÓDIK A RÉGI KÓDOD (Csak az első if feltételt írtuk át df_karbantartas_forras-ra):
    if not df_karbantartas_forras.empty:
        df_rendezett_karbantartas = df_karbantartas_forras.copy()
        
        df_rendezett_karbantartas['Karbantarto_Nev'] = df_rendezett_karbantartas.apply(
            lambda r: f"⚠️ [HIÁNYZÓ GPS] {r['ID']} - {r.get('Név', r.get('Nev', r.get('Ügyintéző', 'Ismeretlen')))} ({r.get('Cím', r.get('Cim', 'Nincs cím'))})"
            if pd.isna(r['Lat']) or pd.isna(r['Lon']) or str(r['Lat']).strip() == "" or float(str(r['Lat']).replace("'", "").replace(",", ".").strip()) > 90
            else f"📍 [Térképen van] {r['ID']} - {r.get('Név', r.get('Nev', r.get('Ügyintéző', 'Ismeretlen')))} ({r.get('Cím', r.get('Cim', 'Nincs cím'))})", axis=1
        )
        
        lista_opciok = df_rendezett_karbantartas['Karbantarto_Nev'].tolist()
        kivallasztott = st.selectbox("Válaszd ki a javítani vagy pótolni kívánt ügyfelet:", lista_opciok)
        
        if kivallasztott:
            kiv_id = kivallasztott.split("] ")[1].split(" - ")[0].strip()
            
            # 🟢 JAVÍTÁS: Különválasztjuk a szűrést az elem lekérésétől
            talalatok = df_karbantartas_forras[df_karbantartas_forras['ID'] == kiv_id]
            
            if not talalatok.empty:
                kiv_sor = talalatok.iloc[0]
                aktualis_cim = kiv_sor.get('Cím', kiv_sor.get('Cim', 'Nincs cím'))
                aktualis_nev = kiv_sor.get('Név', kiv_sor.get('Nev', kiv_sor.get('Ügyintéző', 'Ismeretlen')))
            else:
                # 🟢 Biztonsági védőháló: ha a nagytakarítás miatt épp üres a cache
                st.warning("⚠️ A kiválasztott ügyfél adatai frissülnek. Kérjük, válassz ki egy ügyfelet újra a listából!")
                aktualis_cim = "Frissítés alatt..."
                aktualis_nev = "Frissítés alatt..."

            # 🟢 INNEN JÖN AZ ÚJ GOLYÓÁLLÓ BLOKK AZ UNBOUNDLOCALERROR ELLEN:
            if 'kiv_sor' in locals() and kiv_sor is not None:
                # Ha a kiv_sor egy Pandas Series, átalakítjuk sima szótárrá a biztonság kedvéért
                sor_dict = kiv_sor.to_dict() if hasattr(kiv_sor, 'to_dict') else dict(kiv_sor)
                
                biztonsagos_lat = sor_dict.get('Lat', 'Nincs adat')
                biztonsagos_lon = sor_dict.get('Lon', 'Nincs adat')
                
                # Ha az érték üres vagy NaN, akkor is 'Nincs adat'-ot írunk ki
                if pd.isna(biztonsagos_lat) or str(biztonsagos_lat).strip() == "": biztonsagos_lat = 'Nincs adat'
                if pd.isna(biztonsagos_lon) or str(biztonsagos_lon).strip() == "": biztonsagos_lon = 'Nincs adat'
                
                st.info(f"**Kiválasztva:** {aktualis_nev}\n* **Cím:** {aktualis_cim}\n* **Jelenlegi GPS:** Lat: `{biztonsagos_lat}`, Lon: `{biztonsagos_lon}`")
            else:
                biztonsagos_lat = "Nincs adat"
                biztonsagos_lon = "Nincs adat"
            
            form_col, map_col = st.columns([1.2, 1])
            
            with form_col:
                # 🟢 DEDIKÁLT KOORDINÁTA-KARBANTARTÓ VERZIÓ (CSAK LAT/LON)
                biztonsagos_lat = kiv_sor.get('Lat', 'Nincs adat') if isinstance(kiv_sor, dict) or hasattr(kiv_sor, 'get') else getattr(kiv_sor, 'Lat', 'Nincs adat')
                biztonsagos_lon = kiv_sor.get('Lon', 'Nincs adat') if isinstance(kiv_sor, dict) or hasattr(kiv_sor, 'get') else getattr(kiv_sor, 'Lon', 'Nincs adat')
                
                st.info(f"**Kiválasztva:** {aktualis_nev}\n* **Cím:** {aktualis_cim}\n* **Jelenlegi GPS:** Lat: `{biztonsagos_lat}`, Lon: `{biztonsagos_lon}`")
                
                with st.form("gps_javito_form_vegleges", clear_on_submit=False):
                    # Alapértelmezett érték előkészítése a mezőbe
                    akt_lat = str(biztonsagos_lat).replace("'", "").strip() if biztonsagos_lat != 'Nincs adat' else ""
                    akt_lon = str(biztonsagos_lon).replace("'", "").strip() if biztonsagos_lon != 'Nincs adat' else ""
                    
                    try:
                        valid_lat_test = float(akt_lat.replace(",", "."))
                        if valid_lat_test > 90: alap_ertek = ""
                        else: alap_ertek = f"{akt_lat}, {akt_lon}" if akt_lat and akt_lon else ""
                    except:
                        alap_ertek = ""
                    
                    st.markdown("**Másold be a Google Maps-ről kapott értéket egyben:**")
                    egyben_koordinata = st.text_input("Koordináták (Lat, Lon)", value=alap_ertek, placeholder="Pl: 47.530773, 21.625137")
                    submit = st.form_submit_button("💾 Koordináták mentése és Google Sheets frissítése")
                    
                    if submit:
                        if egyben_koordinata.strip():
                            try:
                                # Formátum ellenőrzése (vesszős vagy szóközös elválasztás)
                                if "," in egyben_koordinata:
                                    reszek = egyben_koordinata.split(",")
                                    nyers_lat, nyers_lon = reszek[0].strip(), reszek[1].strip()
                                else:
                                    reszek = egyben_koordinata.split()
                                    if len(reszek) >= 2:
                                        nyers_lat, nyers_lon = reszek[0].strip(), reszek[1].strip()
                                    else:
                                        st.error("❌ Nem felismerhető koordináta formátum!")
                                        st.stop()
                                
                                # Tisztítás és tiszta FLOAT-tá alakítás
                                clean_lat = nyers_lat.replace("'", "").replace('"', '').replace(",", ".").strip()
                                clean_lon = nyers_lon.replace("'", "").replace('"', '').replace(",", ".").strip()
                                
                                # 🎯 Tiszta szám formátum, 6 tizedesjegyre kerekítve (NINCS APOSZTRÓF, NINCS VESSZŐ!)
                                f_lat = round(float(clean_lat), 6)
                                f_lon = round(float(clean_lon), 6)
                                
                                sh = client.open_by_key(sheet_id)
                                ws = sh.worksheet("Ugyfelkor")
                                
                                # Oszlopok dinamikus megkeresése név alapján
                                fejlec = ws.row_values(1)
                                lat_idx = fejlec.index("Lat") + 1 if "Lat" in fejlec else 4
                                lon_idx = fejlec.index("Lon") + 1 if "Lon" in fejlec else 5
                                
                                cell = ws.find(str(kiv_id))
                                if cell:
                                    # Cellák frissítése tiszta számként a Sheets-ben
                                    ws.update_cell(cell.row, lat_idx, f_lat)
                                    ws.update_cell(cell.row, lon_idx, f_lon)
                                    
                                    # Ha van Utolsó_Rendelés oszlop, frissítjük a dátumot is
                                    if "Utolso_Rendeles" in fejlec:
                                        utolso_idx = fejlec.index("Utolso_Rendeles") + 1
                                        from datetime import datetime
                                        ws.update_cell(cell.row, utolso_idx, datetime.now().strftime('%Y.%m.%d'))
                                    
                                    # 🔥 LOKÁLIS MEMÓRIA AZONNALI UPGRADE-ELÉSE
                                    # Így a térkép azonnal átugrik a jó helyre, nem kell megvárni a cache lejártát
                                    for session_key in ['ugyfelkor_df', 'mdf', 'master_ugyfelkor_df']:
                                        if session_key in st.session_state and st.session_state[session_key] is not None:
                                            try:
                                                df = st.session_state[session_key]
                                                if not df.empty and 'ID' in df.columns:
                                                    df.loc[df['ID'].astype(str) == str(kiv_id), 'Lat'] = f_lat
                                                    df.loc[df['ID'].astype(str) == str(kiv_id), 'Lon'] = f_lon
                                            except Exception as mem_err:
                                                pass

                                    # Biztonsági cache takarítás
                                    if 'google_data_loaded' in st.session_state:
                                        del st.session_state['google_data_loaded']
                                        
                                    st.success(f"✅ Siker! {aktualis_nev} új koordinátái elmentve és a rendszer azonnal frissítve!")
                                    st.rerun()
                                else:
                                    st.error("❌ Hiba: Az ügyfél ID nem található a törzslistában!")
                            except ValueError:
                                st.error("❌ Érvénytelen számformátum a koordinátában!")
                            except Exception as save_err:
                                st.error(f"❌ Mentési hiba lépett fel: {save_err}")
                        else:
                            st.warning("⚠️ Kérlek, adj meg koordinátákat a mentés előtt!")
            
            with map_col:
                st.write("🗺️ **Beágyazott Google Maps segédablak:**")
                import urllib.parse
                biztonsagos_cim = urllib.parse.quote(str(aktualis_cim))
                maps_url = f"https://maps.google.com/maps?q={biztonsagos_cim}&t=&z=16&ie=UTF8&iwloc=&output=embed"
                st.components.v1.iframe(maps_url, height=260, scrolling=True)
                
def get_google_sheets_creds():
    creds_info = st.secrets["gcp_service_account"].to_dict()
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if "private_key" in creds_info:
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
    return service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)

# Most próbáljuk meg feltölteni az igazi kapcsolattal
try:
    creds = get_google_sheets_creds()
    client = gspread.authorize(creds)
except Exception as e:
    st.error(f"Sikertelen Google Sheets kapcsolódás: {e}")
    client = None

def extract_all_meta(pdf_files):
    all_meta = {'jaratok': [], 'ev': '', 'het': '', 'nap': '', 'datum_iso': '', 'api_datum_kulcs': ''}
    
    jarat_re = re.compile(r'(\d{2,4})\.\s*járat|Nyomtatta:\s*(\d{2,4})')
    
    for uploaded_file in pdf_files:
        uploaded_file.seek(0) 
        with pdfplumber.open(uploaded_file) as pdf:
            text = pdf.pages[0].extract_text() or ""
            
            # 1. Járatszámok gyűjtése
            for match in jarat_re.finditer(text):
                j_num = match.group(1) or match.group(2)
                if j_num and j_num not in all_meta['jaratok']:
                    all_meta['jaratok'].append(j_num)
            
            # 2. Dátum infók - Csak ha még üresek
            if not all_meta['ev']:
                ev_m = re.search(r'Év:\s*(\d{4})', text)
                if ev_m: all_meta['ev'] = ev_m.group(1)

            if not all_meta['het']:
                het_m = re.search(r'Hét:\s*(\d{1,2})', text)
                if het_m: all_meta['het'] = het_m.group(1)

            # 3. A NAPOK kinyerése
            if not all_meta['nap']:
                nap_m = re.search(r'Nap:\s*(.*?)(?=InterFood|$)', text, re.DOTALL)
                if nap_m:
                    nap_raw = nap_m.group(1).strip()
                    all_meta['nap'] = nap_raw.rstrip(',')
    
    all_meta['jaratok'].sort()
    
    # --- DÁTUM KISZÁMÍTÁSA FIXEN AZ ÉV, HÉT ÉS NAP ALAPJÁN ---
    if all_meta['ev'] and all_meta['het'] and all_meta['nap']:
        try:
            nap_tisztitott = all_meta['nap'].lower().strip()
            nap_szamok = {
                'hetfo': 1, 'hétfő': 1,
                'kedd': 2,
                'szerda': 3,
                'csutortok': 4, 'csütörtök': 4,
                'pente': 5, 'pénte': 5, 'pentek': 5, 'péntek': 5,
                'szombat': 6,
                'vasarnap': 7, 'vasárnap': 7
            }
            
            nap_szoveg_kulcs = next((k for k in nap_szamok if k in nap_tisztitott), None)
            
            if nap_szoveg_kulcs:
                nap_szama = nap_szamok[nap_szoveg_kulcs]
                target_year = int(all_meta['ev'])
                target_week = int(all_meta['het'])
                
                # Kiszámoljuk a pontos naptári napot az ISO év és hét alapján (%G-%V-%u)
                kalkulalt_datum = datetime.strptime(f"{target_year}-{target_week}-{nap_szama}", "%G-%V-%u")
                
                # Mentjük a megfelelő változókba a meta szótáron belül
                all_meta['datum_iso'] = kalkulalt_datum.strftime("%Y-%m-%d")
                all_meta['api_datum_kulcs'] = kalkulalt_datum.strftime("%Y.%m.%d.")
        except Exception as e:
            pass

    return all_meta

def render_logisztikai_kozpont(sheet):
    st.title("🚚 Logisztikai és Pénzügyi Vezérlőpult")
    st.caption("Központi adminisztráció, standolás, munkaidő és automatizált teljesítmény-ellenőrzés.")
    
    # 🌟 KIBŐVÍTETT FÜLEK (3 helyett most már 5 fülünk van)
    tabs = st.tabs([
        "⚠️ Élő Hibák & Eltérések", 
        "💰 Futár Stand & Elszámolás", 
        "⏱️ Munkaidő Figyelő",
        "🚗 Automata KM Kontroll",
        "📊 Statisztikai Központ & Legek"
    ])
    
    # =========================================================================
    # 1. TAB: ÉLŐ HIBÁK ÉS ELTÉRÉSEK
    # =========================================================================
    with tabs[0]:
        st.subheader("Napközbeni sérülések, hiányok és jóváírások")
        try:
            hibak_sheet = sheet.worksheet("Logisztikai_Hibak")
            hibak_data = hibak_sheet.get_all_records()
            if hibak_data:
                df_hibak = pd.DataFrame(hibak_data)
                if 'Admin_Státusz' in df_hibak.columns:
                    df_hibak['Admin_Státusz'] = df_hibak['Admin_Státusz'].fillna('Feldolgozatlan')
                else:
                    df_hibak['Admin_Státusz'] = 'Feldolgozatlan'
                aktiv_hibak = df_hibak[df_hibak['Admin_Státusz'] == 'Feldolgozatlan']
                
                if not aktiv_hibak.empty:
                    st.error(f"Figyelem! {len(aktiv_hibak)} feldolgozatlan logisztikai hiba van folyamatban!")
                    st.dataframe(
                        aktiv_hibak[['Időbélyeg', 'Járat_ID', 'Ügyfél Neve', 'Cikkszám', 'Étel Neve', 'Mennyiség', 'Összérték', 'Hiba Típusa']],
                        use_container_width=True, hide_index=True
                    )
                    st.write("---")
                    valasztott_sor = st.selectbox("Válaszd ki a feldolgozott ügyfelet:", aktiv_hibak['Ügyfél Neve'].unique())
                    if st.button(f"✅ {valasztott_sor} hibájának lezárása (Jóváírva)"):
                        for idx, row in enumerate(hibak_data):
                            if row['Ügyfél Neve'] == valasztott_sor and row.get('Admin_Státusz', 'Feldolgozatlan') == 'Feldolgozatlan':
                                hibak_sheet.update_cell(idx + 2, 11, "Jóváírva")
                                st.success(f"{valasztott_sor} státusza sikeresen frissítve!")
                                st.rerun()
                else:
                    st.success("Minden logisztikai hiba fel van dolgozva! ✅")
            else:
                st.info("A logisztikai hibalista jelenleg üres.")
        except Exception as e:
            st.warning(f"A Logisztikai_Hibak fül nem elérhető vagy üres: {e}")

    # =========================================================================
    # 2. TAB: RÉSZLETEZETT FUTÁR STAND (Ügyviteli rendszer kompatibilis)
    # =========================================================================
    with tabs[1]:
        st.subheader("Napi pénzügyi stand járatok szerint")
        
        try:
            adatok_sheet = sheet.worksheet("Adatok")
            adatok_data = adatok_sheet.get_all_records()
            df_adatok = pd.DataFrame(adatok_data)
            
            if not df_adatok.empty:
                df_adatok.columns = [c.strip() for c in df_adatok.columns]
                df_adatok['Fizetendő'] = pd.to_numeric(df_adatok['Fizetendő'], errors='coerce').fillna(0)
                
                jaratok = [j for j in df_adatok['Járat'].unique() if str(j).strip() != ""]
                valasztott_jarat = st.selectbox("Válassz járatot a standoláshoz:", jaratok)
                
                if valasztott_jarat:
                    df_jarat = df_adatok[df_adatok['Járat'] == valasztott_jarat]
                    
                    stand_kp = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'KÉSZPÉNZ']['Fizetendő'].sum()
                    stand_kartya = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'BANKKÁRTYA']['Fizetendő'].sum()
                    stand_szep = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'SZÉP KÁRTYA']['Fizetendő'].sum()
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("💵 Leadandó Készpénz", f"{int(stand_kp):,} Ft".replace(",", " "))
                    col2.metric("💳 Bankkártya bizonylat", f"{int(stand_kartya):,} Ft".replace(",", " "))
                    col3.metric("🌸 SZÉP Kártya bizonylat", f"{int(stand_szep):,} Ft".replace(",", " "))
                    
                    st.write("---")
                    st.markdown(f"### 📋 Ügyviteli pipáló lista – {valasztott_jarat} járat")
                    st.caption("A lenti listák sorrendje és összegei megegyeznek azzal, amit a futár lát a telefonján és amit az ügyviteli szoftverben kell kipipálni.")
                    
                    st.markdown("#### 💵 KÉSZPÉNZES ÜGYFELEK (Kipipálandó az ügyviteli rendszerben):")
                    df_kp_list = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'KÉSZPÉNZ']
                    
                    if not df_kp_list.empty:
                        megjelenit_kp = df_kp_list[['ID', 'Név', 'Cím', 'Fizetendő', 'Státusz']].copy()
                        megjelenit_kp['Fizetendő'] = megjelenit_kp['Fizetendő'].apply(lambda x: f"{int(x)} Ft")
                        
                        st.dataframe(
                            megjelenit_kp,
                            column_config={
                                "ID": "Ügyfélkód",
                                "Név": "Ügyfél Neve",
                                "Cím": "Szállítási Cím",
                                "Fizetendő": "Beszedett Összeg",
                                "Státusz": "Futár Státusz"
                            },
                            use_container_width=True, hide_index=True
                        )
                        st.markdown(f"**Készpénzes tételek összesen: {len(df_kp_list)} db ügyfél | Végösszeg: {int(stand_kp):,} Ft**".replace(",", " "))
                    else:
                        st.info("Ezen a járaton nincs készpénzes beszedés.")
                        
                    st.write(" ")
                    st.markdown("#### 💳 BANKKÁRTYÁS ÜGYFELEK (Bizonylatok ellenőrzéséhez):")
                    df_cc_list = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'BANKKÁRTYA']
                    if not df_cc_list.empty:
                        megjelenit_cc = df_cc_list[['ID', 'Név', 'Fizetendő', 'Státusz']].copy()
                        megjelenit_cc['Fizetendő'] = megjelenit_cc['Fizetendő'].apply(lambda x: f"{int(x)} Ft")
                        st.dataframe(megjelenit_cc, use_container_width=True, hide_index=True)
                    else:
                        st.caption("Nincs bankkártyás tétel.")
            else:
                st.info("Nincsenek szállítási adatok az Adatok munkalapon.")
        except Exception as e:
            st.error(f"Hiba a stand adatok beolvasásakor: {e}")

    # =========================================================================
    # 3. TAB: MUNKAIDŐ FIGYELŐ
    # =========================================================================
    with tabs[2]:
        st.subheader("Futárok napi időbélyegei és áruátvételi idői")
        try:
            idok_sheet = sheet.worksheet("Mobil_Idobelyegek")
            idok_data = idok_sheet.get_all_records()
            if idok_data:
                df_idok = pd.DataFrame(idok_data)
                percek = []
                for _, row in df_idok.iterrows():
                    try:
                        fmt = "%H:%M:%S"
                        if row.get('Áruátvétel_Start') and row.get('Áruátvétel_End'):
                            from datetime import datetime
                            start = datetime.strptime(str(row['Áruátvétel_Start']).strip(), fmt)
                            end = datetime.strptime(str(row['Áruátvétel_End']).strip(), fmt)
                            kulonbseg = (end - start).seconds // 60
                            percek.append(f"{kulonbseg} perc")
                        else:
                            percek.append("Folyamatban...")
                    except:
                        percek.append("N/A")
                df_idok['Áruátvételi Idő'] = percek
                st.dataframe(df_idok, use_container_width=True, hide_index=True)
            else:
                st.info("Még nincsenek rögzített időbélyegek.")
        except Exception as e:
            st.warning(f"A Mobil_Idobelyegek fül még üres: {e}")

    # =========================================================================
    # 🟢 4. TAB: AUTOMATA KM KONTROLL (Csalásbiztos modul)
    # =========================================================================
    with tabs[3]:
        st.subheader("🚗 Automatizált Futásteljesítmény Ellenőrzés")
        st.markdown("""
        *Ez a modul a mobil terminál által visszaküldött leadási sorrend és a címek GPS koordinátái alapján automatikusan számolja a futásteljesítményt.*
        **Nincs szükség futár általi km-óra bemondásra – a rendszer a valóságot méri.**
        """)
        
        # Előkészített adatstruktúra a jövő heti teszthez
        km_teszt_adat = {
            "Futár": ["Te (Teszt Üzemmód)"],
            "Járat": ["Észlelt aktív járat"],
            "Címek száma": [len(df_adatok) if 'df_adatok' in locals() and not df_adatok.empty else 0],
            "Ténylegesen bejárt sorrend": ["Optimalizált (Mobil GPS / Időbélyeg szerint)"],
            "Szoftveres Útvonalhossz": ["Számítás alatt... (Jövő héten indul)"],
            "Státusz": ["🔄 Várakozás az első mobil terminálos lezárásra"]
        }
        st.dataframe(pd.DataFrame(km_teszt_adat), use_container_width=True, hide_index=True)
        
        st.info("💡 **Hogyan fog működni?** Amint a mobilodon elkezded kiszállítani a címeket, a rendszer rögzíti, hogy milyen sorrendben nyomtál rájuk. Ebből a modul (háttérben futó távolságmátrixszal) méterre pontosan rekonstruálja a megtett utat, kiküszöbölve a kézi trükközéseket.")

    # =========================================================================
    # 🟢 5. TAB: STATISZTIKAI KÖZPONT & LEGEK
    # =========================================================================
    with tabs[4]:
        st.subheader("📊 Vezetői Kimutatások & Futár Legek")
        st.markdown("Az adatok forrása: az **'Adatok'** munkalap történelmi szállítási és pénzügyi bejegyzései.")
        
        st.warning("📉 **Adatgyűjtés folyamatban:** Mivel a tesztüzem jövő héten indul, a grafikonok jelenleg mintaként illusztrálják a jövőbeli felületet.")
        
        # Vizualizációs helyőrzők
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.markdown("#### 🏆 Top Futárok (Kiszállított címek alapján)")
            demo_top_data = pd.DataFrame({
                'Futár': ['Futár Alajos', 'Futár Béla', 'Te (Előrejelzés)'],
                'Címek': [42, 38, 55]
            }).set_index('Futár')
            st.bar_chart(demo_top_data)
            st.caption("Ki teljesítette a legtöbb címet a kiválasztott időszakban?")

        with chart_col2:
            st.markdown("#### 💸 Napi Pénzügyi Volumenek (Forgalom alakulása)")
            demo_trend_data = pd.DataFrame({
                'Nap': ['Hétfő', 'Kedd', 'Szerda', 'Csütörtök', 'Péntek'],
                'Összforgalom (Ft)': [120000, 145000, 138000, 162000, 195000]
            }).set_index('Nap')
            st.line_chart(demo_trend_data)
            st.caption("A logisztika által mozgatott napi készpénz és kártyás forgalom trendje.")

        st.write("---")
        st.markdown("### 🔍 Gazdaságossági és 'Leggyengébb láncszem' Figyelő")
        
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric(label="Legjövedelmezőbb Járat", value="4002-es járat", delta="+12% forgalom")
        metric_col2.metric(label="Legtöbb Hibát Generáló Kör", value="3001-es kör", delta="5 hiba/hét", delta_color="inverse")
        metric_col3.metric(label="Legoptimálisabb Km/Cím arány", value="1.2 km / cím", delta="-0.4 km megtakarítás")
        
        st.info("☝️ **Vezetői döntéstámogatás:** Amint feltöltődik a Sheets történelmi adatokkal, azonnal látni fogod, ha egy járat üzemanyag- vagy időarányosan veszteségessé válik (pl. túl sokat kell autózni túl kevés címért), így azonnal be tudsz avatkozni a járatok átszervezésébe.")

def sync_interfood_etlap(year, week, sheet_id):
    api_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 🟢 ÚJ KVÓTAVÉDELMI PAJZS: Ha ebben a munkamenetben ez a hét már le lett szinkronizálva, 
    # ne terheljük a Google-t és az Interfood API-t, ugorjuk át!
    cache_key = f"sync_done_{year}_{week}"
    if st.session_state.get(cache_key, False):
        logging.info(f"Interfood étlap szinkron ({year}/W{week}) ebből a munkamenetből már megvolt, átugrás.")
        return True
    
    try:
        # 1. LÉPÉS: Letöltés megkísérlése
        st.info(f"Kapcsolódás az API-hoz: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            st.error(f"Az API hiba kódot küldött: {response.status_code}")
            st.stop()
            return False

        # 2. LÉPÉS: Tartalom ellenőrzése
        content = response.content
        if len(content) < 100:
            st.error("Az API válasza túl rövid, valószínűleg nem egy Excel fájlt kaptunk.")
            st.stop()
            return False

        # 3. LÉPÉS: Excel feldolgozás
        try:
            df = pd.read_excel(BytesIO(content))
        except Exception as ex_err:
            st.error(f"Excel beolvasási hiba: {ex_err}")
            st.write("A kapott válasz eleje (nyers):", content[:100])
            st.stop()
            return False

        # 4. LÉPÉS: Google Sheets feltöltés
        # Hitelesítés javítása, hogy golyóálló legyen
        if "gcp_service_account" in st.secrets:
            creds_info = dict(st.secrets["gcp_service_account"])
        else:
            creds_info = dict(st.secrets)
            
        if "private_key" in creds_info:
            creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
            
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        
        from google.oauth2 import service_account
        import gspread
        from gspread_dataframe import set_with_dataframe
        
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        
        # 🛡️ Itt történt a 429-es hiba a Google túlterhelése miatt:
        sheet = client.open_by_key(sheet_id)
        
        try:
            worksheet = sheet.worksheet("Etlap_API")
        except:
            worksheet = sheet.add_worksheet(title="Etlap_API", rows="1000", cols="20")
            
        worksheet.clear()
        set_with_dataframe(worksheet, df)
        
        # 🟢 SIKER: Elmentjük a memóriába, hogy többször ne fusson le feleslegesen!
        st.session_state[cache_key] = True
        
        st.toast(f"Sikeres szinkron: {year}/W{week}", icon="✅")
        return True
        
    except gspread.exceptions.APIError as api_err:
        # 🛡️ HA A GOOGLE LEZÁRTA A CSAPOT (429), ELKAPJUK ÉS NEM ENGEDJÜK ÖSSZEOMLANI AZ APP-OT
        if "Quota exceeded" in str(api_err):
            st.warning(f"⚠️ Google Sheets hívási limit túllépve (429). A szinkronizálást most átugorjuk, de az app megy tovább!")
            return True
        raise api_err # Ha más típusú Google hiba, akkor engedjük tovább a hibakezelőre
        
    except Exception as e:
        # 1. Piros hibaüzenet kiírása
        st.error(f"❌ KRITIKUS HIBA TÖRTÉNT!")
        
        # 2. Részletes technikai adatok megjelenítése
        with st.expander("Kattints ide a részletes hibaadatokért"):
            st.write(f"Hiba típusa: {type(e).__name__}")
            st.write(f"Üzenet: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
        
        # 3. STOP - Itt megáll az élet, lesz időd másolni
        st.warning("A program futása megállt a hiba miatt. Másold ki a fenti adatokat!")
        st.stop()

def load_etlap_from_sheets(sheet_id):
    """
    Beolvassa a Google Sheets 'Etlap_API' fülét (árak és nevek)
    valamint az új 'Etlap' fülét (fix kategóriák és konyhai sorrend),
    majd mindkettőt elmenti a munkamenetbe.
    """
    try:
        # 1. Kapcsolódás a Sheets-hez
        creds_info = st.secrets["gcp_service_account"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        
        from google.oauth2 import service_account
        import gspread
        
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        
        # =========================================================================
        # VADÚJ RÉSZ: Az 'Etlap' fül beolvasása (Kategóriák és Konyhai Sorrend)
        # =========================================================================
        kategoria_index = {}
        try:
            kat_worksheet = sheet.worksheet("Etlap")
            # Beolvassuk az összes sort szótárként (figyelembe veszi az oszlopneveket!)
            kat_data = kat_worksheet.get_all_records()
            
            for row in kat_data:
                # Tisztítjuk a cikkszámot (pl. "SP1")
                cikkszam = str(row.get('Cikkszam', '')).strip().upper()
                if cikkszam:
                    # Kinyerjük a sorrendet számmá alakítva
                    sorrend_nyers = str(row.get('Konyha_Sorrend', '99')).strip()
                    sorrend_szam = int(sorrend_nyers) if sorrend_nyers.isdigit() else 99
                    
                    kategoria_index[cikkszam] = {
                        "kategoria": row.get('Kategoria', 'Egyéb / Zóna ételek'),
                        "sorrend": sorrend_szam
                    }
            # Elmentjük a globális memóriába, hogy a raklista PDF és a Mobil app is elérje
            st.session_state['kategoria_adatok'] = kategoria_index
        except Exception as kat_err:
            st.warning(f"Az 'Etlap' munkalap (kategóriák) beolvasása sikertelen, de az árakat betöltöm. Hiba: {kat_err}")
            st.session_state['kategoria_adatok'] = {}

        # =========================================================================
        # EREDETI RÉSZ: Az 'Etlap_API' fül beolvasása (Napok szerinti Étlap és Árak)
        # =========================================================================
        worksheet = sheet.worksheet("Etlap_API")
        data = worksheet.get_all_values()
        df = pd.DataFrame(data)
        
        etlap_index = {}
        
        for i in range(len(df)):
            elso_cella = str(df.iloc[i, 0]).strip()
            
            if " - " in elso_cella:
                kod = elso_cella.split(" - ")[0].strip()
                
                for nap_idx in range(1, 7):
                    nev = str(df.iloc[i, nap_idx]).strip()
                    
                    ar = ""
                    if i + 1 < len(df):
                        ar = str(df.iloc[i + 1, nap_idx]).strip()
                    
                    if nev and nev.lower() != "nan" and nev != "":
                        kulcs = f"{nap_idx}_{kod}"
                        etlap_index[kulcs] = {
                            "nev": nev,
                            "ar": ar
                        }
        
        return etlap_index
        
    except Exception as e:
        st.error(f"Hiba az étlap beolvasásakor a Sheets-ből: {e}")
        return {}

def clean_text(text):
    """Eltávolítja a speciális karaktereket, szóközöket és ékezeteket az összehasonlításhoz."""
    if not text or str(text).lower() == "nan": return ""
    # Ékezetek eltávolítása (pl. á -> a)
    text = "".join(c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn')
    # Csak betűk és számok megtartása, kisbetűssé alakítás, szóközök törlése
    text = re.sub(r'[^a-zA-Z0-9]', '', text).lower()
    return text

def load_futar_from_sheets(sheet_id):
    """Betölti a futárok adatait a Google Sheet 'Futárok' lapjáról."""
    try:
        sheet = client.open_by_key(sheet_id).worksheet("Futárok")
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        logger.error(f"Hiba a futárok betöltésekor: {e}")
        return pd.DataFrame()

def save_futar_to_sheets(df, sheet_id):
    """Visszamenti a módosított futár adatokat a Google Sheet 'Futárok' lapjára."""
    try:
        sheet = client.open_by_key(sheet_id).worksheet("Futárok")
        sheet.clear()
        # Az adatok visszaírása
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        return True
    except Exception as e:
        logger.error(f"Hiba a futárok mentésekor: {e}")
        return False

def sync_master_database(sheet_id, ev, start_het, end_het):
    """
    Végigfut a heteken, beolvassa a meglévő Master adatokat, 
    és csak az új ételeket fűzi hozzá, megőrizve a korábbi kellékeket.
    """
    try:
        # Kapcsolódás (a meglévő logikád)
        creds_info = st.secrets["gcp_service_account"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        from google.oauth2 import service_account
        import gspread
        
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        
        try:
            worksheet = sheet.worksheet("Master_Adatbazis")
            # 1. LÉPÉS: Beolvassuk a MÁR MEGLÉVŐ adatokat a Sheet-ről
            existing_data = worksheet.get_all_records()
            # Szótárba rendezzük a meglévőket a 'Tisztított Név' alapján
            master_dict = {
                str(row['Tisztított Név']): {
                    "Eredeti Név": row.get('Eredeti Név', ''),
                    "KodAr_List": str(row.get('Kódok és Árak', '')).split(", ") if row.get('Kódok és Árak') else [],
                    "Kellék": row.get('Kellék', ''),
                    "Gyakoriság": int(row.get('Gyakoriság', 1))
                } for row in existing_data if row.get('Tisztított Név')
            }
            st.info(f"ℹ️ Meglévő adatbázis betöltve: {len(master_dict)} étel.")
        except Exception as e:
            # Ha nincs még ilyen fül, létrehozzuk
            worksheet = sheet.add_worksheet(title="Master_Adatbazis", rows="5000", cols="10")
            master_dict = {}
            st.info("ℹ️ Új Master_Adatbazis fül létrehozva.")

        # 2. LÉPÉS: Új adatok begyűjtése az API-ból
        for het in range(start_het, end_het + 1):
            st.write(f"🔄 {ev}/{het}. hét feldolgozása...")
            url = f"https://ia.interfood.hu/api/v3/excel-export?year={ev}&week={het}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                df = pd.read_excel(BytesIO(response.content), header=None, engine='openpyxl')
                
                for i in range(len(df)):
                    elso_cella = str(df.iloc[i, 0]).strip()
                    if " - " in elso_cella:
                        alap_kod = elso_cella.split(" - ")[0].strip()
                        
                        for nap_idx in range(1, 7):
                            eredeti_nev = str(df.iloc[i, nap_idx]).strip()
                            tiszta_nev = clean_text(eredeti_nev)
                            
                            if tiszta_nev and tiszta_nev != "":
                                ar = ""
                                if i + 1 < len(df):
                                    ar = str(df.iloc[i + 1, nap_idx]).strip().replace('Ft', '').replace(' ', '')
                                
                                kod_ar_par = f"{alap_kod}:{ar} (w{het})"
                                
                                if tiszta_nev in master_dict:
                                    # HA MÁR MEG VAN: Csak a gyakoriságot és esetleg az új kódot adjuk hozzá
                                    master_dict[tiszta_nev]['Gyakoriság'] += 1
                                    if kod_ar_par not in master_dict[tiszta_nev]['KodAr_List']:
                                        master_dict[tiszta_nev]['KodAr_List'].append(kod_ar_par)
                                    # A 'Kellék' oszlophoz NEM NYÚLUNK, megmarad ami benne volt!
                                else:
                                    # HA ÚJ: Létrehozzuk az új bejegyzést
                                    master_dict[tiszta_nev] = {
                                        "Eredeti Név": eredeti_nev.replace('*', '').strip(),
                                        "KodAr_List": [kod_ar_par],
                                        "Kellék": "",
                                        "Gyakoriság": 1
                                    }
            else:
                st.warning(f"Nem sikerült letölteni: {ev}/{het}")

        # 3. LÉPÉS: Az összesített (régi + új) adatok visszaírása
        output_rows = [["Tisztított Név", "Eredeti Név", "Kódok és Árak", "Kellék", "Gyakoriság"]]
        for tiszta, adat in master_dict.items():
            output_rows.append([
                tiszta,
                adat["Eredeti Név"],
                ", ".join(adat["KodAr_List"]),
                adat["Kellék"],
                adat["Gyakoriság"]
            ])
            
        worksheet.clear()
        worksheet.update('A1', output_rows)
        st.success(f"✅ Master Adatbázis frissítve! Összesen {len(master_dict)} egyedi étel található.")
        
    except Exception as e:
        st.error(f"Hiba a Master szinkron során: {e}")

# --- 1. AZ OKOS NÉV-MEMÓRIA BETÖLTÉSE (FRISSÍTVE: SHEET-ALAPÚ ÉS CACHE-MENTES) ---

def load_all_names(sheet_df):
    """
    A Google Sheet-ből betöltött nevekből (Családnév, Keresztnév oszlopok) 
    felépíti a felismeréshez szükséges adatbázist.
    """
    all_names = set()
    titulusok = {"Dr.", "id.", "ifj.", "özv.", "dr.", "vitéz"}
    all_names.update(titulusok)
    
    if sheet_df is not None:
        # Családnevek begyűjtése
        if 'Családnév' in sheet_df.columns:
            csalad_nevek = sheet_df['Családnév'].dropna().unique()
            all_names.update([str(n).strip() for n in csalad_nevek if str(n).strip()])
            
        # Keresztnevek begyűjtése (férfi és női vegyesen)
        if 'Keresztnév' in sheet_df.columns:
            kereszt_nevek = sheet_df['Keresztnév'].dropna().unique()
            for n in kereszt_nevek:
                nev = str(n).strip()
                if nev:
                    all_names.add(nev)
                    # Automatikus -né képzés minden keresztnévre (biztonsági játék)
                    all_names.add(nev + "né")
    
    return all_names

# Használat a fő logikában:
# Amikor beolvasod a neveket tartalmazó Google Sheet-et (legyen a neve pl. names_df):
# NAME_DB = load_all_names(names_df)

# --- 2. NÉV ÉS MEGJEGYZÉS SZÉTVÁLASZTÁSA ---
def split_name_logic(raw_text):
    words = raw_text.split()
    name_parts = []
    comment_parts = []
    is_name_part = True
    
    for word in words:
        clean = word.strip(",./-")
        # Ha benne van a listáidban VAGY nagybetűs, akkor név marad
        if is_name_part and (clean in NAME_DB or word[0].isupper()):
            name_parts.append(word)
        else:
            is_name_part = False
            comment_parts.append(word)
            
    return " ".join(name_parts), " ".join(comment_parts)

# --- 3. MASTER DATA (HOSSZÚ TÁVÚ MEMÓRIA) ---
def load_master_data():
    if os.path.exists("master_data.csv"):
        return pd.read_csv("master_data.csv", dtype={'Ügyfélkód': str})
    return pd.DataFrame(columns=['Ügyfélkód', 'Ügyintéző', 'Cím', 'Telefonszám', 'Megjegyzés'])

def save_to_master(current_df):
    """Ezt hívjuk meg a Mentés gombnál!"""
    master_df = load_master_data()
    # Összefűzzük a mait a régivel, az új adatok felülírják a régit az ID alapján
    updated_master = pd.concat([master_df, current_df[['Ügyfélkód', 'Ügyintéző', 'Cím', 'Telefonszám', 'Megjegyzés']]])
    updated_master = updated_master.drop_duplicates(subset=['Ügyfélkód'], keep='last')
    updated_master.to_csv("master_data.csv", index=False)


# --- 1. FUNKCIÓ: ADATOK FELKÜLDÉSE (UPSERT) ---
def sync_ugyfelkor_fel(df_napi, sheet_id, client):
    if client is None:
        return 0
        
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet("Adatok")
    except:
        ws = sh.add_worksheet(title="Adatok", rows="1000", cols="10")
        ws.append_row(["ID", "Név", "Cím", "Telefon", "Csoport", "Preferált Sorrend", "Megjegyzés", "Utolsó Rendelés"])

    # Beolvasás után kényszerítjük, hogy minden szöveg legyen, így nem lesz típus hiba
    data = ws.get_all_records()
    db_df = pd.DataFrame(data)
    
    if db_df.empty:
        db_df = pd.DataFrame(columns=["ID", "Név", "Cím", "Telefon", "Csoport", "Preferált Sorrend", "Megjegyzés", "Utolsó Rendelés"])
    else:
        # EZ A KRITIKUS RÉSZ: Minden oszlopot szöveggé alakítunk, hogy ne vesszen össze a típusokkal
        db_df = db_df.astype(str)

    ma = datetime.now().strftime("%Y-%m-%d")
    
    for _, row in df_napi.iterrows():
        u_id = str(row.get('temp_id', '')).strip()
        if not u_id or u_id in ['nan', 'None', '']: continue

        u_nev = str(row.get('Ügyintéző', '')).strip()
        u_cim = str(row.get('Cím', '')).strip()
        u_tel = str(row.get('Telefon', '')).strip()
        u_sorrend = str(row.get('Sorrend', '')).strip()
        u_megj = str(row.get('Megjegyzés', '')).strip()

        mask = db_df['ID'].astype(str) == u_id
        if mask.any():
            idx = db_df[mask].index[0]
            
            # Frissítjük az adatokat (most már biztosan szövegként)
            db_df.at[idx, 'Név'] = u_nev
            db_df.at[idx, 'Cím'] = u_cim
            db_df.at[idx, 'Telefon'] = u_tel
            db_df.at[idx, 'Preferált Sorrend'] = u_sorrend
            db_df.at[idx, 'Megjegyzés'] = u_megj
            db_df.at[idx, 'Utolsó Rendelés'] = ma
        else:
            new_row = {
                "ID": u_id, "Név": u_nev, "Cím": u_cim, "Telefon": u_tel,
                "Csoport": "", "Preferált Sorrend": u_sorrend, 
                "Megjegyzés": u_megj, "Utolsó Rendelés": ma
            }
            db_df = pd.concat([db_df, pd.DataFrame([new_row])], ignore_index=True)

    # NaN-ok és "nan" szövegek takarítása mentés előtt
    db_df = db_df.replace('nan', '').fillna("")
    
    final_list = [db_df.columns.values.tolist()] + db_df.values.tolist()
    ws.clear()
    ws.update('A1', final_list)
    return len(df_napi)

# --- 2. FUNKCIÓ: JAVÍTOTT ADATOK VISSZATÖLTÉSE ---
def adatok_visszatoltese_sheetrol(df_napi, sheet_id, client):
    if client is None: return df_napi
    try:
        sh = client.open_by_key(sheet_id)
        ws = sh.worksheet("Adatok")
        db_df = pd.DataFrame(ws.get_all_records())
        
        if db_df.empty: 
            return df_napi
            
        db_df['ID'] = db_df['ID'].astype(str).str.strip()
        
        # Eredeti sorrend rögzítése, ha még nincs
        if 'Original_Order' not in df_napi.columns:
            df_napi['Original_Order'] = range(1, len(df_napi) + 1)

        for i, row in df_napi.iterrows():
            u_id = str(row.get('temp_id', '')).strip()
            match = db_df[db_df['ID'] == u_id]
            
            if not match.empty:
                # Név frissítése
                s_nev = str(match.iloc[0]['Név']).strip()
                if s_nev and s_nev.lower() != 'nan':
                    df_napi.at[i, 'Ügyintéző'] = s_nev
                
                # Sorrend frissítése a Sheet-ről
                s_sorrend = str(match.iloc[0]['Preferált Sorrend']).strip()
                if s_sorrend and s_sorrend.lower() != 'nan' and s_sorrend != "":
                    try:
                        df_napi.at[i, 'Sorrend'] = float(s_sorrend)
                    except:
                        pass
                
                # Csoport és Megjegyzés frissítése
                for col in ['Csoport', 'Megjegyzés']:
                    val = str(match.iloc[0].get(col, '')).strip()
                    if val.lower() != 'nan':
                        df_napi.at[i, col] = val
        
        # A 999-es hiba elkerülése: ha nincs a Sheet-en sorrend, maradjon az Original_Order
        df_napi['Sorrend'] = pd.to_numeric(df_napi['Sorrend'], errors='coerce')
        df_napi['Sorrend'] = df_napi['Sorrend'].fillna(df_napi['Original_Order'])
        
        # RENDEZÉS: Csak a Sorrend számít!
        df_napi = df_napi.sort_values(by=['Sorrend'], ascending=[True])
        
        return df_napi
    except Exception as e:
        st.error(f"Hiba a visszatöltésnél: {e}")
        return df_napi

# --- 3. FŐ FÜGGVÉNY: PDF BEOLVASÁS ÉS BLOKKOSÍTÁS ---
def parse_interfood_pdf(pdf_file, napi_etlap_kodok):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jaratok': []}
    
    # Kibővített Stop Words lista a te meghatározásod alapján
    stop_words = [
        "Összesítés:", 
        "Csilagozott betűnél", # Eltéréssel is: Csillagozott/Csilagozott
        "Összesen:", 
        "Nyomtatta:", 
        "Oldal:", 
        "Menetlevél", 
        "Vége"
    ]

    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        W = page.width
        def c(kocka): return (kocka / 88) * W
        v_lines = [c(0), c(5.5), c(21.5), c(39.5), c(47), c(52), c(82.5), c(88)]

        for pg in pdf.pages:
            # 1. Kinyerjük az aktuális oldal szavait
            words = pg.extract_words(x_tolerance=3, y_tolerance=3)
            
            # --- FÜGGŐLEGES SOROMPÓ (Cutoff) BEÁLLÍTÁSA ---
            footer_elements = [
                w for w in words 
                if any(tag in w['text'] for tag in ["Összesítés", "Csilagozott", "Összesen"])
                and w['top'] > pg.height * 0.5
            ]
            
            page_cutoff = min([w['top'] for w in footer_elements]) - 2 if footer_elements else pg.height

            # 2. Horgonyok gyűjtése csak az aktuális oldalról
            anchors = [w for w in words if re.search(r'[HKSCPZ]-\d{5,7}', w['text'])]
            
            for i, anchor in enumerate(anchors):
                if anchor['top'] >= page_cutoff: continue

                # --- 1. ZÓNA ÉS SZÖVEG BEOLVASÁSA ---
                y_top = max(0, anchor['top'] - 12)
                
                if i + 1 < len(anchors):
                    y_bottom = anchors[i+1]['top'] + 5 
                else:
                    y_bottom = min(page_cutoff, anchor['top'] + 180)
                
                if y_bottom <= y_top: 
                    y_bottom = y_top + 60 

                # --- KRITIKUS JAVÍTÁS: page helyett pg-t használunk! ---
                full_row_box = pg.within_bbox((20, y_top, 585, y_bottom))
                raw_text = full_row_box.extract_text() or ""
                lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
                
                # --- 2. AZONOSÍTÁS ÉS NÉV KINYERÉSE (Szigorú kontrollal) ---
                current_id = anchor['text']
                local_customer_name = ""
                name_line_index = -1
                
                for idx, l in enumerate(lines):
                    if current_id in l:
                        # Kivágjuk az ID-t: "Dr. Vincze Ildikó belülre kérem" (vagy "Kovács Bt. / Kovács János")
                        raw_line = l.replace(current_id, "").strip()
                        
                        # Csak addig gyűjtjük a szavakat, amíg NEVET látunk (Nagybetű/Dr/stb)
                        name_parts = []
                        for word in raw_line.split():
                            if word[0].isupper() or word.startswith("Dr.") or word.lower() in ["id.", "ifj.", "özv."]:
                                name_parts.append(word)
                            else:
                                break
                        local_customer_name = " ".join(name_parts)
                        name_line_index = idx
                        break

                # --- 3. SZÉTVÁLOGATÁS (Részleg + Megjegyzés megtartásával) ---
                reszleg_ceg_lista = []
                hosszu_megj_lista = []

                for idx, l_strip in enumerate(lines):
                    # Alap szűrések
                    if any(x in l_strip for x in ["Debrecen", "Ebes", "Hajdú", "Sor", "Ügyfél", "Össz.", "Nyomtatva:"]): 
                        continue
                    if re.search(PHONE_PAT, l_strip) or re.search(MONEY_PAT, l_strip):
                        continue

                    if idx == name_line_index:
                        # Ez a név sora. Ami itt maradt az ID és a Név levágása után, az a Részleg!
                        # Pl: "S-123 ID. Kovács János Részleg" -> "Részleg" marad meg.
                        maradek = l_strip.replace(current_id, "").replace(local_customer_name, "").strip()
                        
                        if len(maradek) > 1:
                            # Ha a maradék kisbetűvel kezdődik (mint a "belülre kérem"), 
                            # akkor az inkább a hosszú megjegyzéshez tartozik, nem cég/részleg név.
                            if maradek[0].islower():
                                hosszu_megj_lista.append(maradek)
                            else:
                                reszleg_ceg_lista.append(maradek)
                    else:
                        # Minden más sor (ami nem a név sora) a hosszú megjegyzésbe megy
                        hosszu_megj_lista.append(l_strip)

                # --- 4. MENTÉS A VÁLTOZÓKBA ---
                megj_resz_1 = " | ".join(reszleg_ceg_lista)
                megj_resz_2 = " | ".join(hosszu_megj_lista)
                
                # Fontos: frissítsük a globális nevet is, ha a későbbi pontoknak kell
                customer_name = local_customer_name
            
                # A blokk vége: vagy a következő ID, vagy a lap alja (sorompó)
                next_anchor_top = anchors[i+1]['top'] - 5 if i+1 < len(anchors) else page_cutoff
                y_bottom = min(next_anchor_top, page_cutoff)
                
                line_words = [w for w in words if y_top <= w['top'] < y_bottom]
                
                def get_col_text(x_min, x_max):
                    sel = [w for w in line_words if x_min <= (w['x0'] + w['x1'])/2 < x_max]
                    sel.sort(key=lambda x: (x['top'], x['x0']))
                    return " ".join([w['text'] for w in sel])

                # Adatgyűjtés a sávokból
                full_id_area = get_col_text(v_lines[0], v_lines[2])
                id_match = re.search(r'([HKSCPZ]-\d{5,7})', full_id_area)
                
                # --- 0. FEJLÉC ÉS LÁBLÉC TELJES KIZÁRÁSA ---
                line_text_full = " ".join([w['text'] for w in line_words])
                tiltott_szavak = ["járat", "menetterve", "Év:", "Hét:", "Nap:", "InterFood", "oldal", "Nyomtatva", "Összesítés:", "Csilagozott", "Összesen:"]
                
                if any(stop in line_text_full for stop in tiltott_szavak):
                    if not re.search(r'[HKSCPZ]-\d{5,7}', line_text_full):
                        continue

                if id_match:
                    full_id = id_match.group(1)
                    prefix = full_id.split('-')[0]
                    
                    # --- 1. KOORDINÁTÁK ÉS ALAP-SOR MEGHATÁROZÁSA ---
                    W = page.width
                    x40 = (40 / 88) * W
                    x48 = (48 / 88) * W
                    x52_5 = (52.5 / 88) * W
                    
                    y_anchor = (anchor['top'] + anchor['bottom']) / 2
                    # Definiáljuk a row_words-öt az adott sorhoz
                    row_words = [w for w in line_words if abs(((w['top'] + w['bottom']) / 2) - y_anchor) < 8]

                    # --- 2. TELEFON ÉS PÉNZ ---
                    tel_money_words = sorted([w for w in row_words if x40 <= (w['x0'] + w['x1'])/2 < x52_5], key=lambda w: w['top'])
                    
                    phone_val, money_val = "", "0Ft"
                    if tel_money_words:
                        first_y = tel_money_words[0]['top']
                        top_row = [w for w in tel_money_words if abs(w['top'] - first_y) < 4]
                        bottom_row = [w for w in tel_money_words if w not in top_row]
                        top_text = " ".join([w['text'] for w in sorted(top_row, key=lambda w: w['x0'])])
                        bottom_text = " ".join([w['text'] for w in sorted(bottom_row, key=lambda w: w['x0'])])
                        
                        full_text_area = top_text + " " + bottom_text
                        
                        # Telefon felismerése
                        phone_match = re.search(r'(\d{1,2}/\d+)', full_text_area)
                        phone_val = phone_match.group(1).replace(" ", "") if phone_match else ""
                        
                        # --- JAVÍTOTT PÉNZ FELISMERÉS ---
                        # Engedélyezzük a szóközt a mínusz jel után: (-?\s*\d[\d\s]*)\s*Ft
                        # Használjuk a teljes területet, mert a pénz néha elcsúszhat
                        money_match = re.search(r'(-?\s*\d[\d\s]*)\s*Ft', bottom_text if bottom_text else top_text)
                        
                        if money_match:
                            # Kinyerjük a találatot, és töröljük a felesleges szóközöket, DE a mínuszt megtartjuk
                            raw_money = money_match.group(1).replace(" ", "")
                            money_val = f"{raw_money}Ft"
                        else:
                            # Tartalék megoldás: ha nincs Ft, de van szám a végén
                            last_num = re.search(r'(-?\s*\d+)$', (bottom_text.strip() if bottom_text else top_text.strip()))
                            if last_num:
                                money_val = f"{last_num.group(1).replace(' ', '')}Ft"
                            else:
                                money_val = "0Ft"

                    # --- ÜGYINTÉZŐ KERESÉSE (V15 - A Szanyi-specialista) ---
                    x_start_admin = (38 / 88) * W
                    x_end_admin = (54 / 88) * W
                    
                    # Csak azokat a szavakat gyűjtjük, amik az admin sávban vannak
                    admin_candidates = [w for w in line_words if x_start_admin <= (w['x0'] + w['x1'])/2 < x_end_admin]
                    
                    y_start = (anchor['top'] + anchor['bottom']) / 2
                    raw_name_parts = []
                    
                    # STOP-szavak az összesítéshez
                    stop_keywords = ["Összesen", "Összesítés", "Össz"]
                    
                    # Rendezés: fentről le, balról jobbra
                    for w in sorted(admin_candidates, key=lambda x: (x['top'], x['x0'])):
                        t_clean = w['text'].strip()
                        
                        # 1. STOP: Ha elérjük az összesítőt
                        if any(stop.lower() in t_clean.lower() for stop in stop_keywords):
                            break
                            
                        # 2. FÜGGŐLEGES SZŰRÉS: Maradunk az ID magasságában (+/- 35 pixel)
                        if abs(w['top'] - y_start) < 35:
                            # 3. HORIZONTÁLIS VÉDELEM: Ha a szó x1-e túlnyúlik az admin sávon, 
                            # és a szöveg gyanúsan rövid/töredék, akkor az már a megjegyzés
                            if w['x1'] > x_end_admin * 1.02 and len(t_clean) < 6:
                                continue

                            # 4. TÍPUS SZŰRÉS: Pénz, telefon, kódok (pl. 4-SP3)
                            if "Ft" in t_clean: continue
                            if "/" in t_clean and any(c.isdigit() for c in t_clean): continue
                            if re.search(r'\d-[A-Z]', t_clean): continue
                            if t_clean.isdigit() and len(t_clean) < 4: continue
                                
                            raw_name_parts.append(w)

                    # --- ÖSSZEÁLLÍTÁS ÉS SEBÉSZI TISZTÍTÁS ---
                    full_raw_text = " ".join([p['text'] for p in sorted(raw_name_parts, key=lambda x: (x['top'], x['x0']))])
                    
                    # Számok, prefixek, csillagok törlése
                    clean_name = full_raw_text.replace("*", "")
                    clean_name = re.sub(r'\d+', '', clean_name)
                    clean_name = re.sub(r'-[A-Z0-9]{1,3}\b', '', clean_name)
                    
                    # SZÓTÁR ALAPÚ SZŰRÉS (Szanyi Norbert "közöt" és Gabriella "D" ellen)
                    junk_words = ["közöt", "között", "köz", "D", "S", "adag", "db"]
                    
                    final_parts = []
                    for part in clean_name.split():
                        p_stripped = part.strip(" ,.|/-")
                        # Ha a szó benne van a szemét-listában, vagy csak 1 karakter (és nem monogram)
                        if p_stripped.lower() in [j.lower() for j in junk_words]:
                            continue
                        if len(p_stripped) == 1 and not p_stripped.endswith('.'):
                            continue
                        final_parts.append(part)

                    admin_name = " ".join(final_parts).strip(" -/|.,*")
                    admin_name = " ".join(admin_name.split())

                    # --- 4. RENDELÉS ÉS MEGJEGYZÉS SZÉTVÁLASZTÁSA (DINAMIKUS SZŰRÉS) ---
                    
                    width = page.width 
                    # Visszaállunk a biztos 60%-ra (52.5 / 88), hogy a rendelések eleje ne vesszen el
                    x_start_limit = width * 0.596 
                    x_end_limit = width * 0.91    

                    # 1. KIVÁGÁS: A folyosó szavai (most már a 60%-tól)
                    folyoso_words = sorted([
                        w for w in line_words 
                        if (w['x0'] + w['x1'])/2 >= x_start_limit and (w['x0'] + w['x1'])/2 <= x_end_limit
                    ], key=lambda x: (x['top'], x['x0']))
                    
                    # 2. TISZTÍTÁS: CSAK a kódok kellenek, a telefonszámot és az összesítést kidobjuk!
                    tiszta_elemek = []
                    for w in folyoso_words:
                        txt = w['text'].strip()
                        
                        # --- ÚJ: CSAK ITT ÁLLÍTJUK MEG A RENDELÉSEK GYŰJTÉSÉT ---
                        if any(stop in txt for stop in ["Összesítés:", "Csilagozott", "Összesen:"]):
                            break # Itt megáll, de az ember megmarad!
                        
                        # Ha a szó telefonszám formátumú (pl. 30/1234567), akkor átugorjuk
                        if re.match(r'\d{2}/\d+', txt):
                            continue
                            
                        # Csak azt tartjuk meg, ami kód-szerű
                        if re.search(r'[\d\-\u2013\u2014\u2212A-Z\*]', txt):
                            tiszta_elemek.append(txt)

                    # 3. LEGO-RAGASZTÓ: Összehúzzuk a szétesett darabokat
                    raw_folyoso_text = " ".join(tiszta_elemek)
                    # Itt tüntetjük el a szóközöket: "1 - D14" -> "1-D14"
                    fixed_text = re.sub(r'(\d+)\s*([-\u2013\u2014\u2212])\s*', r'\1\2', raw_folyoso_text)

                    # 4. KERESÉS: "Mindent látó" Erika-biztos gyűjtő
                    # Először a biztonságos Legó-ragasztó
                    raw_orders = re.findall(ORDER_PAT, fixed_text)
                    
                    # Ha a Legó nem talált semmit, nézzük meg a dobozban lévő ÖSSZES szót
                    if not raw_orders:
                        # Az összes szót összefűzzük egy hosszú lánccá
                        box_content = " ".join([w['text'] for w in line_words])
                        # Ebben keressük meg az összes érvényes rendelést
                        potential_orders = re.findall(ORDER_PAT, box_content)
                        
                        # Szűrés: Csak azokat tartjuk meg, amik a sor végén (jobb oldalon) vannak
                        # A házszámokat (13-15) az ORDER_PAT (betűvel kezdődő kód) már eleve kiszűri!
                        raw_orders = potential_orders

                    rendeles_str = ", ".join([f"{q}-{c}" for q, c in raw_orders])
                    
                    # 5. MEGJEGYZÉS: A teljes sorból kivonjuk a már megtalált rendeléseket
                    # Így a megjegyzésben megmarad minden, ami a folyosón kívül volt (vagy amit kidobtunk)
                    full_line_text = " ".join([w['text'] for w in sorted(line_words, key=lambda x: x['x0'])])
                    clean_comment = full_line_text
                    
                    for q, c in raw_orders:
                        # Olyan mintát keresünk, ami rugalmas a szóközökre a törlésnél
                        p = rf'{q}\s*[-\u2013\u2014\u2212]\s*{re.escape(c)}'
                        clean_comment = re.sub(p, '', clean_comment, count=1)
                    
                    # Utolsó simítás: Telefonszám, pénz és ID eltávolítása a megjegyzésből
                    clean_comment = re.sub(PHONE_PAT, '', clean_comment)
                    clean_comment = re.sub(MONEY_PAT, '', clean_comment)
                    clean_comment = re.sub(r'^[S|C|P]-\d+\s+', '', clean_comment)
                    
                    megjegyzes = clean_comment.strip(", ").strip()
                    megjegyzes = re.sub(r'\s+', ' ', megjegyzes).strip()

                    # CÍM meghatározása (v_lines[2] és x40 között)
                    address = " ".join([w['text'] for w in sorted([w for w in row_words if v_lines[2] <= (w['x0']+w['x1'])/2 < x40], key=lambda x: x['x0'])]).strip()

                    # --- DINAMIKUS CÍMTISZTÍTÁS (Frissített verzió) ---
                    if admin_name and address:
                        # 1. Előkészítjük a neveket és a cím szavait
                        name_parts_to_erase = [n.strip(" ,.|/-").lower() for n in admin_name.split() if len(n.strip(" ,.|/-")) > 1]
                        # Hozzáadjuk a listához a tiltott titulusokat is, így a while ciklus ezeket is kitakarítja
                        name_parts_to_erase.extend(["dr", "dr.", "idősb", "ifj", "id", "ifj."])
                        
                        address_parts = address.split()
                        
                        # 2. Hátulról előre haladva levágjuk a névmaradványokat ÉS a titulusokat
                        # A ciklus addig fut, amíg a cím utolsó szava szerepel a "tiltólistán"
                        while address_parts:
                            last_word_clean = address_parts[-1].strip(" ,.|/-").lower()
                            if last_word_clean in name_parts_to_erase:
                                address_parts.pop()
                            else:
                                break # Ha olyan szót találunk, ami nem név/titulus, megállunk
                        
                        # 3. Cím visszaállítása
                        address = " ".join(address_parts).strip(" ,.|/-")

                    # --- 1. HORGONYOK ELŐKÉSZÍTÉSE ---
                    raw_line = line_text_full 
                    megj_resz_1 = "" 
                    megj_resz_2 = ""
                    parts = []  # <--- IDE KERÜLJÖN

                    # --- 2. LÉPÉS: SORSZÁM LEVÁGÁSA (AZ ID-IG) ---
                    id_pattern = r'[HKSCPZ]-\d{6}'
                    id_match = re.search(id_pattern, raw_line)
                    working_line = raw_line
                    if id_match:
                        working_line = raw_line[id_match.start():]

                    # --- 3. LÉPÉS: ADATOK KERESÉSE (Horgonyoknak) ---
                    # Telefon és Pénz horgonyok (ezek fixek)
                    phone_for_clean = ""
                    p_match = re.search(PHONE_PAT, working_line)
                    if p_match: phone_for_clean = p_match.group(1)

                    money_for_clean = ""
                    m_match = re.search(MONEY_PAT, working_line)
                    if m_match: money_for_clean = m_match.group(1)

                    # Cím horgony (Irányítószámtól a Telefonig/Pénzig tartó rész)
                    address_for_clean = ""
                    city_match = re.search(r'\b\d{4}\b', working_line)
                    if city_match:
                        # Megkeressük hol kezdődik a város és hol kezdődik a telefon/pénz
                        start_idx = city_match.start()
                        end_pat = f"{re.escape(phone_for_clean)}|{re.escape(money_for_clean)}|Ft|{ORDER_PAT}"
                        end_match = re.search(end_pat, working_line[start_idx:])
                        
                        if end_match:
                            address_for_clean = working_line[start_idx : start_idx + end_match.start()].strip()
                        else:
                            address_for_clean = working_line[start_idx:].strip()

                    # --- 4. LÉPÉS: KONTEXTUS BŐVÍTÉSE (PORSZÍVÓ) ---
                    # Toleranciát használunk a rendezésnél, hogy az egy sorban lévő szavak ne cserélődjenek fel
                    # A 'top' értéket 3 pixelre kerekítjük, így az egy vonalban lévők azonos 'top'-ot kapnak
                    line_words_sorted = sorted(line_words, key=lambda x: (round(x['top'] / 3) * 3, x['x0']))
                    full_block_text = " ".join([w['text'] for w in line_words_sorted])
                    
                    # Levágjuk az elejéről a sorszámot az ID-ig
                    id_match_context = re.search(id_pattern, full_block_text)
                    working_context = full_block_text[id_match_context.start():] if id_match_context else full_block_text

                    # --- 5. LÉPÉS: TISZTÍTOTT KONTEXTUS LÉTREHOZÁSA ---
                    # Csak itt inicializálunk, és rögtön takarítunk
                    megj_resz_1 = "" 
                    megj_resz_2 = "" 

                    # Kiszűrjük a rendelési kódokat és a pénzt, hogy ne zavarják a megjegyzés keresését
                    clean_context = re.sub(ORDER_PAT, '', working_context)
                    clean_context = re.sub(MONEY_PAT, '', clean_context)
                    # A telefonszámot is érdemes kivenni a clean_context-ből, hogy ne zavarjon be megjegyzésként
                    if 'phone_val' in locals() and phone_val:
                        clean_context = clean_context.replace(phone_val, "")

                    # --- 6. LÉPÉS: MEGJEGYZÉS 1. FELE (ID ÉS ZIP KÖZÖTT) ---
                    # Ez kezeli a nevet/részleget az irányítószám előtt
                    zip_match = re.search(r'\b\d{4}\b', clean_context)
                    if zip_match:
                        # Az ID utáni, de a ZIP előtti rész kinyerése
                        pre_zip = clean_context[:zip_match.start()].replace(full_id, "").strip()
                        if pre_zip:
                            if "/" in pre_zip:
                                megj_resz_1 = pre_zip.split("/")[0].strip()
                            else:
                                t_megj = pre_zip
                                if admin_name:
                                    for w in admin_name.split():
                                        if len(w) > 2:
                                            t_megj = re.sub(rf'\b{re.escape(w)}\b', '', t_megj, flags=re.IGNORECASE)
                                megj_resz_1 = t_megj.strip()

                    # --- 7. LÉPÉS: MEGJEGYZÉS 2. FELE (CÍM UTÁNI RÉSZ) ---
                    # Ez találja meg a "Sörfőzde", "Porta" stb. infókat a cím után
                    if address in clean_context:
                        anchor_pos = clean_context.find(address) + len(address)
                        after_address = clean_context[anchor_pos:].strip()
                        
                        # A végét a telefon vagy a sor vége jelzi (a pénzt/rendelést már töröltük)
                        end_m = re.search(re.escape(phone_val), after_address)
                        megj_resz_2 = after_address[:end_m.start()].strip() if end_m else after_address

                    # --- 8. ÖSSZEFŰZÉS ÉS TISZTÍTÁS (Végleges, Ildikó-biztos verzió) ---
                    all_notes = []
                    
                    # 1. Megjegyzés part 1 (Cégnév, részleg az ID mellől)
                    if megj_resz_1.strip():
                        all_notes.append(megj_resz_1.strip())
                    
                    # 2. Megjegyzés part 2 (Hosszú instrukciók új sorokból - EZ HIÁNYZOTT!)
                    if megj_resz_2.strip():
                        all_notes.append(megj_resz_2.strip())
                    
                    # 3. Egyéb gyűjtött részek (pl. Ügyintéző cellából vagy cím végéről)
                    all_notes.extend(parts)

                    # Duplikátumok szűrése az eredeti sorrend megtartásával
                    seen = set()
                    final_parts = []
                    for n in all_notes:
                        n_clean = n.strip()
                        if not n_clean:
                            continue
                        # Kis/nagybetű különbség ne okozzon duplázást
                        if n_clean.lower() not in seen:
                            final_parts.append(n_clean)
                            seen.add(n_clean.lower())

                    # Összefűzés elegáns elválasztóval
                    clean_customer = " | ".join(final_parts)

                    # Junk (felesleges) szavak és mondatok kitakarítása
                    junk_list = [
                        "Felnőtt", "Nyugdíjas", "Gyerek", "Vendég", "Dr.", "idősb", "ifj",
                        "Csilagozott betűnél kiegészítő is van!!!",
                        "Csilagozott betűnél kiegészítő is van"
                    ]
                    
                    for junk in junk_list:
                        # Csak akkor cseréljük, ha pontos egyezés van vagy határolt szó, 
                        # hogy ne rontson bele értelmes szavakba
                        clean_customer = clean_customer.replace(junk, "")

                    # Végső kozmetika: dupla szóközök és felesleges írásjelek eltávolítása a szélekről
                    clean_customer = re.sub(r'\s+', ' ', clean_customer)
                    # Tisztítjuk a maradék elválasztókat, amik a junk törlése után maradtak
                    clean_customer = clean_customer.strip(" -/|.,")
                    
                    # --- 9. RÉSZLEG ÉS INSTRUKCIÓ SZÉTVÁLASZTÁSA ---
                    reszleg = ""
                    if "/" in clean_customer:
                        c_parts = clean_customer.split("/")
                        potential_reszleg = c_parts[0].strip()
                        if admin_name and potential_reszleg.lower() != admin_name.lower():
                            reszleg = potential_reszleg
                    
                    # Ami maradt, az az extra instrukció
                    extra_instructions = clean_customer
                    if reszleg: extra_instructions = extra_instructions.replace(reszleg, "")
                    if admin_name:
                        for n_part in admin_name.split():
                            if len(n_part) > 2:
                                extra_instructions = re.sub(rf'\b{re.escape(n_part)}\b', '', extra_instructions, flags=re.IGNORECASE)

                    extra_instructions = extra_instructions.replace("/", "").strip(" -/|.,")

                    # --- TELEFONSZÁM- ÉS KAPUKÓD-BIZTOS TISZTÍTÁS ---
                    
                    # 1. CSAK a magányos előhívókat bántjuk (pl. "Név 30")
                    # Megnézzük, hogy a 20/30/70 után NINCS-E perjel vagy több számjegy
                    clean_customer = re.sub(r'\b(20|30|70)\b(?![/\d])', '', clean_customer)

                    # 2. Ügyintéző nevének radírozása (finomítva)
                    if admin_name:
                        # Teljes név törlése
                        clean_customer = re.sub(rf'\b{re.escape(admin_name)}\b', '', clean_customer, flags=re.IGNORECASE)
                        # Név részei (pl. Kiss, János), de csak ha önálló szavak
                        for name_part in admin_name.split():
                            if len(name_part) > 2:
                                clean_customer = re.sub(rf'\b{re.escape(name_part)}\b', '', clean_customer, flags=re.IGNORECASE)

                    # 3. Vesszőhegyek takarítása (a # és / jeleket békén hagyja!)
                    # Csak a halmozott vesszőt, pontot és szóközt cseréli egyetlen szóközre
                    clean_customer = re.sub(r'[,.;:|*]{2,}', ' ', clean_customer)

                    # 4. Részleg és Instrukció szétválasztása
                    reszleg = ""
                    extra_instructions = clean_customer
                    if "/" in clean_customer:
                        # Ha a perjel telefonszám része (szám van előtte és utána), nem vágjuk szét!
                        if not re.search(r'\d/\d', clean_customer):
                            c_parts = clean_customer.split("/")
                            reszleg = c_parts[0].strip()
                            extra_instructions = "/".join(c_parts[1:]).strip()

                    # --- 5. INTELLIGENS ÖSSZEFŰZÉS ÉS ÉTLAP ALAPJÚ TAKARÍTÁS ---
                    final_note_parts = []
                    r_clean = reszleg.strip(" ,.-/|*")
                    e_clean = extra_instructions.strip(" ,.-/|*")
                    
                    # --- OKOS TAKARÍTÁS: Itt használjuk a kapott napi_etlap_kodok-at ---
                    # Sorba rendezzük hosszuk szerint csökkenőben (D14 előbb, mint D1)
                    for kod in sorted(napi_etlap_kodok, key=len, reverse=True):
                        if len(kod) > 1:
                            # HOSSZÚ KÓDOK (pl. D14, REPA, E2K):
                            # Töröljük, ha különálló egység (szóhatár: szóköz, kötőjel vagy sor vége)
                            # A minta felismeri: "1-D14", "1 - D14", vagy simán "D14"
                            minta = r'\d*\s*[-\u2013\u2014\u2212]?\s*\b' + re.escape(kod) + r'\b'
                            e_clean = re.sub(minta, '', e_clean)
                        else:
                            # RÖVID KÓDOK (pl. A, P, I, C):
                            # CSAK akkor töröljük, ha van előtte egy szám és egy kötőjel! (pl. 1-A)
                            # Így a nevekben (pl. Attila) lévő betűk biztonságban maradnak.
                            minta = r'\d+\s*[-\u2013\u2014\u2212]\s*\b' + re.escape(kod) + r'\b'
                            e_clean = re.sub(minta, '', e_clean)

                    # Utólagos szemétmentesítés a törlés után maradt jeleknek
                    e_clean = re.sub(r'[-\u2013\u2014\u2212]{2,}', '-', e_clean) # Dupla kötőjel -> sima
                    e_clean = e_clean.replace('  ', ' ').strip(" ,.-/|*")
                    # --- TAKARÍTÁS VÉGE ---

                    # Most már a megtisztított e_clean-t adjuk hozzá a megjegyzéshez
                    if r_clean and len(r_clean) > 1:
                        final_note_parts.append(r_clean)
                    if e_clean and len(e_clean) > 1:
                        # Ellenőrizzük, hogy az extra ne legyen ugyanaz, mint a részleg
                        if not final_note_parts or e_clean.lower() != final_note_parts[0].lower():
                            final_note_parts.append(e_clean)
                    
                    full_note = " | ".join(final_note_parts)
                    
                    # --- 6. UTOLSÓ FINOMHANGOLÁS (JAVÍTOTT, HIBAMENTES) ---
                    
                    # 1. OPTIPONT ÉS ÖSSZESÍTŐK AZONNALI TÖRLÉSE
                    full_note = re.sub(r'(Összesítés:|Csillagozott|Összesen:).*', '', full_note, flags=re.IGNORECASE)

                    # 2. MAGÁNYOS ELŐHÍVÓK IRTÁSA (Fix cserékkel a legbiztosabb)
                    # Előbb a fix elválasztós formák (Erzsébet-ügy megoldása)
                    for num in ["20", "30", "70", "06"]:
                        full_note = full_note.replace(f"| {num} |", "|")
                        full_note = full_note.replace(f"|{num}|", "|")
                        full_note = full_note.replace(f"| {num}", "|")
                        full_note = full_note.replace(f"{num} |", "|")
                    
                    # 3. MAGÁNYOS SZÁMOK TÖRLÉSE (Regex hiba nélkül)
                    # Olyan 20, 30, 70, 06 amiket szóköz vesz körül, de NEM telefonszámok (nincs / utánuk)
                    # A \b (szóhatár) használata biztonságosabb itt
                    full_note = re.sub(r'\b(20|30|70|06)\b(?!\s*/|\s*\d)', '', full_note)

                    # 4. NÉV-DUPLIKÁCIÓ (Globiz-effektus)
                    if "|" in full_note:
                        parts = [p.strip() for p in full_note.split("|")]
                        if len(parts) > 1 and parts[1].lower().startswith(parts[0].lower()):
                            parts[1] = parts[1][len(parts[0]):].strip()
                        # dict.fromkeys kiszűri a duplikált blokkokat
                        full_note = " | ".join(dict.fromkeys([p for p in parts if p]))

                    # 5. ÍRÁSJEL-HALMOZÓDÁS ÉS ÁRVA VESSZŐK
                    # Kenézy-féle vesszőtenger: több vessző/pont/szóköz -> egy szóköz
                    full_note = re.sub(r'([ ,.]*[,.][ ,.]*){2,}', ' ', full_note)
                    # Pipeline melletti szemét takarítása
                    full_note = re.sub(r'\|\s*[,. ]+', '| ', full_note)
                    full_note = re.sub(r'[,. ]+\s*\|', ' |', full_note)

                    # 6. PIPELINE POLÍROZÁS ÉS VÉGSŐ TISZTÍTÁS
                    # Több pipeline egymás után -> egy pipeline
                    full_note = re.sub(r'(\|[ \t]*)+', ' | ', full_note)
                    # Dupla szóközök ki
                    full_note = re.sub(r'\s+', ' ', full_note)
                    # Szélekről minden maradék le (vessző, pont, pipeline, perjel)
                    full_note = full_note.strip(" ,.-/|*")
                    
                    # Rendelés szöveges formázása a CSV-hez
                    mapping = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}
                    full_rendeles_text = f"{mapping.get(prefix, '')}: {rendeles_str}" if rendeles_str else ""

                    mapping = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}
                    full_rendeles_text = f"{mapping.get(prefix, '')}: {rendeles_str}" if rendeles_str else ""

                    rows.append({
                        "ID": full_id, "Ügyintéző": admin_name, "Cím": address, "Telefon": phone_val,
                        "Pénz": money_val, "Rendelés": rendeles_str, "Megjegyzés": full_note,
                        "Összesen": sum(int(q) for q, c in raw_orders) if raw_orders else 0,
                        "Rendelés_Full": full_rendeles_text, "temp_id": full_id.split('-')[-1],
                        "Prefix": prefix, "Csoport": current_group_id if 'current_group_id' in locals() else 0
                    })
    
    if not rows: return [], metadata
    df = pd.DataFrame(rows)
    df['Csoport'] = df.groupby('temp_id').ngroup() + 1
    return df.to_dict('records'), metadata
    
def merge_data(all_rows):
    if not all_rows: 
        return pd.DataFrame()
    
    # --- HIBA JAVÍTÁSA ITT ---
    if isinstance(all_rows, list) and len(all_rows) > 0:
        if not isinstance(all_rows[0], pd.DataFrame):
            combined = pd.DataFrame(all_rows)
        else:
            combined = pd.concat(all_rows, ignore_index=True)
    else:
        combined = all_rows
    # -------------------------

    # 🛑 1. BIZTONSÁGI SZŰRÉS: Kidobjuk a lemondott/üres sorokat még az összefésülés ELŐTT
    if 'Rendelés_Full' in combined.columns:
        combined = combined[combined['Rendelés_Full'].astype(str).str.strip() != ""]
        combined = combined[combined['Rendelés_Full'].notna() & (combined['Rendelés_Full'].astype(str).str.lower() != 'nan')]
    if 'Rendelés' in combined.columns:
        combined = combined[combined['Rendelés'].astype(str).str.strip() != ""]
        combined = combined[combined['Rendelés'].notna() & (combined['Rendelés'].astype(str).str.lower() != 'nan')]

    # Ha a szűrés után nem maradt adat, üres DataFrame-et adunk vissza
    if combined.empty:
        return pd.DataFrame()

    merged = []
    unique_ids = combined['temp_id'].unique()
    
    for tid in unique_ids:
        subset = combined[combined['temp_id'] == tid]
        base = subset.iloc[0].to_dict()
        
        # 🟢 ÚJ: Megtartjuk a PDF-ből jövő egyedi járatszámot ennél az ügyfélnél
        if 'pdf_jarat' in subset.columns:
            nem_ures_jarat = subset['pdf_jarat'].dropna().astype(str).str.strip()
            nem_ures_jarat = nem_ures_jarat[nem_ures_jarat != ""]
            if not nem_ures_jarat.empty:
                base['pdf_jarat'] = nem_ures_jarat.iloc[0]
        
        if len(subset) > 1:
            # Rendelések összefűzése
            all_orders = []
            for _, r in subset.iterrows():
                o_str = str(r.get('Rendelés_Full', '')).strip()
                if o_str and o_str.lower() != 'nan': 
                    all_orders.append(o_str)
            base['Rendelés_Full'] = " | ".join(all_orders)
            
            # DB összeadása
            try:
                base['Összesen'] = sum(pd.to_numeric(subset['Összesen'], errors='coerce').fillna(0))
            except: pass
            
            # PÉNZ: Az első érvényes összeget tartjuk meg (nem adunk össze)
            p_val = ""
            for _, r in subset.iterrows():
                val = str(r.get('Pénz', '')).strip()
                if val and val.lower() != 'nan' and any(c.isdigit() for c in val):
                    p_val = val
                    break
            base['Pénz'] = p_val

        merged.append(base)
    
    res = pd.DataFrame(merged)
    
    # 🛑 2. BIZTONSÁGI SZŰRÉS: Ha az összefűzés után maradt volna üres vagy 'nan' rendelés, azt is kiszűrjük
    if 'Rendelés_Full' in res.columns:
        res = res[res['Rendelés_Full'].astype(str).str.strip() != ""]
        res = res[res['Rendelés_Full'].notna() & (res['Rendelés_Full'].astype(str).str.lower() != 'nan')]
    
    if res.empty:
        return pd.DataFrame()
    
    # 🟢 ÚJ: Áttesszük a hivatalos 'Járat' oszlopba a kinyert egyedi járatokat
    if 'pdf_jarat' in res.columns:
        res['Járat'] = res['pdf_jarat'].astype(str).str.strip()
    
    # Biztosítjuk a tiszta oszlopneveket
    res.columns = [c.strip() for c in res.columns]
    
    # Automatikus sorszámozás 1-től (Ez így most már a lemondások NÉLKÜLI tiszta sorszám lesz!)
    res['Sorrend'] = range(1, len(res) + 1)
    
    # A csoportosítási rész maradhat változatlanul:
    if 'Csoport' in res.columns:
        res['Csoport'] = res['Csoport'].astype(str).replace(['nan', 'None', '0', '0.0'], '')

    # --- CSOPORTOSÍTÁS (Keretezéshez) ---
    res['Csoport'] = 0
    group_id = 1
    for i in range(1, len(res)):
        def clean_addr(s):
            return re.sub(r'\W+', '', str(s)).lower()
        
        addr_prev = clean_addr(res.iloc[i-1]['Cím'])
        addr_curr = clean_addr(res.iloc[i]['Cím'])
        
        if addr_prev == addr_curr and addr_curr != "":
            if res.iloc[i-1]['Csoport'] == 0:
                res.at[res.index[i-1], 'Csoport'] = group_id
                res.at[res.index[i], 'Csoport'] = group_id
                group_id += 1
            else:
                res.at[res.index[i], 'Csoport'] = res.iloc[i-1]['Csoport']
                
    return res
    
# --- FŐ PROGRAMFUTÁS ---
def main():
    import pandas as pd
    # 1. Streamlit alapbeállítás – Ennek KÖTELEZŐEN a legelsőnek kell lennie!
    st.set_page_config(page_title="Interfood Label Master", layout="wide")

    # 2. Globális elérés a gspread kliensnek
    global client  

    # 3. Az ID-k fix definiálása helyben
    SHEET_ID = "1bZrtgqROYijYhyFOFrqYeSTUAsGqZU6GLijObJ1En0o" 
    UGYFELKOR_SHEET_ID = "1nK0OLzVzEFY5bSLhMFfGgs4tOgMEueBgXeb9JUbLSN8"
    SHEET_ID_MASTER = SHEET_ID
    SHEET_ID_UGYFELKOR = UGYFELKOR_SHEET_ID

    # 4. Fontok regisztrálása a nyomtatáshoz
    from nyomtatas_modulok import register_fonts
    register_fonts()

    # 5. Session State alapértékek biztonságos beállítása
    if 'mdf' not in st.session_state: st.session_state.mdf = None
    if 'meta_data' not in st.session_state: st.session_state.meta_data = []
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

    # 6. URL paraméterek lekérése
    query_params = st.query_params
    view = query_params.get("view", None)
    url_jarat = query_params.get("jarat", "")

    # 7. BIZTONSÁGOS OKOSÍTÁS: Ha a parancsikon miatt nincs 'view' a linkben
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
            return # Megállítjuk a futást

    # 8. Logikai nézet beállítása a kód többi részének
    is_mobile_view = (view == "mobile")

    # --- URL PARAMÉTEREK AUTOMATIKUS KIOLVASÁSA ---
    # Kiolvassuk a linkből a járatot és a teszt módot, ha léteznek
    url_jarat = st.query_params.get("jarat", "")
    url_teszt = st.query_params.get("test", "false") == "true"

    # 9. Beléptető rendszer / Biztonsági ellenőrzés
    if not st.session_state.bejelentkezve:
        st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>🎯 Label Master</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #6B7280;'>Biztonságos azonosítás a rendszer használatokhoz</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.warning("🔒 Kérjük, add meg a járatszámodat és az egyedi jelszavadat!")
            
            # AUTOMATIKUS KITÖLTÉS: Ha az URL-ben jött járat, azt rakjuk be alapértelmezettnek (value=url_jarat)
            jarat_input = st.text_input("JÁRATSZÁM (vagy Admin):", value=url_jarat, key="login_jarat_field", placeholder="Pl. 4002 vagy admin")
            password_input = st.text_input("JELSZÓ / KÓD:", type="password", key="login_password_field", placeholder="••••••••")
            
            # TESZT ÜZEMMÓD EXTRA: Ha teszt linkről jött, kap egy gombot a szimulált belépéshez
            if url_teszt and jarat_input:
                st.info(f"🧪 Szimulált belépés észlelve a(z) {jarat_input} járathoz.")
                if st.button("🧪 TESZT BELÉPÉS JELSZÓ NÉLKÜL", type="primary", use_container_width=True):
                    
                    # Szuperbiztos metaadat és futárnév lekérés
                    meta_forras = st.session_state.get('meta_data')
                    if not isinstance(meta_forras, dict): 
                        meta_forras = {} # Ha None vagy nem szótár, kap egy üres szótárt
                    
                    pdf_futar_nev = meta_forras.get('futar_neve', meta_forras.get('futar', ''))
                    
                    # Ha van név a PDF-ben (pl. Szűcs István), akkor azonnal azt használjuk,
                    # ha nincs, akkor alapértelmezetten a te nevedet adjuk meg a teszthez
                    if pdf_futar_nev:
                        st.session_state.user_nev = pdf_futar_nev
                    else:
                        st.session_state.user_nev = "Szűcs István"
                    
                    st.session_state.bejelentkezve = True
                    # Kezeljük a QR-kódból érkező járatokat listaként
                    st.session_state.user_jarat_lista = [j.strip() for j in str(jarat_input).split(",") if j.strip()]
                    st.session_state.user_szerep = "futar"
                    
                    st.success(f"🧪 Sikeres teszt belépés! Név: {st.session_state.user_nev}")
                    st.rerun()

            if st.button("🔑 BIZTONSÁGOS BELÉPÉS", use_container_width=True):
                if not jarat_input or not password_input:
                    st.error("❌ Mindkét mező kitöltése kötelező!")
                else:
                    with st.spinner("⏳ Kapcsolódás a biztonsági szerverhez..."):
                        futar_adatok = _tiszta_futar_lista_letoltes(UGYFELKOR_SHEET_ID)
                    
                    talalt_futar = None
                    tisztitott_input_jarat = str(jarat_input).strip().lower()
                    tisztitott_input_pass = str(password_input).strip()
                    
                    for f in futar_adatok:
                        sheet_jarat = str(f.get('Járat', f.get('Jarat', ''))).strip().lower()
                        sheet_pass = str(f.get('PIN_Kod', '')).replace("'", "").strip()
                        
                        if sheet_pass.endswith('.0'):
                            sheet_pass = sheet_pass[:-2]
                        
                        if sheet_jarat == tisztitott_input_jarat and sheet_pass == tisztitott_input_pass:
                            talalt_futar = f
                            break
                    
                    if talalt_futar:
                        st.session_state.bejelentkezve = True
                        st.session_state.user_nev = talalt_futar.get('Név', 'Ismeretlen felhasználó')
                        
                        # Kezeljük a többszörös járatokat is a biztonság kedvéért (vesszővel elválasztva)
                        raw_jarat = str(talalt_futar.get('Járat', talalt_futar.get('Jarat', ''))).strip()
                        st.session_state.user_jarat_lista = [j.strip() for j in raw_jarat.split(",") if j.strip()]
                        
                        st.session_state.user_szerep = str(talalt_futar.get('Szerep', 'futar')).strip().lower()
                        
                        if "login_jarat_field" in st.session_state: del st.session_state["login_jarat_field"]
                        if "login_password_field" in st.session_state: del st.session_state["login_password_field"]
                        
                        st.success(f"Sikeres belépés! Üdvözlünk, {st.session_state.user_nev}!")
                        st.rerun()
                    else:
                        st.error("❌ Hibás járatszám vagy jelszó!")
        return

    # 10. Alapértelmezett háttér adatbázisok betöltése (Csak sikeres bejelentkezés után fut le)
    # --- AUTOMATIKUS IDŐUTAZÁS FIGYELŐ ÉS SESSION TISZTÍTÓ ---
    try:
        client = gspread.authorize(get_google_sheets_creds())
        sheet = client.open_by_key(SHEET_ID)
        ws_etlap = sheet.worksheet("Etlap_API")
        
        # Villámgyorsan lekérjük csak a legelső sort a felhőből (a dátumokat)
        nyers_fejlec = ws_etlap.row_values(1) 
        jelenlegi_het_trigger = "-".join(nyers_fejlec)
        
        # HA már van elmentett triggerünk, de az NEM egyezik a felhőben lévővel -> IDŐUTAZÁS TÖRTÉNT!
        if 'etlap_trigger_state' in st.session_state and st.session_state.etlap_trigger_state != jelenlegi_het_trigger:
            # Teljes tisztítótűz: eldobjuk a beragadt régi heti session adatokat
            if 'etlap_api_df' in st.session_state: del st.session_state['etlap_api_df']
            if 'master_df' in st.session_state: del st.session_state['master_df']
            if 'etelek_master_df' in st.session_state: del st.session_state['etelek_master_df']
            
            st.session_state.etlap_trigger_state = jelenlegi_het_trigger
        elif 'etlap_trigger_state' not in st.session_state:
            st.session_state.etlap_trigger_state = jelenlegi_het_trigger
            
    except Exception as e:
        # Ha a bejelentkezés még nem történt meg, vagy nincs net, kap egy ideiglenes triggert
        jelenlegi_het_trigger = "INITIAL"

    # Most már az 'if' golyóálló: ha fent töröltük a session-t a hétváltás miatt, akkor kötelezően be fog lépni ide!
    if 'master_df' not in st.session_state or 'etlap_api_df' not in st.session_state:
        with st.spinner("⏳ A Label Master adatbázisok inicializálása... Kérjük, várjon!"):
            try:
                # Mivel fent már megnyitottuk a sheet-et, nem kell újra authorizálni, használhatjuk a meglévőt
                
                # 1. Master Adatbázis betöltése
                m_df = pd.DataFrame(sheet.worksheet("Master_Adatbazis").get_all_records())
                m_df.columns = [col.strip().replace('\ufeff', '') for col in m_df.columns]
                st.session_state.etelek_master_df = m_df  
                st.session_state.master_df = m_df 
                
                # 2. Étlap API betöltése az okosított smart cache függvénnyel
                api_df = load_etlap_api_smart(SHEET_ID, columns_trigger=jelenlegi_het_trigger)
                
                if api_df is not None:
                    st.session_state.etlap_api_df = api_df
                    st.toast("✅ Alap adatbázisok sikeresen betöltve / frissítve!", icon="🔥")
                else:
                    raise Exception("Nem sikerült letölteni az Etlap_API-t.")
                    
            except Exception as e:
                st.warning(f"⚠️ Hiba a táblák betöltésekor: {e}")
                st.session_state.master_df = pd.DataFrame()
                st.session_state.etlap_api_df = pd.DataFrame()

    # Biztosítjuk, hogy a main() függvényen kívüli kódok is lássák a session_state-ben lévő adatokat
    global etlap_api_df, etelek_master_df, master_df, ugyfelkor_df, mdf
    etlap_api_df = st.session_state.get('etlap_api_df', pd.DataFrame())
    etelek_master_df = st.session_state.get('etelek_master_df', pd.DataFrame())
    master_df = etelek_master_df
    ugyfelkor_df = st.session_state.get('ugyfelkor_df', pd.DataFrame())
    mdf = st.session_state.get('mdf', pd.DataFrame())


    # =========================================================================
    # 📱 1. ÁG: QR-KÓDOS MOBIL NÉZET
    # =========================================================================
    if is_mobile_view:
        st.title("📱 Futár Terminál")
        st.caption(f"Bejelentkezve: {st.session_state.user_nev}")
        
        # ==============================================================================
        # 📊 INTELIGENS FUTÁR MŰSZERFAL (GLOBÁLIS MOBIL SIDEBAR - ÉLŐ GOOGLE SHEETS)
        # ==============================================================================
        with st.sidebar:
            st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>📊 Mai Műszerfal</h2>", unsafe_allow_html=True)
            
            # Alapadatok kiírása
            futar_nev_kiir = st.session_state.get('user_nev', 'Ismeretlen Futár')
            jarat_lista_kiir = st.session_state.get('user_jarat_lista', [])
            jarat_szoveg_kiir = ", ".join(map(str, jarat_lista_kiir)) if jarat_lista_kiir else "Nincs"
            
            st.write(f"👤 **Futár:** {futar_nev_kiir}")
            st.write(f"🚚 **Járat(ok):** {jarat_szoveg_kiir}")
            st.write("---")

            # --- ÉLŐ ADATOLVASÁS A GOOGLE SHEETS-BŐL ---
            osszes_cim = 0
            osszes_megallo = 0
            osszes_etel = 0
            forgalmi_ertek = 0
            jutalek = 0

            try:
                # Megnyitjuk a Mobil_Raklista fület, amit az asztali oldal mentett el
                sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR if 'SHEET_ID_UGYFELKOR' in locals() else SHEET_ID)
                ws_raklista = sh_ugyfelkor.worksheet("Mobil_Raklista")
                raklista_adatok = ws_raklista.get_all_records()
                
                if raklista_adatok:
                    import pandas as pd
                    df_mobil_calc = pd.DataFrame(raklista_adatok)
                    df_mobil_calc.columns = [c.strip() for c in df_mobil_calc.columns]
                    
                    # Tisztítjuk a neveket a Sheets-ben és a sessionben is a biztos egyezéshez
                    futar_keresett = str(futar_nev_kiir).strip().lower()
                    df_mobil_calc['Futar_Kereso'] = df_mobil_calc['Jarat_ID / Futar'].astype(str).str.strip().str.lower()
                    
                    # Kis/nagybetű független szűrés
                    df_sajat = df_mobil_calc[df_mobil_calc['Futar_Kereso'] == futar_keresett]
                    
                    # EXTRA BIZTONSÁGI HÁLÓ: Ha így is üres, de van "Szűcs István" a táblában
                    if df_sajat.empty:
                        felhasznalo_jaratai = [str(j).strip() for j in jarat_lista_kiir]
                        if "4002" in felhasznalo_jaratai or "4002" == str(st.session_state.get('user_jarat', '')):
                            df_sajat = df_mobil_calc[df_mobil_calc['Futar_Kereso'] == "szűcs istván"]

                    if not df_sajat.empty:
                        # 1. Ételek száma: dinamikusan a napi raklista adatokból
                        osszes_etel = int(pd.to_numeric(df_sajat['Terv_Darabszam'], errors='coerce').sum())
                        
                        # 2. MEGÁLLÓK ÉS CÍMEK DINAMIKUS SZÁMÍTÁSA (Több járatot és helyettesítést is kezelve!)
                        try:
                            # Kiolvassuk az Adatok fület, pont úgy, ahogy a mobil kiszállítási modul teszi
                            ws_adatok = sh_ugyfelkor.worksheet("Adatok")
                            df_adatok_all = pd.DataFrame(ws_adatok.get_all_records())
                            
                            if not df_adatok_all.empty:
                                # Egységesítjük az oszlopneveket space-ek nélkül
                                df_adatok_all.columns = [str(c).strip() for c in df_adatok_all.columns]
                                
                                # Megkeressük a Járat oszlopot
                                jarat_col_name = None
                                for c in df_adatok_all.columns:
                                    if 'járat' in c.lower() or 'jarat' in c.lower():
                                        jarat_col_name = c
                                        break
                                
                                # Lekérjük a session_state-ből az éppen aktív járatokat (lista)
                                aktiv_jaratok = st.session_state.get('szurt_jaratok', [])
                                if not aktiv_jaratok and 'jarat_id' in st.session_state:
                                    aktiv_jaratok = [st.session_state['jarat_id']]
                                
                                # Stringgé alakítjuk a járatokat a pontos illesztéshez
                                aktiv_jaratok_str = [str(j).strip() for j in aktiv_jaratok]
                                
                                if jarat_col_name and aktiv_jaratok_str:
                                    # Kiszűrjük az ÖSSZES olyan sort, ami az aktív járatok valamelyikéhez tartozik
                                    df_futar_cimei = df_adatok_all[df_adatok_all[jarat_col_name].astype(str).str.strip().isin(aktiv_jaratok_str)]
                                    
                                    if not df_futar_cimei.empty:
                                        # Megkeressük a Cím oszlopot
                                        cim_col_name = None
                                        for c in df_futar_cimei.columns:
                                            if 'cím' in c.lower() or 'cim' in c.lower():
                                                cim_col_name = c
                                                break
                                        
                                        if cim_col_name:
                                            # Megálló: az egyedi fizikai címek száma
                                            osszes_megallo = int(df_futar_cimei[cim_col_name].astype(str).str.strip().nunique())
                                            # Cím: az összes leadandó rendelési sor száma ezen a járaton / járatokon
                                            osszes_cim = len(df_futar_cimei)
                                        else:
                                            osszes_cim = len(df_futar_cimei)
                                            osszes_megallo = osszes_cim
                        except Exception as e_logisztika:
                            pass
                        
                        # Végső vészhelyzeti fallback: ha a fenti számítás valamiért 0-át adna vissza
                        if osszes_cim == 0:
                            for c in df_sajat.columns:
                                if 'cím' in c.lower() or 'cim' in c.lower():
                                    osszes_megallo = int(df_sajat[c].nunique())
                                    osszes_cim = len(df_sajat[c])
                                    break
                        
                        # Alapértelmezett pénzügyi értékek
                        forgalmi_ertek = 0
                        jutalek = 0
                        
                        # 🚀 KÍSÉRLET A MAI PONTOS PÉNZÜGYI ADATOK KIOLVASÁSÁRA A GOOGLE SHEETS-BŐL
                        try:
                            ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary")
                            summary_records = ws_summary.get_all_records()
                            
                            for s_row in summary_records:
                                summary_futar = str(s_row.get('Futar', s_row.get('futar', ''))).strip().lower()
                                if summary_futar == "szűcs istván" or summary_futar == futar_keresett:
                                    forgalmi_ertek = int(s_row.get('Forgalom', 0))
                                    jutalek = int(s_row.get('Jutalek', s_row.get('Jutalék', 0)))
                                    break
                        except Exception as sheets_err:
                            meta_forras = st.session_state.get('meta_data', {})
                            if isinstance(meta_forras, dict) and meta_forras.get('total_ertek', 0) > 0:
                                forgalmi_ertek = meta_forras.get('total_ertek', 0)
                                jutalek = meta_forras.get('futar_jutalek', 0)
            except Exception as e_global_dashboard:
                # Ez a külső try lezárása, ami eddig hiányzott!
                st.sidebar.error(f"⚠️ Műszerfal hiba: {e_global_dashboard}")

            # --- METRIKÁK MEGJELENÍTÉSE A KÉPERNYŐN ---
            st.subheader("💰 Pénzügy & Mennyiség")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.metric("📍 Tervezett megállók", f"{osszes_megallo} db")
                st.metric("🏠 Összes cím (ügyfél)", f"{osszes_cim} db")
            with col_s2:
                st.metric("📦 Összes étel", f"{osszes_etel} adag")
                st.metric("💵 Forgalom", f"{forgalmi_ertek:,} Ft".replace(",", " "))
                
            # A jutalékot kitesszük teljes szélességben kiemelve
            st.metric("⭐ Várható Jutalékod", f"{jutalek:,} Ft".replace(",", " "))
                
            st.write("---")

            # --- 2. FOLYAMATJELZŐ (Kiszállítás haladása) ---
            st.subheader("🏁 Kiszállítás Haladás")
            
            kesz_cimek_szama = 0
            for k in st.session_state.keys():
                if k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres":
                    kesz_cimek_szama += 1
                    
            if osszes_cim > 0:
                haladas_szazalek = min(1.0, kesz_cimek_szama / osszes_cim)
            else:
                haladas_szazalek = 0.0
                
            st.progress(haladas_szazalek)
            st.caption(f"Teljesítve: {kesz_cimek_szama} / {osszes_cim} cím ({int(haladas_szazalek * 100)}%)")
            st.write("---")

            # --- 3. MENET KÖZBENI SÜRGŐS HIBABEJELENTŐ ---
            st.subheader("⚠️ Probléma az úton?")
            with st.expander("🚨 SÜRGŐS HIBABEJELENTÉS"):
                st.write("Sérült, elcserélt vagy elhagyott étel esetén itt jelezheted a központnak:")
                from datetime import datetime
                
                st_hiba_tipus = st.selectbox("Hiba jellege:", ["Sérült étel (kifolyt/kilyukadt)", "Elcserélt étel", "Hiányzó/Elhagyott étel"], key="sidebar_hiba_tipus")
                st_hiba_vevo = st.text_input("Vevő neve / Címe:", placeholder="Pl. Kovács Péter, Fő utca 12.", key="sidebar_hiba_vevo")
                st_hiba_leiras = st.text_area("Rövid leírás (Melyik étel?):", placeholder="Pl. A zóna rántott hús doboza elrepedt, kifolyt.", key="sidebar_hiba_leiras")
                
                if st.button("🚨 HIBA KÜLDÉSE A DISZPÉCSERNEK", type="primary", use_container_width=True, key="sidebar_hiba_submit_btn"):
                    if not st_hiba_vevo or not st_hiba_leiras:
                        st.error("❌ Kérlek, add meg a vevőt és a leírást!")
                    else:
                        is_test_mode = st.query_params.get("test", "false") == "true" or st.session_state.get('teszt_uzemmod', False)
                        
                        if is_test_mode:
                            st.warning(f"🧪 **Teszt mód:** A hibát rögzítettük.")
                        else:
                            try:
                                sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
                                hibak_sheet = sh_ugyfelkor.worksheet("Hibajelentések")
                                most_ido = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                hibak_sheet.append_row([most_ido, futar_nev_kiir, jarat_szoveg_kiir, st_hiba_tipus, st_hiba_vevo, st_hiba_leiras])
                                st.success("✅ A hiba elküldve!")
                            except Exception as e:
                                st.error(f"Mentési hiba: {e}")

        # ==============================================================================
        # TAB-OK (FÜLEK) INDÍTÁSA
        # ==============================================================================
        tab1, tab2, tab3 = st.tabs(["1. Áruátvétel 📦", "2. Címekre szedés 📥", "3. Kiszállítás 🚚"])
        
        # --- 1. TAB: ÁRUÁTVÉTEL (Bekötve a tiszta, különálló mobil_modulok.py-ból) ---
        with tab1:
            render_mobil_aruatvetel(client)
            
        # --- 2. TAB: CÍMEKRE SZEDÉS (KISZERVEZVE A MODULBA) ---
        with tab2:
            render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR)
                
        # --- 3. TAB: KISZÁLLÍTÁS (Most már az éles, térképes modul fut) ---
        with tab3:
            render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR)
                
        if st.button("🚪 Kijelentkezés", key="mob_logout"):
            st.session_state.bejelentkezve = False
            st.rerun()

    # =========================================================================
    # 🖥️ 2. ÁG: TELJES ASZTALI / ADMINISZTRÁCIÓS NÉZET (INTEGRÁLT MENÜRENDSZER)
    # =========================================================================
    else:
        # Felhasználói státusz panel az oldalsáv tetejére
        st.sidebar.markdown(f"### 👤 {st.session_state.user_nev}")
        
        is_admin = st.session_state.user_szerep in ["admin", "superadmin"]
        
        if is_admin:
            st.sidebar.success("⭐ Adminisztrátor Mód")
        else:
            if 'user_jarat_lista' in st.session_state and st.session_state.user_jarat_lista:
                jaratok_szoveg = ", ".join(st.session_state.user_jarat_lista)
                st.sidebar.caption(f"🚚 Aktív járatok: {jaratok_szoveg}")
            else:
                st.sidebar.caption("🚚 Nincs járat hozzárendelve")
            
        if st.sidebar.button("🚪 Kijelentkezés", key="desktop_logout"):
            st.session_state.bejelentkezve = False
            if 'user_jarat_lista' in st.session_state:
                del st.session_state.user_jarat_lista
            st.rerun()
            
        # Oldalsáv vezérlők
        with st.sidebar:
            st.header("⚙️ Kezelés")
            
            # 🌟 ÚJ MENÜVÁLASZTÓ AZ ADMINOKNAK
            if is_admin:
                admin_funkcio = st.radio(
                    "📌 Válassz funkciót:",
                    ["📋 Raklista & Étlap Kezelés", "🚚 Logisztikai Központ & Stand"]
                )
            else:
                admin_funkcio = "📋 Raklista & Étlap Kezelés"
            
            st.divider()
            st.session_state.c_n = st.text_input("Futár Neve", st.session_state.c_n)
            st.session_state.c_p = st.text_input("Telefonszám", st.session_state.c_p)
            kivalasztott_datum = st.date_input("📅 Kiszállítás dátuma (Névnaphoz)")
            
            # ==================================================================
            # 🧪 GLOBÁLIS TESZT ÜZEMMÓD KAPCSOLÓ (A Kezelés blokk alján)
            # ==================================================================
            st.divider()
            
            if 'teszt_uzemmod' not in st.session_state:
                st.session_state.teszt_uzemmod = False
                
            st.session_state.teszt_uzemmod = st.toggle(
                "🧪 TESZT ÜZEMMÓD (Nincs mentés)", 
                value=st.session_state.teszt_uzemmod, 
                help="Ha bekapcsolod, sem a PDF feldolgozás, sem a mobil terminál nem fog írni a Google Sheets-be!"
            )
            
            if st.session_state.teszt_uzemmod:
                st.warning("⚠️ Adatbázis mentés letiltva (Asztali + Mobil)!")
            # ==================================================================
            
            st.divider()

            # ADMINISZTRÁCIÓS SZAKASZ (Csak jogosultaknak)
            if is_admin:
                st.subheader("🛡️ Adminisztrációs Központ")
                ev_most, het_most = get_latest_week_from_master(SHEET_ID_MASTER)
                
                if het_most < 24:
                    st.error(f"⚠️ Étlap figyelmeztetés: Csak a **{het_most}. hétig** van feltöltve!")
                    if st.button("🔄 Master Frissítése a 24. hétig"):
                        with st.spinner("Szinkronizálás folyamatban..."):
                            sync_master_database(SHEET_ID_MASTER, 2026, het_most + 1, 24)
                            st.success("Sikeres frissítés!")
                            st.rerun()
                else:
                    st.success(f"✅ Étlapok naprakészek ({het_most}. hétig betöltve).")

                with st.expander("🛠 Master Adatbázis Karbantartás"):
                    target_year = st.number_input("Év", min_value=2024, max_value=2030, value=2026)
                    start_w = st.number_input("Kezdő hét", min_value=1, max_value=52, value=1)
                    end_w = st.number_input("Záró hét", min_value=1, max_value=52, value=17)
                    if st.button("🚀 Master Adatbázis Építése"):
                        with st.spinner("Szinkronizálás..."):
                            sync_master_database(SHEET_ID_MASTER, target_year, start_w, end_w)
                            st.success("Kész!")

                with st.expander("👤 Felhasználó Kezelés"):
                    if 'futar_df' not in st.session_state:
                        st.session_state.futar_df = load_futar_from_sheets(SHEET_ID_UGYFELKOR)

                    df_to_edit = st.session_state.futar_df.astype(str)
                    edited_df_users = st.data_editor(
                        df_to_edit,
                        column_config={
                            "Szerep": st.column_config.SelectboxColumn(
                                "Szerep",
                                options=["futar", "admin", "superadmin"],
                                required=True,
                            ),
                            "PIN_Kod": st.column_config.TextColumn(
                                "PIN_Kod",
                                required=True
                            )
                        },
                        use_container_width=True,
                        num_rows="dynamic",
                        key="user_editor"
                    )

                    if st.button("💾 Módosítások mentése", key="save_users_btn"):
                        with st.spinner("Mentés..."):
                            if save_futar_to_sheets(edited_df_users, SHEET_ID_UGYFELKOR):
                                st.session_state.futar_df = edited_df_users
                                st.success("Sikeres mentés!")
                                st.rerun()
                            else:
                                st.error("Hiba történt.")

                with st.expander("💻 Fejlesztői eszközök"):
                    if st.button("Log fájl mutatása", use_container_width=True):
                        if os.path.exists(LOG_FILE):
                            with open(LOG_FILE, "r", encoding="utf-8") as f:
                                st.text_area("Naplóbejegyzések", "".join(f.readlines()[-100:]), height=200)
                    if st.button("🗑️ Log törlése", use_container_width=True):
                        if os.path.exists(LOG_FILE):
                            os.remove(LOG_FILE)
                            st.success("Napló törölve.")
                st.divider()

        # =========================================================================
        # 🏛️ FŐKÉPERNYŐ MEGJELENÍTÉSE A MENÜVÁLASZTÁS ALAPJÁN
        # =========================================================================
        if is_admin and admin_funkcio == "🚚 Logisztikai Központ & Stand":
            # Megnyitjuk a táblázatot gspread-el, mert a logisztikai központnak szüksége van rá
            logisztika_sheet_objektum = client.open_by_key(UGYFELKOR_SHEET_ID)
            render_logisztikai_kozpont(logisztika_sheet_objektum)
            
        else:
            # 📋 RAKLISTA GENERÁLÁS ÉS ÉTLAP KEZELÉS (A RÉGI MEGLÉVŐ FŐKÉPERNYŐD)
            # PDF FELTÖLTÉS SECTION
            st.subheader("📄 Új PDF-ek")
            up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
            
            # 🚀 FELDOLGOZÁS GOMB ÉS LOGIKA
            if up_files:
                if st.button("🚀 FELDOLGOZÁS"):
                    # 💥 Első lépésként azonnal töröljük a régi PDF-eket a memóriából a JÓ KULCSOKKAL!
                    for key in ['ready_label_pdf', 'ready_manifest_pdf', 'ready_raklista_pdf']:
                        if key in st.session_state:
                            del st.session_state[key]
                    
                    meta_auto = extract_all_meta(up_files)
                    st.session_state.meta_data = meta_auto
                    
                    ev = meta_auto.get('ev')
                    het = meta_auto.get('het')

                    if ev and het:
                        session_key = f"sync_{ev}_{het}"
                        if session_key not in st.session_state:
                            with st.spinner(f"Étlap szinkronizálása ({ev}/W{het})..."):
                                sync_interfood_etlap(ev, het, SHEET_ID)
                                st.session_state[session_key] = True

                    with st.spinner("Étlap adatok beolvasása..."):
                        etlap_adatok = load_etlap_from_sheets(SHEET_ID)
                        st.session_state.etlap_adatok = etlap_adatok

                        napi_kodok = set()
                        for kulcs in etlap_adatok.keys():
                            parts = kulcs.split("_")
                            if len(parts) > 1:
                                napi_kodok.add(parts[1].strip().upper())
                        st.session_state.napi_etlap_kodok = napi_kodok

                    all_rows = []
                    if 'user_jarat_lista' not in st.session_state:
                        st.session_state.user_jarat_lista = []

                    for f in up_files:
                        f.seek(0)
                        egyedi_jarat_re = re.compile(r'(\d{2,4})\.\s*járat|Nyomtatta:\s*(\d{2,4})')
                        with pdfplumber.open(f) as p_test:
                            t_test = p_test.pages[0].extract_text() or ""
                            m_test = egyedi_jarat_re.search(t_test)
                            fajl_sajat_jarata = (m_test.group(1) or m_test.group(2)) if m_test else None
                        
                        if fajl_sajat_jarata and fajl_sajat_jarata not in st.session_state.user_jarat_lista:
                            st.session_state.user_jarat_lista.append(fajl_sajat_jarata)

                        f.seek(0)
                        rows, _ = parse_interfood_pdf(f, napi_kodok)
                        if rows:
                            for r in rows:
                                r['Járat'] = fajl_sajat_jarata if fajl_sajat_jarata else ""
                            all_rows.extend(rows)

                    if all_rows:
                        df_temp = merge_data(all_rows)
                        with st.spinner("Ügyféladatok szinkronizálása..."):
                            mentett_meta = st.session_state.get('meta_data', None)
                            if mentett_meta and isinstance(mentett_meta, dict) and mentett_meta.get('jaratok'):
                                tartalek_jarat = mentett_meta['jaratok'][0]
                            else:
                                tartalek_jarat = None
                            
                            df_temp, m_df_friss = master_lista_szinkron(df_temp, UGYFELKOR_SHEET_ID, client, jarat_szam=tartalek_jarat)
                            st.session_state.master_df = m_df_friss
                        
                        st.session_state.mdf = df_temp
                        
                        # =========================================================================
                        # 📊 MOBIL MŰSZERFAL ADATAINAK DINAMIKUS KISZÁMÍTÁSA ÉS MENTÉSE (HISTÓRIA LOGIKA)
                        # =========================================================================
                        try:
                            # 1. API dátum kulcs kinyerése a metaadatokból
                            api_datum_kulcs = str(meta_auto.get('datum_kulcs', meta_auto.get('datum', kivalasztott_datum))).strip()
                            
                            # 2. Futár neve és járatok összegyűjtése a bejelentkezett felhasználó alapján
                            aktualis_futar = str(st.session_state.get('user_nev', 'Szűcs István')).strip()
                            
                            feltoltott_jaratok = []
                            if 'Járat' in df_temp.columns:
                                feltoltott_jaratok = df_temp['Járat'].dropna().astype(str).str.strip().unique().tolist()
                                feltoltott_jaratok = [j for j in feltoltott_jaratok if j != "" and j.lower() != 'nan']
                            jarat_szoveg = ", ".join(feltoltott_jaratok) if feltoltott_jaratok else "Nincs"

                            # 3. Összes egyedi cím és megálló számítása
                            szamitott_osszes_megallo = 0
                            szamitott_osszes_cim = 0
                            
                            if 'Cím' in df_temp.columns:
                                # Ha van futár oszlop, rászűrünk az aktuális futárra az egyedi megállóknál
                                if 'Feldolgozó Futár' in df_temp.columns:
                                    df_futar_szurt = df_temp[df_temp['Feldolgozó Futár'].astype(str).str.strip().str.lower() == aktualis_futar.lower()]
                                    if not df_futar_szurt.empty:
                                        szamitott_osszes_megallo = int(df_futar_szurt['Cím'].astype(str).str.strip().nunique())
                                        szamitott_osszes_cim = len(df_futar_szurt)
                                
                                # Fallback, ha nem volt futár szűrés vagy üres lett az eredmény
                                if szamitott_osszes_megallo == 0:
                                    szamitott_osszes_megallo = int(df_temp['Cím'].astype(str).str.strip().nunique())
                                    szamitott_osszes_cim = len(df_temp)
                            else:
                                st.warning("⚠️ A feltöltött adatokban nem található 'Cím' oszlop, a megállók száma 0 lett.")

                            # 4. Összes étel (adagszám) dinamikus összegzése
                            szamitott_osszes_etel = 0
                            darab_col = None
                            for c in df_temp.columns:
                                if 'darab' in c.lower() or 'adag' in c.lower() or 'mennyiseg' in c.lower() or 'db' in c.lower():
                                    darab_col = c
                                    break
                                    
                            if darab_col:
                                szamitott_osszes_etel = int(pd.to_numeric(df_temp[darab_col], errors='coerce').sum())
                            else:
                                st.warning("⚠️ Nem található darabszám vagy adag oszlop, az ételek száma 0 lett.")

                            # 5. Pénzügyi mutatók (Össz Forgalom, Beszedett KP és Borravaló)
                            szamitott_total_ertek = 0
                            szamitott_kp_forgalom = 0
                            szamitott_borravalo = int(st.session_state.get('futar_borravalo', 0))
                            
                            ertek_col = None
                            for c in df_temp.columns:
                                if 'érték' in c.lower() or 'ertek' in c.lower() or 'forgalom' in c.lower() or 'összeg' in c.lower():
                                    ertek_col = c
                                    break
                                    
                            if ertek_col:
                                szamitott_total_ertek = int(pd.to_numeric(df_temp[ertek_col], errors='coerce').sum())
                                szamitott_kp_forgalom = szamitott_total_ertek  # Alapértelmezetten mindent KP-nak tekintünk
                            else:
                                st.error("❌ Nem sikerült kiszámítani a napi forgalmat (hiányzó érték oszlop)! A pénzügyi mutatók 0-zva lettek.")

                        except Exception as e_calc:
                            st.error(f"⚠️ Hiba történt a statisztikák kiszámítása közben: {e_calc}")
                            api_datum_kulcs = str(kivalasztott_datum)
                            aktualis_futar = str(st.session_state.get('user_nev', 'Szűcs István'))
                            jarat_szoveg = "Hiba"
                            szamitott_osszes_megallo = 0
                            szamitott_osszes_cim = 0
                            szamitott_osszes_etel = 0
                            szamitott_total_ertek = 0
                            szamitott_kp_forgalom = 0
                            szamitott_borravalo = 0

                        # 🚀 JUTALÉK LOGIKA INTELLIGENS MEGHATÁROZÁSA (13% vs 14% bónusz sáv)
                        szamitott_jutalek = 0
                        import datetime
                        try:
                            target_sheet_id = SHEET_ID_UGYFELKOR if 'SHEET_ID_UGYFELKOR' in locals() else SHEET_ID
                            sh_ugyfelkor = client.open_by_key(target_sheet_id)
                            
                            # Új, 10 oszlopos tiszta struktúra (Online fizetések nélkül)
                            fejlec = ["Datum", "Futar", "Jaratok", "Tervezett_Megallok", "Osszes_Cim", "Osszes_Etel", "Forgalom_Osszes", "Beszedett_KP", "Borravalo", "Vart_Jutalek"]
                            cols_count = len(fejlec)
                            
                            if "Mobil_Summary" in [w.title for w in sh_ugyfelkor.worksheets()]:
                                ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary")
                                summary_records = ws_summary.get_all_records()
                            else:
                                ws_summary = sh_ugyfelkor.add_worksheet("Mobil_Summary", rows=500, cols=cols_count)
                                ws_summary.append_row(fejlec)
                                summary_records = []

                            # Aktuális hét határainak kiszámítása a bónusz sávhoz
                            ma_dt = datetime.datetime.strptime(api_datum_kulcs, "%Y-%m-%d")
                            het_kezdete = ma_dt - datetime.timedelta(days=ma_dt.weekday())
                            het_vege = het_kezdete + datetime.timedelta(days=6)
                            
                            eheti_eddigi_forgalom = 0
                            existing_row_index = None
                            
                            for idx, row in enumerate(summary_records, start=2):
                                r_date_str = str(row.get('Datum', '')).strip()
                                r_futar = str(row.get('Futar', '')).strip().lower()
                                
                                if r_futar == aktualis_futar.lower():
                                    try:
                                        r_dt = datetime.datetime.strptime(r_date_str, "%Y-%m-%d")
                                        if het_kezdete <= r_dt <= het_vege:
                                            if r_date_str == api_datum_kulcs:
                                                existing_row_index = idx
                                            else:
                                                eheti_eddigi_forgalom += int(pd.to_numeric(row.get('Forgalom_Osszes', 0), errors='coerce'))
                                    except:
                                        pass
                                        
                            # Heti halmozott forgalom ellenőrzése
                            teljes_eheti_forgalom = eheti_eddigi_forgalom + szamitott_total_ertek
                            
                            if teljes_eheti_forgalom >= 2100000:
                                jutalek_kulcs = 0.14
                                st.info(f"🎉 Gratulálunk! Az eheti összesített forgalom ({teljes_eheti_forgalom:,} Ft) elérte a limitet, a mai napra 14% jutalék jár!")
                            else:
                                jutalek_kulcs = 0.13
                                
                            szamitott_jutalek = int(round(szamitott_total_ertek * jutalek_kulcs))

                        except Exception as e_futar_logic:
                            st.error(f"⚠️ Nem sikerült ellenőrizni a heti jutaléksávot, alapértelmezett 13%-al számolunk. Hiba: {e_futar_logic}")
                            szamitott_jutalek = int(round(szamitott_total_ertek * 0.13))

                        # Memória frissítése az alkalmazáson belül
                        if 'meta_data' not in st.session_state or not isinstance(st.session_state.meta_data, dict):
                            st.session_state.meta_data = {}
                        st.session_state.meta_data.update({
                            'datum_kulcs': api_datum_kulcs,
                            'osszes_megallo': szamitott_osszes_megallo,
                            'osszes_cim': szamitott_osszes_cim,
                            'osszes_etel': szamitott_osszes_etel,
                            'total_ertek': szamitott_total_ertek,
                            'kp_forgalom': szamitott_kp_forgalom,
                            'borravalo': szamitott_borravalo,
                            'futar_jutalek': szamitott_jutalek
                        })

                        # 🚀 GOOGLE SHEETS MENTÉS VAGY UPDATE (NINCS .clear(), megmarad a múlt!)
                        if not st.session_state.get('teszt_uzemmod', False):
                            try:
                                uj_adat_sor = [
                                    api_datum_kulcs,
                                    aktualis_futar,
                                    jarat_szoveg,
                                    int(szamitott_osszes_megallo),
                                    int(szamitott_osszes_cim),
                                    int(szamitott_osszes_etel),
                                    int(szamitott_total_ertek),
                                    int(szamitott_kp_forgalom),
                                    int(szamitott_borravalo),
                                    int(szamitott_jutalek)
                                ]
                                
                                if existing_row_index:
                                    # Ha már létezik mai sor a futárnak, finoman felülírjuk az A-J tartományt
                                    cell_range = f"A{existing_row_index}:J{existing_row_index}"
                                    ws_summary.update(cell_range, [uj_adat_sor])
                                    st.success(f"🔄 Mobil_Summary sikeresen FRISSÍTVE: {api_datum_kulcs} - {aktualis_futar}")
                                else:
                                    # Új nap esetén csak hozzáfűzzük a meglévők alá
                                    ws_summary.append_row(uj_adat_sor)
                                    st.success(f"➕ Új napi rekord HOZZÁADVA a Mobil_Summary-hez: {api_datum_kulcs} - {aktualis_futar}")
                                    
                            except Exception as sheets_error:
                                st.error(f"⚠️ Nem sikerült az adatok feltöltése a Google Sheets-be: {sheets_error}")
                        else:
                            st.info("🧪 Teszt üzemmód aktív: A mentés átugorva.")
                        # =========================================================================
                        
                        if feltoltott_jaratok:
                            st.session_state.aktiv_jaratok = feltoltott_jaratok
                        
                        st.success("🎉 A menettervek feldolgozása és a felhő szinkronizáció sikeresen megtörtént!")

            st.divider()

            # FŐABLAK MEGJELENÍTÉSE
            if st.session_state.mdf is not None and not st.session_state.mdf.empty:
                role = check_user_role()
                df_view = st.session_state.mdf.copy()

                if role == "futar":
                    if 'Járat' in df_view.columns and 'user_jarat_lista' in st.session_state:
                        df_view = df_view[df_view['Járat'].astype(str).isin([str(j) for j in st.session_state.user_jarat_lista])].copy()
                
                if df_view.empty:
                    st.warning(f"✉️ Kedves {st.session_state.user_nev}! A mai napra nincsenek aktív címeid.")
                else:
                    if 'Sorrend' not in df_view.columns:
                        df_view['Sorrend'] = range(1, len(df_view) + 1)
                    
                    df_view['Sorrend'] = pd.to_numeric(df_view['Sorrend'], errors='coerce').fillna(999.0).astype(float)

                    for col in df_view.columns:
                        if col != 'Sorrend':
                            df_view[col] = df_view[col].astype(str).replace(['nan', 'None', '<NA>', '0.0', '0'], '')

                    df_view = df_view.sort_values(by='Sorrend').reset_index(drop=True)

                    preferred_order = ["Sorrend", "Ügyintéző", "Cím", "Telefon", "Pénz", "Rendelés", "Csoport", "Megjegyzés", "temp_id"]
                    actual_cols = df_view.columns.tolist()
                    final_column_order = [c for c in preferred_order if c in actual_cols] + [c for c in actual_cols if c not in preferred_order]
                    df_view = df_view[final_column_order]
                            
                # TÁBLÁZAT MEGJELENÍTÉSE
                edited_df = st.data_editor(
                    df_view,
                    column_order=final_column_order, 
                    column_config={
                        "Sorrend": st.column_config.NumberColumn(
                            "Sorrend",
                            help="Írj be tizedest (pl. 88.5) a beszúráshoz!",
                            format="%.1f",
                            step=0.1,
                        ),
                        "Csoport": st.column_config.TextColumn("Csoport"),
                        "Pénz": st.column_config.TextColumn("Pénz"),
                        "temp_id": None, 
                    },
                    num_rows="dynamic",
                    key=f"editor_{st.session_state.editor_key}",
                    use_container_width=True,
                    hide_index=True
                )

                # TÉRKÉP MEGJELENÍTÉSE
                with st.expander("🗺️ Útvonal megtekintése a térképen", expanded=False):
                    utvonal_terkep(df_napi=edited_df, sheet_id=UGYFELKOR_SHEET_ID, client=client) 

                st.subheader("🗄️ Ügyfélkör kezelése")
                gomb_col1, gomb_col2 = st.columns(2)

                with gomb_col1:
                    if st.button("🔄 Sorrend frissítése és újrasorszámozás", use_container_width=True):
                        logger.info("Ideiglenes napi sorrend újrarendezése a felületen...")
                        edited_df['Sorrend'] = pd.to_numeric(edited_df['Sorrend'], errors='coerce').fillna(999)
                        edited_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
                        edited_df['Sorrend'] = range(1, len(edited_df) + 1)
                        st.session_state.mdf = edited_df
                        st.session_state.editor_key += 1
                        st.success("🔄 A sorrend frissítve! A térkép és a PDF-ek az új sorrendet követik.")
                        st.rerun()

                with gomb_col2:
                    if st.button("💾 Módosított adatok (Név, Megjegyzés, Telefon) mentése", use_container_width=True):
                        logger.info("Adatmódosítások mentése a felhőbe tömeges frissítéssel...")
                        try:
                            sh = client.open_by_key(UGYFELKOR_SHEET_ID)
                            ws_ugyfel = sh.worksheet("Ugyfelkor")
                            
                            teljes_adat = ws_ugyfel.get_all_values()
                            if not teljes_adat:
                                st.error("❌ A Google Sheets táblázat üres vagy nem olvasható!")
                                st.stop()
                                
                            fejlec = teljes_adat[0]
                            
                            id_idx = fejlec.index("ID") if "ID" in fejlec else 0
                            nev_idx = fejlec.index("Név") if "Név" in fejlec else (fejlec.index("Nev") if "Nev" in fejlec else 1)
                            cim_idx = fejlec.index("Cím") if "Cím" in fejlec else (fejlec.index("Cim") if "Cim" in fejlec else 2)
                            tel_idx = fejlec.index("Telefon") if "Telefon" in fejlec else 5
                            csop_idx = fejlec.index("Csoport") if "Csoport" in fejlec else 6
                            megj_idx = fejlec.index("Megjegyzés") if "Megjegyzés" in fejlec else (fejlec.index("Megjegyzes") if "Megjegyzes" in fejlec else 7)
                            utolso_idx = fejlec.index("Utolso_Rendeles") if "Utolso_Rendeles" in fejlec else None
                            
                            sheets_id_map = {str(teljes_adat[i][id_idx]).strip(): i for i in range(1, len(teljes_adat))}
                            
                            def tiszta_id_szoveg(val):
                                if pd.isna(val) or val == '': return ''
                                val_str = str(val).strip()
                                if val_str.endswith('.0'): val_str = val_str[:-2]
                                return val_str

                            edited_df_clean = edited_df.copy()
                            if 'ID' not in edited_df_clean.columns:
                                edited_df_clean = edited_df_clean.reset_index()
                                if 'index' in edited_df_clean.columns: edited_df_clean = edited_df_clean.rename(columns={'index': 'ID'})
                                elif 'level_0' in edited_df_clean.columns: edited_df_clean = edited_df_clean.rename(columns={'level_0': 'ID'})

                            if 'ID' not in edited_df_clean.columns:
                                st.error("⚠️ Nem található 'ID' nevű oszlop a szerkesztett adatokban!")
                                st.stop()
                                
                            edited_df_clean['ID'] = edited_df_clean['ID'].apply(tiszta_id_szoveg)
                            módosult_darab = 0
                            
                            for _, row in edited_df_clean.iterrows():
                                current_id = row['ID']
                                if not current_id or current_id not in sheets_id_map: continue
                                
                                sor_mátrix_idx = sheets_id_map[current_id]
                                elerheto_oszlopok = row.index.tolist()
                                
                                if 'Név' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][nev_idx] = str(row['Név']).strip()
                                elif 'Nev' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][nev_idx] = str(row['Nev']).strip()
                                
                                if 'Cím' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][cim_idx] = str(row['Cím']).strip()
                                elif 'Cim' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][cim_idx] = str(row['Cim']).strip()
                                
                                if 'Telefon' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][tel_idx] = str(row['Telefon']).strip()
                                if 'Csoport' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][csop_idx] = str(row['Csoport']).strip()
                                
                                if 'Megjegyzés' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][megj_idx] = str(row['Megjegyzés']).strip()
                                elif 'Megjegyzes' in elerheto_oszlopok: teljes_adat[sor_mátrix_idx][megj_idx] = str(row['Megjegyzes']).strip()
                                
                                # Kézi adatmódosításnál NEM írjuk felül az Utolso_Rendeles-t a mai nappal, 
                                # mert az elrontaná a valós szállítási napok követhetőségét! Érintetlenül hagyjuk.
                                    
                                módosult_darab += 1
                                
                                for session_key in ['ugyfelkor_df', 'mdf', 'master_ugyfelkor_df']:
                                    if session_key in st.session_state and st.session_state[session_key] is not None:
                                        try:
                                            df = st.session_state[session_key]
                                            if not df.empty and 'ID' in df.columns:
                                                mask = df['ID'].astype(str) == str(current_id)
                                                if 'Név' in elerheto_oszlopok: df.loc[mask, 'Név'] = str(row['Név']).strip()
                                                if 'Cím' in elerheto_oszlopok: df.loc[mask, 'Cím'] = str(row['Cím']).strip()
                                                if 'Telefon' in elerheto_oszlopok: df.loc[mask, 'Telefon'] = str(row['Telefon']).strip()
                                                if 'Megjegyzés' in elerheto_oszlopok: df.loc[mask, 'Megjegyzés'] = str(row['Megjegyzés']).strip()
                                        except:
                                            pass

                            if módosult_darab > 0:
                                # ------------------------------------------------------------------
                                # INNEN INDUL A MENTÉS ELŐTTI AUTOMATIKUS TÍPUSTISZTÍTÓ SZŰRŐNK!
                                # ------------------------------------------------------------------
                                # Visszaalakítjuk DataFrame-mé az adatokat, hogy átengedhessük a központi tisztítón
                                df_teljes_tisztitasra = pd.DataFrame(teljes_adat[1:], columns=fejlec)
                                
                                # Átfuttatjuk a kötelező szigorú szűrőnkön
                                df_teljes_tisztitott = kotelezo_ugyfelkor_formatum_tisztitas(df_teljes_tisztitasra)
                                
                                # Visszaalakítjuk a tisztított fésült listát a Google Sheets formátumra (fejléccel együtt)
                                tiszta_mentendo_lista = [fejlec] + df_teljes_tisztitott.values.tolist()
                                
                                # Mentés a Google Sheets-be szigorúan RAW formátumban (hogy a stringek szövegek maradjanak)
                                ws_ugyfel.update('A1', tiszta_mentendo_lista, value_input_option='RAW')
                                # ------------------------------------------------------------------
                                
                                if 'google_data_loaded' in st.session_state:
                                    del st.session_state['google_data_loaded']
                                    
                                st.success(f"🎉 Siker! Összesen {módosult_darab} ügyfél adatai formázva és elmentve a felhőbe, 1 API hívással!")
                                st.balloons()
                                st.rerun()
                            else:
                                st.warning("A szerkesztett adatok ID-jai nem találhatók meg a törzslistában.")
                        except Exception as e:
                            st.error(f"Hiba történt a mentés során: {e}")

                st.divider()

                # PDF DOWNLOADS SECTION
                meta = st.session_state.meta_data if isinstance(st.session_state.meta_data, dict) else {}
                meta['datum_iso'] = str(kivalasztott_datum)
                jaratok_listaja = meta.get('jaratok', [])
                aktualis_jaratok = ", ".join(jaratok_listaja) if jaratok_listaja else "N/A"

                st.info(f"Észlelt járatok a PDF-ekből: **{aktualis_jaratok}** | Időpont: **{meta.get('ev', '')}. {meta.get('het', '')}. hét**")

                if 'napi_etlap_kodok' in st.session_state and st.session_state.napi_etlap_kodok:
                    with st.expander("🍱 Aktuális étlap kódok"):
                        kodok_lista = sorted(list(st.session_state.napi_etlap_kodok))
                        cols = st.columns(5)
                        for i, kod in enumerate(kodok_lista):
                            cols[i % 5].code(kod)
                elif meta.get('ev') and meta.get('het'):
                    st.caption("💡 Az étlap kódok automatikusan frissülnek a '🚀 FELDOLGOZÁS' gomb megnyomásakor.")

                # --- SORTÖRÉS-BIZTOS ÉTEL- ÉS KELLÉKKERESŐ DEBUGGER (FÁZIS 3) ---
                with st.expander("🔍 Kellék Kereső Debug Panel (Fázis 3)", expanded=True):
                    api_kulcs = meta.get('api_datum_kulcs', 'NINCS') # Pl: "2026.05.29."
                    st.write(f"Kiválasztott API dátum kulcs: `{api_kulcs}`")
                    
                    if etlap_api_df is not None:
                        # Tisztított számjegyek a keresett dátumból (pl: "20260529")
                        keresett_nap_szamokkal = "".join(filter(str.isdigit, api_kulcs))
                        
                        # Megkeressük az oszlopot úgy, hogy a cellán belüli sortöréseket szóközre cseréljük és kiszedjük a számokat
                        napi_oszlop = None
                        for col in etlap_api_df.columns:
                            clean_col_name = str(col).replace('\r', '').replace('\n', ' ').strip()
                            col_szamok = "".join(filter(str.isdigit, clean_col_name))
                            
                            if keresett_nap_szamokkal and keresett_nap_szamokkal in col_szamok:
                                napi_oszlop = col
                                break
                        
                        if napi_oszlop:
                            st.success(f"✔ Megtalált napi oszlop (sortöréssel együtt): `{napi_oszlop.replace('\n', ' ')}`")
                        else:
                            st.error(f"❌ Nem található oszlop a(z) `{keresett_nap_szamokkal}` számokkal!")
                            st.write("Rendelkezésre álló oszlopok nyers számai:")
                            st.write({str(c).replace('\n', ' '): "".join(filter(str.isdigit, str(c))) for c in etlap_api_df.columns})
                    else:
                        st.error("Az Etlap_API táblázat nincs betöltve!")

                    st.write("---")
                    st.write("📌 **Ügyfelek ellenőrzése a megtisztított oszlop alapján:**")
                    
                    for idx, r in edited_df.dropna(subset=['Rendelés_Full']).iterrows():
                        rendeles_szoveg = str(r.get('Rendelés_Full', ''))
                        
                        if '*' in rendeles_szoveg:
                            st.write(f"**Ügyfél:** {r.get('Név', 'Névtelen')} (Sor: {idx}) ➔ Rendelés: `{rendeles_szoveg}`")
                            
                            # Rendelések szétszedése (Ünnepi üzemmód miatt mindent nézünk, ami a stringben van)
                            tisztitott_szoveg = rendeles_szoveg.replace('|', ',').replace('Pé:', '').replace('Szo:', '')
                            reszek = [x.strip() for x in tisztitott_szoveg.split(',') if x.strip()]
                            
                            for resz in reszek:
                                if '*' in resz:
                                    # Kód kinyerése (pl: 1-E1K* -> E1K)
                                    kod_match = re.search(r'-([A-Z0-9]+)\*', resz.upper())
                                    if not kod_match:
                                        kod_match = re.search(r'([A-Z0-9]+)\*', resz.upper())
                                        
                                    if kod_match:
                                        t_kod = kod_match.group(1).strip()
                                        st.write(f"  • Észlelt csillagos kód: `{t_kod}`")
                                        
                                        if etlap_api_df is not None and napi_oszlop:
                                            # Keresés az API tábla 1. oszlopában
                                            e_sor = etlap_api_df[etlap_api_df.iloc[:, 0].astype(str).str.strip().str.startswith(t_kod, na=False)]
                                            
                                            if not e_sor.empty:
                                                etel_nev = str(e_sor.iloc[0][napi_oszlop]).strip()
                                                tisztitott_nev = clean_text(etel_nev)
                                                st.write(f"    ➔ 🍲 API Ételnév: `{etel_nev}`")
                                                st.write(f"    ➔ 🧹 Tisztított név: `{tisztitott_nev}`")
                                                
                                                # Keresés a Masterben
                                                if master_df is not None:
                                                    m_row = master_df[master_df['Tisztított Név'] == tisztitott_nev]
                                                    if not m_row.empty:
                                                        kellek = m_row.iloc[0].get('Kellék', 'ÜRES')
                                                        st.success(f"    ➔ 🎉 **MEGTALÁLT KELLÉK: {kellek}**")
                                                    else:
                                                        st.error(f"    ➔ ❌ Nem található ez a név a Master_Adatbazisban!")
                                            else:
                                                st.error(f"    ➔ ❌ A(z) `{t_kod}` kód nincs az API táblázatban!")
                # ------------------------------------

                # 🚀 1. LÉPÉS: Egy közös indító gomb a PDF-ek előkészítéséhez
                st.write("")
                if st.button("🚀 DOKUMENTUMOK ÉS RAKLISTA GENERÁLÁSA", type="primary", use_container_width=True):
                    with st.spinner("⏳ PDF-ek generálása és adatok szinkronizálása folyamatban..."):
                        if 'nevnapok_df' not in st.session_state or st.session_state.nevnapok_df.empty:
                            st.session_state.nevnapok_df = pd.DataFrame()
                            st.session_state.keresztnevek_df = pd.DataFrame()

                        try:
                            label_pdf_buf = create_label_pdf(
                                edited_df, st.session_state.c_n, st.session_state.c_p, meta, 
                                st.session_state.etelek_master_df, st.session_state.nevnapok_df, 
                                st.session_state.keresztnevek_df, st.session_state.etlap_api_df
                            )
                            st.session_state['ready_label_pdf'] = label_pdf_buf.getvalue() if label_pdf_buf else None
                            
                            manifest_pdf_buf = create_manifest_pdf(edited_df, st.session_state.c_n, meta)
                            st.session_state['ready_manifest_pdf'] = manifest_pdf_buf.getvalue() if manifest_pdf_buf else None
                            
                            raklista_pdf_buf = create_raklista_pdf(edited_df, aktualis_jaratok, meta, client.open_by_key(SHEET_ID_UGYFELKOR))
                            st.session_state['ready_raklista_pdf'] = raklista_pdf_buf.getvalue() if raklista_pdf_buf else None
                            
                            st.success("✅ Minden dokumentum sikeresen elkészült és a Google Sheets frissítve!")
                        except Exception as pdf_err:
                            st.error(f"❌ Hiba történt a PDF-ek generálása közben: {pdf_err}")

                # 🚀 2. LÉPÉS: Ha a PDF-ek készen vannak a memóriában, megjelenítjük a letöltő gombokat
                if st.session_state.get('ready_label_pdf') and st.session_state.get('ready_manifest_pdf') and st.session_state.get('ready_raklista_pdf'):
                    st.write("### 📥 Elkészült fájlok letöltése:")
                    dl_c1, dl_c2, dl_c3 = st.columns(3)
                    
                    dl_c1.download_button(
                        "📄 ETIKETTEK LETÖLTÉSE", 
                        data=st.session_state['ready_label_pdf'],
                        file_name="etikettek.pdf", 
                        mime="application/pdf",
                        use_container_width=True
                    )
                    
                    dl_c2.download_button(
                        "📋 MENETTERV LETÖLTÉSE", 
                        data=st.session_state['ready_manifest_pdf'],
                        file_name="menetterv.pdf", 
                        mime="application/pdf",
                        use_container_width=True
                    )
                    
                    dl_c3.download_button(
                        "📊 RAKLISTA LETÖLTÉSE", 
                        data=st.session_state['ready_raklista_pdf'],
                        file_name="raklista.pdf", 
                        mime="application/pdf",
                        use_container_width=True
                    )

                # --- QR-KÓD GENERÁLÁS A MOBIL NÉZETHEZ ---
                st.write("---")
                st.subheader("📱 Mobil Terminál Indítása")
                
                alap_url = "https://interfood-menetterv-etikett-generator.streamlit.app" 
                
                # Szuperbiztos járat_id lekérés a listás struktúrából
                jarat_id = ""
                
                # 1. Elsődlegesen megnézzük a PDF beolvasásból mentett adatokat (session_state)
                meta_forras = st.session_state.get('meta_data', {})
                jarat_lista = meta_forras.get('jaratok', []) # Ez egy lista, pl: ['12'] vagy ['12', '14']
                
                if jarat_lista:
                    # Ha több járat van (helyettesítés), vesszővel elválasztva fűzzük be a linkbe (pl: 12,14)
                    jarat_id = ",".join(str(j) for j in jarat_lista)
                
                # 2. Ha a PDF-ből nem jött semmi, megnézzük a manuális választót (ha van ilyen)
                if not jarat_id:
                    if 'valasztott_jarat' in st.session_state:
                        jarat_id = str(st.session_state.valasztott_jarat)
                
                # Dinamikus teszt paraméter átadása a linknek, ha az asztali gépen aktív a kapcsoló
                if st.session_state.get('teszt_uzemmod', False):
                    mobil_link = f"{alap_url}/?view=mobile&jarat={jarat_id}&test=true"
                else:
                    mobil_link = f"{alap_url}/?view=mobile&jarat={jarat_id}"
                
                import qrcode
                from io import BytesIO
                
                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(mobil_link)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                
                buf = BytesIO()
                img.save(buf, format="PNG")
                byte_im = buf.getvalue()
                
                qr_col1, qr_col2 = st.columns([2, 1])
                with qr_col1:
                    # Kis extra figyelmeztetés a felületre, hogy ne tévesszen meg
                    if st.session_state.get('teszt_uzemmod', False):
                        st.warning("🧪 **A QR-kód TESZT ÜZEMMÓDRA van felkészítve!** A telefonod nem fog éles adatokat módosítani.")
                    
                    st.markdown(f"""
                    💡 **Szkenneld be ezt a QR-kódot a telefonoddal**, hogy megnyisd a **Futár Terminált**!
                    * Automatikusan a mobilra optimalizált nézet fog megnyílni.
                    * A futár azonnal eléri az áruátvételt és a ládázást a **{jarat_id}** járathoz.
                    * Direkt link: [{mobil_link}]({mobil_link})
                    """)
                with qr_col2:
                    st.image(byte_im, caption="Szkenneld be a mobil nézethez", width=180)
                
if __name__ == "__main__":
    main()
