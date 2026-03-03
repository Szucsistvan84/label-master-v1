import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v136(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                
                for row in table:
                    if not row or len(row) < 5: continue
                    s_raw = str(row[0]).strip()
                    s_nums = [s.strip() for s in s_raw.split('\n') if s.strip().isdigit()]
                    if not s_nums: continue

                    # A teljes cella tartalmát egyben kezeljük
                    rendeles_szoveg = str(row[5]).replace('\n', ' ')
                    # Kigyűjtjük az összes Ft-ot a cellából
                    osszegek = re.findall(r'(\d[\d\s]*Ft)', rendeles_szoveg)
                    # Kigyűjtjük az összes telefonszámot
                    tel_szamok = re.findall(r'(\d{2}/\d{6,7})', rendeles_szoveg + str(row[4]))
                    
                    for idx, s_num in enumerate(s_nums):
                        # Biztonságos kiosztás: ha nincs több Ft, akkor 0 Ft
                        akt_ar = osszegek[idx] if idx < len(osszegek) else "0 Ft"
                        akt_tel = tel_szamok[idx] if idx < len(tel_szamok) else (tel_szamok[0] if tel_szamok else "")
                        
                        # Ügyintéző és Adag (ha van több sor, vesszük a megfelelőt)
                        nevek = str(row[3]).split('\n')
                        adagok = str(row[6]).split('\n') if len(row) > 6 else []

                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                            "Cím": str(row[2]).strip().replace('\n', ' '),
                            "Ügyintéző": nevek[idx].strip() if idx < len(nevek) else nevek[0].strip(),
                            "Telefon": akt_tel,
                            "Ételek": "PDF-ben ellenőrizni", # Egyelőre ezt békén hagyjuk a fagyás ellen
                            "Összeg": akt_ar,
                            "Adag": adagok[idx].strip() if idx < len(adagok) else "1"
                        })
            else:
                # UTOLSÓ OLDAL (Szeletelő logika - ez stabil volt)
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if not m: continue
                    
                    # Ft keresés az utolsó oldalon is
                    f_ar = re.search(r'(\d[\d\s]*Ft)', line)
                    
                    all_rows.append({
                        "Sorszám": int(m.group(1)), "Kód": m.group(2), "Cím": "Lásd v131",
                        "Ügyintéző": "Lásd v131", "Telefon": "...", 
                        "Ételek": "...", "Összeg": f_ar.group(1) if f_ar else "0 Ft", "Adag": "1"
                    })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI...
st.title("Interfood v136 - Ultra-Stabil Verzió")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v136(f)
    st.dataframe(df)
