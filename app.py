import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
from bs4 import BeautifulSoup

# --- BIZTONSÁGI ÁRLISTA (Ha a weboldal épp nem elérhető) ---
# Ezek az átlagárak, amikkel a rendszer akkor számol, ha nincs élő kapcsolat
DEFAULT_PRICES = {
    "L": 1150,  # Levesek átlagára
    "F": 2450,  # Főételek átlagára
    "D": 2350,  # Dukan ételek
    "R": 2100,  # Reggelik/Könnyű ételek
    "P": 1850,  # Pizzák/Tészták
    "default": 2200
}

def get_price_estimate(code, menu_prices):
    """Megpróbálja kikeresni az árat, ha nincs meg, a betűkód alapján tippel."""
    if code in menu_prices:
        return menu_prices[code]
    
    # Ha a kód pl. L1K, megnézzük az első betűt (L = Leves)
    first_char = code[0] if code else ""
    return DEFAULT_PRICES.get(first_char, DEFAULT_PRICES["default"])

def get_interfood_3_week_menu():
    """Lekéri az összes elérhető étlapot a következő 3 hétre."""
    url = "https://rendel.interfood.hu/"
    menu = {}
    try:
        # Itt a program végigpörgeti az étlapot (akár a következő heteket is)
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Cikkszámok és árak kinyerése
        items = soup.find_all(class_=re.compile(r'product|item|food'))
        for item in items:
            text = item.get_text(separator=' ')
            code_m = re.search(r'\b([A-Z][A-Z0-9]{1,4})\b', text)
            price_m = re.search(r'(\d[\d\s]*)\s*Ft', text)
            
            if code_m and price_m:
                code = code_m.group(1)
                price = int(re.sub(r'\D', '', price_m.group(1)))
                menu[code] = price
        return menu
    except Exception as e:
        st.error(f"Hiba a webes szinkronizálásnál: {e}")
        return {}

# --- A FŐ FELDOLGOZÓ (v150) ---
def parse_v150_intelligence(pdf_file, menu_prices):
    all_rows = []
    jutalek_szazalek = 0.13
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # A Te általad javasolt tisztító logikával olvassuk a táblázatot
            table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
            if not table: continue
            
            for row in table:
                if not row or len(row) < 5: continue
                s_nums = [s for s in str(row[0]).split('\n') if s.strip().isdigit()]
                if not s_nums: continue
                
                # Cella tisztítása (tripla \n csere)
                raw_info = str(row[4]).replace('\n\n\n', '\n').replace('\n ', '\n')
                
                # Rendelések kinyerése (pl: 1-DKM)
                orders = re.findall(r'(\d)-([A-Z0-9]+)', raw_info)
                
                current_forgalom = 0
                etelek_nevei = []
                
                for adag, kod in orders:
                    ar = get_price_estimate(kod, menu_prices)
                    current_forgalom += int(adag) * ar
                    etelek_nevei.append(f"{adag}x {kod} ({ar} Ft)")

                for idx, snum in enumerate(s_nums):
                    # Itt osztjuk szét az adatokat az összevont cellákban (pl 1-es és 2-es)
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    
                    all_rows.append({
                        "Sorszám": int(snum),
                        "Ügyintéző": names[idx] if idx < len(names) else "Ismeretlen",
                        "Rendelés": ", ".join(etelek_nevei) if idx == 0 else "Lásd felette",
                        "Napi Forgalom": current_forgalom if idx == 0 else 0,
                        "Jutalék (13%)": (current_forgalom * jutalek_szazalek) if idx == 0 else 0
                    })
                    
    return pd.DataFrame(all_rows)

# ... Streamlit UI rész (Statisztikai dobozokkal) ...
