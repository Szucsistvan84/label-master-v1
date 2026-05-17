import gspread
from google.oauth2 import service_account
import streamlit as str_mock  # Csak azért kell, hogy a secrets-ből olvassunk

# 1. HITELESÍTÉS (Pontosan úgy, ahogy az appodban van)
# Feltételezzük, hogy a .streamlit/secrets.toml fájlban ott vannak a hozzáférések
import toml
with open(".streamlit/secrets.toml", "r") as f:
    secrets = toml.load(f)

if "gcp_service_account" in secrets:
    creds_dict = dict(secrets["gcp_service_account"])
else:
    creds_dict = dict(secrets)

if "private_key" in creds_dict: 
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

# 2. TÁBLÁZAT MEGNYITÁSA
# Cseréld ki a saját SHEET ID-dra, ha nem ez az!
SHEET_ID_UGYFELKOR = "IDE_MASOLD_BE_AZ_UGYFELKOR_SHEET_ID_JAT" 

print("⏳ Kapcsolódás a Google Sheets-hez...")
sheet = client.open_by_key(SHEET_ID_UGYFELKOR)
worksheet = sheet.worksheet("Ugyfelkor")

# Letöltjük az összes cellát, hogy lássuk a nyers formátumot
print("⏳ Adatok beolvasása...")
rows = worksheet.get_all_values() # Ez a nyers, látható karaktereket adja vissza

if not rows:
    print("A táblázat üres!")
    exit()

header = rows[0]
try:
    lat_idx = header.index("Lat")
    lon_idx = header.index("Lon")
except ValueError:
    print("❌ Nem találom a 'Lat' vagy 'Lon' oszlopot a fejlécben!")
    exit()

print(f"🧹 Nagytakarítás elindítva a 'Lat' ({lat_idx+1}. oszlop) és 'Lon' ({lon_idx+1}. oszlop) részeken...")

# 3. CELLÁK ÁTVIZSGÁLÁSA ÉS JAVÍTÁSA
javitott_db = 0

# Végigmegyünk az összes soron (a fejlécet kihagyva, ezért 1-től indul a sorszám)
for row_num, row_data in enumerate(rows[1:], start=2):
    # Biztosítjuk, hogy a sorban van elég elem
    if len(row_data) <= max(lat_idx, lon_idx):
        continue
        
    nyers_lat = str(row_data[lat_idx]).strip()
    nyers_lon = str(row_data[lon_idx]).strip()
    
    uj_lat = None
    uj_lon = None
    
    # --- LAT JAVÍTÁS ---
    if nyers_lat:
        # Megtisztítjuk mindenféle sallangtól
        tiszta_lat = nyers_lat.replace("'", "").replace('"', '').replace(",", ".").strip()
        try:
            # Ellenőrizzük, hogy érvényes szám-e
            float(tiszta_lat)
            # Felépítjük a tiszta SZIMPLA aposztrófos + magyar vesszős formátumot
            uj_lat = f"'{tiszta_lat.replace('.', ',')}"
        except ValueError:
            pass # Nem szám, békén hagyjuk
            
    # --- LON JAVÍTÁS ---
    if nyers_lon:
        tiszta_lon = nyers_lon.replace("'", "").replace('"', '').replace(",", ".").strip()
        try:
            float(tiszta_lon)
            uj_lon = f"'{tiszta_lon.replace('.', ',')}"
        except ValueError:
            pass

    # --- FRISSÍTÉS A GOOGLE SHEETS-BEN, HA VÁLTOZOTT ---
    # Csak akkor küldünk kérést, ha a Google Sheets-ben lévő érték eltér a szép, tiszta formátumtól
    if (uj_lat and uj_lat != nyers_lat) or (uj_lon and uj_lon != nyers_lon):
        print(f"  ↳ 🛠️ Javítás a(z) {row_num}. sorban (ID: {row_data[0]}): Lat: {nyers_lat} -> {uj_lat} | Lon: {nyers_lon} -> {uj_lon}")
        
        if uj_lat:
            worksheet.update_cell(row_num, lat_idx + 1, uj_lat)
        if uj_lon:
            worksheet.update_cell(row_num, lon_idx + 1, uj_lon)
            
        javitott_db += 1

print(f"\n✅ KÉSZ! Összesen {javitott_db} ügyfél koordinátája lett tökéletesen egységesítve szóló aposztrófra!")
