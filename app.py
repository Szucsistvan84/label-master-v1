import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v151.30 - Teljes", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v151_30(pdf_file):
    all_data = []
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    customer_code_pat = r'([PZ]-\d{5,7})' # Ügyfélkódok: P-123456 vagy Z-123456

    with pdfplumber.open(pdf_file) as pdf:
        pages = pdf.pages
        for i, page in enumerate(pages):
            # --- TÁBLÁZATOS OLDALAK (1-3) ---
            if i < len(pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or len(row) < 5: continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue

                    # Rendelés és telefon a 4. oszlopból (minden sor!)
                    cell_content = str(row[4])
                    tel_match = re.search(r'\d{2}/\d{6,7}', cell_content.replace(" ",""))
                    tel_final = clean_phone(tel_match.group(0)) if tel_match else " - "
                    
                    orders = re.findall(order_pat, cell_content)
                    order_str = ", ".join(dict.fromkeys(orders))

                    # Ügyfél adatok (Kóddal együtt!)
                    raw_client_info = str(row[1]) # Ügyfél oszlop
                    cust_codes = re.findall(customer_code_pat, raw_client_info)
                    
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    addresses = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                    for idx, snum in enumerate(s_nums):
                        s_int = int(snum)
                        if s_int >= 400: continue
                        
                        # Ügyfélkód hozzáfűzése a névhez, ha van
                        code_prefix = cust_codes[idx] if idx < len(cust_codes) else ""
                        name_val = names[idx] if idx < len(names) else (names[0] if names else "")
                        
                        all_data.append({
                            "Sorszám": s_int,
                            "Ügyfélkód": code_prefix,
                            "Ügyintéző": name_val,
                            "Cím": addresses[idx] if idx < len(addresses) else (addresses[0] if addresses else ""),
                            "Telefon": tel_final if idx == 0 else " - ",
                            "Rendelés": order_str if idx == 0 else "---"
                        })

            # --- UTOLSÓ OLDAL (Soralapú 89-től) ---
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

                    # ZIP alapú szétválasztás
                    zip_m = re.search(r'(\d{4})', l)
                    if zip_m:
                        before_zip = l[:zip_m.start()].replace(str(sid), "", 1).strip()
                        # Név kinyerése a kód után
                        u_n = before_zip.split(u_code)[-1].replace("/", "").strip() if u_code else before_zip
                        u_c = l[zip_m.start():].split(u_t.replace("/",""))[0].split("1-")[0].strip()
                    else:
                        u_n, u_c = "Ellenőrizendő", l

                    all_data.append({
                        "Sorszám": sid, "Ügyfélkód": u_code, "Ügyintéző": u_n, "Cím": u_c, "Telefon": u_t, "Rendelés": u_r
                    })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v151.30 - Minden adat a helyén")
st.success("Ügyfélkódok (P/Z), Rendelések, Tisztított Telefonok.")

f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = parse_interfood_v151_30(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_teljes_adat.csv")
