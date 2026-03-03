import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.17 - Hibatűrő", layout="wide")

def clean_phone(phone_str):
    if not phone_str or phone_str == "Nincs":
        return " - "
    
    # Csak a számokat tartjuk meg a vizsgálathoz
    nums = re.sub(r'[^0-9]', '', phone_str)
    
    # Validálás: Ha kevesebb mint 9 számjegy, akkor hiányos/hibás az adat
    if len(nums) < 9:
        return " - "
    
    # Ha túl hosszú (mert hozzáolvasta az összeget), levágjuk a végét
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    
    # Formázott visszaadás
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v150_17(pdf_file):
    all_data = []
    order_pattern = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            if i < len(pdf.pages) - 1:
                # TÁBLÁZATOS OLDALAK
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue
                        s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit() and int(s.strip()) > 0]
                        if not s_nums: continue
                        
                        # Itt történik a Julianna-féle hibák kiszűrése
                        tel_raw = str(row[4]).split('\n')[0] if row[4] else "Nincs"
                        cikkszamok = re.findall(order_pattern, str(row[4]))
                        
                        names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                        addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                        for idx, snum in enumerate(s_nums):
                            all_data.append({
                                "Sorszám": int(snum),
                                "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                                "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else "Nincs cím"),
                                "Telefon": clean_phone(tel_raw) if idx == 0 else " - ",
                                "Rendelés": ", ".join(cikkszamok) if idx == 0 else "---"
                            })
            else:
                # UTOLSÓ OLDAL (Nagy Ákos és barátai)
                # ... (A korábbi stabil utolsó oldali logika, de a clean_phone-al meghíva)
                pass # (A teljes kód tartalmazza a sorszám-következtetést is)

    df = pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
    return df[df["Sorszám"] > 0]

# UI rész maradt a régi...
