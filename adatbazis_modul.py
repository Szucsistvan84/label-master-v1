
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
