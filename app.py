import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup

# --- ALAPOK ---
st.set_page_config(page_title="Interfood v150.5 - Stabil Hibrid", layout="wide")

DEFAULT_PRICES = {"L_NAGY": 1150, "L_KICSI": 890, "F_NAGY": 2450, "F_KICSI": 1850, "default": 2200}

@st.cache_data(ttl=3600)
def get_live_menu():
    menu = {}
    try:
        url = "https://rendel.interfood.hu/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text(separator=' ')
            codes = re.findall(r'\b[A-Z][A-Z0-9]{1,4}\b', text)
            prices = re.findall(r'(\d[\d\s]*)\s*Ft', text)
            for i in range(min(len(codes), len(prices))):
                p = int(re.sub(r'\D', '', prices[i]))
                if p > 500: menu[codes[i]] = p
    except: pass
    return menu

def estimate_price(code, live_menu):
    if code in live_menu: return live_menu[code]
    is_k = code.endswith('K') or 'DKM' in code
    if code.startswith("L") and len(code) > 1 and code[1].isdigit():
        return DEFAULT_PRICES["L_KICSI"] if is_k else DEFAULT_PRICES["L_NAGY"]
    return DEFAULT_PRICES["F_KICSI"] if is_k else DEFAULT_PRICES["F_NAGY"]

# --- FELDOLGOZÓ ---
def parse_v150_5(pdf_file, live_menu):
    all_rows = []
    jutalek_rate = 0.13
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # 1. RÉSZ: Normál táblázatos oldalak (v131 logika alapján)
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue
                        s_raw_list = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                        if not s_raw_list: continue
                        
                        # Adatok kinyerése
                        names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                        addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]
                        raw_info = str(row[4]).replace('\n\n\n', '\n')
                        
                        # Rendelések és Jutalék
                        found_orders = re.findall(r'(\d-[A-Z0-9]+)', raw_info)
                        napi_ertek = sum(int(o.split('-')[0]) * estimate_price(o.split('-')[1], live_menu) for o in found_orders)
                        
                        # Telefon
                        tel_m = re.search(r'(\d{2}/\d{6,7})', raw_info)
                        tel = tel_m.group(1) if tel_m else "Nincs"

                        for idx, snum in enumerate(s_raw_list):
                            all_rows.append({
                                "Sorszám": int(snum),
                                "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                                "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else "Cím a PDF-ben"),
                                "Telefon": tel,
                                "Rendelés": ", ".join(found_orders) if idx == 0 else "---",
                                "Napi Érték": napi_ertek if idx == 0 else 0,
                                "Jutalék (13%)": (napi_ertek * jutalek_rate) if idx == 0 else 0
                            })
            
            # 2. RÉSZ: Utolsó oldal (A v131 "Szeletelő" integrálása)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    line = line.strip()
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    
                    if irsz_m and tel_m:
                        telefonszam = tel_m.group(1)
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        
                        # Rendelés kódok bányászata az utolsó sorból
                        found_orders = re.findall(r'(\d-[A-Z0-9]+)', line)
                        napi_ertek = sum(int(o.split('-')[0]) * estimate_price(o.split('-')[1], live_menu) for o in found_orders)

                        # Cím és Név szétválasztás (v131 logika)
                        cim_v, nev_v = koztes, "Ellenőrizni"
                        for ut in ut_list:
                            pos = koztes.lower().find(ut.lower())
                            if pos != -1:
                                ut_vege = pos + len(ut)
                                maradek = koztes[ut_vege:].strip().split(' ')
                                hazszam = []
                                nevek = []
                                talalt_nev = False
                                for szo in maradek:
                                    if (szo and szo[0].isupper() and not any(c.isdigit() for c in szo)) or talalt_nev:
                                        talalt_nev = True
                                        nevek.append(szo)
                                    else:
                                        hazszam.append(szo)
                                cim_v = (koztes[:ut_vege].strip() + " " + " ".join(hazszam)).strip()
                                nev_v = " ".join(nevek).strip()
                                break

                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Ügyintéző": nev_v if nev_v else "Nincs név",
                            "Cím": cim_v,
                            "Telefon": telefonszam,
                            "Rendelés": ", ".join(found_orders),
                            "Napi Érték": napi_ertek,
                            "Jutalék (13%)": napi_ertek * jutalek_rate
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.title("🚀 Interfood v150.5 - Stabil Hibrid")
if 'menu' not in st.session_state: st.session_state.menu = get_live_menu()

f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = parse_v150_5(f, st.session_state.menu)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Össz. Napi Forgalom", f"{df['Napi Érték'].sum():,.0f} Ft".replace(',', ' '))
    c2.metric("Saját Jutalék (13%)", f"{df['Jutalék (13%)'].sum():,.0f} Ft".replace(',', ' '), delta="💰")
    c3.metric("Címek Száma", len(df))
    
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_statisztika.csv")
