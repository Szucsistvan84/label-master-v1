import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v122(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
        for i, page in enumerate(pdf.pages):
            is_last_page = (i == total_pages - 1)
            
            if not is_last_page:
                # 1-88 sorok (v120 logika: szigorú rácsok)
                table = page.extract_table({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines"
                })
                if table:
                    for row in table:
                        if not row or len(row) < 4: continue
                        s_raw = str(row[0]).strip()
                        sorszam_match = re.search(r'^(\d+)$', s_raw.split('\n')[0])
                        if not sorszam_match: continue
                        
                        sorszam = sorszam_match.group(1)
                        c1 = str(row[1]).strip()
                        kod_match = re.search(r'([HKSC P Z]-\d{6})', c1)
                        kod = kod_match.group(1) if kod_match else "Nincs kód"
                        
                        cim = str(row[2]).strip().replace('\n', ' ')
                        if "Ügyintéző" in cim: continue
                        
                        c4 = str(row[3]).strip()
                        nev = c4.split('\n')[0] if c4 else "Nincs név"
                        
                        all_rows.append({"Sorszám": int(sorszam), "Kód": kod, "Cím": cim, "Ügyintéző": nev})
            
            else:
                # UTOLSÓ OLDAL (89-101 sorok: szöveges keresés rácsok nélkül)
                text = page.extract_text()
                # Mintát keresünk: Sorszám, Kód+Név, Cím
                # Példa: "97 P-481578 Nagy-Zsom Zsanett 4030 Debrecen, Cser u. 6."
                lines = text.split('\n')
                for line in lines:
                    # Keressük a sorszámmal kezdődő sorokat (89-től felfelé)
                    match = re.search(r'^(\d{2,3})\s+([HKSC P Z]-\d{6})\s+(.*?)\s+(40\d{2}\s+Debrecen,.*)', line)
                    if match:
                        all_rows.append({
                            "Sorszám": int(match.group(1)),
                            "Kód": match.group(2),
                            "Cím": match.group(4).strip(),
                            "Ügyintéző": match.group(3).strip()
                        })
                    else:
                        # Másodlagos keresés, ha a név és a kód külön sorba került az utolsó oldalon
                        match_simple = re.search(r'^(\d{2,3})\s+([HKSC P Z]-\d{6})', line)
                        if match_simple:
                            # Itt egy egyszerűsített rögzítés, ha a rács szétcsúszott
                            all_rows.append({
                                "Sorszám": int(match_simple.group(1)),
                                "Kód": match_simple.group(2),
                                "Cím": "Ellenőrizendő az utolsó oldalon",
                                "Ügyintéző": "Lásd PDF"
                            })

    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám'])
    return df.sort_values("Sorszám")

st.title("Interfood v122 - Kétlépcsős adatkinyerés")
st.info("Logika: v120 rácsos mód (1-88) + Szöveges mód az utolsó oldalon (89-101)")

f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    data = parse_menetterv_v122(f)
    if not data.empty:
        st.write("### Feldolgozott adatok")
        st.dataframe(data)
        
        csv = data.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV letöltése", csv, "interfood_v122.csv", "text/csv")
    else:
        st.error("Nem sikerült adatot kinyerni.")
