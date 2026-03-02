import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v127(pdf_file):
    all_rows = []
    kozteruletek = r'(út|utca|útja|tér|körút|krt|u\.|sor|dűlő|köz|sétány|park)'
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # ... (a táblázatos rész marad a régi, nézzük az utolsó oldalt)
            if i == len(pdf.pages) - 1:
                text = page.extract_text()
                for line in text.split('\n'):
                    line = line.strip()
                    main_match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not main_match: continue
                    
                    s_num, kod = main_match.groups()
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    if not irsz_m or not tel_m: continue
                    
                    raw_block = line[irsz_m.start(1):tel_m.start()].strip()
                    
                    # ÚJ LOGIKA: Intelligens vágás pont nélkül is
                    # 1. Megkeressük a közterület típust és az utána lévő házszámot
                    horgony = re.search(kozteruletek + r'\s+\d+[\w/\.-]*', raw_block, re.IGNORECASE)
                    
                    if horgony:
                        vagas_pontja = horgony.end()
                        maradek = raw_block[vagas_pontja:].strip()
                        
                        # 2. Megnézzük, mi maradt. Ha a maradék nagybetűvel kezdődik (Név), 
                        # akkor ott vágunk. Ha ponttal/vesszővel, azt is kezeljük.
                        nev_match = re.search(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-zâáéíóöőúüű]+\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', maradek)
                        
                        if nev_match:
                            # A név az első két nagybetűs szónál kezdődik
                            cim_resz = raw_block[:vagas_pontja + nev_match.start()].strip()
                            nev_resz = nev_match.group(1).strip()
                        else:
                            # Ha nem találtunk egyértelmű nevet, marad a régi módszer
                            cim_resz = raw_block[:vagas_pontja].strip()
                            nev_resz = maradek
                    else:
                        cim_resz, nev_resz = raw_block, "Ellenőrizni"

                    # ... (rendelés és tisztítás marad)
                    all_rows.append({"Sorszám": int(s_num), "Kód": kod, "Cím": cim_resz, "Ügyintéző": nev_resz})
    
    return pd.DataFrame(all_rows)

# Streamlit UI...
