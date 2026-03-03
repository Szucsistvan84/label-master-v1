import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v135(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue
                        
                        s_raw = str(row[0]).strip()
                        s_nums = [s.strip() for s in s_raw.split('\n') if s.strip().isdigit()]
                        if not s_nums: continue

                        # Minden adatot egy nagy szöveggé gyúrunk a cellán belül a kereséshez
                        rendeles_full = str(row[5]).replace('\n', ' ') if len(row) > 5 else ""
                        prices = re.findall(r'(\d[\d\s]*Ft)', rendeles_full)
                        
                        # Adagok és Nevek listázása
                        nevek = str(row[3]).split('\n')
                        adagok = str(row[6]).split('\n') if len(row) > 6 else []

                        for idx, s_num in enumerate(s_nums):
                            # Összeg kiosztása sorrendben
                            price = prices[idx] if idx < len(prices) else "0 Ft"
                            
                            # Ételkódok: kimentjük az összes kódot, ami betű-szám kombináció (pl. 1-L1K)
                            # De a legegyszerűbb: a teljes szövegből kivonjuk a telefonokat és az árakat
                            food_clean = rendeles_full
                            for p in prices: food_clean = food_clean.replace(p, "")
                            tel_m = re.search(r'(\d{2}/\d+)', food_clean)
                            if tel_m: food_clean = food_clean.replace(tel_m.group(1), "")

                            all_rows.append({
                                "Sorszám": int(s_num),
                                "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                                "Cím": str(row[2]).strip().replace('\n', ' '),
                                "Ügyintéző": nevek[idx].strip() if idx < len(nevek) else nevek[0].strip(),
                                "Telefon": tel_m.group(1) if tel_m else "Nincs",
                                "Ételek": food_clean.strip()[:50], # Csak az eleje, hogy ne legyen túl hosszú
                                "Összeg": price,
                                "Adag": adagok[idx].strip() if idx < len(adagok) else "1"
                            })
            
            else:
                # UTOLSÓ OLDAL (Szigorított Ft keresés)
                text = page.extract_text()
                for line in text.split('\n'):
                    line = line.strip()
                    m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not m: continue
                    
                    # Utolsó oldalon a Ft-ot a teljes sorban keressük
                    price_m = re.search(r'(\d[\d\s]*Ft)', line)
                    price = price_m.group(1) if price_m else "0 Ft"
                    
                    # ... (marad a v134-es stabil cím/név szeletelő rész) ...
                    # [Itt a korábbi kódod marad a cím/név/telefon részre]
                    
                    all_rows.append({
                        "Sorszám": int(m.group(1)), "Kód": m.group(2), "Cím": "Cím...", 
                        "Ügyintéző": "Név...", "Telefon": "Tel...", "Ételek": "Kódok...", 
                        "Összeg": price, "Adag": "1"
                    })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI rész változatlan...
