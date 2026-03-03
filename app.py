import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup

# --- ALAPOK ---
st.set_page_config(page_title="Interfood v150.3 - Teljes Adat", layout="wide")

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
def process_pdf_full(pdf_file, live_menu):
    all_data = []
    jutalek_rate = 0.13
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # Táblázatos oldal (v131 stílus)
            if i < len(pdf.pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                
                for row in table:
                    if not row or len(row) < 5: continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue
                    
                    # Címek és Nevek (v131 logika)
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    addr_raw = [a.strip() for a in str(row[2]).split('\n') if '40' in a]
                    
                    # Infó blokk (Telefon + Étel + Pénz)
                    raw_info = str(row[4]).replace('\n\n\n', '\n').replace('\n ', '\n')
                    info_lines = [l.strip() for l in raw_info.split('\n') if l.strip()]
                    
                    # Telefonszám bányászat
                    tel = "Nincs"
                    for line in info_lines:
                        if '/' in line: tel = line; break
                    
                    # Jutalék számítás
                    codes_found = re.findall(r'(\d)-([A-Z0-9]+)', raw_info)
                    napi_ertek = sum(int(a) * estimate_price(k, live_menu) for a, k in codes_found)
                    
                    for idx, snum in enumerate(s_nums):
                        all_data.append({
                            "Sorszám": int(snum),
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                            "Cím": addr_raw[idx] if idx < len(addr_raw) else (addr_raw[0] if addr_raw else "Debrecen"),
                            "Telefon": tel,
                            "Rendelés": raw_info.replace('\n', ' '),
                            "Napi Érték": napi_ertek if idx == 0 else 0,
                            "Jutalék (13%)": (napi_ertek * jutalek_rate) if idx == 0 else 0
                        })
            
            # Utolsó oldal (v131 szeletelő)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if m:
                        s_num, kod = m.groups()
                        tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                        rend_txt = line[tel_m.end():].strip() if tel_m else "Lásd PDF"
                        
                        codes_found = re.findall(r'(\d)-([A-Z0-9]+)', rend_txt)
                        f_sum = sum(int(a) * estimate_price(k, live_menu) for a, k in codes_found)
                        
                        all_data.append({
                            "Sorszám": int(s_num),
                            "Ügyintéző": "Utolsó oldali név",
                            "Cím": "Utolsó oldali cím",
                            "Telefon": tel_m.group(1) if tel_m else "Nincs",
                            "Rendelés": rend_txt,
                            "Napi Érték": f_sum,
                            "Jutalék (13%)": f_sum * jutalek_rate
                        })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.title("🚀 Interfood v150.3 - Minden egyben")

if 'menu' not in st.session_state:
    st.session_state.menu = get_live_menu()

f = st.file_uploader("Feltöltés", type="pdf")
if f:
    df = process_pdf_full(f, st.session_state.menu)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Össz. Forgalom", f"{df['Napi Érték'].sum():,.0f} Ft".replace(',', ' '))
    c2.metric("Jutalékom", f"{df['Jutalék (13%)'].sum():,.0f} Ft".replace(',', ' '))
    c3.metric("Címek", len(df))
    
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_full.csv")
