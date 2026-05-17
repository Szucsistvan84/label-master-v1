import gspread
from google.oauth2 import service_account
import streamlit as st
import pandas as pd

def google_sheet_nagytakaritas(sheet_id):
    try:
        # HITELESÍTÉS (Streamlit secrets-ből automatikusan)
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
        else:
            creds_dict = dict(st.secrets)

        if "private_key" in creds_dict: 
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        st.info("⏳ Kapcsolódás a Google Sheets-hez...")
        sheet = client.open_by_key(sheet_id)
        worksheet = sheet.worksheet("Ugyfelkor")

        st.info("⏳ Adatok beolvasása és ellenőrzése...")
        rows = worksheet.get_all_values()

        if not rows:
            st.warning("A táblázat üres!")
            return

        header = rows[0]
        try:
            lat_idx = header.index("Lat")
            lon_idx = header.index("Lon")
        except ValueError:
            st.error("❌ Nem találom a 'Lat' vagy 'Lon' oszlopot a táblázatban!")
            return

        javitott_db = 0
        progress_bar = st.progress(0)
        total_rows = len(rows) - 1

        # Végigmegyünk a sorokon és javítunk
        for idx, row_data in enumerate(rows[1:], start=2):
            progress_bar.progress(idx / (total_rows + 1))
            
            if len(row_data) <= max(lat_idx, lon_idx):
                continue
                
            nyers_lat = str(row_data[lat_idx]).strip()
            nyers_lon = str(row_data[lon_idx]).strip()
            
            uj_lat = None
            uj_lon = None
            
            if nyers_lat:
                tiszta_lat = nyers_lat.replace("'", "").replace('"', '').replace(",", ".").strip()
                try:
                    float(tiszta_lat)
                    uj_lat = f"'{tiszta_lat.replace('.', ',')}"
                except ValueError:
                    pass
                    
            if nyers_lon:
                tiszta_lon = nyers_lon.replace("'", "").replace('"', '').replace(",", ".").strip()
                try:
                    float(tiszta_lon)
                    uj_lon = f"'{tiszta_lon.replace('.', ',')}"
                except ValueError:
                    pass

            # Ha változott valami, felküldjük a javítást
            if (uj_lat and uj_lat != nyers_lat) or (uj_lon and uj_lon != nyers_lon):
                st.write(f"🛠️ Javítás a {idx}. sorban (ID: {row_data[0]}): {nyers_lat} ➔ {uj_lat}")
                if uj_lat:
                    worksheet.update_cell(idx, lat_idx + 1, uj_lat)
                if uj_lon:
                    worksheet.update_cell(idx, lon_idx + 1, uj_lon)
                javitott_db += 1

        st.success(f"🎉 SIKER! Összesen {javitott_db} sor lett tökéletesen letisztítva szóló aposztrófra!")
        
        # Cache ürítés, hogy az app azonnal az új tiszta listát lássa
        if 'ugyfelkor_df' in st.session_state:
            del st.session_state['ugyfelkor_df']
            
    except Exception as e:
        st.error(f"Hiba a takarítás során: {e}")
