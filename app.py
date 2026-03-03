import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.8 - Teljes Adat", layout="wide")

def parse_interfood_v150_8(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']
    
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # 1. RÉSZ: TÁBLÁZATOS OLDALAK (1-88 sorszámok)
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 3: continue
                        s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                        if not s_nums: continue
                        
                        full_row_text = " ".join([str(cell) for cell in row if cell])
                        cikkszamok = re.findall(r'(\d-\s?[A-Z0-9]+)', full_row_text)
                        rendeles_str = ", ".join(cikkszamok) if cikkszamok else "Nincs kód"
                        
                        tel_m = re.search(r'(\d{2}/\d{6,7})', full_row_text)
                        tel = tel_m.group(1) if tel_m else "Nincs"
                        
                        names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                        addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                        for idx, snum in enumerate(s_nums):
                            all_rows.append({
                                "Sorszám": int(snum),
                                "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                                "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else ""),
                                "Telefon": tel if idx == 0 else "",
                                "Rendelés": rendeles_str if idx == 0 else "---"
                            })
            
            # 2. RÉSZ: UTOLSÓ OLDAL (Szeletelő logika a nevekhez és címekhez)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    cikkszamok = re.findall(r'(\d-\s?[A-Z0-9]+)', line)
                    rendeles_str = ", ".join(cikkszamok) if cikkszamok else "Nincs kód"
                    
                    # Név és cím visszahozása az utolsó oldalon (v131 logika)
                    cim_v, nev_v = "Lásd PDF", "Nincs név"
                    if irsz_m and tel_m:
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        for ut in ut_list:
                            pos = koztes.lower().find(ut.lower())
                            if pos != -1:
                                ut_vege = pos + len(ut)
                                maradek = koztes[ut_vege:].strip().split(' ')
                                hazszam = []
                                nevek = []
                                talalt_nev = False
                                for szo in maradek:
                                    if (szo and szo[0].isupper() and not any(c.isdigit() for c in szo)) or talalt_nev:
                                        talalt_nev = True
                                        nevek.append(szo)
                                    else:
                                        hazszam.append(szo)
                                cim_v = (koztes[:ut_vege].strip() + " " + " ".join(hazszam)).strip()
                                nev_v = " ".join(nevek).strip()
                                break

                    all_rows.append({
                        "Sorszám": int(s_num),
                        "Ügyintéző": nev_v,
                        "Cím": cim_v,
                        "Telefon": tel_m.group(1) if tel_m else "Nincs",
                        "Rendelés": rendeles_str
                    })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.title("🎯 Interfood v150.8 - Minden Adat Megvan")
st.info("Javítva: 1-88 cikkszámok és 89+ ügyféladatok.")

f = st.file_uploader("Menetterv PDF feltöltése", type="pdf")
if f:
    df = parse_interfood_v150_8(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_teljes_adat.csv")
