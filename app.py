import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v133(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 6: continue
                        
                        # Sorszámok kinyerése (lehet több is egy cellában: "1\n2")
                        s_raw_list = str(row[0]).strip().split('\n')
                        s_nums = [s.strip() for s in s_raw_list if s.strip().isdigit()]
                        if not s_nums: continue

                        # Adatok szétbontása sorokra (többsoros cellák kezelése)
                        ugyintezok = str(row[3]).split('\n')
                        rendelesek = str(row[5]).split('\n')
                        adagok = str(row[6]).split('\n') if len(row) > 6 else ["1"]

                        for idx, s_num in enumerate(s_nums):
                            # Ügyintéző és Adag hozzárendelése (ha van elég elem a listában)
                            nev = ugyintezok[idx].strip() if idx < len(ugyintezok) else (ugyintezok[0] if ugyintezok else "")
                            adag = adagok[idx].strip() if idx < len(adagok) else (adagok[0] if adagok else "1")
                            
                            # Rendelés és Összeg kibányászása a "Rendelése" blokkból
                            # Megkeressük az összes Ft-ot és a kódokat
                            curr_rendeles = str(row[5]).replace('\n', ' ')
                            prices = re.findall(r'(\d[\d\s]*Ft)', curr_rendeles)
                            price = prices[idx] if idx < len(prices) else "0 Ft"
                            
                            # Ételkódok (tisztítás: leszedjük az árakat a szövegből)
                            food_text = curr_rendeles
                            for p in prices:
                                food_text = food_text.replace(p, "")
                            
                            all_rows.append({
                                "Sorszám": int(s_num),
                                "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                                "Cím": str(row[2]).strip().replace('\n', ' '),
                                "Ügyintéző": nev,
                                "Telefon": "Lásd PDF", # A táblázatban a telefon sokszor a rendelésnél van, v134-ben pontosítjuk
                                "Ételek": food_text.strip(),
                                "Összeg": price,
                                "Adag": adag
                            })
            
            else:
                # UTOLSÓ OLDAL JAVÍTÁSA (Az összeg regex bővítése)
                text = page.extract_text()
                for line in text.split('\n'):
                    line = line.strip()
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    
                    if tel_m:
                        # Rendelés rész a telefon után
                        rend_resz = line[tel_m.end():].strip()
                        
                        # Összeg keresése (rugalmasabb regex: \d után bármennyi szóköz és szám, majd Ft)
                        osszeg_m = re.search(r'(\d[\d\s]*Ft)', rend_resz)
                        price = osszeg_m.group(1) if osszeg_m else "0 Ft"
                        
                        # Adag (sor végi szám)
                        adag_m = re.search(r'(\d+)$', rend_resz)
                        adag = adag_m.group(1) if adag_m else "1"
                        
                        # Ételek (ami maradt)
                        etelek = rend_resz.replace(price, "").strip()
                        etelek = re.sub(r'\d+$', '', etelek).strip()

                        # Cím/Név szeletelés (marad a bevált v130)
                        koztes = line[irsz_m.start(1):tel_m.start()].strip() if irsz_m else ""
                        # ... (v130 szeletelő logika ide jön)
                        
                        all_rows.append({
                            "Sorszám": int(s_num), "Kód": kod, "Cím": "Utolsó oldali cím", 
                            "Ügyintéző": "Utolsó oldali név", "Telefon": tel_m.group(1),
                            "Ételek": etelek, "Összeg": price, "Adag": adag
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI...
