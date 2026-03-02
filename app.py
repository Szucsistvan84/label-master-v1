import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v126(pdf_file):
    all_rows = []
    kozteruletek = r'(út|utca|útja|tér|körút|krt|u\.|sor|dűlő|köz|sétány|park)'
    
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if i != total_pages - 1:
                # 1-88 sorok (rácsos mód)
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
                # UTOLSÓ OLDAL (Szöveges mód)
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
                    
                    # ÚJ LOGIKA: Házszám tartományok kezelése (pl. 8-10.)
                    # Keressük a közterület típust, majd utána a számokat, kötőjeleket és pontokat
                    cim_vege_regex = kozteruletek + r'\s+[\d\s\-\/\.a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]+?\.'
                    cim_m = re.search(cim_vege_regex, raw_block, re.IGNORECASE)
                    
                    if cim_m:
                        cim_resz = raw_block[:cim_m.end()].strip()
                        nev_resz = raw_block[cim_m.end():].strip()
                        
                        # Biztonsági tisztítás: Ha a név elején maradt egy szám+pont (pl "10. ")
                        nev_resz = re.sub(r'^\d+\.\s*', '', nev_resz)
                        # Ha a cím végén maradt a név eleje, vagy fordítva
                        if " " in nev_resz:
                            # Ha a név első szava csupa kisbetű vagy szám, akkor az még a cím
                            first_word = nev_resz.split(' ')[0]
                            if first_word.isdigit() or first_word[0].islower():
                                cim_resz += " " + first_word
                                nev_resz = nev_resz[len(first_word):].strip()
                    else:
                        cim_resz, nev_resz = raw_block, "Ellenőrizni"

                    rendeles = line[tel_m.end():].strip()
                    rendeles = re.sub(r'\s\d+$', '', rendeles)

                    all_rows.append({
                        "Sorszám": int(s_num), "Kód": kod, "Cím": cim_resz, 
                        "Ügyintéző": nev_resz, "Rendelés": rendeles
                    })
    return pd.DataFrame(all_rows).sort_values("Sorszám")

st.title("Interfood v126 - 'Kiss Tímea nem királynő' kiadás")
st.info("Javítva: Házszám tartományok (8-10.) és az Ügyintéző névből levágott házszám töredékek.")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    data = parse_menetterv_v126(f)
    st.dataframe(data)
    st.download_button("💾 CSV letöltése", data.to_csv(index=False).encode('utf-8-sig'), "interfood_v126.csv")
