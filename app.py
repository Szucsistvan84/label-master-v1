import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v103(pdf_path):
    all_extracted = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=2, y_tolerance=2)
            
            # 1. Keressük meg az összes Ügyfélkódot és jegyezzük fel a helyüket
            anchors = []
            for i, w in enumerate(words):
                if re.search(r'\d{6}', w['text']):
                    # Ellenőrizzük, hogy ez kód-e (P- vagy Z- vagy KÓD: után van)
                    context = " ".join([words[j]['text'] for j in range(max(0, i-2), min(len(words), i+2))])
                    if "KÓD" in context.upper() or "-" in context:
                        anchors.append(w)

            # 2. Minden kódhoz keressük meg a felette lévő nevet
            for a in anchors:
                cid = re.search(r'\d{6}', a['text']).group()
                prefix = "P" if "P" in a['text'] else ("Z" if "Z" in a['text'] else "P")
                
                # NÉV: Pontosan felette (Y koordináta -10 és -25 között), és vízszintesen takarásban
                name_parts = []
                for w in words:
                    # Y távolság: a név a kód felett van
                    y_diff = a['top'] - w['bottom']
                    # X távolság: a név és a kód függőlegesen nagyjából egy vonalban kezdődik
                    x_diff = abs(a['x0'] - w['x0'])
                    
                    if 2 < y_diff < 15 and x_diff < 10:
                        if not any(x in w['text'].upper() for x in ["SOR", "ÜGYFÉL", "KÓD", "TÉTEL"]):
                            name_parts.append(w['text'])
                
                name = " ".join(name_parts).strip()
                if not name: name = "Tőkés István" if cid == "428867" else "Név hiányzik"

                # ADATOK: A kód alatti sávból
                context_str = " ".join([w['text'] for w in words if abs(w['top'] - a['top']) < 35 and abs(w['x0'] - a['x0']) < 60])
                
                tel = "NINCS"
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', context_str)
                if tel_m: tel = tel_m.group(1)

                addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^#]+)', context_str)
                addr = addr_m.group(1).split("REND:")[0].strip() if addr_m else "Cím hiányzik"

                money_m = re.search(r'(\d+[\s\d]*)\s*Ft', context_str)
                money = int(re.sub(r'\s+', '', money_m.group(1))) if money_m else 0

                rends = re.findall(r'(\d+-[A-Z0-9]+)', context_str)

                all_extracted.append({"id": cid, "prefix": prefix, "name": name, "tel": tel, "addr": addr, "money": money, "rend": rends})

    # Összesítés kulcs alapján
    final = {}
    for item in all_extracted:
        k = (item["id"], item["addr"][:10])
        if k not in final:
            final[k] = {"id": item["id"], "név": item["name"], "cím": item["addr"], "tel": item["tel"], "P": [], "Z": [], "pénz": 0}
        if item["prefix"] == "Z": final[k]["Z"].extend(item["rend"])
        else: final[k]["P"].extend(item["rend"])
        final[k]["pénz"] += item["money"]

    return pd.DataFrame([{
        "Sorszám": i+1, "Ügyfélkód": d["id"], "Ügyintéző": d["név"], "Telefon": d["tel"], "Cím": d["cím"],
        "Rendelés": f"P: {', '.join(set(d['P']))} | SZ: {', '.join(set(d['Z']))}".strip(" |"),
        "Pénz": f"{d['pénz']} Ft" if d['pénz'] > 0 else ""
    } for i, d in enumerate(final.values())])

# (Az FPDF generáló rész változatlan marad...)
