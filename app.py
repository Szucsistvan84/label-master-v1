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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Frame, KeepInFrame, Flowable

# --- GOOGLE SHEETS KONFIGURÁCIÓ ---
SHEET_ID = "1bZrtgqROYijYhyFOFrqYeSTUAsGqZU6GLijObJ1En0o"

def get_google_sheets_creds():
    # Beolvassuk a teljes szekciót a secrets-ből
    creds_info = st.secrets["gcp_service_account"].to_dict()
    
    # Kézzel "megjavítjuk" a kulcsot, ha a Streamlit elrontotta volna a sortöréseket
    if "private_key" in creds_info:
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
    
    return service_account.Credentials.from_service_account_info(creds_info)

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
    
    # Járatszám minta: 4 számjegy + pont + járat VAGY Nyomtatta: 4 számjegy
    jarat_re = re.compile(r'(\d{4})\.\s*járat|Nyomtatta:\s*(\d{4})')
    
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

            # 3. A NAPOK kinyerése (Péntek, Szombat stb.)
            if not all_meta['nap']:
                # Keressük a 'Nap:' utáni részt az 'InterFood' szóig
                nap_m = re.search(r'Nap:\s*(.*?)(?=InterFood|$)', text, re.DOTALL)
                if nap_m:
                    # Tisztítjuk: leszedjük a felesleges vesszőket a végéről és a szóközöket
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
    
    # Ezzel elhitetjük a szerverrel, hogy egy böngésző vagyunk
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # Most már küldjük az azonosítót is (headers=headers)
        response = requests.get(api_url, headers=headers)
        response.raise_for_status() 
        
        df = pd.read_excel(BytesIO(response.content))
        
        # 2. Google Sheets hitelesítés (a már jól bevált módon)
        creds_info = st.secrets["gcp_service_account"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        from google.oauth2 import service_account
        import gspread
        
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        
        # 3. Munkalap kezelése
        try:
            worksheet = sheet.worksheet("Etlap_API")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title="Etlap_API", rows="1000", cols="20")
            
        # 4. Adatok "átöntése"
        worksheet.clear()
        set_with_dataframe(worksheet, df)
        
        st.sidebar.success(format(f"Étlap frissítve: {year}. év {week}. hét"))
        return True
        
    except Exception as e:
        st.error(f"Nem sikerült az étlapot letölteni ({year}/W{week}): {e}")
        return False

# --- PÉLDA A HASZNÁLATRA ---
# Amikor a meta függvényed kiolvassa:
# ev, het = get_meta_info(menetterv_file)
# if ev and het:
#     sync_interfood_etlap(ev, het, SHEET_ID)

def get_etlap_dict(ev, het):
    # A pontos URL struktúra, amit küldtél
    url = f"https://ia.interfood.hu/api/v3/excel-export?year={ev}&week={het}"
    
    try:
        # User-Agent nélkül az API gyakran blokkolja a Python kéréseket
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Excel beolvasása memóriából
        df = pd.read_excel(BytesIO(response.content), header=None, engine='openpyxl')
        
        etlap = {}
        # A közösen kidolgozott "i" (név) és "i+1" (ár) logika
        for i in range(len(df)):
            elso_cella = str(df.iloc[i, 0]).strip()
            
            if " - " in elso_cella:
                parts = elso_cella.split(" - ", 1)
                kod = parts[0].strip()
                kategoria = parts[1].strip()
                nevek = df.iloc[i].values
                
                if i + 1 < len(df):
                    arak = df.iloc[i + 1].values
                    for nap_idx in range(1, 6): # H-P
                        nev = str(nevek[nap_idx]).strip() if pd.notna(nevek[nap_idx]) else ""
                        ar = str(arak[nap_idx]).strip() if pd.notna(arak[nap_idx]) else ""
                        
                        if nev and ar and nev.lower() != "nan" and ar.lower() != "nan":
                            if kod not in etlap:
                                etlap[kod] = {}
                            etlap[kod][nap_idx] = {
                                "nev": nev, 
                                "ar": ar, 
                                "kategoria": kategoria
                            }
        return etlap
    except Exception as e:
        st.error(f"Hiba az étlap letöltésekor ({ev}/{het}): {e}")
        return {}

