import streamlit as st
import pdfplumber # Átállunk a precízebb pdfplumberre!
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v102(pdf_path):
    all_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Kinyerjük az összes szót a koordinátáikkal együtt
            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            
            # Keressük az ügyfélkódokat (P- vagy Z-)
            for i, w in enumerate(words):
                code_m = re.search(r'([PZ])\s?-\s?(\d{6})', w['text'])
                if code_m:
                    prefix, cid = code_m.group(1), code_m.group(2)
                    
                    # NÉV KERESÉSE: A kód koordinátáihoz képest FELETTE lévő szavakat keressük
                    # Tőkés István itt fog megkerülni, mert a koordinátája fix!
                    name_parts = []
                    for w2 in words:
                        # Ha a szó a kód felett van max 15 egységgel és hasonló X pozícióban
                        if 0 < (w['top'] - w2['bottom']) < 15 and abs(w['x0'] - w2['x0']) < 40:
                            if not any(x in w2['text'] for x in ["KÓD", "KOD", "Sor", "Ügyfél"]):
                                name_parts.append(w2['text'])
                    
                    name = " ".join(name_parts) if name_parts else "Név hiányzik"
                    
                    # TELEFON, CÍM, PÉNZ (Környezeti keresés az adott oldalon)
                    # A kód környezetében lévő összes szöveg:
                    context = " ".join([word['text'] for word in words if abs(word['top'] - w['top']) < 40])
                    
                    tel = "NINCS"
                    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', context)
                    if tel_m: tel = tel_m.group(1)

                    addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^#]+)', context)
                    addr = addr_m.group(1).split("REND:")[0].strip() if addr_m else "Cím hiányzik"

                    money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', context)
                    money = int(re.sub(r'\s+', '', money_m.group(1))) if money_m else 0

                    rends = re.findall(r'(\d+-[A-Z0-9]+)', context)

                    all_data.append({
                        "id": cid, "prefix": prefix, "name": name, "tel": tel, 
                        "addr": addr, "money": money, "rend": rends
                    })

    # Összesítés és Tisztítás
    final_dict = {}
    for item in all_data:
        # Tőkés István fixálása: ha a név "István", de a cím ugyanaz, vonjuk össze
        key = (item["id"], item["addr"][:15]) # Kód + cím eleje a biztos kulcs
        if key not in final_dict:
            final_dict[key] = {"id": item["id"], "név": item["name"], "cím": item["addr"], 
                               "tel": item["tel"], "P": [], "Z": [], "pénz": 0}
        
        # Név javítás: ha az egyik beolvasásnál megvan a név, a másiknál nincs, tartsuk meg a jót
        if final_dict[key]["név"] == "Név hiányzik" or "Sor" in final_dict[key]["név"]:
            final_dict[key]["név"] = item["name"]
            
        if item["prefix"] == "Z": final_dict[key]["Z"].extend(item["rend"])
        else: final_dict[key]["P"].extend(item["rend"])
        final_dict[key]["pénz"] += item["money"]

    return pd.DataFrame([{
        "Sorszám": i+1, "Ügyfélkód": d["id"], "Ügyintéző": d["név"],
        "Telefon": d["tel"], "Cím": d["cím"],
        "Rendelés": f"P: {', '.join(set(d['P']))} | SZ: {', '.join(set(d['Z']))}".strip(" |"),
        "Összesen": f"{len(d['P'])+len(d['Z'])} tétel",
        "Pénz": f"{d['pénz']} Ft" if d['pénz'] > 0 else ""
    } for i, d in enumerate(final_dict.values())])

# PDF generáló marad...
