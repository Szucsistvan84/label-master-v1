import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.12 - Teljes & Javított", layout="wide")

def parse_interfood_v150_12(pdf_file):
    all_data = []
    # Szigorú cikkszám minta (szám-betű)
    order_pattern = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            # 1. TÁBLÁZATOS OLDALAK (1-88)
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 3: continue
                        s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit() and int(s.strip()) > 0]
                        if not s_nums: continue
                        
                        full_text = " ".join([str(c) for c in row if c])
                        cikkszamok = re.findall(order_pattern, full_text)
                        tel_m = re.search(r'(\d{2}/\d{6,7})', full_text)
                        
                        names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                        addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                        for idx, snum in enumerate(s_nums):
                            all_data.append({
                                "Sorszám": int(snum),
                                "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                                "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else ""),
                                "Telefon": tel_m.group(1) if tel_m and idx == 0 else ("Nincs" if idx == 0 else ""),
                                "Rendelés": ", ".join(cikkszamok) if idx == 0 else "---"
                            })

            # 2. UTOLSÓ OLDAL (Szeletelés + 92-es mentőöv)
            else:
                text = page.extract_text()
                if not text: continue
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    match = re.search(r'^(\d{1,3})\s+', line)
                    
                    # Ha nincs sorszám az elején, de "ügyfélszerű", sorszám nélkül rögzítjük (None)
                    s_num = int(match.group(1)) if match and int(match.group(1)) > 0 else None
                    
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    cikkszamok = re.findall(order_pattern, line)
                    
                    # Név és cím szeletelés
                    cim_v, nev_v = "Lásd PDF", "Nincs név"
                    if irsz_m and tel_m:
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        for ut in ut_list:
                            pos = koztes.lower().find(ut.lower())
                            if pos != -1:
                                ut_vege = pos + len(ut)
                                parts = koztes[ut_vege:].strip().split(' ')
                                hsz, nevek = [], []
                                found_name = False
                                for p in parts:
                                    if (p and p[0].isupper() and not any(c.isdigit() for c in p)) or found_name:
                                        found_name = True
                                        nevek.append(p)
                                    else: hsz.append(p)
                                cim_v = (koztes[:ut_vege].strip() + " " + " ".join(hsz)).strip()
                                nev_v = " ".join(nevek).strip()
                                break

                    all_data.append({
                        "Sorszám": s_num,
                        "Ügyintéző": nev_v,
                        "Cím": cim_v,
                        "Telefon": tel_m.group(1) if tel_m else "Nincs",
                        "Rendelés": ", ".join(cikkszamok) if cikkszamok else "Nincs kód"
                    })

    # --- HÉZAGPÓTLÁS (A 92-es miatt) ---
    df = pd.DataFrame(all_data)
    for idx in range(len(df)):
        if pd.isna(df.loc[idx, "Sorszám"]):
            prev = df.loc[idx-1, "Sorszám"] if idx > 0 else None
            nxt = df.loc[idx+1, "Sorszám"] if idx < len(df)-1 else None
            if prev and nxt and nxt == prev + 2:
                df.loc[idx, "Sorszám"] = prev + 1

    df = df.dropna(subset=["Sorszám"])
    df["Sorszám"] = df["Sorszám"].astype(int)
    return df.drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.title("🏆 Interfood v150.12 - A Komplett Megoldás")
st.info("Visszatértek az oszlopok, és megmaradt a 92-es sorszám is!")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df_final = parse_interfood_v150_12(f)
    st.dataframe(df_final, use_container_width=True)
    st.download_button("💾 CSV Mentése", df_final.to_csv(index=False).encode('utf-8-sig'), "interfood_rendben.csv")
