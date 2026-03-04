import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v152.90 - Penge", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    # Kibővített és szigorított lista
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    words = raw_name.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        # Tisztítjuk a szót az összehasonlításhoz
        clean_word_comp = word.strip(',./- ').lower()
        
        # 1. Ételkód töredék szűrése (pl. "-SP")
        if re.match(r'^-[A-Z0-9]+$', word):
            continue
            
        # 2. Ellenőrizzük, hogy a szó a "vámház" listáján van-e
        is_addr_element = clean_word_comp in [x.lower() for x in to_move]
        
        # 3. Speciális szabályok: csupa nagybetűs rövidítés VAGY kisbetűs kezdet (ami nem prefix)
        is_corporate = word.isupper() and 2 <= len(word) <= 4
        is_lowercase_junk = word[0].islower() and (word.capitalize() + "." not in allowed_prefixes)
        
        if is_addr_element or is_corporate or is_lowercase_junk:
            moved_to_address.append(word)
        else:
            clean_name_words.append(word)

    # Név véglegesítése
    final_name = " ".join(clean_name_words)
    # Csak betűk és kötőjel maradhat
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    
    # Prefixek védelme
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')

    # Cím összerakása (Irányítószám + a névből áthelyezett részek)
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f
