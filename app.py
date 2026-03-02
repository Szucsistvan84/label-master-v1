import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v124(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
        for i, page in enumerate(pdf.pages):
            is_last_page = (i == total_pages - 1)
            
            if not is_last_page:
                # 1-88 sorok: Standard rácsos feldolgozás
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 4: continue
                        s_raw = str(row[0]).strip().split('\n')[0]
                        if not s_raw.isdigit(): continue
                        kod_m = re.search(r'([HKSC P Z]-\d{6})', str(row[1]))
                        kod = kod_m.group(1) if kod_m else ""
                        cim = str(row[2]).strip().replace('\n', ' ')
                        if "Ügyintéző" in cim: continue
                        nev = str(row[3]).split('\n')[0] if row[3] else ""
                        all_rows.append({"Sorszám": int(s_raw), "Kód": kod, "Cím": cim, "Ügyintéző": nev})
            
            else:
                # UTOLSÓ OLDAL: Speciális Regex horgonyok
                text = page.extract_text()
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    main_match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not main_match: continue
                    
                    s_num = main_match.group(1)
                    kod = main_match.group(2)
                    
                    # Irányítószám keresése (4 jegy szóközökkel)
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    if not irsz_m: continue
                    idx_irsz = irsz_m.start(1)
                    
                    # Telefonszám keresése (Mobil: 20/30/70, Vezetékes: körzet/szám)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    if not tel_m: continue
                    idx_tel = tel_m.start()
                    
                    # A szöveg az Irányítószámtól a Telefonszámig (Cím + Név)
                    raw_block = line[idx_irsz:idx_tel].strip()
                    
                    # FINOMHANGOLÁS: Cím és Név szétválasztása
                    # 1. Szabály: A házszám utáni ". " lezárja a címet
                    split_m = re.search(r'(\d+[a-z/]*\.)\s+', raw_block)
                    
                    if split_m:
                        cim_resz = raw_block[:split_m.end(1)].strip()
                        nev_resz = raw_block[split_m.end(1):].strip()
                    else:
                        # 2. Szabály (Hamar Szabolcs-eset): Nincs pont, de van házszám
                        # Keresünk egy számot (házszám), ami után nagybetűs szó jön
                        hazszam_m = re.search(r'(\d+[a-z/]*)\s+([A-ZÁÉÍÓÖŐÚÜŰ][a-zâáéíóöőúüű]+)', raw_block)
                        if hazszam_m:
                            cim_resz = raw_block[:hazszam_m.end(1)].strip()
                            nev_resz = raw_block[hazszam_m.start(2):].strip()
                        else:
                            cim_resz = raw_block
                            nev_resz = "Ellenőrizni"

                    # Rendelés kinyerése a tel.szám után
                    rendeles_resz = line[tel_m.end():].strip()
                    # Levágjuk az ellenőrző összeget a végéről (utolsó szám)
                    rendeles_resz = re.sub(r'\s\d+$', '', rendeles_resz)

                    all_rows.append({
                        "Sorszám": int(s_num),
                        "Kód": kod,
                        "Cím": cim_resz,
                        "Ügyintéző": nev_resz,
                        "Rendelés": rendeles_resz
                    })

    return pd.DataFrame(all_rows).sort_values("Sorszám")

st.title("Interfood v124 - Precíziós Adatkinyerő")
st.info("Javítva: Batiz Zoltán (vezetékes szám), Cím/Név elválasztás (. ) és Hamar Szabolcs logika.")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v124(f)
    if not data.empty:
        st.dataframe(data)
        csv = data.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV letöltése", csv, "interfood_v124.csv", "text/csv")
