import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v93(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        # Tisztítjuk a sort a nan értékektől
        cells = [str(c).strip() for c in row.values if str(c) != 'nan' and str(c) != '']
        row_str = " ".join(cells)
        
        # Keressük az ügyfélkódot (pl. P-428867)
        code_match = re.search(r'([A-Z])-\s?(\d{6})', row_str)
        if not code_match: continue
        
        day_prefix, cust_id = code_match.group(1), code_match.group(2)
        
        # PÉNZ (Alatta lévő sorból)
        money = 0
        if idx + 1 < len(df_raw):
            next_row_text = " ".join([str(val) for val in df_raw.iloc[idx + 1].values if str(val) != 'nan'])
            money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', next_row_text)
            if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

        # ADATOK KERESÉSE A CELLÁKBAN
        name = "Név hiányzik"
        tel = "NINCS"
        addr = "Cím hiányzik"
        raw_rend = ""

        for c in cells:
            # 1. CÍM (Irányítószám alapján)
            if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', c):
                addr = c
            # 2. TELEFON (Regex alapján)
            elif re.search(r'(\d{2}/[\d\s-]{7,})', c) or c.startswith(('+36', '06')):
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', c)
                if tel_m:
                    tel = tel_m.group(1)
                    # Ami a telefon után van a cellában, az rendelés
                    raw_rend += " " + c.replace(tel, "").strip()
            # 3. NÉV (Legalább 2 szó, nincs benne szám, nem kód)
            elif len(c.split()) >= 2 and not re.search(r'\d', c) and name == "Név hiányzik":
                name = c
            # 4. RENDELÉS (Ha van benne kötőjeles kód)
            elif re.search(r'\d+-[A-Z0-9]+', c):
                raw_rend += " " + c

        # Tisztítás
        rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', raw_rend)
        current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', raw_rend))
        total_db = sum(int(c) for c in rend_codes)

        # TÁROLÁS
        customer_key = (name, addr)
        if customer_key not in temp_storage:
            temp_storage[customer_key] = {
                "kód": cust_id, "név": name, "cím": addr, "tel": tel, 
                "P": "", "Z": "", "db": 0, "pénz": 0, "orig_idx": len(order_list) + 1
            }
            order_list.append(customer_key)
        
        if day_prefix == "Z": temp_storage[customer_key]["Z"] = current_rend_str
        else: temp_storage[customer_key]["P"] = current_rend_str
