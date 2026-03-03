import streamlit as st
import pdfplumber
import pandas as pd
import re

# --- ALAPBEÁLLÍTÁSOK ---
st.set_page_config(page_title="Interfood v150.6 - Adatbányász", layout="wide")

def parse_interfood_v150_6(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # 1. RÉSZ: Táblázatos oldalak (1-88 sorszámok általában itt vannak)
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue
                        
                        # Sorszámok kinyerése
                        s_raw = str(row[0]).split('\n')
                        s_nums = [s.strip() for s in s_raw if s.strip().isdigit()]
                        if not s_nums: continue
                        
                        # Ügyintézők és Címek
                        names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                        addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]
                        
                        # RENDELÉS ÉS TELEFON (Az 5. oszlopból)
                        # Itt most nem vágunk, hanem megkeressük a cikkszámokat (pl. 1-L1K)
                        raw_info = str(row[4]).replace('\n\n\n', '\n')
                        
                        # Telefonszám keresése
                        tel_m = re.search(r'(\d{2}/\d{6,7})', raw_info)
                        tel = tel_m.group(1) if tel_m else "Nincs"
                        
                        # Cikkszámok keresése (pl. 1-L1K vagy 1-DK)
                        cikkszamok = re.findall(r'(\d-[A-Z0-9]+)', raw_info)
                        rendeles_tisztitott = ", ".join(cikkszamok) if cikkszamok else "Nincs kód"

                        for idx, snum in enumerate(s_nums):
                            all_rows.append({
                                "Sorszám": int(snum),
                                "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                                "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else ""),
                                "Telefon": tel,
                                "Rendelés": rendeles_tisztitott if idx == 0 else "---" 
                            })
            
            # 2. RÉSZ: Utolsó oldal (Szeletelő logika a 89+ sorszámokhoz)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    
                    # Cikkszámok keresése a sorban
                    cikkszamok = re.findall(r'(\d-[A-Z0-9]+)', line)
                    rendeles_tisztitott = ", ".join(cikkszamok) if cikkszamok else "Nincs kód"
                    
                    # Cím/Név szeletelés (v131 stabil rész)
                    addr_v = "Lásd PDF"
                    if irsz_m and tel_m:
                        addr_v = line[irsz_m.start(1):tel_m.start()].strip()

                    all_rows.append({
                        "Sorszám": int(s_num),
                        "Ügyintéző": "Lásd PDF",
                        "Cím": addr_v,
                        "Telefon": tel_m.group(1) if tel_m else "Nincs",
                        "Rendelés": rendeles_tisztitott
                    })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.title("🔍 Interfood v150.6 - Cikkszám Vadász")
st.info("Fókuszban az 1-88 sorszámok és a pontos rendelési kódok.")

f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = parse_interfood_v150_6(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 Adatok mentése (CSV)", df.to_csv(index=False).encode('utf-8-sig'), "interfood_cikkszamok.csv")
