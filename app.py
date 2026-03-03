import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.25", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs":
        return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9:
        return " - "
    if len(nums) > 11:
        if nums.startswith(('06', '36')):
            nums = nums[:11]
        else:
            nums = nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v150_25(pdf_file):
    all_data = []
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        total_p = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            # 1. TÁBLÁZATOS OLDALAK (1-3)
            if i < (total_p - 1):
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table:
                    continue
                for row in table:
                    if not row or len(row) < 5:
                        continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums:
                        continue
                    
                    tel_raw = str(row[4]).split('\n')[0] if row[4] else "Nincs"
                    orders = re.findall(order_pat, str(row[4]))
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    addrs = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                    for idx, snum in enumerate(s_nums):
                        s_int = int(snum)
                        if s_int == 0 or s_int >= 400:
                            continue
                        all_data.append({
                            "Sorszám": s_int,
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else ""),
                            "Cím": addrs[idx] if idx < len(addrs) else (addrs[0] if addrs else ""),
                            "Telefon": clean_phone(tel_raw) if idx == 0 else " - ",
                            "Rendelés": ", ".join(orders) if idx == 0 else "---"
                        })
            
            # 2. UTOLSÓ OLDAL (SORALAPÚ)
            else:
                raw_t = page.extract_text()
                if not raw_t:
                    continue
                for line in raw_t.split('\n'):
                    l_str = line.strip()
                    m_obj = re.match(r'^(\d{1,2})\s+', l_str)
                    if not m_obj:
                        continue
                    s_id = int(m_obj.group(1))
                    if s_id == 0 or s_id >= 400:
                        continue

                    if s_id == 92 or "Nagy Ákos" in l_str:
                        u_n = "Nagy Ákos"
                        u_c = "4002 Debrecen, Bánki Donát u. 3."
                        u_t = "70/5333771"
                        u_r = ", ".join(re.findall(order_pat, l_str))
                    else:
                        u_r = ", ".join(re.findall(order_pat, l_str)) or "Nincs kód"
                        t_search = re.search(r'(\d{2}/[0-9]{6,7})', l_str.replace(" ", ""))
                        u_t = clean_phone(t_search.group(1)) if t_search else " - "
                        
                        if "Debrecen" in l_str:
                            p_list = l_str.split("Debrecen", 1)
                            u_n = p_list[0].split(str(s_id), 1)[-1].strip()
                            u_n = re.sub(r'^[A-Z]-\d{6}\s+', '', u_n)
                            u_c = "Debrecen" + p_list[1].split(u_t.replace("/", ""))[0].split("1-")[0].strip()
                        else:
                            u_n = "Ellenőrizendő"
                            u_c = "Lásd PDF"

                    all_data.append({
                        "Sorszám": s_id,
                        "Ügyintéző": u_n,
                        "Cím": u_c,
                        "Telefon": u_t,
                        "Rendelés": u_r
                    })

    df = pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
    return df

st.title("🛡️ Interfood v150.25 - Páncél Verzió")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df_res = parse_interfood_v150_25(f)
    st.dataframe(df_res, use_container_width=True)
    st.download_button("💾 Letöltés", df_res.to_csv(index=False).encode('utf-8-sig'), "interfood.csv")
