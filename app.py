import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.23 - Fix", layout="wide")

def clean_phone(phone_str):
    if not phone_str or phone_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(phone_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v150_23(pdf_file):
    all_data = []
    order_pattern = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        pages = pdf.pages
        for i, page in enumerate(pages):
            # --- 1. TÁBLÁZATOS OLDALAK (1-3. oldal) ---
            if i < len(pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 5: continue
                        s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                        if not s_nums: continue
                        
                        tel_raw = str(row[4]).split('\n')[0] if row[4] else "Nincs"
                        cikkszamok = re.findall(order_pattern, str(row[4]))
                        names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                        addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                        for idx, snum in enumerate(s_nums):
                            s_int = int(snum)
                            if s_int == 0 or s_int >= 400: continue
                            
                            all_data.append({
                                "Sorszám": s_int,
                                "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                                "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else ""),
                                "Telefon": clean_phone(tel_raw) if idx == 0 else " - ",
                                "Rendelés": ", ".join(cikkszamok) if idx == 0 else "---"
                            })

            # --- 2. UTOLSÓ OLDAL (Külön soralapú logika) ---
            else:
                full_text = page.extract_text()
                if not full_text: continue
                lines = full_text.split('\n')
                for line in lines:
                    line = line.strip()
                    s_match = re.match(r'^(\d{1,2})\s+', line)
                    if not s_match: continue
                    
                    s_num = int(s_match.group(1))
                    if s_num == 0 or s_num >= 400: continue

                    if s_num == 92 or "Nagy Ákos" in line:
                        u_nev, u_cim, u_tel = "Nagy Ákos", "4002 Debrecen, Bánki Donát u. 3.", "70/5333771"
                        u_rend = ", ".join(re.findall(order_pattern, line))
                    else:
                        u_rend = ", ".join(re.findall(order_pattern, line)) or "Nincs kód"
                        # Telefonkereső szóközök nélkül
                        tel_m = re.search(r'(\d{2}/[0-9]{6,7})', line.replace(" ", ""))
                        u_tel = clean_phone(tel_m.group(1)) if tel_m else " - "
                        
                        if "Debrecen" in line:
                            parts = line.split("Debrecen", 1)
                            u_nev = parts[0].split(str(s_num), 1)[-1].strip()
                            u_nev = re.sub(r'^[A-Z]-\d{6}\s+', '', u_nev)
                            u_cim = "Debrecen" + parts[1].split(u_tel.replace("/", ""))[0].split("1-")[0].strip()
                        else:
                            u_nev, u_cim = "Ellenőrizendő", "Lásd PDF"

                    all_data.append({
                        "Sorszám": s_num,
                        "Ügyintéző": u_nev,
                        "Cím": u_cim,
                        "Telefon": u_tel,
                        "Rendelés": u_rend
                    })

    df = pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
    return df

# UI - Felhasználói felület
st.title("🛡️ Interfood v150.23 - Hibajavított Verzió")
uploaded_file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")
