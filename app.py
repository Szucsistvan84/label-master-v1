import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup

# --- BEÁLLÍTÁSOK ---
st.set_page_config(page_title="Interfood v150 - Intelligence", layout="wide")

# Átlagárak, ha a webes bányászat sikertelen lenne
DEFAULT_PRICES = {
    "L": 1150, "F": 2450, "D": 2350, "R": 2100, "P": 1850, "default": 2200
}

# --- FUNKCIÓK ---

@st.cache_data(ttl=3600) # Óránként egyszer frissít csak, hogy gyors legyen
def get_interfood_menu():
    """Lekéri az aktuális kódokat és árakat."""
    menu = {}
    try:
        url = "https://rendel.interfood.hu/"
        # User-agent, hogy ne nézzenek botnak
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Itt keressük a kódokat és árakat (egyszerűsített regex szűrés)
            text = soup.get_text(separator=' ')
            # Kódok: pl. DKM, L1K (Nagybetű, szám, 2-5 karakter)
            codes = re.findall(r'\b[A-Z][A-Z0-9]{1,4}\b', text)
            # Árak: pl. 2 450 Ft
            prices = re.findall(r'(\d[\d\s]*)\s*Ft', text)
            
            # Ez egy leegyszerűsített párosítás a demóhoz
            for i in range(min(len(codes), len(prices))):
                p = int(re.sub(r'\D', '', prices[i]))
                if p > 500: # Csak a valós árakat tároljuk
                    menu[codes[i]] = p
        return menu
    except Exception as e:
        return {}

def get_price(code, menu_prices):
    if code in menu_prices:
        return menu_prices[code]
    return DEFAULT_PRICES.get(code[0] if code else "", DEFAULT_PRICES["default"])

def process_pdf(pdf_file, menu_prices):
    all_data = []
    jutalek_szazalek = 0.13
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
            if not table: continue
            
            for row in table:
                if not row or len(row) < 5: continue
                
                # Sorszámok
                s_raw = str(row[0]).split('\n')
                s_nums = [s.strip() for s in s_raw if s.strip().isdigit()]
                if not s_nums: continue
                
                # Adatok tisztítása (Te logikád)
                raw_info = str(row[4]).replace('\n\n\n', '\n').replace('\n ', '\n')
                
                # Rendelés bányászat (pl. 1-DKM)
                orders = re.findall(r'(\d)-([A-Z0-9]+)', raw_info)
                
                # Napi forgalom számítás
                napi_sum = 0
                for adag, kod in orders:
                    napi_sum += int(adag) * get_price(kod, menu_prices)
                
                # Nevek szétosztása
                names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                
                for idx, snum in enumerate(s_nums):
                    all_data.append({
                        "Sorszám": int(snum),
                        "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                        "Rendelés": ", ".join([f"{a}-{k}" for a, k in orders]) if idx == 0 else "---",
                        "Napi Forgalom": napi_sum if idx == 0 else 0,
                        "Jutalék (13%)": (napi_sum * jutalek_szazalek) if idx == 0 else 0
                    })
    return pd.DataFrame(all_data)

# --- FŐ PROGRAM ---
st.title("Interfood v150 - Intelligence")
st.subheader("Automata étlap-szinkron és jutalék számoló")

# Étlap betöltése
if 'menu' not in st.session_state:
    st.session_state.menu = get_interfood_menu()

if not st.session_state.menu:
    st.info("💡 Az élő étlap nem elérhető, becsült árakkal számolunk.")
else:
    st.success(f"✅ Étlap szinkronizálva! ({len(st.session_state.menu)} kód betöltve)")

uploaded_file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if uploaded_file:
    try:
        with st.spinner('Adatok feldolgozása...'):
            df = process_pdf(uploaded_file, st.session_state.menu)
            df = df.drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
            
            # Statisztika
            total_f = df["Napi Forgalom"].sum()
            total_j = df["Jutalék (13%)"].sum()
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Napi össz. forgalom", f"{total_f:,.0f} Ft".replace(',', ' '))
            col2.metric("Saját jutalék (13%)", f"{total_j:,.0f} Ft".replace(',', ' '))
            col3.metric("Címek száma", len(df))
            
            st.divider()
            st.dataframe(df, use_container_width=True)
            
            st.download_button("CSV letöltése", df.to_csv(index=False).encode('utf-8-sig'), "jutalek_elszamolas.csv")
            
    except Exception as e:
        st.error(f"Hiba történt a feldolgozás során: {e}")
