# -*- coding: utf-8 -*-
import gspread
import logging
import re
import pandas as pd
import requests
import streamlit as st
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
from geokodolo_modul import biztonsagos_koordinata_tisztito
from io import BytesIO

# JAVÍTÁS: getLogger használata get_logger helyett
logger = logging.getLogger(__name__)

# --- FIX SHEET ID-K A BIZTONSÁGI MENTÉSBŐL ---
SHEET_ID_MASTER = "1bZrtgqROYijYhyFOFrqYeSTUAsGqZU6GLijObJ1En0o" 
SHEET_ID_UGYFELKOR = "1nK0OLzVzEFY5bSLhMFfGgs4tOgMEueBgXeb9JUbLSN8"

def get_gspread_client():
    """
    Felépíti a Google Sheets kapcsolatot a belső service_account adatokkal.
    """
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # A Streamlit secrets-ből vagy a helyi környezetből olvassa be a hitelesítést
    try:
        if "gcp_service_account" in gspread.io.os.environ:
            # If on cloud environment
            import json
            info = json.loads(gspread.io.os.environ["gcp_service_account"])
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        else:
            # Local testing with Streamlit secrets
            import streamlit as st
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
            
        client = gspread.authorize(creds)
        logger.info("Sikeresen létrejött a Google Sheets API kapcsolat.")
        return client
    except Exception as e:
        logger.error(f"Google Sheets hitelesítési hiba: {e}")
        return None

@st.cache_data(ttl=300, show_spinner="Adatbázisok szinkronizálása...")
def load_sheet_data_cached(_client, sheet_id, worksheet_name):
    """Gyorsítótárazott táblázat beolvasás UNFORMATTED és fallback opciókkal."""
    import pandas as pd  # JAVÍTÁS: Helyi import a cache-környezet elszigeteltsége miatt!
    try:
        sheet = _client.open_by_key(sheet_id)
        worksheet = sheet.worksheet(worksheet_name)
        try:
            records = worksheet.get_all_records(value_render_option='UNFORMATTED_VALUE')
        except:
            records = worksheet.get_all_records()
        return pd.DataFrame(records)
    except Exception as e:
        logger.error(f"Hiba a táblázat beolvasásakor ({worksheet_name}): {e}")
        return pd.DataFrame()

def save_df_to_sheet(client, sheet_id, worksheet_name, df, clear_sheet=True):
    """Biztonságosan felülírja vagy frissíti a Google Sheet adott fülét a DataFrame adataival"""
    import pandas as pd
    try:
        sheet = client.open_by_key(sheet_id)
        worksheet = sheet.worksheet(worksheet_name)
        
        if clear_sheet:
            worksheet.clear()
            
        set_with_dataframe(worksheet, df)
        logger.info(f"Sikeresen mentve a DataFrame a(z) '{worksheet_name}' fülre.")
        return True
    except Exception as e:
        logger.error(f"Hiba a táblázat mentésekor ({worksheet_name}): {e}")
        return False

def kotelezo_ugyfelkor_formatum_tisztitas(df):
    """
    Szigorú típusbiztos szűrő az Ugyfelkor DataFrame-re.
    Garantálja, hogy a Google Sheets-be csak tiszta, számolható adatok kerüljenek.
    A koordinátákat átfuttatja a biztonsagos_koordinata_tisztito-n, és stringként 
    menti, hogy a Google Sheets ne nyelje le a tizedesvesszőket.
    """
    import pandas as pd  # JAVÍTÁS: Biztonságos helyi import
    if df.empty:
        return df
        
    df_clean = df.copy()
    
    # 1. ID kényszerítése tiszta 6 jegyű szöveggé
    if 'ID' in df_clean.columns:
        df_clean['ID'] = df_clean['ID'].astype(str).apply(
            lambda x: "".join(filter(str.isdigit, x.split('.')[0])).strip()
        )
        
    # 2. Nevek és Címek tisztítása a felesleges szóközöktől
    if 'Név' in df_clean.columns:
        df_clean['Név'] = df_clean['Név'].astype(str).str.strip()
    if 'Cím' in df_clean.columns:
        df_clean['Cím'] = df_clean['Cím'].astype(str).str.strip()
        
    # 3. Koordináták precíziós tisztítása és mentése
    for col in ['Lat', 'Lon']:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].apply(biztonsagos_koordinata_tisztito)
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
        
    df_clean = df_clean.fillna("")

    if 'Lat' in df_clean.columns:
        df_clean['Lat'] = df_clean['Lat'].astype(str)
    if 'Lon' in df_clean.columns:
        df_clean['Lon'] = df_clean['Lon'].astype(str)
    
    return df_clean

