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

logger = logging.getLogger(__name__)

SHEET_ID_MASTER = "1bZrtgqROYijYhyFOFrqYeSTUAsGqZU6GLijObJ1En0o" 
SHEET_ID_UGYFELKOR = "1nK0OLzVzEFY5bSLhMFfGgs4tOgMEueBgXeb9JUbLSN8"

def get_gspread_client():
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive"
    ]
    try:
        if "gcp_service_account" in gspread.io.os.environ:
            import json
            info = json.loads(gspread.io.os.environ["gcp_service_account"])
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        else:
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
    import pandas as pd
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

def _tiszta_futar_lista_letoltes(sheet_id):
    import pandas as pd
    import streamlit as st
    client = st.session_state.get('client')
    if not client: 
        return []
    try:
        sheet = client.open_by_key(sheet_id).worksheet("Futárok")
        df = pd.DataFrame(sheet.get_all_records())
        if df.empty:
            return []
        return df.to_dict('records')
    except Exception as e:
        logger.error(f"Hiba a futár lista letöltésekor: {e}")
        return []

def save_df_to_sheet(client, sheet_id, worksheet_name, df, clear_sheet=True):
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
    import pandas as pd
    if df.empty: return df
    df_clean = df.copy()
    
    if 'ID' in df_clean.columns:
        df_clean['ID'] = df_clean['ID'].astype(str).apply(
            lambda x: "".join(filter(str.isdigit, x.split('.')[0])).strip()
        )
    if 'Név' in df_clean.columns:
        df_clean['Név'] = df_clean['Név'].astype(str).str.strip()
    if 'Cím' in df_clean.columns:
        df_clean['Cím'] = df_clean['Cím'].astype(str).str.strip()
        
    for col in ['Lat', 'Lon']:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].apply(biztonsagos_koordinata_tisztito)
            df_clean[col] = df_clean[col].apply(lambda x: f"{x}" if x is not None and not pd.isna(x) else "")
            
    for col in ['Telefon', 'Csoport', 'Megjegyzés', 'Utolso_Rendeles']:
        if col in df_clean.columns:
            df_clean[col] = df_clean[col].astype(str).str.strip().replace(['nan', 'None', '<NA>', 'NaN'], '')
            
    if 'Osszertek' in df_clean.columns:
        df_clean['Osszertek'] = df_clean['Osszertek'].astype(str).str.replace(r'[^0-9-]', '', regex=True)
        df_clean['Osszertek'] = pd.to_numeric(df_clean['Osszertek'], errors='coerce').fillna(0).astype(int)
        
    if 'Rendeles_Szam' in df_clean.columns:
        df_clean['Rendeles_Szam'] = df_clean['Rendeles_Szam'].astype(str).str.replace(r'[^0-9-]', '', regex=True)
        df_clean['Rendeles_Szam'] = pd.to_numeric(df_clean['Rendeles_Szam'], errors='coerce').fillna(0).astype(int)
        
    df_clean = df_clean.fillna("")
    if 'Lat' in df_clean.columns: df_clean['Lat'] = df_clean['Lat'].astype(str)
    if 'Lon' in df_clean.columns: df_clean['Lon'] = df_clean['Lon'].astype(str)
    return df_clean

def get_latest_week_from_master(sheet_id, client):
    import pandas as pd
    try:
        if client is None: return 2026, 0
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
        if not all_weeks: return 2026, 0
        return 2026, max(all_weeks)
    except Exception as e:
        logger.error(f"Hiba történt a hét lekérésekor: {e}")
        return 2026, 0

@st.cache_data(show_spinner="Étlap API frissítése a felhőből...")
def load_etlap_api_smart(_client, sheet_id, columns_trigger=None):
    import pandas as pd
    try:
        if _client is None: return pd.DataFrame()
        sh = _client.open_by_key(sheet_id)
        ws_api = sh.worksheet("Etlap_API")
        df = pd.DataFrame(ws_api.get_all_records())
        df.columns = [str(col).strip().replace('\ufeff', '') for col in df.columns]
        return df
    except Exception as e:
        logger.error(f"❌ Smart Cache hiba az Etlap_API letöltésekor: {e}")
        return pd.DataFrame()

