import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v131_1(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # 1. RÉSZ: Normál táblázatos oldalak
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue 
                        s_raw = str(row[0]).strip().split('\n')[0]
                        if not s_raw.isdigit(): continue
                        
                        kod_m = re.search(r'([HKSC P Z]-\d{6})', str(row[1]))
                        
                        # Telefon és Ételek szétválasztása a 4. oszlopból
                        tel_cell = str(row[4]) if row[4] else ""
                        tel_parts = tel_cell.split('\n')
                        telefonszam = tel_parts[0].strip() if len(tel_parts) > 0 else ""
                        # Minden, ami nem a telefon, az megy az Ételekhez
                        etelek = ", ".join([p.strip() for p in tel_parts[1:] if p.strip()])
                        
                        all_rows.append({
                            "Sorszám": int(s_raw),
                            "Kód": kod_m.group(1) if kod_m else "",
                            "Cím": str(row[2]).strip().replace('\n', ' '),
                            "Ügyintéző": str(row[3]).split('\n')[0] if row[3] else "",
                            "Telefon": telefonszam,
                            "Ételek": etelek
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
                        # A telefon UTÁNI rész az utolsó oldalon az étel rendelés
                        rendeles_resz = line[tel_m.end():].strip()
                        
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        
                        vagas_helye = -1
                        for ut in ut_list:
                            pos = koztes.lower().find(ut.lower())
                            if pos != -1:
                                ut_vege = pos + len(ut)
                                maradek = koztes[ut_vege:].strip()
                                szavak = maradek.split(' ')
                                hazszam_resz = []
                                nev_resz = []
                                talalt_nevet = False
                                for szo in szavak:
                                    is_name_start = (szo and szo[0].isupper() and len(szo) > 1 and not any(c.isdigit() for c in szo))
                                    if is_name_start or talalt_nevet:
                                        talalt_nevet = True
                                        nev_resz.append(szo)
                                    else:
                                        hazszam_resz.append(szo)
                                
                                cim_vegleges = (koztes[:ut_vege].strip() + " " + " ".join(hazszam_resz)).strip()
                                nev_vegleges = " ".join(nev_resz).strip()
                                vagas_helye = 1
                                break
                        
                        if vagas_helye == -1:
                            cim_vegleges, nev_vegleges = koztes, "Ellenőrizni"

                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Kód": kod,
                            "Cím": cim_vegleges,
                            "Ügyintéző": nev_vegleges if nev_vegleges else "Nincs név",
                            "Telefon": telefonszam,
                            "Ételek": rendeles_resz
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# Streamlit UI
st.set_page_config(page_title="Interfood v131.1", layout="wide")
st.title("Interfood v131.1 - Rendelés Gyűjtő")
st.success("Visszaállítva a stabil v131-es címkezelés. Pénz elrejtve, Ételek oszlop hozzáadva.")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v131_1(f)
    # Csak azokat az oszlopokat mutatjuk, amik kellenek
    st.dataframe(df[["Sorszám", "Kód", "Ügyintéző", "Cím", "Telefon", "Ételek"]], use_container_width=True)
    
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("💾 Letöltés CSV-ben", csv, f"interfood_rendelesek_{f.name}.csv")
