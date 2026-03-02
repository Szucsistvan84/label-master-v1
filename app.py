import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v128(pdf_file):
    all_rows = []
    # Kibővített közterület lista
    kozteruletek = ['út', 'utca', 'útja', 'tér', 'körút', 'krt', 'u.', 'sor', 'dűlő', 'köz', 'sétány', 'park']
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # Az utolsó oldalig a régi jól bevált táblázatos módszer
            if i < len(pdf.pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 4: continue
                        s_raw = str(row[0]).strip().split('\n')[0]
                        if not s_raw.isdigit(): continue
                        kod_m = re.search(r'([HKSC P Z]-\d{6})', str(row[1]))
                        all_rows.append({
                            "Sorszám": int(s_raw),
                            "Kód": kod_m.group(1) if kod_m else "",
                            "Cím": str(row[2]).strip().replace('\n', ' '),
                            "Ügyintéző": str(row[3]).split('\n')[0] if row[3] else ""
                        })
            else:
                # UTOLSÓ OLDAL - Hibatűrő darabolás
                text = page.extract_text()
                for line in text.split('\n'):
                    line = line.strip()
                    main_match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not main_match: continue
                    
                    s_num, kod = main_match.groups()
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    if not irsz_m or not tel_m: continue
                    
                    # A rész, ahol a cím és a név van
                    block = line[irsz_m.start(1):tel_m.start()].strip()
                    
                    # DARABOLÁS LÉPÉSEI:
                    found_kozter = None
                    for kt in kozteruletek:
                        if " " + kt in block.lower():
                            found_kozter = kt
                            break
                    
                    if found_kozter:
                        # Szétvágjuk a blokkot a közterület típusánál
                        parts = re.split(f'({found_kozter})', block, flags=re.IGNORECASE)
                        eleje = parts[0] + parts[1] # pl. "4030 Debrecen, Mikepércsi út"
                        hatulja = "".join(parts[2:]).strip() # pl. "73/c Hamar Szabolcs"
                        
                        # A házszám az első szó a hátuljában
                        h_parts = hatulja.split(' ', 1)
                        hazszam = h_parts[0]
                        nev_resz = h_parts[1] if len(h_parts) > 1 else ""
                        
                        # Kiss Tímea 8-10 esete: ha a név számmal/ponttal kezdődik, az még a házszám
                        while nev_resz and (nev_resz[0].isdigit() or nev_resz.startswith('-') or nev_resz.startswith('.')):
                            n_split = nev_resz.split(' ', 1)
                            hazszam += " " + n_split[0]
                            nev_resz = n_split[1] if len(n_split) > 1 else ""
                        
                        cim_vegleges = f"{eleje} {hazszam}".strip()
                        nev_vegleges = nev_resz.strip()
                    else:
                        cim_vegleges, nev_vegleges = block, "Név nem lefejthető"

                    all_rows.append({
                        "Sorszám": int(s_num), "Kód": kod, "Cím": cim_vegleges, 
                        "Ügyintéző": nev_vegleges, "Rendelés": line[tel_m.start():].strip()
                    })
    
    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám'])

# Streamlit UI...