def get_latest_week_from_master(sheet_id, client):
    """Kinyeri a legnagyobb hetet a 'wXX' formátumú szövegekből a megadott klienssel."""
    import pandas as pd  # JAVÍTÁS: Biztonságos helyi import
    try:
        if client is None:
            return 2026, 0
        sheet = client.open_by_key(sheet_id).worksheet("Master_Adatbazis")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        oszlop_nev = "Kódok és Árak" 
        if oszlop_nev not in df.columns:
            logger.error(f"Hiba: Az oszlop '{oszlop_nev}' nem található.")
            return 2026, 0

        all_weeks = []
        for cell_content in df[oszlop_nev].astype(str):
            weeks = re.findall(r'w(\d+)', cell_content)
            all_weeks.extend([int(w) for w in weeks])
            
        if not all_weeks:
            return 2026, 0
            
        return 2026, max(all_weeks)
    except Exception as e:
        logger.error(f"Hiba történt a hét lekérésekor: {e}")
        return 2026, 0

@st.cache_data(show_spinner="Étlap API frissítése a felhőből...")
def load_etlap_api_smart(_client, sheet_id, columns_trigger=None):
    """
    Letölti az Etlap_API munkalapot a Google Sheets-ből a megadott klienssel. 
    Ha a 'columns_trigger' megváltozik, a Streamlit újra letölti!
    """
    import pandas as pd  # JAVÍTÁS: Biztonságos helyi import
    try:
        if _client is None:
            return pd.DataFrame()
            
        sh = _client.open_by_key(sheet_id)
        ws_api = sh.worksheet("Etlap_API")
        
        df = pd.DataFrame(ws_api.get_all_records())
        df.columns = [str(col).strip().replace('\ufeff', '') for col in df.columns]
        return df
    except Exception as e:
        logger.error(f"❌ Smart Cache hiba az Etlap_API letöltésekor: {e}")
        return pd.DataFrame()

