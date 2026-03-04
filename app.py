import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v152.95 - Final", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    # Kibővített szűrőlista
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    # Először szétvágjuk, de letakarítjuk a "szemetet" minden szóról
    words = raw_name.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        # Teljesen letakarított verzió az ellenőrzéshez
        clean_word_comp = re.sub(r'[^a-zA-Z]', '', word).lower()
        
        # 1. Ételkód töredék szűrése (pl. "-SP")
        if re.match(r'^-[A-Z0-9]+$', word):
            continue
            
        # 2. Vámház check: ha a tiszta szó benne van a listában
        if clean_word_comp in [x.lower() for x in to_move]:
            moved_to_address.append(word)
            continue

        # 3. Szigorú cégnév/junk szűrő (csupa nagybetű 2-4 karakter, pl. LGM)
        if word.isupper() and 2 <= len(word) <= 4:
            moved_to_address.append(word)
            continue

        # 4. Kisbetűs szemét (pl. "a", "lp")
        if word[0].islower() and (word.capitalize() + "." not in allowed_prefixes):
            moved_to_address.append(word)
            continue
            
        # Ha minden teszten átment, akkor ez név
        clean_name_words.append(word)

    # Név végső formázása
    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')
    final_name = " ".join(final_name.split()) # Dupla szóközök ki

    # Cím összerakása
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name.strip(), final_addr

# ... (A parse_interfood függvény ugyanaz marad, mint az v152.90-ben)
