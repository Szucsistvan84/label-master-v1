import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup

# --- ALAPBEÁLLÍTÁSOK ---
st.set_page_config(page_title="Interfood Intelligence v150.2", layout="wide")

# Becsült árak múltbéli adatokhoz vagy hálózati hiba esetére
DEFAULT_PRICES = {
    "L_NAGY": 1150,  # Leves nagy adag (pl. L1)
    "L_KICSI": 890,   # Leves kis adag (pl. L1K)
    "F_NAGY": 2450,  # Főétel nagy adag
    "F_KICSI": 1850,  # Főétel kis adag (pl. F1K, DKM)
    "default": 2200
}

# --- FUNKCIÓK ---

@st.cache_data(ttl=3600)
def get_live_menu():
    """Lekéri az aktuális kódokat és árakat az Interfoodról."""
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
    except:
        pass
    return menu

def estimate_price(code, live_menu):
    """Okos ár-becslő: L+szám logika és kis adag kezelés."""
    if code in live_menu:
        return live_menu[code]
    
    is_kis_adag = code.endswith('K') or 'DKM' in code
    first_char = code[0] if code else ""
    
    if first_char == "L" and len(code) > 1 and code[1].isdigit():
        return DEFAULT_PRICES["L_KICSI"] if is_kis_adag else DEFAULT_PRICES["L_NAGY"]
    
    return DEFAULT_PRICES["F_KICSI"] if is_kis_adag else DEFAULT_PRICES["F_NAGY"]

def process_interfood_pdf(pdf_file, live_menu):
    all_data = []
    jutalek_kulcs = 0.13
    
    with pdfplumber.open(pdf_file) as pdf:
        # Utolsó oldal kivételével táblázatként kezeljük
        for i, page in enumerate(pdf.pages[:-1]):
            table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
            if not table: continue
            
            for row in table:
                if not row or len(row) < 5: continue
                s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                if not s_nums: continue
                
                # Rendelések kinyerése a Te 'tisztító' logikáddal
                raw_info = str(row[4]).replace('\n\n\n', '\n').replace('\n ', '\n')
                orders = re.findall(r'(\d)-([A-Z0-9]+)', raw_info)
                
                napi_forgalom = sum(int(adag) * estimate_price(kod, live_menu) for adag, kod in orders)
                names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                
                for idx, snum in enumerate(s_nums):
                    all_data.append({
                        "Sorszám": int(snum),
                        "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                        "Rendelés": ", ".join([f"{a}-{k}" for a, k in orders]) if idx == 0 else "---",
                        "Napi Érték": napi_forgalom if idx == 0 else 0,
                        "Jutalék (13%)": (napi_forgalom * jutalek_kulcs) if idx == 0 else 0
                    })
        
        # Utolsó oldal (szöveges feldolgozás)
        last_page_text = pdf.pages[-1].extract_text()
        if last_page_text:
            for line in last_page_text.split('\n'):
                m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                if m:
                    s_num, kod = m.groups()
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    rendeles_szoveg = line[tel_m.end():].strip() if tel_m else ""
                    rendeles_szoveg = re.sub(r'\s+\d+$', '', rendeles_szoveg)
                    
                    o_list = re.findall(r'(\d)-([A-Z0-9]+)', rendeles_szoveg)
                    f_sum = sum(int(a) * estimate_price(k, live_menu) for a, k in o_list)
                    
                    all_data.append({
                        "Sorszám": int(s_num),
                        "Ügyintéző": "Utolsó oldali név",
                        "Rendelés": rendeles_szoveg,
                        "Napi Érték": f_sum,
                        "Jutalék (13%)": f_sum * jutalek_kulcs
                    })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.title("📊 Interfood Intelligence v150.2")
st.markdown("Automata étlap-szinkronizálás és jutalék statisztika")

if 'menu' not in st.session_state:
    st.session_state.menu = get_live_menu()

uploaded_file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if uploaded_file:
    try:
        df = process_interfood_pdf(uploaded_file, st.session_state.menu)
        
        # Dashboard elemek
        total_forgalom = df["Napi Érték"].sum()
        total_jutalek = df["Jutalék (13%)"].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Napi össz-forgalom", f"{total_forgalom:,.0f} Ft".replace(',', ' '))
        c2.metric("Napi jutalékom (13%)", f"{total_jutalek:,.0f} Ft".replace(',', ' '), delta="💰")
        c3.metric("Kiszállított címek", len(df))
        
        st.divider()
        st.dataframe(df, use_container_width=True)
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 Elszámolás letöltése (CSV)", csv, "interfood_jutalek.csv", "text/csv")
        
    except Exception as e:
        st.error(f"Hiba történt: {e}")