# --- 1. AZ OKOS NÉV-MEMÓRIA BETÖLTÉSE ---
@st.cache_data
def load_all_names():
    all_names = set()
    titulusok = {"Dr.", "id.", "ifj.", "özv.", "dr.", "vitéz"}
    all_names.update(titulusok)
    
    # A 3 fájl, amit te most tettél rendbe
    files = ["ferfi_nevek.txt", "noi_nevek.txt", "csaladnevek.txt"]
    for fname in files:
        if os.path.exists(fname):
            with open(fname, "r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip()
                    if name:
                        all_names.add(name)
                        # Női neveknél a -né-t is kezeljük
                        if fname == "noi_nevek.txt":
                            all_names.add(name + "né")
    return all_names

NAME_DB = load_all_names()

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
    # Ha az all_rows nem DataFrame-ek listája, hanem soroké, 
    # akkor előbb csinálunk belőle egy nagy táblázatot.
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
    
    # Sorrend fixálása
    if 'Sorrend' in res.columns:
        res['Sorrend'] = pd.to_numeric(res['Sorrend'], errors='coerce')
        res = res.sort_values('Sorrend')

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

def create_label_pdf(df, fn, ft, meta):
    if df is None or df.empty: return None
    if 'Sorrend' not in df.columns: df['Sorrend'] = range(1, len(df) + 1)
    df = df.sort_values('Sorrend')
    
    # --- ÚJ: Bázis nap meghatározása ---
    bazis_nap_rovid = get_day_short(meta.get('nap', ''))
    nap_list = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo"]

    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70 * mm, 42.42 * mm
    inner_m = 5.5 * mm 
    usable_w = lw - (2 * inner_m)

    # Tömörített sorköz a rendeléseknek
    # Fontos: A Paragraph-nak meg kell adni, mi legyen a Bold párja
    order_s = ParagraphStyle('Order', 
                             fontName=f_reg, 
                             fontSize=7.5, 
                             leading=8.0)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1)

    total_slots = math.ceil(len(df) / 21) * 21

    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        lift = 4.5 * mm if row_i == 0 else 0
        y_eff = y + lift 

        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
            # --- ÚJ: Precíziós nap-alapú formázás (JAVÍTOTT VÁLTOZÓKKAL) ---
            import re
            r_full = str(r.get('Rendelés_Full', r.get('Rendelés', '')))
            kulonleges = False
            
            # Szétvágjuk a szöveget ott, ahol új nap kezdődik, de megtartjuk az elválasztókat is
            # A regex figyeli a | jelet és a napok neveit is
            napi_blokkok = re.split(r'(\s*\|\s*|(?=Hé:|Ke:|Sze:|Csü:|Pé:|Szo:))', r_full)
            
            formazott_reszek = [] # Ezt kereste a hibaüzenet!
            
            for blokk in napi_blokkok:
                if not blokk or not blokk.strip(): 
                    if blokk: formazott_reszek.append(blokk)
                    continue
                
                szin_blokk = blokk
                # Megnézzük, hogy ez a blokk egy különleges nappal kezdődik-e
                for n in nap_list:
                    n_tag = f"{n}:"
                    if n_tag in blokk:
                        if n != bazis_nap_rovid:
                            kulonleges = True
                            # Vastagítás és méretnövelés a teljes blokkra
                            szin_blokk = f'<font name="{f_bold}" size="8.2">{blokk}</font>'
                        break
                
                formazott_reszek.append(szin_blokk)
            
            # Újra összefűzzük a darabokat
            formazott_rendeles = "".join(formazott_reszek)

            # 1. Név mögötti szürkítés (Csak ha különleges nap van a sorban)
            if kulonleges:
                p.saveState()
                p.setFillColor(colors.Color(0.88, 0.88, 0.88))
                # A téglalap pontosan a név alá pozicionálva
                p.rect(x + inner_m - 1*mm, top_y - 9.5 * mm, usable_w + 2*mm, 5.5 * mm, fill=1, stroke=0)
                p.restoreState()

            # 2. Fejléc adatok
            p.setFont(f_bold, 10)
            p.drawString(x + inner_m, top_y - 3 * mm, f"#{int(r['Sorrend'])}")
            
            display_id = str(r.get('temp_id', 'N/A'))
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, top_y - 3 * mm, f"ID: {display_id}")

            p.setFont(f_bold, 9)
            p.drawString(x + inner_m, top_y - 8.5 * mm, str(r.get('Ügyintéző', ''))[:25])
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, top_y - 8.5 * mm, str(r.get('Telefon', '')))

            p.setFont(f_reg, 7)
            p.drawString(x + inner_m, top_y - 12.5 * mm, str(r.get('Cím', ''))[:45])

            # 3. Rendelés (A formázott, szelektíven félkövérített szöveggel)
            para = Paragraph(formazott_rendeles, order_s)
            pw, ph = para.wrap(usable_w, 15 * mm)
            para.drawOn(p, x + inner_m, y_eff + inner_m + 6.8 * mm)

            # 4. Fizetendő és Darab
            penz = str(r.get('Pénz', '0 Ft')).replace(" ", "")
            if penz not in ["0Ft", "", "0"]:
                p.setFont(f_bold, 9)
                p.drawString(x + inner_m, y_eff + 5.5 * mm, f"Fizet: {str(r.get('Pénz', ''))}")
            
            p.setFont(f_bold, 8)
            p.drawRightString(x + lw - inner_m, y_eff + 5.5 * mm, f"Össz: {int(r.get('Összesen', 0))} db")

            # 5. Elválasztó vonal és Futár
            p.setDash(1, 0) 
            p.setStrokeColor(colors.black)
            p.setLineWidth(0.1)
            p.line(x + inner_m, y_eff + 5 * mm, x + lw - inner_m, y_eff + 5 * mm)
            
            p.setFont(f_reg, 6)
            p.drawCentredString(x + lw / 2, y_eff + 2.5 * mm, f"Futár: {fn} | {ft}")

        else:
            # --- MARKETING ETIKETT (Érintetlenül hagyva) ---
            m_text = (
                f"<font size='10' name='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető</b></font>"
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
        'IDStyle': ParagraphStyle('IDStyle', fontName=f_reg, fontSize=7.5, leading=9, alignment=2, textColor=colors.gray)
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
        groups = df['Csoport'].values
        start_idx = None
        for i in range(len(groups)):
            if groups[i] > 0:
                if start_idx is None: start_idx = i
                if i == len(groups) - 1 or groups[i+1] != groups[i]:
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
                    # Félkövérré tesszük a nem bázis napot
                    formazott_rendeles = formazott_rendeles.replace(n_tag, f"<b>{n_tag}</b>")

        # Az adatokba már a formázott rendelést tesszük vissza (ez valószínűleg már megvan a kódodban)
        # ...

        # --- AZ ÚJ FORMÁZÁSI LOGIKA ---
        if kulonleges:
            # 1. HÁTTÉRSZÍN: Most a (2, i+1) cellára tesszük, ami a RENDELÉS oszlop (0-tól számolva a 3. oszlop)
            # Megjegyzés: A menettervben az oszlopok: 0:#, 1:NÉV, 2:RENDELÉS...
            special_bg = colors.Color(0.85, 0.85, 0.85) # Kicsit sötétebb szürke
            table_styles.append(('BACKGROUND', (2, i+1), (2, i+1), special_bg))
            
            # 2. KERET: Vastag, szaggatott vonal a rendelés cella köré
            # 'ROUNDED' sarkokat a ReportLab nem tud cellánként, de a szaggatott vonalat igen:
            # (típus, honnan, meddig, vastagság, szín, szaggatás_hossza, szóköz_hossza)
            table_styles.append(('BOX', (2, i+1), (2, i+1), 1.5, colors.black, None, (2, 2)))

        prefix = "↑ " if (row.get('Csoport', 0) > 0 and i > 0 and df.iloc[i-1].get('Csoport') == row.get('Csoport')) else ""
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
        
        table_data.append([
            f"{int(row.get('Sorrend', i+1))}",                   # 0: #
            info_flow,                                           # 1: Név/Cím
            Paragraph(formazott_rendeles, styles['Small']),      # 2: Rendelés
            Checkbox(10),                                        # 3: ☐ (EZ AZ ÚJ HELYE)
            Paragraph(f"<b>{penz_val}</b>", styles['Normal']),   # 4: Pénz
            Paragraph(str(row.get('Telefon', '')), styles['Small']), # 5: Tel
            str(row.get('Összesen', ''))                         # 6: DB
        ])

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(table_styles))
    elements.append(t)
    
    # --- SPECIÁLIS CANVAS AZ OLDALSZÁMOZÁSHOZ ÉS LÁBLÉCHEZ ---
    class FinalCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            canvas.Canvas.__init__(self, *args, **kwargs)
            self.pages = []

        def showPage(self):
            # Elmentjük az oldal állapotát a későbbi számozáshoz
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
            
            # 1. BAL OLDAL: Járat menetterve + Meta adatok
            j_str = ", ".join(meta.get('jaratok', []))
            footer_left = f"{j_str}. járat menetterve | {meta.get('ev', '')}. év, {meta.get('het', '')}. hét | {meta.get('nap', '')}"
            self.drawString(15*mm, 10*mm, footer_left)
            
            # 2. JOBB OLDAL: X / Y oldal formátum
            footer_right = f"{self._pageNumber} / {page_count}. oldal"
            self.drawRightString(A4[0] - 15*mm, 10*mm, footer_right)
            
            self.restoreState()

    # --- PDF ÉPÍTÉSE ---
    # Ez az egy sor váltja ki a korábbi doc.build-et és a footer hívásokat
    doc.build(elements, canvasmaker=FinalCanvas)
    
    buffer.seek(0)
    return buffer
    
