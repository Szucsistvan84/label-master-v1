import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_and_split_cell(cell_text):
    """A Te logikád: tripla és szóközös törések egységesítése."""
    if not cell_text: return []
    # Tisztítás
    t = str(cell_text).replace('\n\n\n', '\n').replace('\n ', '\n')
    # Üres sorok kiszűrése
    return [l.strip() for l in t.split('\n') if l.strip()]

def parse_menetterv_v131_4(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # 1. RÉSZ: TÁBLÁZATOS OLDALAK
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                
                for row in table:
                    if not row or len(row) < 5: continue
                    
                    # Sorszámok kinyerése
                    s_nums = [s for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue
                    
                    # Tisztított adatsorok a Te logikád szerint
                    names = clean_and_split_cell(row[3])
                    info_block = clean_and_split_cell(row[4])
                    
                    # Címek (2. oszlop) - itt néha nehéz szétvágni, de próbáljuk meg az irányítószámoknál
                    addresses = clean_and_split_cell(row[2])
                    addresses = [a for a in addresses if '40' in a] # Csak a debreceni irányítószámos sorok
                    
                    for idx, snum in enumerate(s_nums):
                        # MINTA KERESÉS az info_block-ban (Telefon, Étel, Pénz)
                        # Megpróbáljuk az adott ügyfélhez tartozó részt behatárolni
                        tel = "Nincs"
                        etel = "Nincs"
                        
                        # Ebben a blokkban keressük a mintákat (hogy ne keveredjenek az ügyfelek)
                        # Ha több ügyfél van, mindenki kap egy szeletet a listából
                        for line in info_block:
                            if '/' in line and tel == "Nincs": tel = line
                            elif '-' in line and etel == "Nincs": etel = line
                        
                        all_rows.append({
                            "Sorszám": int(snum),
                            "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                            "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else "Lásd a PDF-ben"),
                            "Telefon": tel,
                            "Rendelés": etel
                        })

            # 2. RÉSZ: UTOLSÓ OLDAL (Szeletelő)
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if match:
                        s_num, kod = match.groups()
                        tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                        rendeles = line[tel_m.end():].strip() if tel_m else "Nincs"
                        # Összesítő levágása a végéről
                        rendeles = re.sub(r'\s+\d+$', '', rendeles)
                        
                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Kód": kod,
                            "Ügyintéző": "Utolsó oldali név",
                            "Cím": "Utolsó oldali cím",
                            "Telefon": tel_m.group(1) if tel_m else "Nincs",
                            "Rendelés": rendeles
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.set_page_config(page_title="Interfood v131.4", layout="wide")
st.title("Interfood v131.4 - A Tisztító")

f = st.file_uploader("Töltsd fel a PDF-et", type="pdf")
if f:
    try:
        df = parse_menetterv_v131_4(f)
        st.success(f"Beolvasva: {len(df)} sor")
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_tisztitott.csv")
    except Exception as e:
        st.error(f"Valami elromlott: {e}")
