# utils.py
import streamlit as st
import gspread
from google.oauth2 import service_account

def init_google_sheets():
    """
    Inicializálja a Google Sheets klienst a st.secrets alapján.
    Eredményt menti a session_state-be is, hogy bárhonnan elérhető legyen.
    """
    if 'client' in st.session_state and st.session_state['client'] is not None:
        return st.session_state['client']

    try:
        # Támogatja mindkét st.secrets struktúrát (ha be van ágyazva gcp_service_account alá, vagy ha ömlesztve van)
        if "gcp_service_account" in st.secrets:
            creds_info = dict(st.secrets["gcp_service_account"])
        else:
            creds_info = dict(st.secrets)
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets", 
            "https://www.googleapis.com/auth/drive"
        ]
        
        if "private_key" in creds_info:
            creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
            
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Elmentjük központilag, így pl. a vizualizacio.py is egyből látni fogja
        st.session_state['client'] = client
        return client
        
    except Exception as e:
        st.error(f"🚨 Sikertelen Google Sheets kapcsolódás: {e}")
        st.session_state['client'] = None
        return None
