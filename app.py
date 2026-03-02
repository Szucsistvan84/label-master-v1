import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v130(pdf_file):
    all_rows = []
    # Az úttípusok, amik után a házszámot keressük
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # 1. RÉSZ: Táblázatos oldalak (Statisztikailag stabil)
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
            
            # 2. RÉSZ: Az "utolsó oldal" (Itt volt a fagyás, most lineárissá tesszük)
            else:
                text = page.extract_text()
                if not text: continue
                
                for line in text.split('\n'):
                    line = line.strip()
                    # Sorszám + Kód azonosítása (pl. "93 P-414090")
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    
                    if irsz_m and tel_m:
                        # Kivágjuk a blokkot az irányítószámtól a telefonig
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        
                        vagas_helye = -1
                        for ut in ut_list:
                            pos = koztes.lower().find(ut.lower())
                            if pos != -1:
                                # Megkeressük az út utáni első szóközt (ami a házszám után van)
                                # Pl: "Mikepércsi út 73/c Hamar Szabolcs"
                                # 'út' utáni rész: ' 73/c Hamar Szabolcs'
                                ut_vege = pos + len(ut)
                                maradek = koztes[ut_vege:].strip()
                                
                                # A házszámot az első szóközig vesszük, DE ha Kiss Tímea tartománya van (8-10.), 
                                # akkor addig megyünk, amíg betűt nem találunk nagybetűvel
                                szavak = maradek.split(' ')
                                hazszam_resz = []
                                nev_resz = []
                                
                                talalt_nevet = False
                                for szo in szavak:
                                    # Ha a szó nagybetűvel kezdődik ÉS nem csak egy karakter (pl. 73/A) 
                                    # ÉS nem szám/pont/kötőjel keveréke, akkor az már a név
                                    is_name_start = (szo and szo[0].isupper() and len(szo) > 1 and not any(c.isdigit() for c in szo))
                                    
                                    if is_name_start or talalt_nevet:
                                        talalt_nevet = True
                                        nev_resz.append(szo)
                                    else:
                                        hazszam_resz.append(szo)
                                
                                cim_vegleges = (koztes[:ut_vege].strip() + " " + " ".join(hazszam_resz)).strip()
                                nev_vegleges = " ".join(nev_resz).strip()
                                vagas_helye = 1 # Jelöljük, hogy megvan
                                break
                        
                        if vagas_helye == -1:
                            cim_vegleges, nev_vegleges = koztes, "Ellenőrizni"

                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Kód": kod,
                            "Cím": cim_vegleges,
                            "Ügyintéző": nev_vegleges if nev_vegleges else "Nincs név"
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# Streamlit felület
st.title("Interfood v130 - 'Lineáris Biztonság'")
st.write("Ebben a verzióban nincsenek ciklusok a szövegfeldolgozásban, így nem tud lefagyni.")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v130(f)
    st.dataframe(df)
    st.download_button("CSV letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v130.csv")
