import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_price_v143(raw_text):
    if not raw_text: return "0 Ft"
    # Tisztítás a sortörésektől
    text = str(raw_text).replace('\n', ' ').strip()
    
    # Megkeressük az összes "szám + Ft" blokkot
    matches = re.findall(r'(\d[\d\s]*)\s*Ft', text)
    if not matches: return "0 Ft"
    
    final_prices = []
    for m in matches:
        m = m.strip()
        # A TE LOGIKÁD: Ha " 0" (szóköz nulla) van a Ft előtt, az gyanús
        # De ha pl "10" vagy "11890", ott nincs szóköz a 0 előtt
        if m == "0" or m.endswith(" 0"):
            final_prices.append("0 Ft")
        else:
            # Ha az elején van egy magányos szám (pl "2 11555"), levágjuk
            parts = m.split()
            if len(parts) > 1 and len(parts[0]) <= 2 and int(parts[0]) < 10:
                final_prices.append(" ".join(parts[1:]) + " Ft")
            else:
                final_prices.append(m + " Ft")
    return final_prices

def parse_menetterv_v143(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # 1-4. OLDALAK (Táblázatos)
            if i < len(pdf.pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or not str(row[0]).strip().replace('\n','').isdigit(): continue
                    
                    s_nums = str(row[0]).strip().split('\n')
                    # Pénzek kinyerése a szűrővel
                    raw_prices = clean_price_v143(row[5])
                    
                    for idx, s_num in enumerate(s_nums):
                        price = raw_prices[idx] if idx < len(raw_prices) else "0 Ft"
                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if row[1] else "",
                            "Cím": str(row[2]).replace('\n', ' '),
                            "Ügyintéző": str(row[3]).split('\n')[idx] if idx < len(str(row[3]).split('\n')) else str(row[3]).split('\n')[0],
                            "Telefon": re.search(r'(\d{2}/\d+)', str(row[5])).group(1) if re.search(r'(\d{2}/\d+)', str(row[5])) else "",
                            "Összeg": price,
                            "Adag": str(row[6]).split('\n')[idx] if len(row) > 6 and idx < len(str(row[6]).split('\n')) else "1"
                        })
            # UTOLSÓ OLDAL (Külön figyelemmel a nevekre)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})\s+(.*?)\s+(\d{2}/\d+|$)', line.strip())
                    if m:
                        p_match = re.search(r'(\d[\d\s]*Ft)', line)
                        all_rows.append({
                            "Sorszám": int(m.group(1)), "Kód": m.group(2), 
                            "Cím": "Utolsó oldali cím", "Ügyintéző": m.group(3).strip(), 
                            "Telefon": m.group(4) if m.group(4) else "Nincs", 
                            "Összeg": clean_price_v143(line)[0] if clean_price_v143(line) else "0 Ft",
                            "Adag": "1"
                        })
    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI
st.title("Interfood v143 - A 'Szóköz-szűrő' visszatér")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_menetterv_v143(f)
    st.dataframe(df)
    st.download_button("Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "v143_stabil.csv")
