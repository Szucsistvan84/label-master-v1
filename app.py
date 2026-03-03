import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v152.00", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v152(pdf_file):
    all_data = []
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    customer_code_pat = r'([PZ]-\d{5,7})'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A pdfplumber 'extract_table' funkciója pont ezeket a "blokkokat" különíti el
            # függetlenül attól, hogy van-e látható vonal vagy nincs
            table = page.extract_table({
                "vertical_strategy": "text", 
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
            })
            
            if not table: continue

            for row in table:
                # Tisztítás: csak azokat a sorokat nézzük, amik sorszámmal kezdődnek
                if not row or not str(row[0]).strip().isdigit():
                    continue
                
                # A Te példád alapján a blokkok kiosztása:
                # [0]: Sorszám ("99")
                # [1]: Ügyfélkód + szemét ("P-418503 Mister Minit...")
                # [2]: Teljes cím ("4026 Debrecen, Péterfia u. 18.")
                # [3]: Ügyintéző ("Batiz Zoltán") -> EZ NAGYON KELL!
                # [4]: Telefon és Rendelés ("52/537369 0 Ft 1-L1K...")
                # [5]: Összeg/Egyéb ("2")

                try:
                    s_id = int(str(row[0]).strip())
                    if s_id >= 400: continue # Fejléc/Lábléc szűrés

                    # 2. blokkból csak az ügyfélkód
                    c_code_match = re.search(customer_code_pat, str(row[1]))
                    u_code = c_code_match.group(0) if c_code_match else ""

                    # 3. blokk a teljes cím
                    u_cim = str(row[2]).replace("\n", " ").strip()

                    # 4. blokk az ügyintéző (Név)
                    u_nev = str(row[3]).replace("\n", " ").strip()

                    # 5. blokkból telefon és rendelés (a már jól működő regexekkel)
                    cell_5 = str(row[4])
                    t_m = re.search(r'\d{2}/\d{6,7}', cell_5.replace(" ",""))
                    u_tel = clean_phone(t_m.group(0)) if t_m else " - "
                    
                    u_rend = ", ".join(dict.fromkeys(re.findall(order_pat, cell_5))) or "---"

                    all_data.append({
                        "Sorszám": s_id,
                        "Ügyfélkód": u_code,
                        "Ügyintéző": u_nev,
                        "Cím": u_cim,
                        "Telefon": u_tel,
                        "Rendelés": u_rend
                    })
                except:
                    continue

    df = pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
    return df

# UI
st.title("🚀 Interfood v152.00 - Blokk-alapú feldolgozás")
st.markdown("Ez a verzió a megadott 6 blokkos felépítés szerint szedi szét az adatokat.")

f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = parse_interfood_v152(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_vegleges.csv")
