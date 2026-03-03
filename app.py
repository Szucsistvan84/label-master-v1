import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.7 - Cikkszám Fixer", layout="wide")

def parse_interfood_v150_7(pdf_file):
    all_rows = []
    
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # TÁBLÁZATOS OLDALAK (Itt volt a hiba az 1-88-nál)
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 3: continue
                        
                        # Sorszám kinyerése (mindig az első oszlop)
                        s_raw = str(row[0]).split('\n')
                        s_nums = [s.strip() for s in s_raw if s.strip().isdigit()]
                        if not s_nums: continue
                        
                        # ÖSSZES cella tartalmát összeöntjük egy nagy szöveggé a kereséshez
                        full_row_text = " ".join([str(cell) for cell in row if cell])
                        
                        # Cikkszámok keresése az EGÉSZ sorban (pl. 1-L1K, 1-DK, 2-F2)
                        # Kibővítettem, hogy a "1- " szóközös verziót is elkapja
                        cikkszamok = re.findall(r'(\d-\s?[A-Z0-9]+)', full_row_text)
                        rendeles_tisztitott = ", ".join(cikkszamok) if cikkszamok else "Nincs kód"
                        
                        # Telefon keresése az egész sorban
                        tel_m = re.search(r'(\d{2}/\d{6,7})', full_row_text)
                        tel = tel_m.group(1) if tel_m else "Nincs"
                        
                        # Ügyintéző és Cím (marad a v131-es helyén, de ha üres, keresünk máshol)
                        name = str(row[3]).split('\n')[0] if len(row) > 3 else ""
                        addr = str(row[2]).replace('\n', ' ') if len(row) > 2 else ""

                        for idx, snum in enumerate(s_nums):
                            all_rows.append({
                                "Sorszám": int(snum),
                                "Ügyintéző": name if idx == 0 else "",
                                "Cím": addr if idx == 0 else "",
                                "Telefon": tel if idx == 0 else "",
                                "Rendelés": rendeles_tisztitott if idx == 0 else "---"
                            })
            
            # UTOLSÓ OLDAL (Szeletelő logika a 89+ sorszámokhoz)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    cikkszamok = re.findall(r'(\d-\s?[A-Z0-9]+)', line)
                    rendeles_tisztitott = ", ".join(cikkszamok) if cikkszamok else "Nincs kód"

                    all_rows.append({
                        "Sorszám": int(s_num),
                        "Ügyintéző": "Utolsó oldali ügyfél",
                        "Cím": "Lásd PDF",
                        "Telefon": tel_m.group(1) if tel_m else "Nincs",
                        "Rendelés": rendeles_tisztitott
                    })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.title("🎯 Interfood v150.7 - Cikkszám Elkapó")
st.warning("Ebben a verzióban az egész sort átvizsgáljuk kódok után, így az 1-88 soroknak is meg kell lenniük.")

f = st.file_uploader("Töltsd fel a PDF-et", type="pdf")
if f:
    df = parse_interfood_v150_7(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_javitott_v7.csv")
