import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v132(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # 1. RÉSZ: Táblázatos oldalak
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 6: continue 
                        s_raw = str(row[0]).strip().split('\n')[0]
                        if not s_raw.isdigit(): continue
                        
                        kod_m = re.search(r'([HKSC P Z]-\d{6})', str(row[1]))
                        tel_raw = str(row[4]).replace('\n', ' ') if row[4] else ""
                        
                        # Ft és Étel kódok szétválasztása a cellán belül
                        rendeles_raw = str(row[5]).replace('\n', ' ') if len(row) > 5 else ""
                        osszeg_m = re.search(r'(\d[\d\s]*Ft)', rendeles_raw)
                        osszeg = osszeg_m.group(1) if osszeg_m else "0 Ft"
                        etelek = rendeles_raw.replace(osszeg, "").strip()
                        
                        # Utolsó oszlop az adagszám
                        adag = str(row[6]).strip() if len(row) > 6 else "1"
                        
                        all_rows.append({
                            "Sorszám": int(s_raw),
                            "Kód": kod_m.group(1) if kod_m else "",
                            "Cím": str(row[2]).strip().replace('\n', ' '),
                            "Ügyintéző": str(row[3]).split('\n')[0] if row[3] else "",
                            "Telefon": re.search(r'(\d{2}/\d+)', tel_raw).group(1) if re.search(r'(\d{2}/\d+)', tel_raw) else "",
                            "Ételek": etelek,
                            "Összeg": osszeg,
                            "Adag": adag
                        })
            
            # 2. RÉSZ: Utolsó oldal
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    line = line.strip()
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    
                    if irsz_m and tel_m:
                        telefonszam = tel_m.group(1)
                        # A telefon UTÁNI rész feldolgozása (Rendelés + Ft + Adag)
                        rendeles_blokk = line[tel_m.end():].strip()
                        
                        # Adagszám: a sor legvégső száma
                        adag_m = re.search(r'(\d+)$', rendeles_blokk)
                        adag = adag_m.group(1) if adag_m else "1"
                        rendeles_maradek = rendeles_blokk[:adag_m.start()].strip() if adag_m else rendeles_blokk
                        
                        # Összeg (Ft) keresése
                        osszeg_m = re.search(r'(\d[\d\s]*Ft)', rendeles_maradek)
                        osszeg = osszeg_m.group(1) if osszeg_m else "0 Ft"
                        etelek = rendeles_maradek.replace(osszeg, "").strip()
                        
                        # Cím és Név (v130/131 bevált logika)
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        cim_vegleges, nev_vegleges = koztes, "Ellenőrizni"
                        
                        for ut in ut_list:
                            pos = koztes.lower().find(ut.lower())
                            if pos != -1:
                                ut_vege = pos + len(ut)
                                szavak = koztes[ut_vege:].strip().split(' ')
                                hazszam_resz, nev_resz, talalt_nevet = [], [], False
                                for szo in szavak:
                                    if (szo and szo[0].isupper() and len(szo) > 1 and not any(c.isdigit() for c in szo)) or talalt_nevet:
                                        talalt_nevet = True
                                        nev_resz.append(szo)
                                    else:
                                        hazszam_resz.append(szo)
                                cim_vegleges = (koztes[:ut_vege].strip() + " " + " ".join(hazszam_resz)).strip()
                                nev_vegleges = " ".join(nev_resz).strip()
                                break

                        all_rows.append({
                            "Sorszám": int(s_num), "Kód": kod, "Cím": cim_vegleges, 
                            "Ügyintéző": nev_vegleges if nev_vegleges else "Nincs név",
                            "Telefon": telefonszam, "Ételek": etelek, "Összeg": osszeg, "Adag": adag
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# Streamlit UI
st.title("Interfood v132 - A Teljes Adatbázis")
st.write("Cím, Név, Telefon, Ételek, Összeg és Adagszám kinyerése folyamatban.")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v132(f)
    st.dataframe(df, use_container_width=True)
    
    # Egy kis statisztika a végére, ha már itt vagyunk
    osszes_adag = pd.to_numeric(df['Adag'], errors='coerce').sum()
    st.metric("Összesített adagszám", f"{int(osszes_adag)} adag")
    
    st.download_button("💾 CSV Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v132.csv")
