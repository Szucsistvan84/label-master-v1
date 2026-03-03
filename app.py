import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.9 - Adat Tisztító", layout="wide")

def parse_interfood_v150_9(pdf_file):
    all_rows = []
    # Olyan minta, ami darabszámmal kezdődik, kötőjel, majd BETŰVEL kezdődő kód (pl. 1-L1K)
    # Így a házszámokat (pl. 2-26) kihagyja.
    order_pattern = r'(\d-\s?[A-Z][A-Z0-9]*)'
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
                        
                        # CSAK a betűvel kezdődő kódokat gyűjtjük ki
                        cikkszamok = re.findall(order_pattern, full_row_text)
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
            
            # 2. RÉSZ: UTOLSÓ OLDAL (Szeletelő + 92-es javítás)
            else:
                text = page.extract_text()
                if not text: continue
                # Tisztítjuk a szöveget a 92-eshez hasonló törések ellen
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    # Keresünk sorszámot a sor elején
                    match = re.search(r'^(\d{1,3})\s+', line)
                    if not match: continue
                    
                    s_num = match.group(1)
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    
                    # Cikkszámok szűrése itt is: csak betűvel kezdődő kód jöhet
                    cikkszamok = re.findall(order_pattern, line)
                    rendeles_str = ", ".join(cikkszamok) if cikkszamok else "Nincs kód"
                    
                    # Név és cím logika
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
st.title("🎯 Interfood v150.9 - Házszám-szűrő Kiadás")
st.info("Javítva: 92-es sorszám és a házszámok (pl. 2-26) kiszűrése a rendelések közül.")

f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = parse_interfood_v150_9(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_tisztitott.csv")