def master_lista_szinkron(df_napi, sheet_id, client, jarat_szam=None):
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
    master_df = pd.DataFrame()

    def tiszta_id_konverzio(x):
        if pd.isna(x) or x == "": return ""
        s = str(x).replace("'", "").replace(' ', '').strip()
        if '-' in s: s = s.split('-')[-1]
        tisztitott = "".join(filter(str.isdigit, s))
        return tisztitott if len(tisztitott) > 0 else ""

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
        if 'Lat' in master_df.columns: master_df['Lat'] = master_df['Lat'].apply(biztonsagos_koordinata_tisztito)
        if 'Lon' in master_df.columns: master_df['Lon'] = master_df['Lon'].apply(biztonsagos_koordinata_tisztito)
        st.session_state.ugyfelkor_df = master_df.copy()
        st.session_state.mdf = master_df.copy()
    except Exception as e:
        st.error(f"❌ Hiba a törzslista elérésekor: {e}")
        return df_napi, pd.DataFrame()

    st.info("🔄 Ügyfélkör adatbázis aktualizálása és koordináták ellenőrzése...")
    try:
        def kényszeritett_koordinata_tisztito(val):
            if pd.isna(val) or str(val).strip() in ["", "0", "0.0", "None", "nan", "NaN"]: return ""
            s = str(val).replace(",", ".").replace(" ", "").strip().lstrip("'")
            if "." not in s and len(s) >= 6: s = s[:2] + "." + s[2:]
            return s

        def kényszeritett_cim_tisztito(nyers_szoveg):
            if not nyers_szoveg: return ""
            s = re.sub(r'\(.*?\)', '', str(nyers_szoveg)).strip()
            s = s.replace('$', '').strip()
            s = re.sub(r'\.?\s+\d+/\d+.*$', '', s)
            s = re.split(r'(?i)\s+(fszt|fsz|emelet|em|ajtó|ajto|lh|lph).*$', s)[0]
            return s.strip().rstrip(',').rstrip('.')

        if not master_df.empty:
            master_df = kotelezo_ugyfelkor_formatum_tisztitas(master_df)
            if 'Lat' in master_df.columns: master_df['Lat'] = master_df['Lat'].apply(kényszeritett_koordinata_tisztito)
            if 'Lon' in master_df.columns: master_df['Lon'] = master_df['Lon'].apply(kényszeritett_koordinata_tisztito)
        
        meta_forras = st.session_state.get('meta_data', {})
        szallitas_napja = meta_forras.get('datum_iso', datetime.now().strftime("%Y-%m-%d"))
        új_koordináta_számláló = 0
        geolocator_helyi = Nominatim(user_agent="Interfood_Express_Delivery_App_v3_2026")
        
        for idx, row in df_napi.iterrows():
            # --- TISZTA ID-ALAPÚ ÖSSZEHASONLÍTÁS A DUPLIKÁCIÓK ELLEN (Golyóálló módon) ---
            u_id = tiszta_id_konverzio(row['ID'])
            if not u_id or u_id == "" or u_id == "nan": continue
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
                st.info(f"📍 GPS koordináta keresése: {nev}...")
                lat, lon = None, None
                try:
                    time.sleep(1.3)
                    location = geolocator_helyi.geocode(keresesi_cim, timeout=10)
                    if location: lat, lon = location.latitude, location.longitude
                    else:
                        vágott_cim_iranyitoszam_nelkul = re.sub(r'^\d{4}\s+', '', keresesi_cim).strip()
                        location_vágott = geolocator_helyi.geocode(vágott_cim_iranyitoszam_nelkul, timeout=10)
                        if location_vágott: lat, lon = location_vágott.latitude, location_vágott.longitude
                except Exception as e_geo:
                    lat, lon = None, None
                if lat is not None and lon is not None:
                    lat_clean = str(round(float(lat), 6))
                    lon_clean = str(round(float(lon), 6))
                    st.success(f"🎯 GPS sikeresen megvan: {nev} -> ({lat_clean}, {lon_clean})")
                    új_koordináta_számláló += 1

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
                    'ID': u_id, 'Név': row.get('Név', row.get('Ügyintéző', 'Ismeretlen Ügyfél')),
                    'Cím': row.get('Cím', row.get('Cim', '')), 'Lat': str(lat_clean), 'Lon': str(lon_clean),
                    'Telefon': str(row.get('Telefon', '')), 'Csoport': str(row.get('Csoport', '')),
                    'Megjegyzés': str(row.get('Megjegyzés', row.get('Megjegyzes', ''))),
                    'Utolso_Rendeles': szallitas_napja, 'Osszertek': mai_rendeles_erteke, 'Rendeles_Szam': 1
                }
                master_df = pd.concat([master_df, pd.DataFrame([uj_sor])], ignore_index=True)

        master_df['Lat'] = master_df['Lat'].astype(str).str.strip().replace(['nan', 'None', '0.0', '0'], '')
        master_df['Lon'] = master_df['Lon'].astype(str).str.strip().replace(['nan', 'None', '0.0', '0'], '')
        df_ugyfelkor_vegleges = kotelezo_ugyfelkor_formatum_tisztitas(master_df)
        set_with_dataframe(ws_ugyfel, df_ugyfelkor_vegleges, row=1, col=1, include_index=False, resize=True)
        master_df = df_ugyfelkor_vegleges.copy()
        if 'google_data_loaded' in st.session_state: del st.session_state['google_data_loaded']
    except Exception as e_full_process:
        st.error(f"❌ Nem sikerült az ügyfélkör automatikus frissítése: {e_full_process}")
        
    if not master_df.empty:
        # --- PREFEKTUSI JAVÍTÁS A DUPLIKÁCIÓK ELLENI SZINKRONHOZ ---
        # Ideiglenesen megtisztítjuk a napi ID oszlopot a merge művelethez
        df_napi['temp_clean_id'] = df_napi['ID'].apply(tiszta_id_konverzio)
        master_df['temp_clean_id'] = master_df['ID'].apply(tiszta_id_konverzio)
        
        df_napi = df_napi.drop(columns=['Lat', 'Lon'], errors='ignore')
        b_cols = ['temp_clean_id', 'Lat', 'Lon']
        for c in ['Csoport', 'Megjegyzés']:
            if c in master_df.columns and c not in df_napi.columns: 
                b_cols.append(c)
                
        # Összeillesztés a tiszta id alapján (figyelve a duplikációkra)
        merged_df = df_napi.merge(master_df[b_cols].drop_duplicates('temp_clean_id'), on='temp_clean_id', how='left')
        df_napi = merged_df.drop(columns=['temp_clean_id'])
        master_df = master_df.drop(columns=['temp_clean_id'])
        
    df_napi['Lat'] = df_napi['Lat'].apply(biztonsagos_koordinata_tisztito)
    df_napi['Lon'] = df_napi['Lon'].apply(biztonsagos_koordinata_tisztito)
    df_napi['Sorrend'] = range(1, len(df_napi) + 1)

    if 'Név' not in df_napi.columns:
        if 'Ügyintéző' in df_napi.columns: df_napi['Név'] = df_napi['Ügyintéző']
        else: df_napi['Név'] = "Ismeretlen"
    if 'Fizetendő' not in df_napi.columns and 'Pénz' in df_napi.columns:
        df_napi['Fizetendő'] = df_napi['Pénz']
    if 'Járat' not in df_napi.columns: df_napi['Járat'] = jarat_szam if jarat_szam else ""

    for col in ['Rendelés', 'Megjegyzés', 'Fizetési Mód', 'Státusz', 'Időbélyeg', 'Telefon', 'Csoport']:
        if col not in df_napi.columns: df_napi[col] = "Kiszállítás alatt" if col == 'Státusz' else ""

    try:
        ws_adatok = sh.worksheet("Adatok")
        existing_records = ws_adatok.get_all_records()
        df_existing = pd.DataFrame(existing_records) if existing_records else pd.DataFrame()
        if 'Rendelés_Full' in df_napi.columns:
            df_napi['Rendelés'] = df_napi.apply(
                lambda row: str(row['Rendelés_Full']).strip() if str(row.get('Rendelés_Full', '')).strip() != "" else row['Rendelés'], axis=1
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
        ws_adatok.clear()
        set_with_dataframe(ws_adatok, save_df, include_index=False, include_column_header=True)
        st.success("🚀 Mobil terminál adatsorok (Adatok) sikeresen szinkronizálva a felhőbe!")
    except Exception as e:
        logger.warning(f"Sinc hiba: {e}")
    return df_napi, master_df

def sync_interfood_etlap(year, week, sheet_id):
    import pandas as pd
    api_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {"User-Agent": "Mozilla/5.0"}
    cache_key = f"sync_done_{year}_{week}"
    if st.session_state.get(cache_key, False): return True
    try:
        response = requests.get(api_url, headers=headers, timeout=15)
        if response.status_code != 200: return False
        df = pd.read_excel(BytesIO(response.content))
        client = st.session_state.get('client')
        sheet = client.open_by_key(sheet_id)
        try: worksheet = sheet.worksheet("Etlap_API")
        except: worksheet = sheet.add_worksheet(title="Etlap_API", rows="1000", cols="20")
        worksheet.clear()
        set_with_dataframe(worksheet, df)
        st.session_state[cache_key] = True
        return True
    except Exception as e:
        return False

def load_etlap_from_sheets(sheet_id):
    import pandas as pd
    client = st.session_state.get('client')
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
                    kategoria_index[cikkszam] = {
                        "kategoria": row.get('Kategoria', 'Egyéb / Zóna ételek'),
                        "sorrend": int(sorrend_nyers) if sorrend_nyers.isdigit() else 99
                    }
            st.session_state['kategoria_adatok'] = kategoria_index
        except: pass
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
                    if i + 1 < len(df): ar = str(df.iloc[i + 1, nap_idx]).strip().replace('Ft', '').replace(' ', '')
                    if nev and nev.lower() != "nan" and nev != "":
                        etlap_index[f"{nap_idx}_{kod}"] = {"nev": nev, "ar": ar}
        return etlap_index
    except Exception as e:
        return {}

def load_futar_from_sheets(sheet_id):
    import pandas as pd
    client = st.session_state.get('client')
    if not client: return pd.DataFrame()
    try:
        sheet = client.open_by_key(sheet_id).worksheet("Futárok")
        return pd.DataFrame(sheet.get_all_records())
    except: return pd.DataFrame()

def save_futar_to_sheets(df, sheet_id):
    client = st.session_state.get('client')
    try:
        sheet = client.open_by_key(sheet_id).worksheet("Futárok")
        sheet.clear()
        sheet.update([df.columns.values.tolist()] + df.values.tolist())
        return True
    except: return False

def sync_master_database(sheet_id, ev, start_het, end_het):
    import pandas as pd
    import requests
    from io import BytesIO
    from utils import clean_text
    client = st.session_state.get('client')
    try:
        try:
            worksheet = sheet.open_by_key(sheet_id).worksheet("Master_Adatbazis")
            existing_data = worksheet.get_all_records()
            master_dict = {
                str(row['Tisztított Név']): {
                    "Eredeti Név": row.get('Eredeti Név', ''),
                    "KodAr_List": str(row.get('Kódok és Árak', '')).split(", ") if row.get('Kódok és Árak') else [],
                    "Kellék": row.get('Kellék', ''), "Gyakoriság": int(row.get('Gyakoriság', 1))
                } for row in existing_data if row.get('Tisztított Név')
            }
        except Exception:
            worksheet = client.open_by_key(sheet_id).add_worksheet(title="Master_Adatbazis", rows="5000", cols="10")
            master_dict = {}

        for het in range(start_het, end_het + 1):
            url = f"https://ia.interfood.hu/api/v3/excel-export?year={ev}&week={het}"
            response = requests.get(url, headers={'User-Agent': 'Mozilla'}, timeout=15)
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
                                ar = str(df.iloc[i + 1, nap_idx]).strip().replace('Ft', '').replace(' ', '') if i + 1 < len(df) else ""
                                kod_ar_par = f"{alap_kod}:{ar} (w{het})"
                                if tiszta_nev in master_dict:
                                    master_dict[tiszta_nev]['Gyakoriság'] += 1
                                    if kod_ar_par not in master_dict[tiszta_nev]['KodAr_List']: master_dict[tiszta_nev]['KodAr_List'].append(kod_ar_par)
                                else:
                                    master_dict[tiszta_nev] = {
                                        "Eredeti Név": eredeti_nev.replace('*', '').strip(),
                                        "KodAr_List": [kod_ar_par], "Kellék": "", "Gyakoriság": 1
                                    }
        output_rows = [["Tisztított Név", "Eredeti Név", "Kódok és Árak", "Kellék", "Gyakoriság"]]
        for tiszta, adat in master_dict.items():
            output_rows.append([tiszta, adat["Eredeti Név"], ", ".join(adat["KodAr_List"]), adat["Kellék"], adat["Gyakoriság"]])
        worksheet.clear()
        worksheet.update('A1', output_rows)
        return True
    except Exception as e:
        return False
