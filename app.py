import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v153.110 - The Guardian", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    # 1. KÖTŐJELEK EGYSÉGESÍTÉSE
    name_text = raw_name.replace('–', '-').replace('—', '-')
    
    # 2. RENDELÉSKÓDOK ELTÁVOLÍTÁSA A NÉVBŐL (hogy ne maradjon ott pl. -K)
    # Csak a szóköz utáni kötőjeles kódokat bántjuk
    name_text = re.sub(r'\s+-[A-Z0-9]+\b', '', name_text)
    
    words = name_text.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        # Egybetűs szűrő (Árpád "a" betűje)
        if len(word) == 1:
            if word == 'É': clean_name_words.append(word)
            else: moved_to_address.append(word)
            continue

        clean_word_comp = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]', '', word).lower()
        
        # Kulcsszavak és cégnevek (LGM stb.)
        if clean_word_comp in [x.lower() for x in to_move] or (word.isupper() and 2 <= len(word) <= 4):
            moved_to_address.append(word)
            continue

        # Kisbetűs szavak (ha nem prefix)
        if len(word) > 0 and word[0].islower():
            if (word.capitalize() + "." not in allowed_prefixes):
                moved_to_address.append(word)
                continue
        
        clean_name_words.append(word)

    # Név összeállítása (Számokat ITT töröljük, de a rendelés ekkor már biztonságban van máshol!)
    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')
    final_name = re.sub(r'^[aA]\s+', '', final_name).strip()

    # Cím
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name, final_addr

def parse_interfood(pdf_file):
    all_data = []
    customer_code_pat = r'([HKSCPZ]-\d{5,7})'
    # Ez a regex most már nagyon figyel a mennyiségekre:
    order_pat = r'(\d+-\s?[A-Z][A-Z0-9]*|-[A-Z][A-Z0-9]*)'

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
                b3, b4 = [], []
                full_line_text = " ".join([w['text'] for w in line_words])
                
                # Sorszám ellenőrzése
                s_match = re.match(r'^(\d+)', line_words[0]['text']) if line_words else None
                if not s_match: continue
                s_id = int(s_match.group(1))

                for w in line_words:
                    x = w['x0']
                    if 160 <= x < 330: b3.append(w['text'])
                    elif 330 <= x < 460: b4.append(w['text'])

                # 1. ELŐSZÖR A RENDELÉSTMENTJÜK KI A NYERS SZÖVEGBŐL
                raw_orders = re.findall(order_pat, full_line_text)
                unique_orders = []
                seen = set()
                for o in raw_orders:
                    clean_o = o.replace(" ", "")
                    if clean_o not in seen:
                        unique_orders.append(clean_o)
                        seen.add(clean_o)

                # 2. DARABSZÁM SZÁMÍTÁSA
                total_qty = 0
                for order in unique_orders:
                    qty_match = re.match(r'^(\d+)-', order)
                    total_qty += int(qty_match.group(1)) if qty_match else 1

                # 3. CSAK EZUTÁN TISZTÍTJUK A NEVET
                u_nev, u_cim = process_name_and_address(" ".join(b4), " ".join(b3))
                
                u_code_m = re.search(customer_code_pat, full_line_text)
                u_code = u_code_m.group(0) if u_code_m else ""
                
                t_m = re.search(r'\d{2}/\d{6,7}', full_line_text.replace(" ",""))
                u_tel = clean_phone(t_m.group(0)) if t_m else " - "

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": u_tel,
                    "Rendelés": ", ".join(unique_orders) or "---",
                    "Összesen": f"{total_qty} db"
                })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v153.110 - The Guardian")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 Letöltés (CSV)", csv, "interfood_guardian.csv", "text/csv")
