import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v153.100 - The Accurate", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    # Csak a nevet tisztítjuk, a rendeléskódokat (szám-kötőjel-betű) kíméljük
    normalized_name = raw_name.replace('–', '-').replace('—', '-')
    
    # Szigorúbb név-tisztítás: csak a magányos kódokat vesszük ki a névből
    # A regex most már figyeli, hogy ne vágjon bele a mennyiségbe
    normalized_name = re.sub(r'\s+-[A-Z0-9]+\b', '', normalized_name)
    
    words = normalized_name.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        # Egybetűs szűrő (Árpád "a" betűje)
        if len(word) == 1:
            if word == 'É': clean_name_words.append(word)
            else: moved_to_address.append(word)
            continue

        clean_word_comp = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]', '', word).lower()
        if clean_word_comp in [x.lower() for x in to_move] or (word.isupper() and 2 <= len(word) <= 4):
            moved_to_address.append(word)
            continue

        if len(word) > 0 and word[0].islower():
            if (word.capitalize() + "." not in allowed_prefixes):
                moved_to_address.append(word)
                continue
        clean_name_words.append(word)

    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')
    final_name = re.sub(r'^[aA]\s+', '', final_name).strip()

    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name, final_addr

def parse_interfood(pdf_file):
    all_data = []
    customer_code_pat = r'([HKSCPZ]-\d{5,7})'
    # Javított rendelés regex: kötelezően keresi a számot is az elején, ha van
    order_pat = r'(\d+-[A-Z][A-Z0-9]*|-[A-Z][A-Z0-9]*)'

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
                
                # A név tisztítása most már nem bántja a számokat a sor elején
                u_nev, u_cim = process_name_and_address(" ".join(b4), " ".join(b3))
                
                t_m = re.search(r'\d{2}/\d{6,7}', full_line_text.replace(" ",""))
                u_tel = clean_phone(t_m.group(0)) if t_m else " - "
                
                # Rendelések kinyerése és darabszám számítás
                raw_orders = re.findall(order_pat, full_line_text)
                # Duplikátumok kiszűrése sorrend megtartásával
                seen = set()
                unique_orders = [x for x in raw_orders if not (x in seen or seen.add(x))]
                
                total_qty = 0
                for order in unique_orders:
                    qty_match = re.match(r'^(\d+)-', order)
                    total_qty += int(qty_match.group(1)) if qty_match else 1
                
                u_rend = ", ".join(unique_orders) or "---"
                u_osszesen = f"{total_qty} db"

                all_data.append({
                    "Sorszám": int(s_id_str),
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": u_tel,
                    "Rendelés": u_rend,
                    "Összesen": u_osszesen
                })
    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v153.100 - The Accurate")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 Letöltés (CSV)", csv, "interfood_final_v100.csv", "text/csv")
