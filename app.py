import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.22 - Fix", layout="wide")

def clean_phone(phone_str):
    if not phone_str or phone_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(phone_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v150_22(pdf_file):
    all_data = []
    order_pattern = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        pages = pdf.pages
        for i, page in enumerate(pages):
            # --- 1. TÁBLÁZATOS OLDALAK ---
            if i < len(pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue
                        s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                        if not s_nums: continue
                        
                        tel_raw = str(row[4]).split('\n')[0] if row[4] else "Nincs"
                        cikkszamok = re.findall(order_pattern, str(row[4]))
                        names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                        addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                        for idx, snum in enumerate(s_nums):
                            s_int = int(snum)
                            if s_int == 0 or s_int >= 400: continue
                            
                            all_data.append({
                                "Sorszám": s_int,
                                "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                                "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else ""),
                                "Telefon": clean_phone(tel_raw) if idx == 0 else " - ",
                                "Rendelés": ", ".join(cikkszamok) if idx == 0 else "---"
                            })

            # --- 2. UTOLSÓ OLDAL (SORALAPÚ) ---
            else:
                text = page.
