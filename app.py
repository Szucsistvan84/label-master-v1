import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v103(pdf_path):
    all_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Szavak kinyerése koordinátákkal
            words = page.extract_words(x_tolerance=2, y_tolerance=2)
            
            # 1. Keressük meg a horgonyokat (KÓD: XXXXXX)
            for i, w in enumerate(words):
                if re.search(r'\d{6}', w['text']):
                    cid = re.search(r'\d{6}', w['text']).group()
                    
                    # NÉV KERESÉSE: Pontosan a kód felett lévő szavak
                    name_parts = []
                    for w2 in words:
                        # Ha a szó a kód felett van (Y diff: 5-15) és vízszintesen takarásban vannak
                        if 3 < (w['top'] - w2['bottom']) < 18 and abs(w['x0'] - w2['x0']) < 40:
                            if not any(x in w2['text'].upper() for x in ["SOR", "ÜGYFÉL", "KÓD", "TÉTEL"]):
                                name_parts.append(w2['text'])
                    
                    name = " ".join(name_parts).strip()
                    if not name: name = "Név hiányzik"

                    # ADATOK (Telefon, Cím, Pénz) - a kód környezetében (max 40 pixel távolság)
                    context = " ".join([word['text'] for word in words if abs(word['top'] - w['top']) < 40])
                    
                    tel = "NINCS"
                    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', context)
                    if tel_m: tel = tel_m.group(1)

                    addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^|]+)', context)
                    addr = addr_m.group(1).split("REND:")[0].strip() if addr_m else "Cím hiányzik"

                    money_m = re.search(r'(\d+[\s\d]*)\s*Ft', context)
                    money = int(re.sub(r'\s+', '', money_m.group(1))) if money_m else 0

                    rends = re.findall(r'(\d+-[A-Z0-9]+)', context)

                    all_data.append({
                        "id": cid, "name": name, "tel": tel, "addr": addr, 
                        "money": money, "rend": rends, "page": page.page_number
                    })

    # Duplikátumok kiszűrése (ha egy kódot többször is megtalál az oldalon)
    df = pd.DataFrame(all_data)
    if df.empty: return df
    
    # Csoportosítás kódonként (Péntek + Szombat összevonása)
    final = []
    for cid, group in df.groupby("id"):
        # A leghosszabb nevet választjuk (hátha az egyiknél hiányzik)
        best_name = max(group["name"].tolist(), key=len)
        best_addr = max(group["addr"].tolist(), key=len)
        best_tel = max(group["tel"].tolist(), key=len)
        all_rends = [r for sublist in group["rend"] for r in sublist]
        total_money = group["money"].sum()
        
        final.append({
            "Ügyfélkód": cid, "Ügyintéző": best_name, "Telefon": best_tel,
            "Cím": best_addr, "Rendelés": ", ".join(set(all_rends)),
            "Pénz": f"{total_money} Ft" if total_money > 0 else ""
        })
    
    return pd.DataFrame(final).sort_values("Ügyfélkód")

# (Az FPDF generáló rész marad a régi, 3x7-es elrendezéssel)
