import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v153.120 - Final Fix", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    # 1. KÓDOK TÖRLÉSE A NÉVBŐL: csak ha magányos -K vagy hasonló (szóköz után)
    name_text = raw_name.replace('–', '-').replace('—', '-')
    name_text = re.sub(r'\s+-[A-Z0-9]+\b', '', name_text)
    # A mennyiségeket (pl. 1-) ITT NEM TÖRÖLJÜK, mert az a név tisztításakor amúgy is kiesik a szám-szűrőn
    
    words = name_text.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
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

    # Név végső tisztítása: CSAK betűk maradnak, így az ottfelejtett sorszámok/mennyiségek eltűnnek
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
    # Ez a regex most már minden variációt elkap (számmal vagy anélkül)
    order_pat = r'(\b\d+-[A-Z][A-Z0-9]*|-[A-Z][A-Z0-9]*)'

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
                full_line_text = " ".join([w['text'] for w in line_words])
                
                # SORSZÁM KERESÉS: Bárhol a sor elején
                s_match = re.search(r'^(\d+)', full_line_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                # Oszlopok szétosztása
                b3, b4 = [], []
                for w in line_words:
                    x = w['x0']
                    if 150 <= x < 330: b3.append(w['text'])
                    elif 330 <= x < 480: b4.append(w['text'])

                # RENDELÉSEK: A teljes sorból szedjük ki, mielőtt bármit törölnénk!
                raw_orders = re.findall(order_pat, full_line_text)
                unique_orders = []
                seen = set()
                total_qty = 0
                for o in raw_orders:
                    clean_o = o.strip()
                    if clean_o not in seen:
                        unique_orders.append(clean_o)
                        seen.add(clean_o)
                        qty_match = re.match(r'^(\d+)-', clean_o)
                        total_qty += int(qty_match.group(1)) if qty_match else 1

                u_nev, u_cim = process_name_and_address(" ".join(b4), " ".join(b3))
                u_code_m = re.search(customer_code_pat, full_line_text)
                u_code = u_code_m.group(0) if u_code_m else ""
                t_m = re.search(r'\d{2}/\d{6,7}', full_line_text.replace(" ",""))
                u_tel = clean_phone(t_m.group(0)) if t_m else " - "

                if u_nev or u_code: # Csak ha van értékelhető adat
                    all_data.append({
                        "Sorszám": s_id,
                        "Ügyfélkód": u_code,
                        "Ügyintéző": u_nev,
                        "Cím": u_cim,
                        "Telefon": u_tel,
                        "Rendelés": ", ".join(unique_orders) or "---",
                        "Összesen": f"{total_qty} db"
                    })

    df = pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
    return df[df['Sorszám'] > 0] # A biztonság kedvéért a 0-ás sorokat eldobjuk

st.title("🛡️ Interfood v153.120 - Final Fix")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 Letöltés", df.to_csv(index=False).encode('utf-8-sig'), "interfood_final.csv")