def create_raklista_pdf(df, jarat_info, meta_dict):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=7 * mm, bottomMargin=12 * mm, leftMargin=8 * mm, rightMargin=8 * mm)
    etlap = st.session_state.get('etlap', {})

    ev = meta_dict.get('ev', '')
    het = meta_dict.get('het', '')
    napok = meta_dict.get('nap', '') 
    
    dates_str = f"{ev}. {het}. hét ({napok})"

    # --- 1. NAPOK ÖSSZESÍTÉSE (HÁRMAS SZÓTÁR LOGIKA) ---
    # Ez köti össze a Te rövidítéseidet az Excel prefixekkel
    label_to_prefix = {
        "Hé": "H",
        "Ke": "K",
        "Sze": "S",
        "Csü": "C",
        "Pé": "P",
        "Szo": "Z"
    }

    # Ez pedig a PDF-ben való szép kiíráshoz kell
    prefix_to_nev = {
        "H": "Hétfő", "K": "Kedd", "S": "Szerda", 
        "C": "Csütörtök", "P": "Péntek", "Z": "Szombat"
    }

    counts = {}
    for _, r in df.iterrows():
        order_str = str(r.get('Rendelés_Full', ''))
        # A Rendelés_Full nálad pl: "Csü: 1-A | Pé: 2-B"
        day_parts = order_str.split('|')
        for part in day_parts:
            part = part.strip()
            prefix = ""
            
            # Megkeressük, melyik címkéd van a szövegben
            for label, pfx in label_to_prefix.items():
                if f"{label}:" in part: # A kettőspont fontos a pontos egyezéshez
                    prefix = pfx
                    break
            
            if not prefix: continue
            
            # Megkeressük a darabszámot és a kódot (8-A)
            # A regex mindenféle kötőjelet felismer
            found = re.findall(ORDER_PAT, part)
            for qty, code in found:
                # ITT A LÉNYEG: A kulcs "C_A" lesz, mert a prefixet a label_to_prefix-ből vettük!
                full_key = f"{prefix}_{code.strip().upper()}"
                counts[full_key] = counts.get(full_key, 0) + int(qty)
                
    # Stílusok
    header_style = ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)
    normal_row_style = ParagraphStyle('NR', fontName=f_reg, fontSize=6.5, leading=7.5)
    star_row_style = ParagraphStyle('SR', fontName=f_bold, fontSize=6.5, leading=7.5)

    data = [[
        Paragraph("<b>NAP</b>", header_style),
        Paragraph("<b>KÓD</b>", header_style),
        Paragraph("<b>DB</b>", header_style),
        Paragraph("<b>[ ]</b>", header_style),
        Paragraph("<b>MEGNEVEZÉS</b>", header_style),
        Paragraph("<b>ÁR</b>", header_style),
        Paragraph("<b>ÖSSZES</b>", header_style)
    ]]

    total_qty = 0
    total_money = 0

    # --- 2. TÁBLÁZAT FELTÖLTÉSE (JAVÍTOTT LOGIKA) ---
    # Sorba rendezzük a kulcsokat: Hétfő (H), Kedd (K)... sorrendben
    day_order = {"H":1, "K":2, "S":3, "C":4, "P":5, "Z":6}
    sorted_keys = sorted(counts.keys(), key=lambda x: (day_order.get(x.split('_')[0], 9), x.split('_')[1]))

    for full_key in sorted_keys:
        db = counts[full_key]
        prefix = full_key.split('_')[0]   # Pl. "C"
        code_label = full_key.split('_')[1] # Pl. "A"
        
        # Itt dől el a nap neve a PDF-ben! 
        # A "C"-ből "Csütörtök" lesz, a "P"-ből "Péntek"
        day_long = prefix_to_nev.get(prefix, prefix)
        
        # Étlap adatok lekérése a C_A, P_A stb. kulcs alapján
        info = etlap.get(full_key, {})
        ar = info.get('ar', 0)
        nev = info.get('nev', '---')
        
        subtotal = db * ar
        
        # Csillagos tétel ellenőrzése a stílushoz
        is_starred = "*" in code_label
        current_font = f_bold if is_starred else f_reg
        current_p_style = star_row_style if is_starred else normal_row_style

        data.append([
            Paragraph(day_long, ParagraphStyle('D', fontName=current_font, fontSize=5.5, alignment=1)),
            Paragraph(code_label, ParagraphStyle('K', fontName=current_font, fontSize=7.5, alignment=1)),
            Paragraph(f"{db} db", ParagraphStyle('Q', fontName=current_font, fontSize=7.5, alignment=1)),
            Paragraph("[  ]", ParagraphStyle('CB', fontName=f_reg, fontSize=8, alignment=1)),
            Paragraph(nev, current_p_style),
            Paragraph(f"{ar} Ft", ParagraphStyle('A', fontName=current_font, fontSize=7, alignment=2)),
            Paragraph(f"{subtotal} Ft", ParagraphStyle('S', fontName=current_font, fontSize=7, alignment=2))
        ])
        total_qty += db
        total_money += subtotal

    # --- INNENTŐL A TÖBBI RÉSZ (Táblázat stílus, Összesítő) MARADHAT ---
    col_widths = [12 * mm, 15 * mm, 12 * mm, 8 * mm, 105 * mm, 18 * mm, 24 * mm]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))

    jutalek = int(total_money * 0.13)
    summary_data = [
        ["", "", "", "", "ÖSSZESEN:", f"{total_qty} db", f"{total_money} Ft"],
        ["", "", "", "", "JUTALÉK (13%):", "", f"{jutalek} Ft"]
    ]
    st_table = Table(summary_data, colWidths=col_widths)
    st_table.setStyle(TableStyle([
        ('FONTNAME', (4, 0), (-1, -1), f_bold),
        ('FONTSIZE', (4, 0), (-1, -1), 8.5),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('ALIGN', (5, 0), (6, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LINEABOVE', (4, 0), (-1, 0), 0.5, colors.black),
    ]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_reg, 7)
        canvas.drawRightString(200 * mm, 8 * mm, f"{doc.page}. oldal")
        canvas.restoreState()

    elements = [
        Paragraph(f"<b>RAKLISTA ÉS ELSZÁMOLÁS</b>", ParagraphStyle('T', fontName=f_bold, fontSize=11)),
        Paragraph(f"Időszak: {dates_str} | Járat: {jarat_info}",
                  ParagraphStyle('S', fontName=f_reg, fontSize=8.5, spaceAfter=3)),
        t,
        Spacer(1, 3 * mm),
        st_table
    ]

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf
    
    # --- FŐ PROGRAMFUTÁS JAVÍTVA ---
    
    if st.session_state.mdf is not None:
        # Biztosítjuk, hogy legyen Csoport oszlop
        if 'Csoport' not in st.session_state.mdf.columns:
            st.session_state.mdf['Csoport'] = ""

        st.subheader("📦 Adatok ellenőrzése és Sorrendezés")
        
        edited_df = st.data_editor(
            st.session_state.mdf,
            key=f"editor_{st.session_state.get('editor_key', 0)}", 
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "Csoport": st.column_config.TextColumn(
                    "Csoport",
                    help="Azonos jel esetén (pl. '1') a PDF-ben egy keretbe kerülnek.",
                    width="small"
                ),
                "Sorrend": st.column_config.NumberColumn("Sor", format="%.1f", width="small"),
                "Ügyintéző": "Név",
                "Telefon": "Tel",
                "Pénz": "Összeg",
                "Megjegyzés": "Infó"
            }
        )

def main():
    st.set_page_config(page_title="Interfood Label Master", layout="wide")
    register_fonts()

    # 1. SESSION STATE INICIALIZÁLÁSA (Itt tároljuk a futár adatait is)
    if 'mdf' not in st.session_state:
        st.session_state.mdf = None
    if 'meta_data' not in st.session_state:
        st.session_state.meta_data = []
    if 'weights' not in st.session_state:
        st.session_state.weights = {}
    if 'editor_key' not in st.session_state:
        st.session_state.editor_key = 0
    if 'c_n' not in st.session_state:
        st.session_state.c_n = "Szűcs István"
    if 'c_p' not in st.session_state:
        st.session_state.c_p = "+36 20 886 8971"

    # 2. OLDALSÁV (SIDEBAR)
    with st.sidebar:
        st.header("⚙️ Kezelés")
        st.session_state.c_n = st.text_input("Futár Neve", st.session_state.c_n)
        st.session_state.c_p = st.text_input("Telefonszám", st.session_state.c_p)
        st.divider()
        
        # --- KORÁBBI MENTÉS BETÖLTÉSE ---
        st.subheader("📂 Korábbi mentés")
        import_file = st.file_uploader("Exportált CSV visszatöltése", type=['csv'])
        
        if import_file is not None:
            if st.button("📥 CSV BETÖLTÉSE"):
                # Nyers betöltés, nem futtatunk rajta tisztító algoritmust!
                df_imported = pd.read_csv(import_file)
                
                # Biztosítjuk, hogy a Sorrend oszlop szám formátumú legyen
                if 'Sorrend' in df_imported.columns:
                    df_imported['Sorrend'] = pd.to_numeric(df_imported['Sorrend'], errors='coerce').fillna(999)
                
                st.session_state.mdf = df_imported
                st.success("Mentés sikeresen visszatöltve!")
                st.rerun()

        st.divider()

        # 1. A függvény elején (vagy a main elején) adjunk neki egy alapértéket, 
        # hogy ne legyen "Unbound" (ismeretlen)
        meta_auto = {} 
        
        st.subheader("📄 Új PDF-ek")
        up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
        
        if up_files:
            if st.button("🚀 FELDOLGOZÁS"):
                # 1. Metaadatok kinyerése
                meta_auto = extract_all_meta(up_files)
                st.session_state.meta_data = meta_auto
                
                ev = meta_auto.get('ev')
                het = meta_auto.get('het')

                # --- ÚJ RÉSZ: Google Sheets szinkronizálás ---
                if ev and het:
                    session_key = f"sync_{ev}_{het}"
                    if session_key not in st.session_state:
                        with st.spinner(f"Étlap szinkronizálása a Google Sheets-be ({ev}/W{het})..."):
                            # Itt hívjuk meg a korábban írt függvényt
                            sync_interfood_etlap(ev, het, SHEET_ID)
                            st.session_state[session_key] = True
                # --- ÚJ RÉSZ VÉGE ---

                # Étlap kódok letöltése (folytatódik a régi kódod)
                napi_kodok = set()
                with st.spinner("Étlap kódok letöltése..."):
                    # ... innentől változatlan a kódod ...
                    etlap_dict = get_etlap_dict(meta_auto['ev'], meta_auto['het'])
                    for kulcs in etlap_dict.keys():
                        parts = kulcs.split("_")
                        if len(parts) > 1:
                            napi_kodok.add(parts[1].strip().upper())
                
                # ELMENTJÜK
                st.session_state.napi_etlap_kodok = napi_kodok

                # PDF feldolgozás
                all_rows = []
                for f in up_files:
                    f.seek(0)
                    # Itt adjuk át a friss kódokat!
                    rows, _ = parse_interfood_pdf(f, napi_kodok)
                    if rows:
                        all_rows.extend(rows)

                if all_rows:
                    # Táblázat generálása (a meglévő merge_data kódod)
                    df_temp = merge_data(all_rows)
                    st.session_state.mdf = df_temp
                    st.rerun()

    # 3. FŐABLAK MEGJELENÍTÉSE
    if st.session_state.mdf is not None and not st.session_state.mdf.empty:
        df_to_edit = st.session_state.mdf.copy()
        
        # --- BIZTONSÁGI JAVÍTÁS: Ellenőrizzük, létezik-e az oszlop ---
        if 'Sorrend' not in df_to_edit.columns:
            # Ha nincs, létrehozzuk 1, 2, 3... sorszámokkal
            df_to_edit['Sorrend'] = range(1, len(df_to_edit) + 1)
        
        # KRITIKUS: Kényszerítjük a 'float' típust, hogy a 88.5 is működjön
        df_to_edit['Sorrend'] = pd.to_numeric(df_to_edit['Sorrend'], errors='coerce').fillna(999).astype(float)
        
        # Rendezés a táblázat megjelenítése előtt
        df_to_edit = df_to_edit.sort_values(by='Sorrend').reset_index(drop=True)
    
        st.subheader("Szállítási lista")
        
        # Oszloprend beállítása
        all_cols = df_to_edit.columns.tolist()
        if 'Sorrend' in all_cols:
            all_cols.remove('Sorrend')
            new_column_order = ['Sorrend'] + all_cols
        else:
            new_column_order = all_cols
        
        edited_df = st.data_editor(
            df_to_edit,
            column_order=new_column_order,
            column_config={
                "Sorrend": st.column_config.NumberColumn(
                    "Sorrend",
                    help="Írj be tizedest (pl. 88.5), majd nyomj a lenti gombra!",
                    format="%.1f", # Ez mutatja a tizedest a táblázatban!
                    step=0.1,
                ),
                "Pénz": st.column_config.TextColumn("Pénz", disabled=False),
            },
            num_rows="dynamic",
            key=st.session_state.editor_key,
            use_container_width=True
        )
    
        # MENTÉS ÉS ÚJRARANKEZÉS GOMB
        if st.button("💾 SORREND VÉGLEGESÍTÉSE (Újraszámozás)"):
            # Itt már az edited_df-et használjuk, mert a fenti editor már létrehozta
            temp_df = edited_df.copy()
            
            # 1. Számmá alakítás (hogy a tizedesek alapján rendezni tudjunk)
            temp_df['Sorrend'] = pd.to_numeric(temp_df['Sorrend'], errors='coerce').fillna(999)
            
            # 2. Fizikai sorbarendezés
            temp_df.sort_values('Sorrend', inplace=True)
            
            # 3. Újrasorszámozás egész számokkal (1, 2, 3...)
            temp_df['Sorrend'] = range(1, len(temp_df) + 1)
            
            # 4. Mentés a session-be és frissítés
            st.session_state.mdf = temp_df
            st.session_state.editor_key += 1 
            st.success("Sorrend véglegesítve, a lista újra lett sorszámozva!")
            st.rerun()

        st.divider()

        # 3. PDF LETÖLTÉS - Végleges, stabil verzió
        
        # Biztosítjuk, hogy a meta egy szótár legyen
        meta = st.session_state.meta_data if isinstance(st.session_state.meta_data, dict) else {}
        
        # Kiszámoljuk a járatszámokat az új struktúrából
        jaratok_listaja = meta.get('jaratok', [])
        aktualis_jaratok = ", ".join(jaratok_listaja) if jaratok_listaja else "N/A"

        # 1. Alap járat és időpont információk (marad a st.info, de kicsit bővítve)
        st.info(f"Észlelt járatok a PDF-ekből: **{aktualis_jaratok}** | Időpont: **{meta.get('ev', '')}. {meta.get('het', '')}. hét**")

        # 2. ÚJ: ÉTLAP KÓDOK MEGJELENÍTÉSE (Csak ha van adat a session_state-ben)
        if 'napi_etlap_kodok' in st.session_state and st.session_state.napi_etlap_kodok:
            with st.expander("🍱 Aktuális étlap kódok (ezek lesznek törölve a megjegyzésekből)"):
                # Sorbarendezzük a kódokat ABC szerint
                kodok_lista = sorted(list(st.session_state.napi_etlap_kodok))
                
                # 5 oszlopra bontjuk a megjelenítést, hogy ne legyen túl hosszú a lista függőlegesen
                cols = st.columns(5)
                for i, kod in enumerate(kodok_lista):
                    # A kódokat kis "kódblokk" stílusban jelenítjük meg
                    cols[i % 5].code(kod)
        elif meta.get('ev') and meta.get('het'):
            # Ha még nincs betöltve, egy tipp a felhasználónak
            st.caption("💡 Az étlap kódok automatikusan frissülnek a '🚀 FELDOLGOZÁS' gomb megnyomásakor.")

        c1, c2, c3 = st.columns(3)
        
        c1.download_button(
            "📄 ETIKETTEK", 
            create_label_pdf(edited_df, st.session_state.c_n, st.session_state.c_p, meta), # <--- Itt a 'meta' a végén!
            "etikettek.pdf", 
            use_container_width=True
        )
        c2.download_button(
            "📋 MENETTERV", 
            create_manifest_pdf(edited_df, st.session_state.c_n, meta), 
            "menetterv.pdf", use_container_width=True
        )
        c3.download_button(
            "📊 RAKLISTA", 
            create_raklista_pdf(edited_df, aktualis_jaratok, meta), 
            "raklista.pdf", use_container_width=True
        )

        st.divider()
        st.write("### 💾 Táblázat mentése és exportálása")
        
        # Új sor a mentési gomboknak
        save_col1, save_col2 = st.columns(2)

        with save_col1:
            # Fájlnév összeállítása a meta adatokból
            # Pl.: 4002_4003_jarat_2026_03_31.csv
            
            # Járatszámok összefűzése (ha több van, alulvonással)
            jarat_str = "_".join(meta.get('jaratok', ['Ismeretlen']))
            
            # Aktuális dátum formázása
            import datetime
            d_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # Az általad kért szintaktika: Sorrendezés mentés-járatszám-év-hó-nap
            beszedes_filenev = f"Sorrendezes_mentes-{jarat_str}-{d_str}.csv"
            
            csv_data = edited_df.to_csv(index=False, encoding='utf-8-sig')
            
            st.download_button(
                label="📥 KÉSZ TÁBLÁZAT MENTÉSE (CSV)",
                data=csv_data,
                file_name=beszedes_filenev,
                mime='text/csv',
                use_container_width=True
            )

        with save_col2:
            # Itt egy kis emlékeztető vagy állapotjelző
            st.info("A CSV mentése után ezt a fájlt használd a holnapi visszatöltéshez.")

if __name__ == "__main__":
    main()
