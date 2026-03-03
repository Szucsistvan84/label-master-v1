import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v150.28 - Univerzális", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v150_28(pdf_file):
    all_data = []
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    zip_pat = r'(?<!\d)([1-9]\d{3})(?!\d)' # Pontosan 4 jegyű szám, ami nem sorszám

    with pdfplumber.open(pdf_file) as pdf:
        pages = pdf.pages
        for i, page in enumerate(pages):
            # --- 1. OLDALAK (TÁBLÁZATOS) ---
            if i < (len(pages) - 1):
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                for row in table:
                    if not row or len(row) < 5: continue
                    s_nums = [s.strip() for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue
                    
                    tel_raw = str(row[4]).split('\n')[0] if row[4] else "Nincs"
                    orders = re.findall(order_pat, str(row[4]))
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    addrs = [a.strip() for a in str(row[2]).split('\n') if a.strip()]

                    for idx, snum in enumerate(s_nums):
                        s_int = int(snum)
                        if s_int == 0 or s_int >= 400: continue
                        all_data.append({
                            "Sorszám": s_int,
                            "Ügyintéző": names[idx] if idx < len(names) else (names[0] if names else "Nincs név"),
                            "Cím": addrs[idx] if idx < len(addrs) else (addrs[0] if addrs else "Nincs cím"),
                            "Telefon": clean_phone(tel_raw) if idx == 0 else " - ",
                            "Rendelés": ", ".join(orders) if idx == 0 else "---"
                        })
            
            # --- UTOLSÓ OLDAL (SORALAPÚ + ZIP FÓKUSZ) ---
            else:
                raw_t = page.extract_text()
                if not raw_t: continue
                for line in raw_t.split('\n'):
                    l_str = line.strip()
                    m_obj = re.match(r'^(\d{1,3})\s+', l_str)
                    if not m_obj: continue
                    
                    s_id = int(m_obj.group(1))
                    if s_id == 0 or s_id >= 400: continue

                    # Alapértelmezett értékek adatmentéshez
                    u_n, u_c, u_t, u_r = "Lásd PDF", l_str, " - ", "Nincs kód"

                    # 1. Rendelés és Telefon kinyerése
                    u_r = ", ".join(re.findall(order_pat, l_str)) or "Nincs kód"
                    t_search = re.search(r'(\d{2}/[0-9]{6,7})', l_str.replace(" ", ""))
                    u_t = clean_phone(t_search.group(1)) if t_search else " - "

                    # 2. Elválasztás Irányítószám (ZIP) alapján
                    zip_found = re.search(zip_pat, l_str)
                    if zip_found:
                        zip_start = zip_found.start()
                        # Név: sorszám után, ZIP előtt (P-kód mentesítve)
                        name_part = l_str[:zip_start].replace(str(s_id), "", 1).strip()
                        u_n = re.sub(r'^[A-Z]-\d{6}\s+', '', name_part)
                        
                        # Cím: ZIP-től a telefonig vagy rendelésig
                        addr_part = l_str[zip_start:]
                        # Levágjuk a végét (telefon, rendelés, összegek)
                        clean_addr = addr_part.split(u_t.replace("/", ""))[0]
                        for code in re.findall(order_pat, clean_addr):
                            clean_addr = clean_addr.split(code)[0]
                        u_c = clean_addr.strip().rstrip(',')

                    all_data.append({
                        "Sorszám": s_id, "Ügyintéző": u_n, "Cím": u_c, "Telefon": u_t, "Rendelés": u_r
                    })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# UI
st.title("🌍 Interfood v150.28 - Országos Verzió")
st.info("A felismerés irányítószám-alapú, így bármely magyar városnál működik.")

f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = parse_interfood_v150_28(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_export.csv")
