import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v151.40 - Final Fix", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v151_40(pdf_file):
    all_data = []
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    customer_code_pat = r'([PZ]-\d{5,7})'
    zip_pat = r'(\d{4})'

    with pdfplumber.open(pdf_file) as pdf:
        pages = pdf.pages
        for i, page in enumerate(pages):
            # --- 1-3. OLDAL: TÁBLÁZAT ---
            if i < len(pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or len(row) < 2: continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue

                    # RENDELÉS: Az egész sorban keresünk (biztos ami biztos)
                    full_row_text = " ".join([str(x) for x in row])
                    orders = re.findall(order_pat, full_row_text)
                    order_str = ", ".join(dict.fromkeys(orders))
                    
                    # TELEFON: szintén az egész sorból
                    tel_match = re.search(r'\d{2}/\d{6,7}', full_row_text.replace(" ",""))
                    tel_final = clean_phone(tel_match.group(0)) if tel_match else " - "

                    # ÜGYFÉLKÓD
                    cust_codes = re.findall(customer_code_pat, str(row[1]))
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                    for idx, snum in enumerate(s_nums):
                        s_int = int(snum)
                        if s_int >= 400: continue
                        all_data.append({
                            "Sorszám": s_int,
                            "Ügyfélkód": cust_codes[idx] if idx < len(cust_codes) else (cust_codes[0] if cust_codes else ""),
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                            "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else ""),
                            "Telefon": tel_final if idx == 0 else " - ",
                            "Rendelés": order_str if idx == 0 else "---"
                        })

            # --- 4. OLDAL: SORALAPÚ ---
            else:
                text = page.extract_text()
                if not text: continue
                for line in text.split('\n'):
                    l = line.strip()
                    m = re.match(r'^(\d{1,3})\s+', l)
                    if not m: continue
                    sid = int(m.group(1))
                    if sid >= 400: continue

                    u_code = "".join(re.findall(customer_code_pat, l))
                    u_r = ", ".join(re.findall(order_pat, l)) or "---"
                    t_m = re.search(r'(\d{2}/[0-9]{6,7})', l.replace(" ", ""))
                    u_t = clean_phone(t_m.group(0)) if t_m else " - "

                    zip_m = re.search(zip_pat, l)
                    if zip_m:
                        # NÉV: Sorszám és Irányítószám között, kód nélkül
                        name_area = l[m.end():zip_m.start()].replace(u_code, "").replace("/", "").strip()
                        # Tisztítás a felesleges szóközöktől és "Kft"-től a név elején
                        u_n = name_area.split("Kft")[-1].split("kft")[-1].strip()
                        
                        # CÍM: Irányítószámtól a telefonig
                        addr_area = l[zip_m.start():]
                        u_c = addr_area.split(u_t.replace("/",""))[0].split("1-")[0].strip()
                    else:
                        u_n, u_c = "Ellenőrizendő", l

                    all_data.append({
                        "Sorszám": sid, "Ügyfélkód": u_code, "Ügyintéző": u_n, "Cím": u_c, "Telefon": u_t, "Rendelés": u_r
                    })

    df = pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
    return df

st.title("🛡️ Interfood v151.40 - Final Fix")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood_v151_40(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_javitott_v40.csv")
