import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import requests
import PIL.ImageDraw
import openpyxl
import os
import gspread
import base64
import unicodedata
import folium
import logging
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from streamlit_folium import st_folium
from datetime import datetime
from gspread_dataframe import set_with_dataframe
from google.oauth2 import service_account
from google.oauth2.service_account import Credentials
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Frame, KeepInFrame, Flowable, PageBreak
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget

def check_user_role():
    """Visszaadja a felhasználó szerepkörét."""
    # Ha nincs bejelentkezve, alapértelmezett a 'futar'
    role = st.session_state.get('user_szerep', 'futar')
    
    # Itt ellenőrizzük, hogy a te neved szerepel-e a "Szuper Admin" listán
    # Írd be a saját felhasználói nevedet ide (ami a rendszerben van):
    if st.session_state.get('user_nev') == "SajátNeved": 
        return "superadmin"
        
    return role

def biztonsagos_koordinata_tisztito(val):
    """
    Minden létező koordináta formátumot (sima szám, magyar vesszős, 
    szimpla vagy dupla aposztrófos hibákat) tiszta float számmá alakít,
    és ellenőrzi az országos kompatibilitást (Magyarország geofence).
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() == "none" or s == "0" or s == "0.0":
        return None
        
    # Letakarítjuk az összes szimpla és dupla aposztrófot, backticket
    s = s.replace("'", "").replace('"', '').replace('`', '')
    # Magyar tizedesvessző kicserélése pontra
    s = s.replace(",", ".")
    
    try:
        f = float(s)
        
        # 🌍 ORSZÁGOS KOMPATIBILITÁSÚ GEODEKOR (Magyarország határa)
        # Ha a szám valamiért egybefüggő 8-9 jegyű egész számként maradt (pl. 475271541)
        if abs(f) > 1000:
            # Ha 47-tel vagy 46-tal kezdődik (szélesség)
            if str(abs(int(f))).startswith(('46', '47', '48')):
                f = f / 10000000 if len(str(int(f))) >= 9 else f / 1000000
            # Ha 16 és 22 között kezdődik (hosszúság)
            elif str(abs(int(f))).startswith(('16', '17', '18', '19', '20', '21', '22')):
                f = f / 10000000 if len(str(int(f))) >= 9 else f / 1000000
        
        # Szigorú magyarországi kerítés ellenőrzés
        # Lat: 45.5 - 48.8 | Lon: 16.0 - 23.0
        if 45.5 <= f <= 48.8 or 16.0 <= f <= 23.0:
            return round(f, 7)
        else:
            return None # Ha kiesik az országból, eldobjuk a hibás értéket
    except:
        return None

# 2. LOGGOLÁS BEÁLLÍTÁSA
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

# --- GOOGLE SHEETS KONFIGURÁCIÓ ---
SHEET_ID_MASTER = "1bZrtgqROYijYhyFOFrqYeSTUAsGqZU6GLijObJ1En0o"
SHEET_ID_UGYFELKOR = "1nK0OLzVzEFY5bSLhMFfGgs4tOgMEueBgXeb9JUbLSN8"

# --- ADATBÁZIS SEGÉDFÜGGVÉNYEK ---
def get_latest_week_from_master(sheet_id):
    """Kinyeri a legnagyobb hetet a 'wXX' formátumú szövegekből."""
    try:
        sheet = client.open_by_key(sheet_id).worksheet("Master_Adatbazis")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # 🟢 EZT ÍRD ÁT A PONTOS OSZLOPNEVEDRE!
        oszlop_nev = "Kódok és Árak" 
        
        if oszlop_nev not in df.columns:
            # Ha ezt látod a képernyőn, akkor nem egyezik a név
            st.error(f"Hiba: Az oszlop '{oszlop_nev}' nem található. Elérhetőek: {df.columns.tolist()}")
            return 2026, 0

        all_weeks = []
        for cell_content in df[oszlop_nev].astype(str):
            weeks = re.findall(r'w(\d+)', cell_content)
            all_weeks.extend([int(w) for w in weeks])
            
        if not all_weeks:
            return 2026, 0
            
        return 2026, max(all_weeks)
    except Exception as e:
        # 🟢 Hogy lásd a valódi hibát (pl. engedélyezési hiba), írassuk ki:
        st.error(f"Hiba történt: {e}")
        return 2026, 0
        
# ==============================================================================
# 4. GOOGLE SHEETS KAPCSOLAT ÉS ADATOK BETÖLTÉSE (MAXIMÁLIS KVÓTAVÉDELEMMEL)
# ==============================================================================
import gspread
import pandas as pd
import time
from google.oauth2.service_account import Credentials

# CSAK AKKOR TÖLTÜNK LE, HA MÉG EBBEN A MUNKAMENETBEN NEM TÖRTÉNT MEG
if "google_data_loaded" not in st.session_state:
    with st.spinner("🔄 Alapadatok biztonságos betöltése... (Kvótakímélő mód aktív)"):
        try:
            # Hitelesítés összeállítása
            if "gcp_service_account" in st.secrets:
                creds_dict = dict(st.secrets["gcp_service_account"])
            else:
                creds_dict = dict(st.secrets)

            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

            creds = Credentials.from_service_account_info(creds_dict, scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ])
            client = gspread.authorize(creds)
            
            # --- 1. TÁBLÁZAT: Master Data (Biztonsági szünetekkel) ---
            sh_master = client.open_by_key(SHEET_ID_MASTER)
            time.sleep(2.0)  # Emelt szünet a Google API-nak
            
            ws_etlap = sh_master.worksheet("Etlap")
            st.session_state.etlap_api_df = pd.DataFrame(ws_etlap.get_all_records())
            time.sleep(2.0)
            
            ws_etelek = sh_master.worksheet("Master_Adatbazis")
            st.session_state.etelek_master_df = pd.DataFrame(ws_etelek.get_all_records())
            time.sleep(2.0)
            
            ws_nevnapok = sh_master.worksheet("Nevnapok")
            st.session_state.nevnapok_df = pd.DataFrame(ws_nevnapok.get_all_records())
            time.sleep(2.0)
            
            ws_keresztnevek = sh_master.worksheet("Keresztnevek")
            st.session_state.keresztnevek_df = pd.DataFrame(ws_keresztnevek.get_all_records())
            time.sleep(1.0)
            
            # --- JAVÍTÁS: Nem töltjük le az ügyfélkört előre az indításkor! ---
            # Kezdetben csak egy üres vázat hozunk létre a session_state-ben, nehogy összeomoljon az app.
            # Ezt a PDF feldolgozása gomb (vagy a Karbantartó panel) fogja frissíteni valódi adatokkal.
            if "ugyfelkor_df" not in st.session_state or st.session_state.ugyfelkor_df is None:
                ures_vaz = pd.DataFrame(columns=['ID', 'Név', 'Cím', 'Lat', 'Lon', 'Telefon', 'Csoport', 'Megjegyzés'])
                st.session_state.ugyfelkor_df = ures_vaz
                st.session_state.mdf = ures_vaz
            
            # Megjelöljük a sikeres betöltést
            st.session_state.google_data_loaded = True
            st.success("✅ Alapadatok sikeresen szinkronizálva!")
            time.sleep(0.5)
            st.rerun()

        except Exception as e:
            st.error(f"❌ Hiba a táblák betöltésekor: {e}")
            st.stop()

# Globális változók biztonságos átadása default értékekkel (ha még üresek lennének)
etlap_api_df = st.session_state.get('etlap_api_df', pd.DataFrame())
etelek_master_df = st.session_state.get('etelek_master_df', pd.DataFrame())
nevnapok_df = st.session_state.get('nevnapok_df', pd.DataFrame())
keresztnevek_df = st.session_state.get('keresztnevek_df', pd.DataFrame())
ugyfelkor_df = st.session_state.get('ugyfelkor_df', pd.DataFrame())
mdf = st.session_state.get('mdf', pd.DataFrame())

# 2. Ügyfelek, címek, GPS, sorrend (Etikett_Ugyfelkor_DB)
UGYFELKOR_SHEET_ID = "1nK0OLzVzEFY5bSLhMFfGgs4tOgMEueBgXeb9JUbLSN8"

# --- GEOCODING SETUP ---
geolocator = Nominatim(user_agent="futarszoli_app")
logger.info("Geolocator inicializálva.")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.5)

# Itt hozzuk létre üresen, minden függvényen kívül
client = None 

def get_coordinates(address):
    """
    Lekéri a megadott cím koordinátáit a Nominatim segítségével, 
    hibakezeléssel és naplózással kiegészítve.
    A GYÖKÉROK JAVÍTÁSA: Kényszerített ponttal ellátott String formátumot ad vissza,
    hogy a Google Sheets/Excel ne tudja tizedesvesszővé alakítani!
    """
    try:
        # Itt a 'geocode' objektumot használjuk, ami a RateLimiter-en keresztül fut
        location = geocode(address) 
        
        if location:
            # Szöveggé alakítjuk fix 7 tizedesjeggyel, ponttal elválasztva
            # Az elejére rakott apostróffal (') kényszerítjük a Google Sheets-et a String tárolásra!
            str_lat = f"'{location.latitude:.7f}"
            str_lon = f"'{location.longitude:.7f}"
            
            logger.info(f"Cím sikeresen feloldva: {address} -> Lat: {str_lat}, Lon: {str_lon}")
            return str_lat, str_lon
        else:
            logger.warning(f"Nem található koordináta a címhez: {address}")
            return None, None
            
    except Exception as e:
        logger.error(f"Váratlan hiba a geocoding során ({address}): {e}")
        return None, None

def tisztitott_cim_lekerese(nyers_szoveg):
    if not nyers_szoveg:
        return ""
    # Tisztítás a felesleges karakterektől
    szoveg = nyers_szoveg.replace('$', '').strip()
    
    # REGEX: Irányítószám (4 szám) + Város + Utca + Házszám
    # Ez a minta megengedi a pontokat az utca után és keresi a számokat utána
    minta = r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-áéíóöőúüű]+\s*,\s*[^,]+?\s\d+[a-zA-Z0-9\/\-\.]*)'
    match = re.search(minta, szoveg)
    
    if match:
        return match.group(1).strip()
    
    # Ha a bonyolult minta nem talál semmit, egy egyszerűbb vágás, ami nem bántja a házszámot
    # Csak a tipikus emelet/ajtó kulcsszavaktól vágunk
    tisztitott = szoveg.split('. fsz')[0].split('. fszt')[0].split(', fsz')[0]
    return tisztitott.strip()

# ==============================================================================
# 🟢 FUTÁR JOGOSULTSÁGOK LETÖLTÉSE A GOOGLE SHEETS-BŐL
# ==============================================================================
@st.cache_data(ttl=300)  # 5 percig őrzi meg a memóriában a futárokat, hogy védje a kvótát
def _tiszta_futar_lista_letoltes(sheet_id):
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
    else:
        creds_dict = dict(st.secrets)
        
    if "private_key" in creds_dict: 
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds", 
        "https://www.googleapis.com/auth/drive"
    ])
    local_client = gspread.authorize(creds)
    sh = local_client.open_by_key(sheet_id)
    
    try:
        ws_futarok = sh.worksheet("Futárok")
        return ws_futarok.get_all_records()
    except Exception as e:
        return []

# ==============================================================================
# 🟢 1. AZ ÜGYFÉLKÖR BEOLVASÁSÁNAK GYORSÍTÓTÁRAZÁSA (API VÉDELEM)
# Ez teljesen kívül helyezkedik el, így a Streamlit képes megfelelően cache-elni!
# ==============================================================================
@st.cache_data(ttl=600)
def _tiszta_ugyfelkor_letoltes(sheet_id):
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
    else:
        creds_dict = dict(st.secrets)
        
    if "private_key" in creds_dict: 
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds", 
        "https://www.googleapis.com/auth/drive"
    ])
    local_client = gspread.authorize(creds)
    sh = local_client.open_by_key(sheet_id)  
    ws_ugyfel = sh.worksheet("Ugyfelkor")
    
    try:
        records = ws_ugyfel.get_all_records(value_render_option='UNFORMATTED_VALUE')
    except:
        records = ws_ugyfel.get_all_records()
        
    return records

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

    # --- 3. LÉPÉS: ÚJ ÜGYFELEK ÉSZLELÉSE ÉS AUTOMATIKUS GEOMAPOLÁSA ---
    uj_ugyfelek = []
    for _, row in df_napi.iterrows():
        u_id = str(row['ID'])
        if not u_id: 
            continue
            
        if master_df.empty or u_id not in master_df['ID'].values:
            nev = row.get('Ügyintéző', row.get('Név', row.get('Nev', 'Ismeretlen név')))
            eredeti_cim = str(row.get('Cím', row.get('Cim', '')))
            
            try:
                keresesi_cim = tisztitott_cim_lekerese(eredeti_cim)
            except NameError:
                keresesi_cim = eredeti_cim
            
            logger.info(f"✨ Új ügyfél észleléve: {nev} ({u_id}). Koordináták lekérése...")
            st.info(f"Új ügyfél fedezve fel: {nev} - GPS lekérés...")
            
            try:
                lat, lon = get_coordinates(keresesi_cim)
                time.sleep(0.2)
            except Exception as e:
                logger.error(f"Hiba a geocoding során ({nev}): {e}")
                lat, lon = None, None
            
            lat_str = biztonsagos_float(lat)
            lon_str = biztonsagos_float(lon)
            
            if lat:
                st.success(f"📍 GPS megvan: {nev}")
            else:
                st.warning(f"⚠️ Nem találtam koordinátát: {nev}")

            uj_adat = {
                'ID': u_id,
                'Név': nev,
                'Cím': eredeti_cim,
                'Lat': lat_str,
                'Lon': lon_str,
                'Telefon': str(row.get('Telefon', '')),
                'Csoport': str(row.get('Csoport', '')),
                'Megjegyzés': str(row.get('Megjegyzés', row.get('Megjegyzes', ''))),
                'Utolso_Rendeles': pd.Timestamp.now().strftime('%Y.%m.%d'),
                'Osszertek': '0Ft',
                'Rendeles_Szam': 1
            }
            uj_ugyfelek.append(uj_adat)

            elokeszitett_uj_adat = uj_adat.copy()
            elokeszitett_uj_adat['Lat'] = lat if lat else None
            elokeszitett_uj_adat['Lon'] = lon if lon else None
            master_df = pd.concat([master_df, pd.DataFrame([elokeszitett_uj_adat])], ignore_index=True)

    # Új ügyfelek mentése a törzsbe (Ugyfelkor fül) CSAK bővítéssel!
    if uj_ugyfelek:
        try:
            logger.info(f"{len(uj_ugyfelek)} új ügyfél hozzáadása a törzslistához...")
            new_rows_df = pd.DataFrame(uj_ugyfelek).fillna("")
            
            time.sleep(1.0)
            ws_ugyfel.append_rows(new_rows_df.values.tolist(), value_input_option='RAW')
            logger.info("Lokális master_df frissítve az új ügyfelekkel, API hívás megspórolva.")
            
        except Exception as e:
            logger.error(f"Hiba az új ügyfelek mentésekor: {e}")
            st.error("Az új ügyfeleket nem sikerült elmenteni a törzslistába!")

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

    # --- 7. LÉPÉS: FRISSÍTÉS AZ "ADATOK" FÜLRE (SZIGORÚ HIERARCHIA) ---
    try:
        time.sleep(1.0)
        ws_adatok = sh.worksheet("Adatok")
        ws_adatok.clear()  
        
        # 🟢 JAVÍTÁS ÜNNEPI / ÖSSZEVONT RENDELÉSEKHEZ:
        # Ha a merge_data legenerálta a teljes, összevont rendelési sztringet,
        # akkor ezt használjuk a felhőbe küldéshez a sima csonka Rendelés oszlop helyett.
        if 'Rendelés_Full' in df_napi.columns:
            # Csak ott írjuk felül, ahol a Rendelés_Full nem üres
            df_napi['Rendelés'] = df_napi.apply(
                lambda row: str(row['Rendelés_Full']).strip() if str(row.get('Rendelés_Full', '')).strip() != "" else row['Rendelés'], 
                axis=1
            )
        
        # Ez a hivatalos, kért 15 oszlopos séma
        export_cols = [
            'ID', 'Név', 'Cím', 'Telefon', 'Csoport', 'Sorrend', 'Lat', 'Lon', 
            'Rendelés', 'Megjegyzés', 'Járat', 'Fizetendő', 'Fizetési Mód', 'Státusz', 'Időbélyeg'
        ]
        
        # Csak azokat pakoljuk bele, amik kellenek, és pont ebben a sorrendben
        save_df = df_napi[export_cols].copy()
        
        # Tisztítjuk a koordinátákat és kényszerítjük az objektum típust a típuskonfliktusok ellen
        save_df['Lat'] = save_df['Lat'].apply(biztonsagos_float)
        save_df['Lon'] = save_df['Lon'].apply(biztonsagos_float)
        save_df['ID'] = save_df['ID'].astype(str)
        
        for col in save_df.columns:
            save_df[col] = save_df[col].astype(object)
        save_df = save_df.fillna('')
        
        # Feltöltés fejléccel együtt
        set_with_dataframe(ws_adatok, save_df, include_index=False, include_column_header=True)
        logger.info("🚀 A mai menetterv sikeresen kiküldve az 'Adatok' fülre az előírt 15 oszloppal!")
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
                                
                                # Tisztítás (aposztrófok, idézőjelek lekapása, tizedespontosítás)
                                clean_lat = nyers_lat.replace("'", "").replace('"', '').replace(",", ".").strip()
                                clean_lon = nyers_lon.replace("'", "").replace('"', '').replace(",", ".").strip()
                                
                                # Kerekítés és formázás (magyar vesszős string, elején vezérlő aposztróffal)
                                formazott_lat = f"'{str(round(float(clean_lat), 7)).replace('.', ',')}"
                                formazott_lon = f"'{str(round(float(clean_lon), 7)).replace('.', ',')}"
                                
                                sh = client.open_by_key(sheet_id)
                                ws = sh.worksheet("Ugyfelkor")
                                
                                # Oszlopok dinamikus megkeresése név alapján
                                fejlec = ws.row_values(1)
                                lat_idx = fejlec.index("Lat") + 1 if "Lat" in fejlec else 4
                                lon_idx = fejlec.index("Lon") + 1 if "Lon" in fejlec else 5
                                
                                cell = ws.find(str(kiv_id))
                                if cell:
                                    # Cellák frissítése a Sheets-ben
                                    ws.update_cell(cell.row, lat_idx, formazott_lat)
                                    ws.update_cell(cell.row, lon_idx, formazott_lon)
                                    
                                    st.success(f"✅ Siker! {aktualis_nev} új koordinátái elmentve!")
                                    
                                    # Cache ürítések a friss adatok azonnali megjelenítéséhez
                                    if 'google_data_loaded' in st.session_state:
                                        del st.session_state['google_data_loaded']
                                    if 'master_ugyfelkor_df' in st.session_state:
                                        st.session_state['master_ugyfelkor_df'] = None
                                    if 'ugyfelkor_df' in st.session_state:
                                        st.session_state['ugyfelkor_df'] = None
                                        
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

def load_names_from_sheets(sheet_id):
    try:
        creds_info = st.secrets["gcp_service_account"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = service_account.Credentials.from_service_account_info(
            creds_info, 
            scopes=scopes
        )
        
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        
        # --- 1. Vezetéknevek ---
        v_sheet = sheet.worksheet("Vezeteknevek")
        v_list = set(str(name).strip() for name in v_sheet.col_values(1)[1:] if name)
        
        # --- 2. Keresztnevek ---
        k_sheet = sheet.worksheet("Keresztnevek")
        k_data = k_sheet.get_all_records()
        k_dict = {str(row.get('Keresztnév', '')).strip(): str(row.get('Nem', '')).strip() 
                  for row in k_data if row.get('Keresztnév')}
        
        # --- 3. Névnapok (HIÁNYZÓ RÉSZ PÓTLÁSA) ---
        # Ha van ilyen munkalapod, így töltsd be:
        try:
            n_sheet = sheet.worksheet("Nevnapok") # Írd át a pontos névre!
            n_data = n_sheet.get_all_records()
            # Itt feltételezem a táblázat szerkezetét:
            n_dict = {str(row.get('Dátum', '')).strip(): str(row.get('Név', '')).strip() for row in n_data}
        except:
            n_dict = {} # Ha nincs ilyen sheet, üres marad
        
        return v_list, k_dict, n_dict

    except Exception as e:
        st.error(f"Hiba a Google Sheets betöltésekor: {e}")
        # Fontos: 3 értéket adjunk vissza hiba esetén is!
        return set(), {}, {}

# --- ALAPBEÁLLÍTÁSOK ---
PHONE_PAT = r'(\d{2}/\d[\d\s,]*\d)'
# Frissített minta: felismeri a sima (-), az en-dash (–) és az em-dash (—) jeleket is
# \d+         -> Darabszám (legalább egy számjegy)
# \s*-\s* -> Kötőjel (szóközökkel vagy anélkül)
# [A-Z]       -> A cikkszám ELSŐ karaktere KÖTELEZŐEN BETŰ
# [A-Z0-9*+]* -> A többi karakter lehet betű, szám vagy speciális jel (*, +)
ORDER_PAT = r'(\d+)\s*[-\u2013\u2014\u2212]\s*([A-Z][A-Z0-9*+]*)'
# Frissített, "szóköz-toleráns" regex
MONEY_PAT = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

# --- EZT A SEGÉDFÜGGVÉNYT TEDD A KÓD ELEJÉRE ---
def get_day_short(day_str):
    if not day_str: return ""
    primary_day = day_str.split(',')[0].strip() # "Csütörtök, Péntek" -> "Csütörtök"
    day_map = {
        "Hétfő": "Hé", "Kedd": "Ke", "Szerda": "Sze",
        "Csütörtök": "Csü", "Péntek": "Pé", "Szombat": "Szo"
    }
    return day_map.get(primary_day, primary_day[:2])

def extract_all_meta(pdf_files):
    all_meta = {'jaratok': [], 'ev': '', 'het': '', 'nap': ''}
    
    # 🟢 JAVÍTOTT: 2, 3 és 4 jegyű járatszámokat is felismer (\d{2,4})
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
    return all_meta

def register_fonts():
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        
        return 'DejaVu', 'DejaVu-Bold'
    except Exception as e:
        return 'Helvetica', 'Helvetica-Bold'

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

def format_kellek_alert(pdf_kod, pdf_nev, master_df):
    """Meghatározza a kellék riasztást a csillagos szabály szerint."""
    if master_df is None or master_df.empty: return ""
    
    tiszta_nev = clean_text(pdf_nev)
    match = master_df[master_df['Tisztított Név'] == tiszta_nev]
    
    if not match.empty:
        kellek = str(match.iloc[0]['Kellék']).strip()
        if not kellek or kellek.lower() == "nan" or kellek == "": return ""
        
        # Csillagos szabály: Ha a kellék * jellegű (pl. *Tzatziki)
        if kellek.startswith('*'):
            if '*' in str(pdf_kod): # Csak ha a PDF kódjában is van csillag
                return f"⚠ + {kellek.replace('*', '').strip().upper()}"
            return ""
        else:
            # Sima kellék (mindenki kapja)
            return f"⚠ + {kellek.upper()}"
    return ""

def get_gender_and_nevnap(full_name, nevnapok_df, keresztnevek_df, target_date):
    # A target_date formátuma: "2026-04-24"
    mai_sor = nevnapok_df[nevnapok_df['Datum'] == target_date]
    if mai_sor.empty: return None
    
    mai_nevek = [n.strip() for n in str(mai_sor.iloc[0]['Nevek']).split(',')]
    
    # 2. Vevő nevének ellenőrzése
    name_parts = str(full_name).split(' ')
    for part in name_parts:
        clean_part = part.strip().lower()
        if clean_part in mai_nevek:
            # Megvan a névnapos! Nem meghatározása
            gender_match = keresztnevek_df[keresztnevek_df['Keresztnév'].str.lower() == clean_part]
            
            ikon = "✨" # Alapértelmezett (Férfi vagy ismeretlen)
            if not gender_match.empty:
                nem = str(gender_match.iloc[0]['Nem']).lower()
                if 'nő' in nem:
                    ikon = "✿"
            
            return f"{ikon} Boldog névnapot, {part}! {ikon}"
    return None

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

def format_kellek_alert(pdf_kod, pdf_nev, master_df):
    """
    Meghatározza, hogy kell-e kellék riasztás az adott tételhez.
    Visszatérési érték: "⚠ + TZATZIKI" formátum vagy üres string.
    """
    tiszta_nev = clean_text(pdf_nev)
    # Megkeressük az ételt a Master táblában a tisztított név alapján
    match = master_df[master_df['Tisztított Név'] == tiszta_nev]
    
    if not match.empty:
        kellek = str(match.iloc[0]['Kellék']).strip()
        
        # Ha nincs kitöltve kellék, nem csinálunk semmit
        if not kellek or kellek.lower() == "nan" or kellek == "":
            return ""
        
        # --- A CSILLAGOS SZABÁLY ---
        if kellek.startswith('*'):
            # Csak akkor riasztunk, ha a PDF-ből jövő kód is csillagos
            if '*' in pdf_kod:
                tiszta_kellek = kellek.replace('*', '').strip().upper()
                return f"⚠ + {tiszta_kellek}"
            else:
                return "" # Belül van a csomagban, nem kell külön adni
        else:
            # Sima kellék (mindenki kapja)
            return f"⚠ + {kellek.upper()}"
            
    return ""

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

    merged = []
    unique_ids = combined['temp_id'].unique()
    
    for tid in unique_ids:
        subset = combined[combined['temp_id'] == tid]
        base = subset.iloc[0].to_dict()
        
        # 🟢 ÚJ: Megtartjuk a PDF-ből jövő egyedi járatszámot ennél az ügyfélnél
        if 'pdf_jarat' in subset.columns:
            # Ha valamiért eltérne a csoporton belül, az első érvényeset vesszük ki
            nem_ures_jarat = subset['pdf_jarat'].dropna().astype(str).str.strip()
            nem_ures_jarat = nem_ures_jarat[nem_ures_jarat != ""]
            if not nem_ures_jarat.empty:
                base['pdf_jarat'] = nem_ures_jarat.iloc[0]
        
        if len(subset) > 1:
            # Rendelések összefűzése
            all_orders = []
            for _, r in subset.iterrows():
                o_str = str(r.get('Rendelés_Full', '')).strip()
                if o_str: all_orders.append(o_str)
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
    
    # 🟢 ÚJ: Áttesszük a hivatalos 'Járat' oszlopba a kinyert egyedi járatokat
    if 'pdf_jarat' in res.columns:
        res['Járat'] = res['pdf_jarat'].astype(str).str.strip()
    
    # Biztosítjuk a tiszta oszlopneveket
    res.columns = [c.strip() for c in res.columns]
    
    # Automatikus sorszámozás 1-től
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
    
def create_label_pdf(df, fn, ft, meta, master_df, nevnapok_df, keresztnevek_df, etlap_api_df):
    if df is None or df.empty: return None
    if 'Sorrend' not in df.columns: df['Sorrend'] = range(1, len(df) + 1)
    df = df.sort_values('Sorrend')
    
    bazis_nap_rovid = get_day_short(meta.get('nap', ''))
    nap_list = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo"]

    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70 * mm, 42.42 * mm
    inner_m = 5.5 * mm 
    usable_w = lw - (2 * inner_m)

    # --- STÍLUSOK FINOMHANGOLÁSA ---
    # Leading (sorköz) csökkentve 8.0-ról 7.5-re, fontSize marad 7-esen a tömörségért
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=7, leading=7.5)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=7.5, leading=10, alignment=1)

    total_slots = math.ceil(len(df) / 21) * 21
    pdf_datum = meta.get('datum_iso', '')
    
    if not pdf_datum or len(str(pdf_datum)) < 5:
        import datetime
        pdf_datum = datetime.datetime.now().strftime("%Y-%m-%d")

    kulcs_nevnap = str(pdf_datum)[-5:].replace('.', '-') 
    kulcs_api_datum = str(pdf_datum).replace('-', '.')
    if not kulcs_api_datum.endswith('.'):
        kulcs_api_datum += "."

    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        # Ez emeli fel az egész etikettet a lap alján, hogy ne lógjon le
        lift = 4.5 * mm if row_i == 0 else 0
        y_eff = y + lift 

        if i < len(df):
            r = df.iloc[i]
            # Az alappozícióhoz hozzáadjuk a lift-et, hogy minden feljebb csússzon a lap alján
            top_y = y + lh - inner_m + lift
            
            # --- RENDELÉS FORMÁZÁSA ---
            r_full = str(r.get('Rendelés_Full', r.get('Rendelés', '')))
            kulonleges = False
            napi_blokkok = re.split(r'(\s*\|\s*|(?=Hé:|Ke:|Sze:|Csü:|Pé:|Szo:))', r_full)
            formazott_reszek = []
            
            for blokk in napi_blokkok:
                if not blokk or not blokk.strip(): 
                    if blokk: formazott_reszek.append(blokk)
                    continue
                szin_blokk = blokk
                for n in nap_list:
                    n_tag = f"{n}:"
                    if n_tag in blokk:
                        if n != bazis_nap_rovid:
                            kulonleges = True
                            szin_blokk = f'<font name="{f_bold}" size="8">{blokk}</font>'
                        break
                formazott_reszek.append(szin_blokk)
            
            formazott_rendeles = "".join(formazott_reszek)

            # --- NÉVNAP ÉS KELLÉK KERESÉS (JAVÍTOTT, ATOMBIZTOS VERZIÓ) ---
            nevnap_uzenet = ""
            if nevnapok_df is not None and not nevnapok_df.empty and kulcs_nevnap != "NINCS":
                # Dinamikus oszlopnév meghatározás (Datum / Dátum / 0. oszlop)
                n_dat_col = next((c for c in ['Datum', 'Dátum', 'datum', 'dátum'] if c in nevnapok_df.columns), nevnapok_df.columns[0])
                # Dinamikus oszlopnév a neveknek (Nevek / Név / Nev / 1. oszlop)
                n_nev_col = next((c for c in ['Nevek', 'Név', 'Nev', 'nevek'] if c in nevnapok_df.columns), nevnapok_df.columns[1] if len(nevnapok_df.columns) > 1 else nevnapok_df.columns[0])

                try:
                    mai_sor = nevnapok_df[nevnapok_df[n_dat_col].astype(str).str.contains(kulcs_nevnap)]
                    if not mai_sor.empty:
                        t_nev = str(r.get('Ügyintéző', '')).strip()
                        for t in ["Dr.", "dr.", "id.", "ifj.", "özv.", "Özv."]:
                            t_nev = t_nev.replace(t, "")
                        szavak = [s.strip() for s in t_nev.split() if s.strip()]
                        keresztnev = szavak[1] if len(szavak) > 1 else (szavak[0] if szavak else "")
                        
                        # Biztonságos ellenőrzés a felderített név oszlop alapján
                        ma_unneplok = [n.strip().lower() for n in str(mai_sor.iloc[0][n_nev_col]).split(',')]
                        if keresztnev.lower().strip() in ma_unneplok:
                            nevnap_uzenet = f"★ Boldog Névnapot, {keresztnev}! ★"
                except Exception as e_nv_belso:
                    # Ha bármi egyedi hiba lenne (pl. üres cella), nem engedjük összeomlani a PDF-et
                    logger.warning(f"Hiba az ügyfél névnap ellenőrzésekor: {e_nv_belso}")
                    nevnap_uzenet = ""

            kellek_kiiras = ""
            if kulcs_api_datum != "NINCS" and etlap_api_df is not None:
                keresett_nap_szamokkal = "".join(filter(str.isdigit, kulcs_api_datum))
                napi_oszlop = next((col for col in etlap_api_df.columns if keresett_nap_szamokkal in "".join(filter(str.isdigit, str(col)))), None)
                
                if napi_oszlop:
                    tiszta_szoveg = re.sub(r'<[^>]*>', '', formazott_rendeles)
                    csillagosok = re.findall(r'([A-Z0-9\-]+)\*', tiszta_szoveg.upper())
                    talalt_kellekek = []
                    for nyers_kod in csillagosok:
                        tiszta_kod = nyers_kod.split('-')[-1].strip()
                        etel_sor = etlap_api_df[etlap_api_df.iloc[:, 0].astype(str).str.contains(rf"\b{tiszta_kod}\b", na=False)]
                        if not etel_sor.empty:
                            keresett_nev_tiszta = re.sub(r'[^a-z0-9]', '', str(etel_sor.iloc[0][napi_oszlop]).lower())
                            if master_df is not None:
                                for _, m_row in master_df.iterrows():
                                    if re.sub(r'[^a-z0-9]', '', str(m_row.get('Eredeti Név', '')).lower()) == keresett_nev_tiszta:
                                        kell = str(m_row.get('Kellék', '')).strip()
                                        if kell and kell.lower() != 'nan':
                                            talalt_kellekek.append(f"{tiszta_kod}: {kell}")
                                        break
                    if talalt_kellekek:
                        # 1. CSOPORTOSÍTÁS: Össze gyűjtjük, melyik kellékhez melyik kódok tartoznak
                        kellek_szotar = {}
                        for item in talalt_kellekek:
                            try:
                                # Szétválasztjuk a kódot és a nevet (pl. "L2: Zsemlekockák")
                                kod, nev = item.split(": ", 1)
                                if nev not in kellek_szotar:
                                    kellek_szotar[nev] = []
                                # Csak akkor adjuk hozzá a kódot, ha még nincs benne (duplikáció szűrés)
                                if kod not in kellek_szotar[nev]:
                                    kellek_szotar[nev].append(kod)
                            except:
                                continue

                        # 2. SZÖVEG ÖSSZEÁLLÍTÁSA: "Kód1, Kód2: Kelléknév" formátum
                        osszevont_elemek = []
                        for nev, kodok in kellek_szotar.items():
                            # Sorrendbe rakjuk a kódokat (pl. KM, L2) és összefűzzük a névvel
                            kodok_szoveg = ", ".join(sorted(kodok))
                            osszevont_elemek.append(f"{kodok_szoveg}: {nev}")
                        
                        # 3. VÉGLEGES KIÍRÁS: Pontosvesszővel elválasztva a különböző kellékcsoportokat
                        kellek_kiiras = "; ".join(osszevont_elemek)

            # --- DINAMIKUS ELTOLÁS A LAP ALJÁN (ISMÉTELT FINOMÍTÁS) ---
            # row_i == 0 jelentése: a lap legalsó sora (7., 14., 21. etikett)
            # -0.5 mm-re állítjuk, hogy az előzőhöz képest 1 mm-t süllyedjen
            biztonsagi_emeles = -0.5 * mm if row_i == 0 else 0

            # --- 1. FEJLÉC (Sorszám és ID) ---
            p.setFont(f_bold, 8)
            p.drawString(x + inner_m, top_y - (3 * mm) + biztonsagi_emeles, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 7)
            p.drawRightString(x + lw - inner_m, top_y - (3 * mm) + biztonsagi_emeles, f"ID: {str(r.get('temp_id', 'N/A'))}")

            # --- 2. NÉV ÉS TELEFON POZÍCIÓ ---
            nev_y_pozicio = top_y - 7.0 * mm + biztonsagi_emeles
            
            # SZÜRKE TÉGLALAP (Szombati/Különleges rendelés esetén)
            if kulonleges:
                p.saveState()
                p.setFillColor(colors.lightgrey, alpha=0.3)
                p.rect(x + 0.5*mm, nev_y_pozicio - 1.5*mm, lw - 1*mm, 5 * mm, fill=1, stroke=0)
                p.restoreState()
            
            # Ügyintéző neve
            p.setFont(f_bold, 8.5)
            p.drawString(x + inner_m, nev_y_pozicio, str(r.get('Ügyintéző', ''))[:25])
            
            # Telefonszám
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, nev_y_pozicio, str(r.get('Telefon', '')))
            
            # --- 3. CÍM KIÍRÁSA ---
            p.setFont(f_reg, 7)
            p.drawString(x + inner_m, top_y - 10.5 * mm + biztonsagi_emeles, str(r.get('Cím', ''))[:45])

            # RENDELÉS BLOKK - Jön feljebb, hogy kövesse a fejlécet
            # Eddig y_eff + 16 mm volt, most y_eff + 19 mm-re emeljük
            para = Paragraph(formazott_rendeles, order_s)
            pw, ph = para.wrap(usable_w, 18 * mm)
            para.drawOn(p, x + inner_m, y_eff + 19 * mm) 

            # --- ALSÓ SÁV (Vonal, Fizetendő és Összesítő) ---
            p.setLineWidth(0.1)
            p.line(x + inner_m, y_eff + 6 * mm, x + lw - inner_m, y_eff + 6 * mm)

            # FIZETENDŐ - VISSZAÁLLÍTVA A 'Pénz' VÁLTOZÓRA ÉS AZ EREDETI LOGIKÁRA
            penz_nyers = str(r.get('Pénz', '0 Ft'))
            penz_tisztitott = penz_nyers.replace(" ", "")
            
            # Csak akkor írjuk ki, ha nem 0 és nem üres
            if penz_tisztitott not in ["0Ft", "", "0", "0ft"]:
                p.setFont(f_bold, 9) # Marad a kért 9-es méret
                p.drawString(x + inner_m, y_eff + 7 * mm, f"Fizet: {penz_nyers}")

            # ÖSSZESÍTŐ - Jobb oldalon (A biztosan működő 'Összesen' kulccsal)
            p.setFont(f_bold, 7.5)
            # 🟢 JAVÍTOTT, BIZTONSÁGOS VERZIÓ:
            try:
                osszesen_db = int(float(str(r.get('Összesen', 0)).replace("'", "").strip() or 0))
            except ValueError:
                osszesen_db = 0  # Ha mégis szöveg maradt volna benne, akkor 0 db-ot ír ki, de nem omlik össze!
            
            p.drawRightString(x + lw - inner_m, y_eff + 7 * mm, f"Össz: {osszesen_db} db")

            # --- KELLÉK SOR (Fentebb tolva: 12.5 mm) ---
            if kellek_kiiras:
                p.saveState()
                p.setFont(f_bold, 6)
                t_kellek = kellek_kiiras.replace("Kellék:", "").strip()
                p.drawCentredString(x + lw / 2, y_eff + 12.5 * mm, f"⚠+ {t_kellek} +⚠")
                p.restoreState()

            # --- LEGALJA (Névnap vagy Futár) ---
            if nevnap_uzenet:
                p.setFont(f_reg, 8) 
                p.drawCentredString(x + lw / 2, y_eff + 2.5 * mm, nevnap_uzenet)
            else:
                p.setFont(f_reg, 6.5)
                p.drawCentredString(x + lw / 2, y_eff + 2.5 * mm, f"Futár: {fn} | {ft}")

        else:
            # MARKETING ETIKETT (Változatlan)
            m_text = (
                f"<font size='10' name='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető!</b></font>"
            )
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(usable_w, lh - (2 * inner_m) - lift)
            para.drawOn(p, x + (lw - pw) / 2, y_eff + (lh - ph) / 2)

    p.save()
    buf.seek(0)
    return buf
    
# --- ÚJ OSZTÁLY A RAJZOLT NÉGYZETHEZ (Marad, ahogy írtad) ---
class Checkbox(Flowable):
    def __init__(self, size=10):
        Flowable.__init__(self)
        self.width = size
        self.height = size

    def draw(self):
        self.canv.setLineWidth(0.8)
        self.canv.setStrokeColor(colors.black)
        self.canv.rect(0, 0, self.width, self.height, stroke=1, fill=0)

class NumberingCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        # Ez a rész üres marad, mert a footer függvény fog rajzolni
        pass

def create_manifest_pdf(df, c_n, meta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=5*mm, leftMargin=5*mm, topMargin=8*mm, bottomMargin=12*mm)
    f_reg, f_bold = register_fonts()

    styles = {
        'Normal': ParagraphStyle('Normal', fontName=f_reg, fontSize=8, leading=8.5),
        'Small': ParagraphStyle('Small', fontName=f_reg, fontSize=7, leading=8),
        'Header': ParagraphStyle('Header', fontName=f_bold, fontSize=10, leading=11, alignment=1),
        'NameBold': ParagraphStyle('NameBold', fontName=f_bold, fontSize=8.5, leading=9),
        'IDStyle': ParagraphStyle('IDStyle', fontName=f_reg, fontSize=7.5, leading=9, alignment=2, textColor=colors.gray),
        # Új stílusok a QR kód oldalához
        'QRTitle': ParagraphStyle('QRTitle', fontName=f_bold, fontSize=14, leading=16, alignment=1, spaceAfter=15),
        'QRText': ParagraphStyle('QRText', fontName=f_reg, fontSize=10, leading=14, alignment=1)
    }

    # --- ÚJ: Bázis nap meghatározása ---
    bazis_nap_rovid = get_day_short(meta.get('nap', ''))
    nap_list = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo"]

    elements = []
    j_str = ", ".join(meta.get('jaratok', []))
    header_str = f"MENETTERV - Járat(ok): {j_str} | {meta.get('ev', '')}. év, {meta.get('het', '')}. hét | {meta.get('nap', '')}"
    elements.append(Paragraph(header_str, styles['Header']))
    elements.append(Spacer(1, 2*mm))

    # 1. FEJLÉC ÉS OSZLOPSZÉLESSÉGEK FRISSÍTÉSE
    # Sorrend: #, NÉV, RENDELÉS, ☐, PÉNZ, TEL, DB
    table_data = [["#", "NÉV / CÍM / INFÓ", "RENDELÉS", "☐", "PÉNZ", "TEL", "DB"]]
    col_widths = [8*mm, 95*mm, 32*mm, 10*mm, 18*mm, 24*mm, 8*mm]

    table_styles = [
        ('FONTNAME', (0,0), (-1,0), f_bold),
        ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (4,0), (4,-1), 'RIGHT'),  # Pénz most már a 4. index (0-tól számolva)
        ('ALIGN', (3,0), (3,-1), 'CENTER'), # Checkbox középre
        ('ALIGN', (6,0), (6,-1), 'CENTER'), # DB középre
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
    ]

    if 'Csoport' in df.columns:
        groups = df['Csoport'].astype(str).values
        start_idx = None
        for i in range(len(groups)):
            curr_val = str(groups[i]).strip().lower()
            is_valid_group = curr_val and curr_val not in ['0', '0.0', 'nan', 'none', '']
            
            if is_valid_group:
                if start_idx is None: start_idx = i
                next_val = ""
                if i + 1 < len(groups):
                    next_val = str(groups[i+1]).strip().lower()

                if i == len(groups) - 1 or next_val != curr_val:
                    r_s, r_e = start_idx + 1, i + 1
                    table_styles.append(('BOX', (0, r_s), (-1, r_e), 1.3, colors.black))
                    table_styles.append(('BACKGROUND', (0, r_s), (-1, r_e), colors.Color(0.96, 0.96, 0.96)))
                    start_idx = None

    for i, row in df.iterrows():
        r_full = str(row.get('Rendelés_Full', ''))
        
        # --- Dinamikus szürkítés és félkövérítés logikája ---
        kulonleges = False
        formazott_rendeles = r_full
        
        for n in nap_list:
            n_tag = f"{n}:"
            if n_tag in r_full:
                if n != bazis_nap_rovid:
                    kulonleges = True
                    formazott_rendeles = formazott_rendeles.replace(n_tag, f"<b>{n_tag}</b>")

        if kulonleges:
            special_bg = colors.Color(0.85, 0.85, 0.85)
            table_styles.append(('BACKGROUND', (2, i+1), (2, i+1), special_bg))
            table_styles.append(('BOX', (2, i+1), (2, i+1), 1.5, colors.black, None, (2, 2)))

        # --- CSOPORTJELZŐ HÁROMSZÖG ÉS HIBAJAVÍTÁS ---
        curr_grp = str(row.get('Csoport', '')).strip().lower()
        prev_grp = str(df.iloc[i-1].get('Csoport', '')).strip().lower() if i > 0 else ""

        is_valid = curr_grp and curr_grp not in ['0', '0.0', 'nan', 'none', '']

        prefix = "▲ " if (is_valid and i > 0 and curr_grp == prev_grp) else ""
        u_name = str(row.get('Ügyintéző', ''))[:45]
        u_id = str(row.get('temp_id', ''))
        
        t_inner = Table([[Paragraph(f"{prefix}{u_name}", styles['NameBold']), Paragraph(f"ID: {u_id}", styles['IDStyle'])]], 
                        colWidths=[70*mm, 22*mm], style=[('LEFTPADDING', (0,0), (-1,-1), 0), ('TOPPADDING', (0,0), (-1,-1), 0)])

        info_flow = [t_inner, Paragraph(str(row.get('Cím', '')), styles['Normal'])]
        
        megj = str(row.get('Megjegyzés', '')).strip()
        if megj and megj.lower() != 'nan':
            info_flow.append(Paragraph(megj, styles['Small']))

        p_raw = str(row.get('Pénz', '')).strip()
        digits_only = "".join(re.findall(r'\d+', p_raw))
        penz_val = p_raw if (digits_only and int(digits_only) > 0) else "" 
        
        sorszam_nyers = row.get('Sorrend', i+1)
        try:
            sorszam_vegleges = str(int(float(sorszam_nyers)))
        except:
            sorszam_vegleges = str(i+1)

        table_data.append([
            sorszam_vegleges,                                    # 0: #
            info_flow,                                           # 1: Név/Cím
            Paragraph(formazott_rendeles, styles['Small']),      # 2: Rendelés
            Checkbox(10),                                        # 3: ☐
            Paragraph(f"<b>{penz_val}</b>", styles['Normal']),   # 4: Pénz
            Paragraph(str(row.get('Telefon', '')), styles['Small']), # 5: Tel
            str(row.get('Összesen', ''))                         # 6: DB
        ])

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(table_styles))
    elements.append(t)
    
    # =========================================================================
    # --- UTOLSÓ OLDAL: QR-KÓD GENERÁLÁS A MOBIL TERMINÁLHOZ ---
    # =========================================================================
    from reportlab.platypus import PageBreak
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    elements.append(PageBreak()) # Kényszerített új oldal az utolsó lapra
    elements.append(Spacer(1, 40*mm)) # Egy kis fenti térköz, hogy középtájt legyen
    
    elements.append(Paragraph("📱 DIGITÁLIS FUTÁR TERMINÁL INDÍTÁSA", styles['QRTitle']))
    
    # Dinamikus link generálása a járatazonosítóval
    alap_url = "https://interfood-menetterv-etikett-generator.streamlit.app"
    jarat_id = meta.get('jarat', '')
    mobil_link = f"{alap_url}/?view=mobile&jarat={jarat_id}"
    
    # QR kód widget létrehozása (140x140 pont méretben)
    qr_code = QrCodeWidget(mobil_link)
    qr_code.barWidth = 140
    qr_code.barHeight = 140
    qr_code.qrVersion = 1
    
    # Beletesszük egy Drawing rajzfelületbe, hogy középre rendezhessük
    d = Drawing(140, 140)
    d.add(qr_code)
    d.hAlign = 'CENTER'
    
    elements.append(d)
    elements.append(Spacer(1, 10*mm))
    
    magyarázat = f"""
    Szkenneld be a fenti QR-kódot a telefonoddal a mobilra optimalizált nézet megnyitásához!<br/><br/>
    <b>Aktuális járat:</b> {jarat_id if jarat_id else j_str}<br/>
    <i>A rendszer automatikusan bejelentkeztet és betölti a hozzá tartozó adatokat.</i>
    """
    elements.append(Paragraph(magyarázat, styles['QRText']))
    # =========================================================================
    
    # --- SPECIÁLIS CANVAS AZ OLDALSZÁMOZÁSHOZ ÉS LÁBLÉCHEZ ---
    class FinalCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            canvas.Canvas.__init__(self, *args, **kwargs)
            self.pages = []

        def showPage(self):
            self.pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            page_count = len(self.pages)
            for state in self.pages:
                self.__dict__.update(state)
                self.draw_footer(page_count)
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)

        def draw_footer(self, page_count):
            self.saveState()
            self.setFont(f_reg, 7)
            
            j_str = ", ".join(meta.get('jaratok', []))
            footer_left = f"{j_str}. járat menetterve | {meta.get('ev', '')}. év, {meta.get('het', '')}. hét | {meta.get('nap', '')}"
            self.drawString(15*mm, 10*mm, footer_left)
            
            footer_right = f"{self._pageNumber} / {page_count}. oldal"
            self.drawRightString(A4[0] - 15*mm, 10*mm, footer_right)
            
            self.restoreState()

    doc.build(elements, canvasmaker=FinalCanvas)
    
    buffer.seek(0)
    return buffer
    
def create_raklista_pdf(df, jarat_info, meta_dict):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    
    # Kicsit növeljük a margókat a szép keretek miatt
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=10 * mm, bottomMargin=12 * mm, leftMargin=10 * mm, rightMargin=10 * mm)
    
    etlap = st.session_state.get('etlap_adatok', {})
    kategoria_adatok = st.session_state.get('kategoria_adatok', {}) # Az új táblázatunk!

    ev = meta_dict.get('ev', '')
    het = meta_dict.get('het', '')
    napok = meta_dict.get('nap', '') 
    dates_str = f"{ev}. {het}. hét ({napok})"

    label_to_prefix = {"Hé": "H", "Ke": "K", "Sze": "S", "Csü": "C", "Pé": "P", "Szo": "Z"}
    prefix_to_nev = {"H": "Hétfő", "K": "Kedd", "S": "Szerda", "C": "Csütörtök", "P": "Péntek", "Z": "Szombat"}
    prefix_to_num = {"H": "1", "K": "2", "S": "3", "C": "4", "P": "5", "Z": "6"}

    # 1. DARABSZÁMOK ÖSSZEGYŰJTÉSE
    counts = {}
    for _, r in df.iterrows():
        order_str = str(r.get('Rendelés_Full', ''))
        day_parts = order_str.split('|')
        for part in day_parts:
            part = part.strip()
            prefix = ""
            for label, pfx in label_to_prefix.items():
                if f"{label}:" in part:
                    prefix = pfx
                    break
            if not prefix: continue
            
            found = re.findall(ORDER_PAT, part)
            for qty, code in found:
                full_key = f"{prefix}_{code.strip().upper()}"
                counts[full_key] = counts.get(full_key, 0) + int(qty)

    # Stílusok definíciója
    title_style = ParagraphStyle('T', fontName=f_bold, fontSize=12, leading=14, spaceAfter=2)
    meta_style = ParagraphStyle('M', fontName=f_reg, fontSize=9, leading=11, spaceAfter=6)
    
    cat_header_style = ParagraphStyle('CH', fontName=f_bold, fontSize=8.5, leading=10, textColor=colors.HexColor('#1A1A1A'))
    th_style = ParagraphStyle('TH', fontName=f_bold, fontSize=7.5, leading=9, alignment=1, textColor=colors.HexColor('#444444'))
    
    row_reg_style = ParagraphStyle('RR', fontName=f_reg, fontSize=7, leading=8.5)
    row_bold_style = ParagraphStyle('RB', fontName=f_bold, fontSize=7, leading=8.5)
    center_style = ParagraphStyle('C', fontName=f_reg, fontSize=7, leading=8.5, alignment=1)
    center_bold_style = ParagraphStyle('CB', fontName=f_bold, fontSize=7.5, leading=8.5, alignment=1)
    right_style = ParagraphStyle('R', fontName=f_reg, fontSize=7, leading=8.5, alignment=2)
    right_bold_style = ParagraphStyle('R', fontName=f_bold, fontSize=7, leading=8.5, alignment=2)

    # SZÉP VEKTOROS CHECKBOX RAJZOLÁSA (Mint a menetterven)
    def get_checkbox():
        d = Drawing(10, 10)
        d.hAlign = 'CENTER'
        d.vAlign = 'MIDDLE'
        # Rajzolunk egy 8x8 mm-es négyzetet vékony fekete szegéllyel, fehér belsővel
        from reportlab.graphics.shapes import Rect
        d.add(Rect(1, 1, 8, 8, fillColor=colors.white, strokeColor=colors.HexColor('#555555'), strokeWidth=0.6))
        return d

    # 2. TÉTELEK BESOROLÁSA ÉS CSOPORTOSÍTÁSA KATEGÓRIÁK SZERINT
    # Létrehozunk egy struktúrát: kategoria_csoportok[kategoria_neve] = [tételek listája]
    # És elmentjük a kategóriák sorrendi számát is, hogy a végén rendezni tudjuk a kategóriákat!
    kategoria_csoportok = {}
    kategoria_sorrendek = {} # Megjegyzi, melyik kategóriának mi a sorszáma
    
    total_qty = 0
    total_money = 0

    for full_key, db in counts.items():
        prefix = full_key.split('_')[0]
        code_label = full_key.split('_')[1]
        day_long = prefix_to_nev.get(prefix, prefix)
        
        keresett_kod = code_label.replace('*', '').strip()
        num_prefix = prefix_to_num.get(prefix, "1")
        sheets_key = f"{num_prefix}_{keresett_kod}"
        
        info = etlap.get(sheets_key, {})
        nev = info.get('nev', '---')
        
        # Ár kezelése
        nyers_ar = str(info.get('ar', '0')).replace('Ft', '').replace(' ', '').strip()
        ar = int(nyers_ar) if nyers_ar and nyers_ar.isdigit() else 0
        subtotal = db * ar
        
        total_qty += db
        total_money += subtotal

        # === KATEGÓRIA ÉS SORREND KINYERÉSE AZ ÚJ TÁBLÁZATBÓL ===
        # Megnézzük a tiszta cikkszám alapján (pl. SP1, L1)
        kat_info = kategoria_adatok.get(keresett_kod, {'kategoria': 'Egyéb / Zóna ételek', 'sorrend': 99})
        kat_nev = kat_info['kategoria']
        kat_sorszam = kat_info['sorrend']
        
        kategoria_sorrendek[kat_nev] = kat_sorszam
        
        if kat_nev not in kategoria_csoportok:
            kategoria_csoportok[kat_nev] = []
            
        kategoria_csoportok[kat_nev].append({
            'day': day_long,
            'code': code_label,
            'db': db,
            'nev': nev,
            'ar': ar,
            'subtotal': subtotal,
            'starred': "*" in code_label
        })

    # 3. KATEGÓRIÁK RENDEZÉSE A KONYHAI SORREND ALAPJÁN
    rendezett_kategoriak = sorted(kategoria_csoportok.keys(), key=lambda x: kategoria_sorrendek.get(x, 99))

    # Elements lista építése a PDF-hez
    elements = [
        Paragraph("<b>RAKLISTA ÉS ELSZÁMOLÁS (KATEGORIZÁLT)</b>", title_style),
        Paragraph(f"Időszak: {dates_str} | Járat: {jarat_info}", meta_style),
        Spacer(1, 2 * mm)
    ]

    # Oszlopszélességek (Összesen 190 mm, ami pontosan kitölti az A4-et 10mm-es margókkal)
    col_widths = [15 * mm, 16 * mm, 12 * mm, 10 * mm, 95 * mm, 18 * mm, 24 * mm]

    # 4. TÁBLÁZATOK GENERÁLÁSA KATEGÓRIÁNKÉNT
    for kat in rendezett_kategoriak:
        # Minden kategóriának saját külön táblázatot adunk, így gyönyörűen bekeretezhető
        kat_data = []
        
        # A - Kategória Fejléc Sor (Egybeolvasztva az egész szélességben)
        kat_data.append([Paragraph(f"<b>📂 {kat.upper()}</b>", cat_header_style), "", "", "", "", "", ""])
        
        # B - Oszlopnevek fejléc sor
        kat_data.append([
            Paragraph("<b>NAP</b>", th_style),
            Paragraph("<b>KÓD</b>", th_style),
            Paragraph("<b>DB</b>", th_style),
            Paragraph("<b>[ ]</b>", th_style),
            Paragraph("<b>MEGNEVEZÉS</b>", th_style),
            Paragraph("<b>ÁR</b>", th_style),
            Paragraph("<b>ÖSSZES</b>", th_style)
        ])
        
        # C - Tételek hozzáadása (A kategórián belül nap és kód szerint rendezve)
        tetelek = sorted(kategoria_csoportok[kat], key=lambda x: (x['day'], x['code']))
        
        for tétel in tetelek:
            font = f_bold if tétel['starred'] else f_reg
            p_style = row_bold_style if tétel['starred'] else row_reg_style
            c_style = center_bold_style if tétel['starred'] else center_style
            
            kat_data.append([
                Paragraph(tétel['day'], center_style),
                Paragraph(tétel['code'], c_style),
                Paragraph(f"<b>{tétel['db']} db</b>", c_style),
                get_checkbox(), # Rajzolt négyzet!
                Paragraph(tétel['nev'], p_style),
                Paragraph(f"{tétel['ar']} Ft", right_style),
                Paragraph(f"{tétel['subtotal']} Ft", right_bold_style if tétel['starred'] else right_style)
            ])
            
        # Táblázat létrehozása és formázása (Bekeretezés)
        t = Table(kat_data, colWidths=col_widths, repeatRows=2)
        
        t_style = [
            # Kategória fejléc formázása (szürke háttér, vastag alsó vonal)
            ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAEAEA')),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
            ('TOPPADDING', (0, 0), (-1, 0), 3),
            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#222222')),
            
            # Oszlop fejléc formázása (világosabb szürke)
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#F5F5F5')),
            ('BOTTOMPADDING', (0, 1), (-1, 1), 2),
            ('TOPPADDING', (0, 1), (-1, 1), 2),
            ('LINEBELOW', (0, 1), (-1, 1), 0.6, colors.HexColor('#666666')),
            
            # Általános sorbeállítások
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (3, 2), (3, -1), 'CENTER'), # Checkbox középre igazítása
            ('TOPPADDING', (0, 2), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 2), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            
            # BELSŐ RÁCS: Vékony, finom szürke elválasztó vonalak a sorok között
            ('ROWBACKGROUNDS', (0, 2), (-1, -1), [colors.white, colors.HexColor('#FAFAFA')]),
            ('LINEBELOW', (0, 2), (-1, -1), 0.3, colors.HexColor('#E0E0E0')),
            
            # KÜLSŐ KERET: Vastagabb fekete keret az EGÉSZ kategória-blokk köré
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#222222')),
        ]
        t.setStyle(TableStyle(t_style))
        
        elements.append(t)
        elements.append(Spacer(1, 4 * mm)) # Térköz a kategória-blokkok között

    # 5. PÉNZÜGYI ÖSSZESÍTŐ TÁBLÁZAT (A lap aljára)
    jutalek = int(total_money * 0.13)
    summary_data = [
        ["", "", "", "", "ÖSSZESEN:", f"{total_qty} db", f"{total_money} Ft"],
        ["", "", "", "", "JUTALÉK (13%):", "", f"{jutalek} Ft"]
    ]
    st_table = Table(summary_data, colWidths=col_widths)
    st_table.setStyle(TableStyle([
        ('FONTNAME', (4, 0), (-1, -1), f_bold),
        ('FONTSIZE', (4, 0), (-1, -1), 9),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('ALIGN', (5, 0), (6, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LINEABOVE', (4, 0), (-1, 0), 0.8, colors.black),
    ]))
    
    elements.append(st_table)

    # Oldalszámozás lábléc
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_reg, 7.5)
        canvas.drawRightString(200 * mm, 8 * mm, f"{doc.page}. oldal")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    
    # OKOSÍTÁS: Elmentjük a rendezett adatokat a mobil app részére is!
    # Így a mobil_terminal() függvénynek már csak ki kell olvasnia ezt a struktúrát, 
    # és gépelés/újraszámolás nélkül, azonnal a tökéletes kategóriás felületet kapja a futár!
    st.session_state['mobil_raklista_adatok'] = {
        'kategoriak': rendezett_kategoriak,
        'csoportok': kategoria_csoportok
    }
    
    return buf
    
# --- FŐ PROGRAMFUTÁS ---
def main():
    # 1. Globális elérés a gspread kliensnek
    global client  

    # 2. Az ID-k fix definiálása helyben
    SHEET_ID = "1bZrtgqROYijYhyFOFrqYeSTUAsGqZU6GLijObJ1En0o" 
    UGYFELKOR_SHEET_ID = "1nK0OLzVzEFY5bSLhMFfGgs4tOgMEueBgXeb9JUbLSN8"
    SHEET_ID_MASTER = SHEET_ID # Biztonsági másolat, ha a kódod máshol így hivatkozik rá
    SHEET_ID_UGYFELKOR = UGYFELKOR_SHEET_ID

    # 1. Lekérjük a linkből a paramétereket
    query_params = st.query_params
    view = query_params.get("view", None)
    url_jarat = query_params.get("jarat", "")

    # 2. BIZTONSÁGOS OKOSÍTÁS: Ha a parancsikon miatt nincs 'view' a linkben
    if view is None:
        # Ha már be van töltve Excel/API adat a munkamenetben, akkor ez az asztali admin
        if 'edited_df' in st.session_state:
            view = "desktop"
        else:
            # Ha nincs adat (mert a futár most nyitotta meg a parancsikont üresen)
            st.markdown("### 📱 Interfood Futár Terminál")
            st.info("A parancsikonról indítottad az alkalmazást. Kattints az alábbi gombra a folytatáshoz:")
            
            # Ez a gomb mobilnézetbe teszi az appot és frissít egyet
            if st.button("🚀 MOBIL TERMINÁL INDÍTÁSA", use_container_width=True, type="primary"):
                st.query_params.update(view="mobile")
                st.rerun()
                
            st.write("---")
            with st.expander("💻 Adminisztrátori belépés (Asztali nézet)"):
                if st.button("Asztali verzió megnyitása"):
                    st.query_params.update(view="desktop")
                    st.rerun()
            return # Megállítjuk a futást, hogy ne dobjon üres táblázatos hibákat alatta

    # 3. Beállítjuk a logikai változót a kód többi részének
    is_mobile_view = (view == "mobile")

    # 🟢 ALVÓ MÓD / RENDSZERÉBRESZTÉS ELLENŐRZÉSE
    with st.spinner("⏳ A Label Master rendszer ébredezik és kapcsolódik a szerverhez... Kérjük, várjon egy pillanatot!"):
        if "bejelentkezve" not in st.session_state:
            st.session_state.bejelentkezve = False
            st.session_state.user_nev = ""
            st.session_state.user_jarat = ""
            st.session_state.user_szerep = "futar"
        
        app_ready = True 

    # Ha még nincs bejelentkezve, megállítjuk az appot
    if not st.session_state.bejelentkezve and app_ready:
        st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>🎯 Label Master</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #6B7280;'>Biztonságos azonosítás a rendszer használatához</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.warning("🔒 Kérjük, add meg a járatszámodat és az egyedi jelszavadat!")
            jarat_input = st.text_input("JÁRATSZÁM (vagy Admin):", key="login_jarat_field", placeholder="Pl. 4002 vagy admin")
            password_input = st.text_input("JELSZÓ / KÓD:", type="password", key="login_password_field", placeholder="••••••••")
            
            if st.button("🔑 BIZTONSÁGOS BELÉPÉS", use_container_width=True):
                if not jarat_input or not password_input:
                    st.error("❌ Mindkét mező kitöltése kötelező!")
                else:
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
                        alap_jarat = str(talalt_futar.get('Járat', talalt_futar.get('Jarat', ''))).strip()
                        st.session_state.user_jarat_lista = [alap_jarat] 
                        st.session_state.user_szerep = str(talalt_futar.get('Szerep', 'futar')).strip().lower()
                        
                        st.success(f"Sikeres belépés! Üdvözlünk, {st.session_state.user_nev}!")
                        st.rerun()
                        
        return 

    # App alapbeállításai és háttér adatbázisok betöltése
    st.set_page_config(page_title="Interfood Label Master", layout="wide")
    register_fonts()

    if 'mdf' not in st.session_state: st.session_state.mdf = None
    if 'meta_data' not in st.session_state: st.session_state.meta_data = []
    if 'weights' not in st.session_state: st.session_state.weights = {}
    if 'editor_key' not in st.session_state: st.session_state.editor_key = 0
    if 'c_n' not in st.session_state: st.session_state.c_n = "Szűcs István"
    if 'c_p' not in st.session_state: st.session_state.c_p = "+36 20 886 8971"

    if 'master_df' not in st.session_state:
        try:
            client = gspread.authorize(get_google_sheets_creds())
            sheet = client.open_by_key(SHEET_ID)
            
            m_df = pd.DataFrame(sheet.worksheet("Master_Adatbazis").get_all_records())
            m_df.columns = [col.strip().replace('\ufeff', '') for col in m_df.columns]
            st.session_state.etelek_master_df = m_df  
            
            n_df = pd.DataFrame(sheet.worksheet("Nevnapok").get_all_records())
            n_df.columns = [col.strip().replace('\ufeff', '') for col in n_df.columns]
            st.session_state.nevnapok_df = n_df
            
            k_df = pd.DataFrame(sheet.worksheet("Keresztnevek").get_all_records())
            k_df.columns = [col.strip().replace('\ufeff', '') for col in k_df.columns]
            st.session_state.keresztnevek_df = k_df

            api_df = pd.DataFrame(sheet.worksheet("Etlap_API").get_all_records())
            api_df.columns = [str(col).replace('\n', ' ').strip().replace('\ufeff', '') for col in api_df.columns]
            st.session_state.etlap_api_df = api_df
            
            st.success("✅ Minden adatbázis (Master, Névnapok, API) sikeresen betöltve!")
        except Exception as e:
            st.warning(f"⚠️ Hiba a táblák betöltésekor: {e}")
            st.session_state.master_df = pd.DataFrame()
            st.session_state.nevnapok_df = pd.DataFrame()
            st.session_state.keresztnevek_df = pd.DataFrame()
            st.session_state.etlap_api_df = pd.DataFrame()


    # =========================================================================
    # 📱 1. ÁG: QR-KÓDOS MOBIL NÉZET
    # =========================================================================
    if is_mobile_view:
        st.title("📱 Futár Terminál")
        st.caption(f"Bejelentkezve: {st.session_state.user_nev}")
        
        tab1, tab2, tab3 = st.tabs(["1. Áruátvétel 📦", "2. Címekre szedés 📥", "3. Kiszállítás 🚚"])
        
        with tab1:
            st.subheader("📦 Ömlesztett áruátvétel")
            st.info("Ellenőrizd a rekeszek tartalmát a konyha sorrendje szerint!")
            st.markdown("### Ellenőrző lista:")
            st.checkbox("Minta étel - Sport menü (Teszt darabszám)")
            if st.button("Áruátvétel kész ✅", key="mob_atvetel_btn", use_container_width=True):
                st.success("Áruátvétel rögzítve!")

        with tab2:
            st.subheader("📥 Bepakolás Thermoládákba")
            st.warning("A lista FORDÍTOTT sorrendben jelenik meg a bepakoláshoz!")
            if 'aktualis_lada_szam' not in st.session_state:
                st.session_state.aktualis_lada_szam = 1
            st.metric("Aktuális Thermoláda:", f"{st.session_state.aktualis_lada_szam}. láda")
            if st.button("📦 Láda lezárása (Megtelt)", key="mob_lada_btn", use_container_width=True):
                st.session_state.aktualis_lada_szam += 1
                st.rerun()

        with tab3:
            st.subheader("🚚 Kiszállítási útvonal")
            with st.container(border=True):
                st.markdown("### 1. Cím: Minta Ügyfél")
                st.markdown("📍 1000 Budapest, Próba utca 1.")
                st.button("Kiszállítva ✅", key="mob_kiszall_btn", type="primary", use_container_width=True)
                
        if st.button("🚪 Kijelentkezés", key="mob_logout"):
            st.session_state.bejelentkezve = False
            st.rerun()


    # =========================================================================
    # 🖥️ 2. ÁG: TELJES ASZTALI / ADMINISZTRÁCIÓS NÉZET (VÁLTOZATLAN LOGIKA)
    # =========================================================================
    else:
        # Felhasználói státusz panel az oldalsáv tetejére
        st.sidebar.markdown(f"### 👤 {st.session_state.user_nev}")
        
        if st.session_state.user_szerep == "admin" or st.session_state.user_szerep == "superadmin":
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
            st.session_state.c_n = st.text_input("Futár Neve", st.session_state.c_n)
            st.session_state.c_p = st.text_input("Telefonszám", st.session_state.c_p)
            kivalasztott_datum = st.date_input("📅 Kiszállítás dátuma (Névnaphoz)")
            st.divider()

            # ADMINISZTRÁCIÓS SZAKASZ (Csak jogosultaknak)
            if check_user_role() in ["admin", "superadmin"]:
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

            # PDF FELTÖLTÉS SECTION
            st.subheader("📄 Új PDF-ek")
            up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
            
            if up_files:
                if st.button("🚀 FELDOLGOZÁS"):
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
                        
                        if 'Járat' in df_temp.columns:
                            feltoltott_jaratok = df_temp['Járat'].dropna().astype(str).str.strip().unique().tolist()
                            feltoltott_jaratok = [j for j in feltoltott_jaratok if j != "" and j.lower() != 'nan']
                            if feltoltott_jaratok:
                                st.session_state.aktiv_jaratok = feltoltott_jaratok
                        
                        st.success("🎉 A menettervek feldolgozása és a felhő szinkronizáció sikeresen megtörtént!")
                        st.rerun()

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
                    logger.info("Adatmódosítások mentése a felhőbe...")
                    try:
                        sh = client.open_by_key(UGYFELKOR_SHEET_ID)
                        ws_ugyfel = sh.worksheet("Ugyfelkor")
                        sheets_df = pd.DataFrame(ws_ugyfel.get_all_records())
                        
                        for col in sheets_df.columns:
                            sheets_df[col] = sheets_df[col].astype(object)
                        sheets_df = sheets_df.fillna('')
                        
                        def tiszta_id_szoveg(val):
                            if pd.isna(val) or val == '': return ''
                            val_str = str(val).strip()
                            if val_str.endswith('.0'): val_str = val_str[:-2]
                            return val_str

                        sheets_df['ID'] = sheets_df['ID'].apply(tiszta_id_szoveg)
                        edited_df_clean = edited_df.copy()
                        
                        if 'ID' not in edited_df_clean.columns and edited_df_clean.index.name == 'ID':
                            edited_df_clean = edited_df_clean.reset_index()
                        elif 'ID' not in edited_df_clean.columns and 'ID' in sheets_df.columns:
                            edited_df_clean = edited_df_clean.reset_index()
                            if 'index' in edited_df_clean.columns: edited_df_clean = edited_df_clean.rename(columns={'index': 'ID'})
                            elif 'level_0' in edited_df_clean.columns: edited_df_clean = edited_df_clean.rename(columns={'level_0': 'ID'})

                        edited_df_clean = edited_df_clean.astype(object).fillna('')
                        
                        if 'ID' not in edited_df_clean.columns:
                            st.error("⚠️ Nem található 'ID' nevű oszlop a szerkesztett adatokban!")
                            st.stop()
                            
                        edited_df_clean['ID'] = edited_df_clean['ID'].apply(tiszta_id_szoveg)
                        módosult_darab = 0
                        
                        for _, row in edited_df_clean.iterrows():
                            current_id = row['ID']
                            if not current_id: continue
                            idx = sheets_df[sheets_df['ID'] == current_id].index
                            if not idx.empty:
                                sheet_idx = idx[0]
                                módosult_darab += 1
                                elerheto_oszlopok = row.index.tolist()
                                
                                if 'Név' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Név'] = str(row['Név']).strip()
                                elif 'Nev' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Név'] = str(row['Nev']).strip()
                                elif 'Ügyintéző' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Név'] = str(row['Ügyintéző']).strip()
                                
                                if 'Cím' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Cím'] = str(row['Cím']).strip()
                                elif 'Cim' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Cím'] = str(row['Cim']).strip()
                                
                                if 'Telefon' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Telefon'] = str(row['Telefon']).strip()
                                if 'Csoport' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Csoport'] = str(row['Csoport']).strip()
                                
                                if 'Megjegyzés' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Megjegyzés'] = str(row['Megjegyzés']).strip()
                                elif 'Megjegyzes' in elerheto_oszlopok: sheets_df.at[sheet_idx, 'Megjegyzés'] = str(row['Megjegyzes']).strip()
                                
                                if 'Lat' in elerheto_oszlopok and str(row['Lat']).strip() != '': sheets_df.at[sheet_idx, 'Lat'] = row['Lat']
                                if 'Lon' in elerheto_oszlopok and str(row['Lon']).strip() != '': sheets_df.at[sheet_idx, 'Lon'] = row['Lon']

                        if módosult_darab > 0:
                            ws_ugyfel.clear()
                            from gspread_dataframe import set_with_dataframe
                            set_with_dataframe(ws_ugyfel, sheets_df)
                            st.success(f"🎉 Siker! Összesen {módosult_darab} ügyfél adatai elmentve!")
                            st.balloons()
                            st.rerun()
                        else:
                            st.warning("Letöltött ID-k nem egyeznek.")
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

            c1, c2, c3 = st.columns(3)
            c1.download_button(
                "📄 ETIKETTEK", 
                create_label_pdf(edited_df, st.session_state.c_n, st.session_state.c_p, meta, st.session_state.etelek_master_df, st.session_state.nevnapok_df, st.session_state.keresztnevek_df, st.session_state.etlap_api_df),
                "etikettek.pdf", use_container_width=True
            )
            c2.download_button("📋 MENETTERV", create_manifest_pdf(edited_df, st.session_state.c_n, meta), "menetterv.pdf", use_container_width=True)
            c3.download_button("📊 RAKLISTA", create_raklista_pdf(edited_df, aktualis_jaratok, meta), "raklista.pdf", use_container_width=True)

            # --- QR-KÓD GENERÁLÁS A MOBIL NÉZETHEZ ---
            st.write("---")
            st.subheader("📱 Mobil Terminál Indítása")
            
            # Az appod pontos címe a megfelelő paraméterekkel
            # A meta['jarat'] segítségével a QR-kód már eleve tudni fogja, melyik járatról van szó
            alap_url = "https://interfood-menetterv-etikett-generator.streamlit.app" 
            jarat_id = meta.get('jarat', '')
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
