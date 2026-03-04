import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v152.30 - Fix Blokk", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def parse_interfood_v152_30(pdf_file):
    all_data = []
    customer_code_pat = r'([PZ]-\d{5,7})'
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Kivonjuk a szavakat pozícióval
            words = page.extract_words()
            
            # Sorokba rendezzük (y koordináta alapján)
            lines = {}
            for w in words:
                y = round(w['top'], 1) 
                found = False
                for existing_y in lines:
                    if abs(y - existing_y) < 3: # 3 pixel tűrés egy soron belül
                        lines[existing_y].append(w)
                        found = True
                        break
                if not found: lines[y] = [w]

            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                
                # Meghatározzuk a 6 blokkot vízszintes pozíció (x0) alapján
                # Ezek az értékek a PDF standard szélességéhez (595 pt) vannak igazítva
                b1, b2, b3, b4, b5 = [], [], [], [], []
                
                for w in line_words:
                    x = w['x0']
                    if x < 45: b1.append(w['text'])       # 1. blokk: Sorszám
                    elif x < 150: b2.append(w['text'])    # 2. blokk: Ügyfél / Kód
                    elif x < 330: b3.append(w['text'])    # 3. blokk: Cím
                    elif x < 450: b4.append(w['text'])    # 4. blokk: Ügyintéző (A NÉV!)
                    else: b5.append(w['text'])            # 5. blokk: Tel/Rendelés
                
                s_id_str = "".join(b1).strip()
                if not s_id_str.isdigit(): continue
                
                s_id = int(s_id_str)
                if s_id >= 400: continue

                # 2. blokk: Csak a kód
                u_code = "".join(re.findall(customer_code_pat, " ".join(b2)))
                
                # 3. blokk: Cím (Irányítószám + Utca)
                u_cim = " ".join(b3).strip()
                
                # 4. blokk: Ügyintéző (Ez az a blokk, amit kértél!)
                u_nev = " ".join(b4).strip()
                
                # 5. blokk: Telefon és Rendelés
                b5_str = " ".join(b5)
                t_m = re.search(r'\d{2}/\d{6,7}', b5_str.replace(" ",""))
                u_tel = clean_phone(t_m.group(0)) if t_m else " - "
                u_rend = ", ".join(dict.fromkeys(re.findall(order_pat, b5_str))) or "---"

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": u_tel,
                    "Rendelés": u_rend
                })

    if not all_data:
        return pd.DataFrame(columns=["Sorszám", "Ügyfélkód", "Ügyintéző", "Cím", "Telefon", "Rendelés"])
    
    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v152.30 - Fix Blokk Verzió")
f = st.file_uploader("Feltöltés", type="pdf")
if f:
    df = parse_interfood_v152_30(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_fix.csv")
    else:
        st.error("Nem sikerült adatot kinyerni. Ellenőrizd a PDF-et!")
