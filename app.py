import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v152.20 - Virtual Lines", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == "Nincs": return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    if len(nums) > 11:
        nums = nums[:11] if nums.startswith(('06', '36')) else nums[:9]
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v152_20(pdf_file):
    all_data = []
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'
    customer_code_pat = r'([PZ]-\d{5,7})'
    
    # EZEK A VIRTUÁLIS VONALAK (x koordináták pixelben)
    # A PDF szélessége általában ~600 pont. Ezeket a határokat a Te PDF-edhez lőttem be:
    v_lines = [35, 75, 260, 410, 540] 

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Itt "rajzoljuk be" a vonalakat az explicit_vertical_lines paraméterrel
            table = page.extract_table({
                "vertical_strategy": "explicit", 
                "explicit_vertical_lines": v_lines,
                "horizontal_strategy": "text",
                "snap_tolerance": 3,
            })
            
            if not table: continue

            for row in table:
                # Csak sorszámmal kezdődő sorokat dolgozunk fel
                if not row or not str(row[0]).strip().replace('\n','').isdigit():
                    continue
                
                try:
                    # 1. blokk: Sorszám
                    s_id = int(str(row[0]).strip())
                    if s_id >= 400: continue

                    # 2. blokk: Ügyfélkód (Csak a kódot tartjuk meg)
                    c_code_match = re.search(customer_code_pat, str(row[1]))
                    u_code = c_code_match.group(0) if c_code_match else ""

                    # 3. blokk: Cím (Változatlanul)
                    u_cim = str(row[2]).replace("\n", " ").strip()

                    # 4. blokk: Ügyintéző (Ami neked nagyon kell!)
                    u_nev = str(row[3]).replace("\n", " ").strip()

                    # 5. blokk: Telefon és Rendelés
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

st.title("🛡️ Interfood v152.20 - Virtuális Vonalakkal")
st.info("Ez a verzió kényszerített oszlophatárokat használ, így a nevek nem csúsznak át a címbe.")

f = st.file_uploader("Menetterv PDF", type="pdf")
if f:
    df = parse_interfood_v152_20(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_virtual.csv")
