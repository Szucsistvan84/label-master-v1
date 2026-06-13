
# -*- coding: utf-8 -*-
import gspread
import logging
import pandas as pd
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe

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
            # Ha környezeti változóban van (pl. Streamlit Cloud)
            import json
            info = json.loads(gspread.io.os.environ["gcp_service_account"])
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        else:
            # Helyi teszteléshez a gyári st.secrets-ből (ha elérhető)
            import streamlit as st
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
            
        client = gspread.authorize(creds)
        logger.info("Sikeresen létrejött a Google Sheets API kapcsolat.")
        return client
    except Exception as e:
        logger.error(f"Google Sheets hitelesítési hiba: {e}")
        return None

def load_sheet_data(client, sheet_id, worksheet_name):
    """Beolvas egy adott fület egy Google Sheet-ből és Pandas DataFrame-et csinál belőle"""
    try:
        sheet = client.open_by_key(sheet_id)
        worksheet = sheet.worksheet(worksheet_name)
        records = worksheet.get_all_records()
        return pd.DataFrame(records)
    except Exception as e:
        logger.error(f"Hiba a táblázat beolvasásakor ({worksheet_name}): {e}")
        return pd.DataFrame()

def save_df_to_sheet(client, sheet_id, worksheet_name, df, clear_sheet=True):
    """Biztonságosan felülírja vagy frissíti a Google Sheet adott fülét a DataFrame adataival"""
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

