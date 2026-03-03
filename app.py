import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_price_v138(raw_text):
    if not raw_text or "Ft" not in raw_text:
        return "0 Ft"
    
    # 1. Megkeressük az utolsó "Ft" előtti részt
    # 2. Csak a számokat és a szóközöket tartjuk meg közvetlenül a Ft előtt
    # Regex magyarázat: keress számokat, amik szóközökkel vannak elválasztva, de csak ha a Ft követi őket
    match = re.findall(r'(\d[\d\s]*)\s*Ft', raw_text)
    if match:
        # Az utolsó talált számcsoportot tisztítjuk (szóközök ki, ezresek be)
        pure_num = re.sub(r'\s+', '', match[-1])
        if pure_num.isdigit():
            return f"{int(pure_num):,}".replace(',', ' ') + " Ft"
    return "0 Ft"

def parse_menetterv_v138(pdf_file):
    all_rows = []
    # ... (A v137-es alapstruktúra marad) ...
    
    # A sorsdöntő változás a kinyerésnél:
    # search_area = line + next_line
    # price = clean_price_v138(search_area)
    
    # ... (táblázat-összefésülés marad) ...
    return pd.DataFrame(all_rows)

st.title("Interfood v138 - Tiszta Összegek")
# UI...
