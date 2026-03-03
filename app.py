import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_money(text):
    if not text or "Ft" not in text: return "0 Ft"
    # Megkeressük a Ft-ot és az előtte lévő számokat
    match = re.search(r'(\d[\d\s]*)\s*Ft', text)
    if match:
        num_part = match.group(1).strip()
        # Ha szóközök vannak (pl. 2 11 555), csak az utolsó két blokkot tartjuk meg
        # Mert az összeg 100 Ft és 99 999 Ft között mozoghat (2 vagy 3 számcsoport max)
        parts = num_part.split()
        if len(parts) > 2 and len(parts[0]) <= 2: # Ha az első szám gyanúsan kicsi (pl. egy adagszám "2")
            return " ".join(parts[1:]) + " Ft"
        return num_part + " Ft"
    return "0 Ft"

def parse_menetterv_v140(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # TÁBLÁZATOS OLDALAK
            if i < len(pdf.pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or not str(row[0]).strip().replace('\n','').isdigit(): continue
                    
                    s_nums = str(row[0]).strip().split('\n')
                    # A "Rendelése" cella (row[5]) tartalmát szétbontjuk
                    rendeles_cell = str(row[5]) if len(row) > 5 else ""
                    prices = re.findall(r'(\d[\d\s]*Ft)', rendeles_cell.replace('\n', ' '))
                    
                    for idx, s_num in enumerate(s_nums):
                        price_raw = prices[idx] if idx < len(prices) else "0 Ft"
                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if row[1] else "",
                            "Cím": str(row[2]).replace('\n', ' '),
                            "Ügyintéző": str(row[3]).split('\n')[idx] if idx < len(str(row[3]).split('\n')) else str(row[3]).split('\n')[0],
                            "Telefon": re.search(r'(\d{2}/\d+)', rendeles_cell).group(1) if re.search(r'(\d{2}/\d+)', rendeles_cell) else "",
                            "Összeg": clean_money(price_raw),
                            "Adag": str(row[6]).split('\n')[idx] if len(row) > 6 and idx < len(str(row[6]).split('\n')) else "1"
                        })
            # UTOLSÓ OLDAL (Stabil v131 logika)
            else:
                text = page.extract_text()
                for line in text.split('\n'):
                    m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if m:
                        p_match = re.search(r'(\d[\d\s]*Ft)', line)
                        all_rows.append({
                            "Sorszám": int(m.group(1)), "Kód": m.group(2), "Cím": "Ellenőrizni",
                            "Ügyintéző": "Ellenőrizni", "Telefon": "Ellenőrizni",
                            "Összeg": clean_money(p_match.group(1)) if p_match else "0 Ft", "Adag": "1"
                        })
    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("Interfood v140 - A stabil visszatérés")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v140(f)
    st.dataframe(df)
    st.download_button("Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "v140.csv")
