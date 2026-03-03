import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_money_v144(raw_text):
    if not raw_text: return "0 Ft"
    # Minden szóközt és újsort egységesítünk
    t = " ".join(str(raw_text).split())
    
    # A szabályod: Ha van szóköz a 0 előtt: " 0 Ft"
    # Megkeressük az összes összeget
    matches = re.findall(r'(\d[\d\s]*Ft)', t)
    if not matches: return "0 Ft"
    
    results = []
    for m in matches:
        # Ha a "Ft" előtt közvetlenül egy magányos "0" áll, aminek szóköz van az elején
        # Pl: "2 0 Ft" -> a " 0 Ft" rész miatt ez nulla
        if re.search(r'\s0\s*Ft', " " + m):
            results.append("0 Ft")
        else:
            # Ha valódi szám (nincs szóköz a 0 előtt, pl 11550), akkor tisztítjuk az elejét
            parts = m.replace("Ft", "").strip().split()
            if len(parts) > 1 and len(parts[0]) <= 2: # Levágjuk a magányos adagszámot
                results.append(" ".join(parts[1:]) + " Ft")
            else:
                results.append(m)
    return results

def parse_pdf_v144(pdf_file):
    all_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text: continue
            
            # Keressük a sorokat: Sorszám + Kód (v131 logika)
            lines = text.split('\n')
            for j, line in enumerate(lines):
                # Mint pl: "1 P-428867"
                match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                if match:
                    s_num = match.group(1)
                    kod = match.group(2)
                    
                    # Kontextus: a sor és az alatta lévő 3 sor (hogy minden infó meglegyen)
                    context = " ".join(lines[j:j+4])
                    
                    # Telefonszám (v131 szerint)
                    tel = re.search(r'(\d{2}/\d{6,7})', context)
                    
                    # Összeg a te szóköz-szabályoddal
                    prices = clean_money_v144(context)
                    price = prices[0] if prices else "0 Ft"
                    
                    # Név keresése (a kód utáni rész a sorban)
                    name_part = line.split(kod)[-1].strip()
                    # Cím keresése (általában a következő sor eleje)
                    address = lines[j+1].strip() if j+1 < len(lines) else ""

                    all_data.append({
                        "Sorszám": int(s_num),
                        "Kód": kod,
                        "Ügyintéző": name_part[:30], # Rövidítve, hogy ne csússzon el
                        "Cím": address,
                        "Telefon": tel.group(1) if tel else "Nincs",
                        "Összeg": price
                    })
                    
    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI
st.title("Interfood v144 - A v131 Javított Kiadása")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_pdf_v144(f)
    st.dataframe(df)
    st.download_button("Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v144.csv")
