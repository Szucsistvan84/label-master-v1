import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v152.80 - Cleaner", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    # Címbe áthelyezendő kulcsszavak (LGM is benne van)
    addr_parts = ['lph', 'lp', 'lépcsőház', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    words = raw_name.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        clean_word = word.strip(',. ')
        
        # 1. Rendelésmaradvány szűrés (pl. "-SP", "-DK")
        if re.match(r'^-[A-Z0-9]+$', word):
            continue # Ezt egyszerűen eldobjuk, mert a Rendelés oszlopban már megvan
            
        # 2. Cím-elemek és cégnév maradványok (LGM)
        is_addr_marker = clean_word.lower() in [p.lower() for p in addr_parts]
        is_lowercase_junk = word[0].islower() and word + "." not in allowed_prefixes
        is_corporate_shout = word.isupper() and len(word) >= 2 and len(word) <= 4
        is_single_letter = len(clean_word) == 1 and clean_word.lower() not in ['é']

        if is_addr_marker or is_lowercase_junk or is_corporate_shout or is_single_letter:
            moved_to_address.append(word)
        else:
            clean_name_words.append(word)

    # Név tisztítása
    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')

    # Cím összerakása
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name.strip(), final_addr

def parse_interfood_v152_80(pdf_file):
    all_data = []
    customer_code_pat = r'([HKSCPZ]-\d{5,7})'
    order_pat = r'([1-9]-\s?[A-Z][A-Z0-9]*)'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1) 
                if not any(abs(y - existing_y) < 3 for existing_y in lines):
                    lines[y] = [w]
                else:
                    for existing_y in lines:
                        if abs(y - existing_y) < 3:
                            lines[existing_y].append(w)
                            break

            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                b1, b2, b3, b4, b5 = [], [], [], [], []
                
                for w in line_words:
                    x = w['x0']
                    if x < 40: b1.append(w['text'])
                    elif x < 160: b2.append(w['text'])
                    elif x < 330: b3.append(w['text'])
                    elif x < 460: b4.append(w['text'])
                    else: b5.append(w['text'])
                
                s_id_str = "".join(b1).strip()
                if not s_id_str.isdigit(): continue
                
                full_line_text = " ".join([w['text'] for w in line_words])
                u_code_match = re.search(customer_code_pat, full_line_text)
                u_code = u_code_match.group(0) if u_code_match else ""
                
                # Feldolgozás
                u_nev, u_cim = process_name_and_address(" ".join(b4), " ".join(b3))
                
                t_m = re.search(r'\d{2}/\d{6,7}', full_line_text.replace(" ",""))
                u_tel = clean_phone(t_m.group(0)) if t_m else " - "
                u_rend = ", ".join(dict.fromkeys(re.findall(order_pat, full_line_text))) or "---"

                all_data.append({
                    "Sorszám": int(s_id_str),
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": u_tel,
                    "Rendelés": u_rend
                })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v152.80 - Cleaner")
st.markdown("Eltávolítja az SP-típusú maradványokat a névből és az LGM-et a címbe dobja.")

f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood_v152_80(f)
    st.dataframe(df, use_container_width=True)
    st.download_button("💾 Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_clean.csv")
