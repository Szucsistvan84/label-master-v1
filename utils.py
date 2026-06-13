# utils.py
import logging
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

def setup_logging():
    """Beállítja az alkalmazás szintű loggolást."""
    LOG_FILE = "utvonaltervezo.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def init_test_mode():
    """Inicializálja a teszt üzemmódot a session state-ben és az URL paraméterekben."""
    if 'teszt_uzemmod' not in st.session_state:
        st.session_state.teszt_uzemmod = False

    if "test" in st.query_params and st.query_params["test"] == "true":
        st.session_state.teszt_uzemmod = True

def check_user_role():
    """Visszaadja a felhasználó aktuális szerepkörét."""
    role = st.session_state.get('user_szerep', 'futar')
    if st.session_state.get('user_nev') == "SajátNeved": 
        return "superadmin"
    return role

def clean_text(text):
    """Eltávolítja a speciális karaktereket, szóközöket és ékezeteket az összehasonlításhoz."""
    if not text or str(text).lower() == "nan": return ""
    # Ékezetek eltávolítása (pl. á -> a)
    text = "".join(c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn')
    # Csak betűk és számok megtartása, kisbetűssé alakítás, szóközök törlése
    text = re.sub(r'[^a-zA-Z0-9]', '', text).lower()
    return text
