import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup

# --- ALAPBEÁLLÍTÁSOK ---
st.set_page_config(page_title="Interfood v150.4 - Javított", layout="wide")

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

# --- FŐ FELDOLGOZÓ ---
def process_pdf_v150_4(pdf_file, live_menu):
    all_data = []
    jutalek_rate = 0.13
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
            
            # 1. TÁBLÁZATOS OLDALAK (Eleje és közepe)
            if table and i < len(pdf.pages) - 1:
                for row in table:
                    if not row or len(row) < 5: continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue
                    
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    addr_raw = [a.strip() for a in str(row[2]).split('\n') if '40' in a or ' u.' in a or ' út' in a]
                    raw_info = str(row[4]).replace('\n\n\n', '\n')
                    
                    # Csak az ételkódokat bányásszuk ki (pl. 1-DK)
                    found_orders = re.findall(r'(\d-[A-Z0-9]+)', raw_info)
                    order_str = ", ".join(found_orders)
                    
                    # Telefonszám keresése
                    tel_match = re.search(r'(\d{2}/\d{6,7})', raw_info)
                    tel = tel_match.group(1) if tel_match else "Nincs"
                    
                    # Pénzügyi számítás
                    napi_ertek = 0
                    for item in found_orders:
                        parts = item.split('-')
                        if len(parts) == 2:
                            napi_ertek += int(parts[0]) * estimate_price(parts[1], live_menu)
                    
                    for idx, snum in enumerate(s_nums):
                        all_data.append({
                            "Sorszám": int(snum),
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                            "Cím": addr_raw[idx] if idx < len(addr_raw) else (addr_raw[0] if addr_raw else "Cím a PDF-ben"),
                            "Telefon": tel,
                            "Rendelés": order_str if idx == 0 else "---",
                            "Napi Érték": napi_ertek if idx == 0 else 0,
                            "Jutalék (13%)": (napi_ertek * jutalek_rate) if idx == 0 else 0
                        })
            
            # 2. SZÖVEGES OLDALAK (Utolsó oldal fixálása)
            else:
                lines = text.split('\n') if text else []
                for line in lines:
                    # Sorszám és Kód keresése a sor elején
                    m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if m:
                        s_num = m.group(1)
                        tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                        tel = tel_m.group(1) if tel_m else "Nincs"
                        
                        # Rendelés kódok bányászata a sorból
                        found_orders = re.findall(r'(\d-[A-Z0-9]+)', line)
                        order_str = ", ".join(found_orders)
                        
                        f_sum = 0
                        for item in found_orders:
                            parts = item.split('-')
                            if len(parts) == 2:
                                f_sum += int(parts[0]) * estimate_price(parts[1], live_menu)
                        
                        all_data.append({
                            "Sorszám": int(s_num),
                            "Ügyintéző": "Lásd PDF (Utolsó oldal)",
                            "Cím": "Lásd PDF (Utolsó oldal)",
                            "Telefon": tel,
                            "Rendelés": order_str,
                            "Napi Érték": f_sum,
                            "Jutalék (13%)": f_sum * jutalek_rate
                        })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
if 'menu' not in st.session_state:
    st.session_state.menu = get_live_menu()

st.title("Interfood v150.4 - Adatmentő Verzió")
f = st.file_uploader("Menetterv feltöltése", type="pdf")

if f:
    df = process_pdf_v150_4(f, st.session_state.menu)
    
    # Dashboard
    c1, c2, c3 = st.columns(3)
    c1.metric("Össz. Forgalom", f"{df['Napi Érték'].sum():,.0f} Ft".replace(',', ' '))
    c2.metric("Jutalék (13%)", f"{df['Jutalék (13%)'].sum():,.0f} Ft".replace(',', ' '))
    c3.metric("Sorok száma", len(df))
    
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_javitott.csv")
