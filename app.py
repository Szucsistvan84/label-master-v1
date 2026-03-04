import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v152.40 - Polír", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def clean_name(name_str):
    """Tisztítja a nevet: tiltott karakterek és prefixumok kezelése"""
    if not name_str: return ""
    # Csak betűk, szóköz, kötőjel és pont maradhat (vessző és számok repülnek)
    cleaned = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', name_str)
    
    # Pontok kezelése: csak a megengedett előtagoknál maradhat meg a pont
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.']
    # Ideiglenesen elmentjük a pontokat a prefixekben
    for pref in allowed_prefixes:
        cleaned = cleaned.replace(pref, pref.replace('.', '___'))
    
    # Minden egyéb pontot törlünk
    cleaned = cleaned.replace('.', '')
    
    # Visszatesszük a prefixek pontjait
    cleaned = cleaned.replace('___', '.')
    return cleaned.strip()

def clean_address(addr_str):
    """Cím tisztítása: mindent vágunk az irányítószám (4 számjegy) elől"""
    zip_match = re.search(r'(\d{4})', addr_str)
    if zip_match:
        return addr_str[zip_match.start():].strip()
    return addr_str.strip()

def parse_interfood_v152_40(pdf_file):
    all_data = []
    customer_code_pat = r'([PZ]-\d{5,7})'
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1) 
                found = False
                for existing_y in lines:
                    if abs(y - existing_y) < 3:
                        lines[existing_y].append(w)
                        found = True
                        break
                if not found: lines[y] = [w]

            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                b1, b2, b3, b4, b5 = [], [], [], [], []
                
                for w in line_words:
                    x = w['x0']
                    if x < 45: b1.append(w['text'])
                    elif x < 150: b2.append(w['text'])
                    elif x < 330: b3.append(w['text'])
                    elif x < 450: b4.append(w['text'])
                    else: b5.append(w['text'])
                
                s_id_str = "".join(b1).strip()
                if not s_id_str.isdigit(): continue
                s_id = int(s_id_str)
                if s_id >= 400: continue

                u_code = "".join(re.findall(customer_code_pat, " ".join(b2)))
                
                # CÍM ÉS NÉV TISZTÍTÁSA AZ ÚJ FÜGGVÉNYEKKEL
                u_cim = clean_address(" ".join(b3))
                u_nev = clean_name(" ".join(b4))
                
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

st.title("🛡️ Interfood v152.40 - Polír Verzió")
st.markdown("Tisztított nevek (számok/vesszők nélkül) és irányítószámmal induló címek.")

f = st.file_uploader("Feltöltés", type="pdf")
if f:
    df = parse_interfood_v152_40(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_polir.csv")