def master_lista_szinkron(df_napi, sheet_id, client, jarat_szam=None):
    """
    Összefésüli a napi listát a törzslistával (Ugyfelkor) szigorúan 6 jegyű ID alapján.
    Az 'Ugyfelkor' fület CSAK BŐVÍTI az új ügyfelekkel, az 'Adatok' fület szinkronizálja.
    """
    import pandas as pd
    import streamlit as st
    import logging
    import time
    from datetime import datetime
    from gspread_dataframe import set_with_dataframe
    from geopy.geocoders import Nominatim
    import re
    
    from geokodolo_modul import biztonsagos_koordinata_tisztito
    
    logger = logging.getLogger(__name__)
    logger.info("🧬 Master lista szinkronizálása elindult az új struktúra alapján (Kvötavédelemmel)...")
    master_df = pd.DataFrame()

    def tiszta_id_konverzio(x):
        if pd.isna(x) or x == "":
            return ""
        s = str(x).replace("'", "").replace(' ', '').strip()
        if '-' in s:
            s = s.split('-')[-1]
        tisztitott = "".join(filter(str.isdigit, s))
        return tisztitott if len(tisztitott) > 0 else ""

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
        
        master_df = load_sheet_data_cached(client, sheet_id, "Ugyfelkor")
        
        if master_df.empty:
            master_df = pd.DataFrame(columns=['ID', 'Név', 'Cím', 'Lat', 'Lon', 'Telefon', 'Csoport', 'Megjegyzés', 'Utolso_Rendeles', 'Osszertek', 'Rendeles_Szam'])
            
        master_df.columns = [c.strip() for c in master_df.columns]
        
        if 'ID' in master_df.columns:
            master_df['ID'] = master_df['ID'].astype(str).str.strip().apply(lambda x: x.split('.')[0] if x.endswith('.0') else x)
            master_df['ID'] = master_df['ID'].apply(tiszta_id_konverzio)
            
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
    
    try:
        def kényszeritett_koordinata_tisztito(val):
            if pd.isna(val) or str(val).strip() in ["", "0", "0.0", "None", "nan", "NaN"]:
                return ""
            s = str(val).replace(",", ".").replace(" ", "").strip().lstrip("'")
            if "." not in s and len(s) >= 6:
                s = s[:2] + "." + s[2:]
            return s

        def kényszeritett_cim_tisztito(nyers_szoveg):
            if not nyers_szoveg:
                return ""
            s = re.sub(r'\(.*?\)', '', str(nyers_szoveg)).strip()
            s = s.replace('$', '').strip()
            s = re.sub(r'\.?\s+\d+/\d+.*$', '', s)
            s = re.split(r'(?i)\s+(fszt|fsz|emelet|em|ajtó|ajto|lh|lph).*$', s)[0]
            return s.strip().rstrip(',').rstrip('.')

        if not master_df.empty:
            master_df = kotelezo_ugyfelkor_formatum_tisztitas(master_df)
            if 'Lat' in master_df.columns:
                master_df['Lat'] = master_df['Lat'].apply(kényszeritett_koordinata_tisztito)
            if 'Lon' in master_df.columns:
                master_df['Lon'] = master_df['Lon'].apply(kényszeritett_koordinata_tisztito)
        
        meta_forras = st.session_state.get('meta_data', {})
        szallitas_napja = meta_forras.get('datum_iso', datetime.now().strftime("%Y-%m-%d"))
        
        új_koordináta_számláló = 0
        geolocator_helyi = Nominatim(user_agent="Interfood_Express_Delivery_App_v3_2026")
        
        for idx, row in df_napi.iterrows():
            u_id = str(row['ID']).strip()
            if not u_id or u_id == "" or u_id == "nan": 
                continue
                
            mai_rendeles_erteke = 0
            if 'Fizetendő' in row and pd.notna(row['Fizetendő']):
                tisztitott_ar = str(row['Fizetendő']).replace('Ft', '').replace(' ', '').strip()
                if tisztitott_ar.isdigit() or (tisztitott_ar.startswith('-') and tisztitott_ar[1:].isdigit()):
                    mai_rendeles_erteke = int(tisztitott_ar)
            
            van_koordinata = False
            lat_clean, lon_clean = "", ""
            
            if not master_df.empty and 'ID' in master_df.columns:
                if u_id in master_df['ID'].values:
                    talalat = master_df[master_df['ID'] == u_id]
                    lat_str = kényszeritett_koordinata_tisztito(talalat.iloc[0].get('Lat'))
                    lon_str = kényszeritett_koordinata_tisztito(talalat.iloc[0].get('Lon'))
                    
                    if lat_str != "" and lon_str != "":
                        lat_clean = lat_str
                        lon_clean = lon_str
                        van_koordinata = True
            
            if not van_koordinata:
                nev = row.get('Ügyintéző', row.get('Név', row.get('Nev', 'Ismeretlen név')))
                eredeti_cim = str(row.get('Cím', row.get('Cim', '')))
                keresesi_cim = kényszeritett_cim_tisztito(eredeti_cim)
                    
                logger.info(f"✨ Koordináta keresése CÍM alapján: {nev} ({u_id}) -> {keresesi_cim}")
                st.info(f"📍 GPS koordináta keresése: {nev}...")
                
                lat, lon = None, None
                try:
                    time.sleep(1.3)
                    location = geolocator_helyi.geocode(keresesi_cim, timeout=10)
                    if location:
                        lat, lon = location.latitude, location.longitude
                    else:
                        vágott_cim_iranyitoszam_nelkul = re.sub(r'^\d{4}\s+', '', keresesi_cim).strip()
                        location_vágott = geolocator_helyi.geocode(vágott_cim_iranyitoszam_nelkul, timeout=10)
                        if location_vágott:
                            lat, lon = location_vágott.latitude, location_vágott.longitude
                        else:
                            utca_szint = ", ".join(keresesi_cim.split(",")[:2])
                            utca_szint = re.sub(r'\s+\d+\s*$', '', utca_szint).strip()
                            location_utca = geolocator_helyi.geocode(utca_szint, timeout=10)
                            if location_utca:
                                lat, lon = location_utca.latitude, location_utca.longitude
                                
                except Exception as e_geo:
                    logger.error(f"Hiba a geocoding során ({nev}): {e_geo}")
                    lat, lon = None, None
                    
                if lat is not None and lon is not None:
                    lat_clean = str(round(float(lat), 6))
                    lon_clean = str(round(float(lon), 6))
                    st.success(f"🎯 GPS sikeresen megvan: {nev} -> ({lat_clean}, {lon_clean})")
                    új_koordináta_számláló += 1
                else:
                    st.warning(f"⚠️ Nem találtam koordinátát a címre: {eredeti_cim} ({nev})")
                    lat_clean, lon_clean = "", ""

            if not master_df.empty and u_id in master_df['ID'].values:
                idx_ugyfel = master_df[master_df['ID'] == u_id].index[0]
                try:
                    jelenlegi_ertek = int(float(str(master_df.at[idx_ugyfel, 'Osszertek']).strip() or 0))
                    jelenlegi_szam = int(float(str(master_df.at[idx_ugyfel, 'Rendeles_Szam']).strip() or 0))
                except:
                    jelenlegi_ertek, jelenlegi_szam = 0, 0

                master_df.at[idx_ugyfel, 'Osszertek'] = jelenlegi_ertek + mai_rendeles_erteke
                master_df.at[idx_ugyfel, 'Rendeles_Szam'] = jelenlegi_szam + 1
                master_df.at[idx_ugyfel, 'Utolso_Rendeles'] = szallitas_napja
                master_df.at[idx_ugyfel, 'Lat'] = str(lat_clean)
                master_df.at[idx_ugyfel, 'Lon'] = str(lon_clean)
            else:
                uj_sor = {
                    'ID': u_id,
                    'Név': row.get('Név', row.get('Ügyintéző', 'Ismeretlen Ügyfél')),
                    'Cím': row.get('Cím', row.get('Cim', '')),
                    'Lat': str(lat_clean),
                    'Lon': str(lon_clean),
                    'Telefon': str(row.get('Telefon', '')),
                    'Csoport': str(row.get('Csoport', '')),
                    'Megjegyzés': str(row.get('Megjegyzés', row.get('Megjegyzes', ''))),
                    'Utolso_Rendeles': szallitas_napja,
                    'Osszertek': mai_rendeles_erteke,
                    'Rendeles_Szam': 1
                }
                master_df = pd.concat([master_df, pd.DataFrame([uj_sor])], ignore_index=True)

        master_df['Lat'] = master_df['Lat'].astype(str).str.strip().replace(['nan', 'None', '0.0', '0'], '')
        master_df['Lon'] = master_df['Lon'].astype(str).str.strip().replace(['nan', 'None', '0.0', '0'], '')

        df_ugyfelkor_vegleges = kotelezo_ugyfelkor_formatum_tisztitas(master_df)
        
        set_with_dataframe(ws_ugyfel, df_ugyfelkor_vegleges, row=1, col=1, include_index=False, resize=True)
        st.success(f"🎉 Ügyfélkör adatbázis sikeresen frissítve! Új koordináták pótolva: {új_koordináta_számláló} db.")

        master_df = df_ugyfelkor_vegleges.copy()
        if 'google_data_loaded' in st.session_state:
            del st.session_state['google_data_loaded']
            
    except Exception as e_full_process:
        logger.error(f"Súlyos hiba az ügyfélkör frissítése során: {e_full_process}")
        st.error(f"❌ Nem sikerült az ügyfélkör automatikus frissítése: {e_full_process}")
        
    # --- 4. LÉPÉS: SZIGORÚ ÖSSZEFÉSÜLÉS ---
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

    # --- 5. LÉPÉS: SORSZÁM GENERÁLÁSA ---
    df_napi['Sorrend'] = range(1, len(df_napi) + 1)

    # --- 6. LÉPÉS: OSZLOPOK KITÖLTÉSE ---
    if 'Név' not in df_napi.columns:
        if 'Ügyintéző' in df_napi.columns: df_napi['Név'] = df_napi['Ügyintéző']
        elif 'Nev' in df_napi.columns: df_napi['Név'] = df_napi['Nev']
        else: df_napi['Név'] = "Ismeretlen"

    if 'Fizetendő' not in df_napi.columns and 'Pénz' in df_napi.columns:
        df_napi['Fizetendő'] = df_napi['Pénz']

    if 'Járat' not in df_napi.columns:
        df_napi['Járat'] = jarat_szam if jarat_szam else ""
    else:
        df_napi['Járat'] = df_napi['Járat'].fillna("")
        if jarat_szam:
            df_napi['Járat'] = df_napi['Járat'].apply(lambda x: jarat_szam if str(x).strip() == "" else x)

    for col in ['Rendelés', 'Megjegyzés', 'Fizetési Mód', 'Státusz', 'Időbélyeg', 'Telefon', 'Csoport']:
        if col not in df_napi.columns:
            df_napi[col] = "Kiszállítás alatt" if col == 'Státusz' else ""

    # --- 7. LÉPÉS: FRISSÍTÉS AZ "ADATOK" FÜLRE ---
    try:
        time.sleep(1.0)
        ws_adatok = sh.worksheet("Adatok")
        existing_records = ws_adatok.get_all_records()
        df_existing = pd.DataFrame(existing_records) if existing_records else pd.DataFrame()
        if not df_existing.empty:
            df_existing.columns = [c.strip() for c in df_existing.columns]

        if 'Rendelés_Full' in df_napi.columns:
            df_napi['Rendelés'] = df_napi.apply(
                lambda row: str(row['Rendelés_Full']).strip() if str(row.get('Rendelés_Full', '')).strip() != "" else row['Rendelés'], 
                axis=1
            )
        
        aktualis_futar_nev = st.session_state.get('user_nev', 'Ismeretlen_Feltölto')
        df_napi['Feldolgozó Futár'] = aktualis_futar_nev
        
        export_cols = ['ID', 'Név', 'Cím', 'Telefon', 'Csoport', 'Sorrend', 'Lat', 'Lon', 'Rendelés', 'Megjegyzés', 'Járat', 'Fizetendő', 'Fizetési Mód', 'Státusz', 'Időbélyeg', 'Feldolgozó Futár']
        df_uj_adatok = df_napi[export_cols].copy()
        
        if not df_existing.empty and 'Feldolgozó Futár' in df_existing.columns:
            df_mások_adatai = df_existing[df_existing['Feldolgozó Futár'] != aktualis_futar_nev]
            df_saját_lezárt_adatai = df_existing[(df_existing['Feldolgozó Futár'] == aktualis_futar_nev) & (df_existing['Időbélyeg'].astype(str).str.strip() != "")]
            save_df = pd.concat([df_mások_adatai, df_saját_lezárt_adatai, df_uj_adatok], ignore_index=True)
        else:
            save_df = df_uj_adatok

        save_df['Lat'] = save_df['Lat'].astype(str).str.strip().replace(['nan', 'None', '0.0', '0'], '')
        save_df['Lon'] = save_df['Lon'].astype(str).str.strip().replace(['nan', 'None', '0.0', '0'], '')
        save_df['ID'] = save_df['ID'].astype(str)
        
        for col in save_df.columns:
            save_df[col] = save_df[col].astype(object)
        save_df = save_df.fillna('')
        
        ws_adatok.clear()
        set_with_dataframe(ws_adatok, save_df, include_index=False, include_column_header=True)
        logger.info("🚀 Biztonságos, többfelhasználós szinkronizáció kész! Minden kolléga adata megőrizve.")
        st.success("🚀 Mobil terminál adatsorok (Adatok) sikeresen szinkronizálva a felhőbe!")

        # --- STATISZTIKA MENTÉS A MOBIL_SUMMARY LAPRA ---
        try:
            ws_summary = sh.worksheet("Mobil_Summary")
            osszes_etel = 0
            if 'Rendelés' in df_uj_adatok.columns:
                for _, r in df_uj_adatok.iterrows():
                    r_szoveg = str(r.get('Rendelés', ''))
                    darabok = re.findall(r'(\d+)-', r_szoveg)
                    osszes_etel += sum(int(d) for d in darabok) if darabok else (1 if r_szoveg.strip() and r_szoveg.lower() != 'none' else 0)

            forgalom_osszes = 0
            if 'Fizetendő' in df_uj_adatok.columns:
                f_sor = df_uj_adatok['Fizetendő'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                forgalom_osszes = int(pd.to_numeric(f_sor, errors='coerce').fillna(0).sum())

            try:
                datum_obj = datetime.strptime(szallitas_napja, "%Y-%m-%d")
                aktualis_ev, aktualis_het, _ = datum_obj.isocalendar()
            except:
                aktualis_ev, aktualis_het = datetime.now().isocalendar()[0], datetime.now().isocalendar()[1]

            eddigi_heti_forgalom = 0
            summary_records = ws_summary.get_all_records()
            
            if summary_records:
                df_sum_history = pd.DataFrame(summary_records)
                df_sum_history.columns = [str(c).strip() for c in df_sum_history.columns]
                
                d_col = next((c for c in df_sum_history.columns if 'dátum' in c.lower() or 'datum' in c.lower()), df_sum_history.columns[0])
                f_col = next((c for c in df_sum_history.columns if 'futár' in c.lower() or 'futar' in c.lower()), df_sum_history.columns[1])
                p_col = next((c for c in df_sum_history.columns if 'forgalom' in c.lower() or 'bevétel' in c.lower()), df_sum_history.columns[6])

                df_futar_history = df_sum_history[df_sum_history[f_col].astype(str).str.strip() == aktualis_futar_nev.strip()]
                
                for _, hist_row in df_futar_history.iterrows():
                    hist_date_str = str(hist_row[d_col]).strip()
                    try:
                        hist_dt = datetime.strptime(hist_date_str, "%Y-%m-%d")
                        h_ev, h_het, _ = hist_dt.isocalendar()
                        if h_ev == aktualis_ev and h_het == aktualis_het:
                            hist_money = str(hist_row[p_col]).replace(' ', '').replace('Ft', '').strip()
                            hist_money = "".join(filter(str.isdigit, hist_money))
                            if hist_money.isdigit():
                                eddigi_heti_forgalom += int(hist_money)
                    except:
                        continue

            teljes_heti_volumen = eddigi_heti_forgalom + forgalom_osszes
            if teljes_heti_volumen >= 2100000:
                jutalek_szazalek = 0.14
                st.info(f"🚀 Gratuláció! A heti összesített forgalom ({teljes_heti_volumen:,} Ft) átlépte a limitet. 14%-os emelt jutalék érvényes!")
            else:
                jutalek_szazalek = 0.13
                st.info(f"📊 Aktuális heti összesített forgalom: {teljes_heti_volumen:,} Ft (Alap 13%-os sáv).")

            vart_jutalek = int(forgalom_osszes * jutalek_szazalek)
            jaratok_str = ", ".join(df_uj_adatok['Járat'].astype(str).unique())

            summary_row = [szallitas_napja, aktualis_futar_nev, jaratok_str, len(df_uj_adatok), len(df_uj_adatok), osszes_etel, forgalom_osszes, 0, 0, vart_jutalek]
            ws_summary.append_row(summary_row)
            st.success(f"📈 Napi rekord rögzítve a heti elszámolás alapján ({jutalek_szazalek*100}% jutalékkal: {vart_jutalek:,} Ft)!")
            
        except Exception as e_sum:
            logger.error(f"Hiba a Mobil_Summary mentésekor: {e_sum}")
            st.warning(f"⚠️ A statisztikai összefoglalót nem sikerült rögzíteni: {e_sum}")
            
    except Exception as e:
        logger.warning(f"A szinkronizáció megszakadt az 'Adatok' fül frissítésekor: {e}")

    logger.info("Szinkronizáció teljesen kész.")
    return df_napi, master_df

def sync_interfood_etlap(year, week, sheet_id):
    """
    Letölti az Interfood étlapot az API-ból Excel formátumban,
    és feltölti a Google Sheets 'Etlap_API' munkalapjára.
    """
    import pandas as pd  # JAVÍTÁS: Biztonságos helyi import
    api_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    cache_key = f"sync_done_{year}_{week}"
    if st.session_state.get(cache_key, False):
        logging.info(f"Interfood étlap szinkron ({year}/W{week}) ebből a munkamenetből már megvolt, átugrás.")
        return True
    
    try:
        st.info(f"🔮 Kapcsolódás az API-hoz: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            st.error(f"Az API hiba kódot küldött: {response.status_code}")
            st.stop()
            return False

        content = response.content
        if len(content) < 100:
            st.error("Az API válasza túl rövid, valószínűleg nem egy Excel fájlt kaptunk.")
            st.stop()
            return False

        try:
            df = pd.read_excel(BytesIO(content))
        except Exception as ex_err:
            st.error(f"Excel beolvasási hiba: {ex_err}")
            st.write("A kapott válasz eleje (nyers):", content[:100])
            st.stop()
            return False

        client = st.session_state.get('client')
        if not client:
            st.error("❌ Google Sheets kliens nem érhető el! Nem sikerült a hitelesítés.")
            st.stop()
            return False
            
        sheet = client.open_by_key(sheet_id)
        
        try:
            worksheet = sheet.worksheet("Etlap_API")
        except:
            worksheet = sheet.add_worksheet(title="Etlap_API", rows="1000", cols="20")
            
        worksheet.clear()
        set_with_dataframe(worksheet, df)
        
        st.session_state[cache_key] = True
        st.toast(f"Sikeres szinkron: {year}/W{week}", icon="✅")
        return True
        
    except gspread.exceptions.APIError as api_err:
        if "Quota exceeded" in str(api_err):
            st.warning(f"⚠️ Google Sheets hívási limit túllépve (429). A szinkronizálást most átugorjuk, de az app megy tovább!")
            return True
        raise api_err
        
    except Exception as e:
        st.error(f"❌ KRITIKUS HIBA TÖRTÉNT!")
        with st.expander("Kattints ide a részletes hibaadatokért"):
            st.write(f"Hiba típusa: {type(e).__name__}")
            st.write(f"Üzenet: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
        
        st.warning("A program futása megállt a hiba miatt. Másold ki a fenti adatokat!")
        st.stop()

def load_etlap_from_sheets(sheet_id):
    """
    Beolvassa a Google Sheets 'Etlap' és 'Etlap_API' fülét,
    majd az adatokat strukturált indexként adja vissza/menti a session_state-be.
    """
    import streamlit as st
    import pandas as pd  # JAVÍTÁS: Biztonságos helyi import
    
    client = st.session_state.get('client')
    if not client:
        st.error("❌ Google Sheets kapcsolat nem érhető el a load_etlap_from_sheets funkcióban!")
        return {}

    try:
        sheet = client.open_by_key(sheet_id)
        
        kategoria_index = {}
        try:
            kat_worksheet = sheet.worksheet("Etlap")
            kat_data = kat_worksheet.get_all_records()
            
            for row in kat_data:
                cikkszam = str(row.get('Cikkszam', '')).strip().upper()
                if cikkszam:
                    sorrend_nyers = str(row.get('Konyha_Sorrend', '99')).strip()
                    sorrend_szam = int(sorrend_nyers) if sorrend_nyers.isdigit() else 99
                    
                    kategoria_index[cikkszam] = {
                        "kategoria": row.get('Kategoria', 'Egyéb / Zóna ételek'),
                        "sorrend": sorrend_szam
                    }
            st.session_state['kategoria_adatok'] = kategoria_index
        except Exception as kat_err:
            st.warning(f"⚠️ Az 'Etlap' munkalap beolvasása sikertelen, de az árakat betöltöm. Hiba: {kat_err}")
            st.session_state['kategoria_adatok'] = {}

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
                        ar = str(df.iloc[i + 1, nap_idx]).strip().replace('Ft', '').replace(' ', '')
                    
                    if nev and nev.lower() != "nan" and nev != "":
                        kulcs = f"{nap_idx}_{kod}"
                        etlap_index[kulcs] = {
                            "nev": nev,
                            "ar": ar
                        }
        
        return etlap_index
        
    except Exception as e:
        st.error(f"❌ Hiba az étlap beolvasásakor a Sheets-ből: {e}")
        return {}

def load_futar_from_sheets(sheet_id):
    """Betölti a futárok adatait a Google Sheet 'Futárok' lapjáról."""
    import streamlit as st
    import pandas as pd  # JAVÍTÁS: Biztonságos helyi import
    import logging
    
    logger = logging.getLogger(__name__)
    client = st.session_state.get('client')
    if not client:
        logger.error("❌ Google Sheets kapcsolat nem érhető el a load_futar_from_sheets funkcióban!")
        return pd.DataFrame()

    try:
        sheet = client.open_by_key(sheet_id).worksheet("Futárok")
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        logger.error(f"Hiba a futárok betöltésekor: {e}")
        return pd.DataFrame()

def save_futar_to_sheets(df, sheet_id):
    """Visszamenti a módosított futár adatokat a Google Sheet 'Futárok' lapjára."""
    import streamlit as st
    import pandas as pd  # JAVÍTÁS: Biztonságos helyi import
    import logging
    
    logger = logging.getLogger(__name__)
    client = st.session_state.get('client')
    if not client:
        logger.error("❌ Google Sheets kapcsolat nem érhető el a save_futar_to_sheets funkcióban!")
        return False

    try:
        sheet = client.open_by_key(sheet_id).worksheet("Futárok")
        sheet.clear()
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
    import streamlit as st
    import pandas as pd
    import requests
    from io import BytesIO
    from utils import clean_text
    
    client = st.session_state.get('client')
    if not client:
        st.error("❌ Google Sheets kapcsolat nem érhető el a sync_master_database funkcióban!")
        return False

    try:
        try:
            worksheet = sheet.open_by_key(sheet_id).worksheet("Master_Adatbazis")
            existing_data = worksheet.get_all_records()
            master_dict = {
                str(row['Tisztított Név']): {
                    "Eredeti Név": row.get('Eredeti Név', ''),
                    "KodAr_List": str(row.get('Kódok és Árak', '')).split(", ") if row.get('Kódok és Árak') else [],
                    "Kellék": row.get('Kellék', ''),
                    "Gyakoriság": int(row.get('Gyakoriság', 1))
                } for row in existing_data if row.get('Tisztított Név')
            }
            st.info(f"ℹ️ Meglévő adatbázis betöltve: {len(master_dict)} étel.")
        except Exception:
            sheet_obj = client.open_by_key(sheet_id)
            worksheet = sheet_obj.add_worksheet(title="Master_Adatbazis", rows="5000", cols="10")
            master_dict = {}
            st.info("ℹ️ Új Master_Adatbazis fül létrehozva.")

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
                                    master_dict[tiszta_nev]['Gyakoriság'] += 1
                                    if kod_ar_par not in master_dict[tiszta_nev]['KodAr_List']:
                                        master_dict[tiszta_nev]['KodAr_List'].append(kod_ar_par)
                                else:
                                    master_dict[tiszta_nev] = {
                                        "Eredeti Név": eredeti_nev.replace('*', '').strip(),
                                        "KodAr_List": [kod_ar_par],
                                        "Kellék": "",
                                        "Gyakoriság": 1
                                    }
            else:
                st.warning(f"Nem sikerült letölteni: {ev}/{het}")

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
        return True
        
    except Exception as e:
        st.error(f"Hiba a Master szinkron során: {e}")
        return False

def load_master_data():
    """Betölti a hosszú távú memóriát a helyi CSV fájlból."""
    import os
    import pandas as pd
    
    if os.path.exists("master_data.csv"):
        return pd.read_csv("master_data.csv", dtype={'Ügyfélkód': str})
    return pd.DataFrame(columns=['Ügyfélkód', 'Ügyintéző', 'Cím', 'Telefonszám', 'Megjegyzés'])

def save_to_master(current_df):
    """Összefűzi a friss adatokat a meglévő helyi CSV master adattal, az újak felülírják a régit."""
    import pandas as pd
    
    master_df = load_master_data()
    updated_master = pd.concat([master_df, current_df[['Ügyfélkód', 'Ügyintéző', 'Cím', 'Telefonszám', 'Megjegyzés']]])
    updated_master = updated_master.drop_duplicates(subset=['Ügyfélkód'], keep='last')
    updated_master.to_csv("master_data.csv", index=False)

def sync_ugyfelkor_fel(df_napi, sheet_id):
    """
    Feltölti a napi ügyféladatokat a Google Sheet 'Adatok' fülére (Upsert).
    Ha az ID már létezik, frissíti az adatokat, ha új, akkor hozzáfűzi.
    """
    import streamlit as st
    import pandas as pd
    from datetime import datetime

    client = st.session_state.get('client')
    if client is None:
        return 0
        
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet("Adatok")
    except:
        ws = sh.add_worksheet(title="Adatok", rows="1000", cols="10")
        ws.append_row(["ID", "Név", "Cím", "Telefon", "Csoport", "Preferált Sorrend", "Megjegyzés", "Utolsó Rendelés"])

    data = ws.get_all_records()
    db_df = pd.DataFrame(data)
    
    if db_df.empty:
        db_df = pd.DataFrame(columns=["ID", "Név", "Cím", "Telefon", "Csoport", "Preferált Sorrend", "Megjegyzés", "Utolsó Rendelés"])
    else:
        db_df = db_df.astype(str)

    ma = datetime.now().strftime("%Y-%m-%d")
    
    for _, row in df_napi.iterrows():
        u_id = str(row.get('temp_id', '')).strip()
        if not u_id or u_id in ['nan', 'None', '']: 
            continue

        u_nev = str(row.get('Ügyintéző', '')).strip()
        u_cim = str(row.get('Cím', '')).strip()
        u_tel = str(row.get('Telefon', '')).strip()
        u_sorrend = str(row.get('Sorrend', '')).strip()
        u_megj = str(row.get('Megjegyzés', '')).strip()

        mask = db_df['ID'].astype(str) == u_id
        if mask.any():
            idx = db_df[mask].index[0]
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

    db_df = db_df.replace('nan', '').fillna("")
    
    final_list = [db_df.columns.values.tolist()] + db_df.values.tolist()
    ws.clear()
    ws.update('A1', final_list)
    return len(df_napi)

def adatok_visszatoltese_sheetrol(df_napi, sheet_id):
    """
    A Google Sheet 'Adatok' füléről visszatölti a korábban mentett ügyféladatokat,
    frissíti a napi DataFrame-et (nevek, preferált sorrend, megjegyzések),
    majd a beállított sorrend alapján rendezi a táblázatot.
    """
    import streamlit as st
    import pandas as pd
    
    client = st.session_state.get('client')
    if client is None: 
        return df_napi
        
    try:
        sh = client.open_by_key(sheet_id)
        ws = sh.worksheet("Adatok")
        db_df = pd.DataFrame(ws.get_all_records())
        
        if db_df.empty: 
            return df_napi
            
        db_df['ID'] = db_df['ID'].astype(str).str.strip()
        
        if 'Original_Order' not in df_napi.columns:
            df_napi['Original_Order'] = range(1, len(df_napi) + 1)

        for i, row in df_napi.iterrows():
            u_id = str(row.get('temp_id', '')).strip()
            match = db_df[db_df['ID'] == u_id]
            
            if not match.empty:
                s_nev = str(match.iloc[0]['Név']).strip()
                if s_nev and s_nev.lower() != 'nan':
                    df_napi.at[i, 'Ügyintéző'] = s_nev
                
                s_sorrend = str(match.iloc[0]['Preferált Sorrend']).strip()
                if s_sorrend and s_sorrend.lower() != 'nan' and s_sorrend != "":
                    try:
                        df_napi.at[i, 'Sorrend'] = float(s_sorrend)
                    except:
                        pass
                
                for col in ['Csoport', 'Megjegyzés']:
                    val = str(match.iloc[0].get(col, '')).strip()
                    if val.lower() != 'nan':
                        df_napi.at[i, col] = val
        
        df_napi['Sorrend'] = pd.to_numeric(df_napi['Sorrend'], errors='coerce')
        df_napi['Sorrend'] = df_napi['Sorrend'].fillna(df_napi['Original_Order'])
        
        df_napi = df_napi.sort_values(by=['Sorrend'], ascending=[True])
        
        return df_napi
    except Exception as e:
        st.error(f"❌ Hiba a visszatöltésnél: {e}")
        return df_napi

def _tiszta_futar_lista_letoltes(sheet_id):
    """Biztonságosan letölti a futárok listáját a PIN kódos azonosításhoz."""
    import streamlit as st
    import pandas as pd
    
    client = st.session_state.get('client')
    if client is None:
        return []
        
    try:
        sh = client.open_by_key(sheet_id)
        try:
            ws = sh.worksheet("Futárok")
        except Exception:
            ws = sh.get_worksheet(0) 
        return ws.get_all_records()
    except Exception as e:
        st.error(f"Hiba a futár lista letöltésekor: {e}")
        return []
