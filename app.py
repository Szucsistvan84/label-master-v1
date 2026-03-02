import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v125(pdf_file):
    all_rows = []
    # Gyakori közterület típusok a cím azonosításához
    kozteruletek = r'(út|utca|útja|tér|körút|krt|u\.|sor|dűlő|köz|sétány|park)'
    
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
        for i, page in enumerate(pdf.pages):
            is_last_page = (i == total_pages - 1)
            
            if not is_last_page:
                # 1-88: Megbízható v120 rács mód
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
                # UTOLSÓ OLDAL: Intelligens szövegfelosztás
                text = page.extract_text()
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    main_match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not main_match: continue
                    
                    s_num = main_match.group(1)
                    kod = main_match.group(2)
                    
                    # 1. Horgony: Irányítószám (4 jegy)
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    if not irsz_m: continue
                    idx_irsz = irsz_m.start(1)
                    
                    # 2. Horgony: Telefonszám
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    if not tel_m: continue
                    idx_tel = tel_m.start()
                    
                    # A nyers blokk, amiben a Cím és a Név van
                    raw_block = line[idx_irsz:idx_tel].strip()
                    
                    # 3. Keresztmetszet: Hol van a közterület típusa és a házszám?
                    # Keressük az "út", "utca" stb. utáni házszámot (szám + esetleges betű/jel)
                    cim_vege_regex = kozteruletek + r'\s+\d+[/a-zA-Z\.]*'
                    cim_m = re.search(cim_vege_regex, raw_block, re.IGNORECASE)
                    
                    if cim_m:
                        idx_split = cim_m.end()
                        cim_resz = raw_block[:idx_split].strip()
                        nev_resz = raw_block[idx_split:].strip()
                        
                        # Ha a név rész ponttal kezdődik (pl. ". Szuromi"), vágjuk le a pontot
                        nev_resz = re.sub(r'^[^\w\s]+', '', nev_resz).strip()
                    else:
                        # Ha nincs házszám, de van város (Debrecen,)
                        varos_m = re.search(r'[A-Z][a-zâáéíóöőúüű]+,', raw_block)
                        if varos_m:
                            # Próbálunk egy értelmes vágást a cím után
                            cim_resz = raw_block
                            nev_resz = "Név nem azonosítható"
                        else:
                            cim_resz = raw_block
                            nev_resz = "Ellenőrizni"

                    rendeles_resz = line[idx_tel:].strip()
                    # Tisztítás: Telefonszám leválasztása a rendelésről
                    rendeles_resz = re.sub(r'^\d{2}/\d{6,7}\s*', '', rendeles_resz)
                    # Sor végi összesítő darabszám levágása
                    rendeles_resz = re.sub(r'\s\d+$', '', rendeles_resz)

                    all_rows.append({
                        "Sorszám": int(s_num),
                        "Kód": kod,
                        "Cím": cim_resz,
                        "Ügyintéző": nev_resz,
                        "Rendelés": rendeles_resz
                    })

    return pd.DataFrame(all_rows).sort_values("Sorszám")

st.title("Interfood v125 - Közterület-alapú felismerő")
st.info("Finomítva: Mikepércsi út 73/c és Szuromi Fanni esetei kezelve.")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v125(f)
    if not data.empty:
        st.dataframe(data)
        csv = data.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV letöltése", csv, "interfood_v125.csv", "text/csv")
