import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v134(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # 1. RÉSZ: Táblázatos oldalak (FAGYÁSMENTESÍTVE)
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue
                        
                        # Alap adatok kinyerése
                        s_raw = str(row[0]).strip()
                        if not any(c.isdigit() for c in s_raw): continue
                        
                        # Szétbontjuk, ha több sorszám van (pl. 1\n2)
                        s_nums = [s.strip() for s in s_raw.split('\n') if s.strip().isdigit()]
                        
                        # A "Rendelése" cellát (row[5]) és az "Össz" cellát (row[6]) sorokra bontjuk
                        rendeles_sorok = str(row[5]).split('\n') if len(row) > 5 else []
                        ossz_sorok = str(row[6]).split('\n') if len(row) > 6 else []
                        
                        # Telefonszámot gyakran a rendelés cellába teszi a PDF
                        tel_m = re.search(r'(\d{2}/\d{6,7})', str(row[5]) + str(row[4]))
                        tel_szam = tel_m.group(1) if tel_m else ""

                        for idx, s_num in enumerate(s_nums):
                            # Megkeressük az ehhez a sorszámhoz tartozó Ft összeget
                            # Megnézzük a rendelés sorait, és az első "Ft"-os sort keressük
                            ar = "0 Ft"
                            etelek = []
                            
                            # Végigfutunk a rendelés sorain, és próbáljuk párosítani
                            for r_line in rendeles_sorok:
                                if "Ft" in r_line:
                                    # Ha ez az első Ft, az az 1. sorszámé, stb.
                                    # Egyszerűsítés: az összes Ft-ot begyűjtjük és sorrendben kiosztjuk
                                    all_prices = re.findall(r'(\d[\d\s]*Ft)', str(row[5]).replace('\n', ' '))
                                    if idx < len(all_prices):
                                        ar = all_prices[idx]
                                    break
                            
                            # Ételkódok: minden, ami nem Ft és nem telefon
                            food_text = " ".join([l for l in rendeles_sorok if "Ft" not in l and "/" not in l]).strip()

                            all_rows.append({
                                "Sorszám": int(s_num),
                                "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                                "Cím": str(row[2]).strip().replace('\n', ' '),
                                "Ügyintéző": str(row[3]).split('\n')[idx] if idx < len(str(row[3]).split('\n')) else str(row[3]).split('\n')[0],
                                "Telefon": tel_szam,
                                "Ételek": food_text,
                                "Összeg": ar,
                                "Adag": ossz_sorok[idx].strip() if idx < len(ossz_sorok) else "1"
                            })
            
            # 2. RÉSZ: Utolsó oldal (A v131-es stabil alapján)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    line = line.strip()
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    
                    if tel_m:
                        rend_resz = line[tel_m.end():].strip()
                        osszeg_m = re.search(r'(\d[\d\s]{2,10}Ft)', rend_resz)
                        price = osszeg_m.group(1) if osszeg_m else "0 Ft"
                        
                        adag_m = re.search(r'(\d+)$', line)
                        adag = adag_m.group(1) if adag_m else "1"
                        
                        # Cím/Név szétválasztás (v130/131 stabil verzió)
                        koztes = line[irsz_m.start(1):tel_m.start()].strip() if irsz_m else ""
                        cim_v, nev_v = koztes, "Ellenőrizni"
                        for ut in ut_list:
                            if ut.lower() in koztes.lower():
                                pos = koztes.lower().find(ut.lower()) + len(ut)
                                maradek = koztes[pos:].strip().split(' ')
                                h_resz, n_resz, t_n = [], [], False
                                for szo in maradek:
                                    if (szo and szo[0].isupper() and len(szo) > 1 and not any(c.isdigit() for c in szo)) or t_n:
                                        t_n = True; n_resz.append(szo)
                                    else: h_resz.append(szo)
                                cim_v = (koztes[:pos].strip() + " " + " ".join(h_resz)).strip()
                                nev_v = " ".join(n_resz).strip()
                                break

                        all_rows.append({
                            "Sorszám": int(s_num), "Kód": kod, "Cím": cim_v, "Ügyintéző": nev_v,
                            "Telefon": tel_m.group(1), "Ételek": rend_resz.replace(price, "").strip(),
                            "Összeg": price, "Adag": adag
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- Streamlit UI ---
st.title("Interfood v134 - A Tőkés-Fixer")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v134(f)
    st.dataframe(df, use_container_width=True)
    st.metric("Összes adag", int(pd.to_numeric(df['Adag'], errors='coerce').sum()))
    st.download_button("CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v134.csv")
