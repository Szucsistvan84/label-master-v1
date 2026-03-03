import streamlit as st
import pdfplumber
import pandas as pd
import re

def extract_food_codes(text):
    """Minden ételkódot kigyűjt, ami 'szám-betűk' formátumú."""
    if not text: return "Nincs"
    codes = re.findall(r'(\d-[A-Z0-9]+(?:, \d-[A-Z0-9]+)*)', text)
    return ", ".join(codes) if codes else "Nincs"

def parse_menetterv_v131_5(pdf_file):
    all_rows = []
    ut_list = [' út', ' utca', ' útja', ' tér', ' körút', ' krt', ' u.', ' sor', ' dűlő', ' köz', ' sétány']

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # --- 1. RÉSZ: TÁBLÁZATOS OLDALAK ---
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or len(row) < 5: continue
                    s_nums = [s for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue
                    
                    # Tisztítás a Te logikád szerint
                    names = [n.strip() for n in str(row[3]).replace('\n\n\n', '\n').split('\n') if n.strip()]
                    raw_info = str(row[4]).replace('\n\n\n', '\n').replace('\n ', '\n')
                    info_lines = [l.strip() for l in raw_info.split('\n') if l.strip()]
                    
                    # Címek kinyerése
                    addr_raw = str(row[2]).replace('\n\n\n', '\n').split('\n')
                    addresses = [a.strip() for a in addr_raw if any(zip_code in a for zip_code in ['402', '403'])]

                    for idx, snum in enumerate(s_nums):
                        # Telefonszám keresése az infó blokkban
                        current_tel = "Nincs"
                        for line in info_lines:
                            if '/' in line: current_tel = line; break
                        
                        all_rows.append({
                            "Sorszám": int(snum),
                            "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                            "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else "Nincs cím"),
                            "Telefon": current_tel,
                            "Rendelés": extract_food_codes(raw_info) # Itt bányásszuk ki az ételeket!
                        })

            # --- 2. RÉSZ: UTOLSÓ OLDAL (Szeletelő visszahozása) ---
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                    if not match: continue
                    
                    s_num, kod = match.groups()
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    
                    if irsz_m and tel_m:
                        telefonszam = tel_m.group(1)
                        rendeles = line[tel_m.end():].strip()
                        rendeles = re.sub(r'\s+\d+$', '', rendeles) # Összesítő levágása
                        
                        # Cím és Név szeletelés (a v131 eredeti logikája)
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        cim_v, nev_v = koztes, "Ellenőrizni"
                        for ut in ut_list:
                            pos = koztes.lower().find(ut.lower())
                            if pos != -1:
                                ut_vege = pos + len(ut)
                                maradek = koztes[ut_vege:].strip()
                                # Szétválasztjuk a házszámot és a nevet (Nagybetűvel kezdődik a név)
                                m_nev = re.search(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+.*)', maradek)
                                if m_nev:
                                    cim_v = koztes[:ut_vege].strip() + " " + maradek[:m_nev.start()].strip()
                                    nev_v = m_nev.group(1).strip()
                                break
                        
                        all_rows.append({
                            "Sorszám": int(s_num),
                            "Kód": kod,
                            "Ügyintéző": nev_v,
                            "Cím": cim_v,
                            "Telefon": telefonszam,
                            "Rendelés": rendeles
                        })

    return pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI (Streamlit) ---
st.set_page_config(page_title="Interfood v131.5", layout="wide")
st.title("Interfood v131.5 - A Teljes Megoldás")

f = st.file_uploader("PDF fájl feltöltése", type="pdf")
if f:
    try:
        df = parse_menetterv_v131_5(f)
        st.success(f"Kész! {len(df)} sor feldolgozva.")
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 Letöltés CSV-ben", df.to_csv(index=False).encode('utf-8-sig'), "interfood_final.csv")
    except Exception as e:
        st.error(f"Hiba: {e}")
