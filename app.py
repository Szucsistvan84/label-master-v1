import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_phone(text):
    # Tisztítás: csak számok és perjel maradjon a mintához
    return re.sub(r'[^\d/]', '', text)

def parse_menetterv_v123(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
        for i, page in enumerate(pdf.pages):
            is_last_page = (i == total_pages - 1)
            
            if not is_last_page:
                # 1-88 sorok: Marad a bevált v120 rácsos logika
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 4: continue
                        s_raw = str(row[0]).strip().split('\n')[0]
                        if not s_raw.isdigit(): continue
                        
                        kod_match = re.search(r'([HKSC P Z]-\d{6})', str(row[1]))
                        kod = kod_match.group(1) if kod_match else ""
                        cim = str(row[2]).strip().replace('\n', ' ')
                        if "Ügyintéző" in cim: continue
                        
                        c4 = str(row[3]).strip()
                        nev = c4.split('\n')[0] if c4 else ""
                        
                        all_rows.append({"Sorszám": int(s_raw), "Kód": kod, "Cím": cim, "Ügyintéző": nev})
            
            else:
                # UTOLSÓ OLDAL: Az általad javasolt logikai horgonyok alapján
                text = page.extract_text()
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    # 1. Sorszám és Kód azonosítása
                    main_match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not main_match: continue
                    
                    sorszam = main_match.group(1)
                    kod = main_match.group(2)
                    
                    # 2. Cím kezdete (4 jegyű irányítószám keresése szóközök között)
                    # Olyan 4 számot keresünk, ami nem része a 6 jegyű kódnak
                    iranyitoszam_match = re.search(r'\s(\d{4})\s', line)
                    if not iranyitoszam_match: continue
                    idx_irsz = iranyitoszam_match.start(1)
                    
                    # 3. Telefonszám keresése (Horgony a Cím végéhez és a Névhez)
                    # 20/30/70-es kezdettel
                    tel_match = re.search(r'(20|30|70)/\d{7}', line)
                    
                    if tel_match:
                        idx_tel_start = tel_match.start()
                        idx_tel_end = tel_match.end()
                        
                        # A CÍM: Az irányítószámtól a NÉV-ig tart. 
                        # De a név a telefonszám előtt van.
                        # Keressük meg a név kezdetét (általában a cím utáni nagybetűs rész)
                        # Egyszerűsítve: Ami az Irányítószám és a Tel.szám között van, az a Cím + Név
                        koztes_szoveg = line[idx_irsz:idx_tel_start].strip()
                        
                        # Választóvonal a Cím és a Név között: 
                        # A te leírásod szerint a Név (Juhász-Takács Angéla) a Cím után van közvetlenül.
                        # Itt egy trükk: a Cím általában "u. 3." vagy "út 12." jellegűre végződik
                        cim_vege_match = re.search(r'(\d+\.|[a-zA-Z]\.)\s+[A-Z]', koztes_szoveg)
                        if cim_vege_match:
                            cim_resz = koztes_szoveg[:cim_vege_match.start(1)+2].strip()
                            nev_resz = koztes_szoveg[cim_vege_match.start(1)+2:].strip()
                        else:
                            # Ha nem találunk egyértelmű határt, próbáljuk meg a Debrecen kulcsszót
                            # Országosítás miatt: az irányítószám utáni első 15-20 karakter biztos cím
                            cim_resz = koztes_szoveg # Ideiglenesen
                            nev_resz = "Név keresése..."

                        # 4. Rendelés: A telefonszám utáni rész a sor végéig, levágva az utolsó számot
                        rendeles_resz = line[idx_tel_end:].strip()
                        
                        all_rows.append({
                            "Sorszám": int(sorszam),
                            "Kód": kod,
                            "Cím": cim_resz,
                            "Ügyintéző": nev_resz,
                            "Rendelés": rendeles_resz
                        })

    return pd.DataFrame(all_rows).sort_values("Sorszám")

st.title("Interfood v123 - Országos Címfelismerő")
st.info("Új logika: Irányítószám (4 jegy) és Telefonszám horgonyok használata.")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v123(f)
    if not data.empty:
        st.dataframe(data)
        csv = data.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV letöltése", csv, "interfood_v123.csv", "text/csv")
