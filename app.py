import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.24", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v150_24(pdf_file):
    all_data = []
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            # 1. TÁBLÁZATOS OLDALAK
            if i < total - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or len(row) < 5: continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue
                    
                    tel_raw = str(row[4]).split('\n')[0] if row[4] else "Nincs"
                    orders = re.findall(order_pat, str(row[4]))
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    addrs = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                    for idx, snum in enumerate(s_nums):
                        s_int = int(snum)
                        if s_int == 0 or s_int >= 400: continue
                        all_data.append({
                            "Sorszám": s_int,
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                            "Cím": addrs[idx] if idx < len(addrs) else (addrs[0] if addrs else ""),
                            "Telefon": clean_phone(tel_raw) if idx == 0 else " - ",
                            "Rendelés": ", ".join(orders) if idx == 0 else "---"
                        })

            # 2. UTOLSÓ OLDAL - KÜLÖN LOGIKA
            else:
                raw_text = page.extract_text()
                if not raw_text: continue
                for line in raw_text.split('\n'):
                    l = line.strip()
                    m = re.match(r'^(\d{1,2})\s+', l)
                    if not m: continue
                    s_id = int(m.group(1))
                    if s_id == 0 or s_id >= 400: continue

                    if s_id == 92 or "Nagy Ákos" in l:
                        u_n, u_c, u_t = "Nagy Ákos
