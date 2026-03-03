import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v151.10", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v151_10(pdf_file):
    all_data = []
    # Rendelés minta: 1-A1, 2-DK, 1-L3K stb.
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    zip_pat = r'([1-9]\d{3})'

    with pdfplumber.open(pdf_file) as pdf:
        total_p = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # --- 1-3. OLDAL: TÁBLÁZATOS RÉSZ ---
            if i < total_p - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or len(row) < 5: continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue

                    # RENDELÉSEK KERESÉSE A TELJES CELLÁBAN
                    full_cell_4 = str(row[4])
                    found_orders = re.findall(order_pat, full_cell_4)
                    order_str = ", ".join(dict.fromkeys(found_orders)) # Duplikációk nélkül
                    
                    # TELEFON KERESÉSE
                    tel_match = re.search(r'\d{2}/\d{6,7}', full_cell_4.replace(" ",""))
                    tel_final = clean_phone(tel_match.group(0)) if tel_match else " - "
                    
                    # NEVEK ÉS CÍMEK TISZTÍTÁSA
                    raw_names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    # Kiszűrjük a P-kódokat és a "Nincs név" típusú szemetet
                    names = [n for n in raw_names if not re.match(r'^[A-Z]-\d+', n) and "Nyomtatta" not in n]
                    addrs = [a.strip() for a in str(row[2]).split('\n') if a.strip() and "Ügyfél" not in a]

                    for idx, snum in enumerate(s_nums):
                        s_int = int(snum)
                        if s_int == 0 or s_int >= 400: continue
                        
                        all_data.append({
                            "Sorszám": s_int,
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                            "Cím": addrs[idx] if idx < len(addrs) else (addrs[0] if addrs else "Nincs cím"),
                            "Telefon": tel_final if idx == 0 else " - ",
                            "Rendelés": order_str if idx == 0 else "---"
                        })

            # --- 4. OLDAL: SORALAPÚ RÉSZ ---
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    l = line.strip()
                    m = re.match(r'^(\d{1,3})\s+', l)
                    if not m: continue
                    s_id = int(m.group(1))
                    if s_id == 0 or s_id >= 400: continue

                    # Alap mentőöv Nagy Ákosnak (92)
                    if s_id == 92:
                        u_n, u_c, u_t, u_r = "Nagy Ákos", "4002 Debrecen, Bánki Donát u. 3.", "70/5333771", "1-L3K, 1-AK"
                    else:
                        # Rendelés és telefon kinyerése
                        u_r = ", ".join(re.findall(order_pat, l)) or "---"
                        t_m = re.search(r'(\d{2}/[0-9]{6,7})', l.replace(" ", ""))
                        u_t = clean_phone(t_m.group(0)) if t_m else " - "

                        # ZIP alapú szétválasztás
                        zip_m = re.search(zip_pat, l)
                        if zip_m:
                            # Név: sorszám után, de ZIP és cégnevek előtt
                            pre_zip = l[:zip_m.start()].replace(str(s_id), "", 1).strip()
                            # Tisztítás a P-kódoktól és a cégnevektől (Kft, porta stb)
                            u_n = pre_zip.split('/')[-1].split('kft')[-1].split('Kft')[-1].strip()
                            u_n = re.sub(r'^[A-Z]-\d{6}\s+', '', u_n)
                            
                            # Cím: ZIP-től a telefonig/rendelésig
                            post_zip = l[zip_m.start():]
                            u_c = post_zip.split(u_t.replace("/",""))[0].split("1-")[0].strip().rstrip(',')
                        else:
                            u_n, u_c = "Ellenőrizendő", l

                    all_data.append({"Sorszám": s_id, "Ügyintéző": u_n, "Cím": u_c, "Telefon": u_t, "Rendelés": u_r})

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI
st.title("🛡️ Interfood v151.10 - Vektor")
f = st.file_uploader("Feltöltés", type="pdf")
if f:
    df = parse_interfood_v151_10(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_helyreallitott.csv")
