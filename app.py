import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v141(pdf_file):
    all_rows = []
    # Telefonszám, Összeg és Adag minták
    tel_re = re.compile(r'(\d{2}/\d{6,7})')
    price_re = re.compile(r'(\d[\d\s]{0,10}Ft)')
    
    with pdfplumber.open(pdf_file) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text: continue
            
            # Oldalankénti táblázat a nevekhez/címekhez (v131 stílus)
            table = page.extract_table()
            
            # Sorok feldolgozása nyers szövegből a fagyás ellen
            lines = text.split('\n')
            for i, line in enumerate(lines):
                # Sorszám + Kód keresése (pl. 1 P-428867)
                match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                if match:
                    s_num = int(match.group(1))
                    kod = match.group(2)
                    
                    # Keresési tartomány: az aktuális sor és a következő 2 sor (Tőkés-huzat)
                    context = " ".join(lines[i:i+3])
                    
                    # 1. ÖSSZEG JAVÍTÁSA (A Te ötleted: Ft után vágunk)
                    price = "0 Ft"
                    if "Ft" in context:
                        # Mindent levágunk az ELSŐ Ft után, ami a sorszámhoz tartozik
                        cut_text = context[:context.find("Ft")+2]
                        p_match = price_re.findall(cut_text)
                        if p_match:
                            # Az utolsó találat a levágott szövegben a miénk
                            raw_p = p_match[-1].strip()
                            # Tisztítás: ha "2 11 555 Ft", levágjuk a magányos adagszámot az elejéről
                            p_parts = raw_p.split()
                            if len(p_parts) > 2 and len(p_parts[0]) <= 2:
                                price = " ".join(p_parts[1:])
                            else:
                                price = raw_p

                    # 2. TELEFON ÉS ADAG
                    tel = tel_re.search(context).group(1) if tel_re.search(context) else ""
                    
                    # Adag számítása a kódokból (1-L1K stb)
                    adag_matches = re.findall(r'(\d+)-[A-Z0-9]+', context)
                    calc_adag = sum(int(a) for a in adag_matches) if adag_matches else 1

                    # 3. NÉV ÉS CÍM (Összefésülés a táblázattal, ha lehet)
                    u_nev, u_cim = "Ismeretlen", "Ismeretlen"
                    if table:
                        for row in table:
                            if row and str(row[0]).strip().startswith(str(s_num)):
                                u_cim = str(row[2]).replace('\n', ' ') if len(row) > 2 else u_cim
                                u_nev = str(row[3]).split('\n')[0] if len(row) > 3 else u_nev
                                break

                    all_rows.append({
                        "Sorszám": s_num,
                        "Kód": kod,
                        "Cím": u_cim,
                        "Ügyintéző": u_nev,
                        "Telefon": tel,
                        "Összeg": price,
                        "Adag": calc_adag
                    })

    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám', 'Kód'])
    return df.sort_values("Sorszám")

# UI
st.title("Interfood v141 - Stabil & Ft-Stop")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v141(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v141.csv")
