import streamlit as st
import pdfplumber
import pandas as pd
import re

# Streamlit oldal konfigurációja
st.set_page_config(page_title="Interfood v153.80 - The Neutralizer", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    # 1. SZUPER-KÖTŐJEL SZŰRŐ: Minden típusú kötőjelet (-, –, —) egységesítünk
    normalized_name = raw_name.replace('–', '-').replace('—', '-')
    
    # Kódok (pl. -K, -SP, -DKM) törlése a névből
    normalized_name = re.sub(r'\s*-[A-Z0-9]+\b', '', normalized_name)
    
    words = normalized_name.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        # 2. Egybetűs szűrő (pl. "a" névelő ellen)
        if len(word) == 1:
            if word == 'É':
                clean_name_words.append(word)
            else:
                moved_to_address.append(word)
            continue

        clean_word_comp = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]', '', word).lower()

        # 3. Kulcsszavak és cégnevek címbe mozgatása
        if clean_word_comp in [x.lower() for x in to_move] or (word.isupper() and 2 <= len(word) <= 4):
            moved_to_address.append(word)
            continue

        # 4. Kisbetűs szavak szűrése
        if len(word) > 0 and word[0].islower():
            if (word.capitalize() + "." not in allowed_prefixes):
                moved_to_address.append(word)
                continue
            
        clean_name_words.append(word)

    # 5. Név végső formázása
    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    
    # Prefix pontok kezelése
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')
    
    # 6. Biztonsági öv: "a " vagy "A " törlése a név elejéről
    final_name = re.sub(r'^[aA]\s+', '', final_name).strip()

    # Cím összeállítása
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name, final_addr

def parse_interfood(pdf_file):
    all_data = []
    customer_code_pat = r'([HKSCPZ]-\d{5,7})'
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
                line_words = sorted
