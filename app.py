import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v159.0 - Safe Guard", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == " - ": return "nincs tel. szám"
    
    # Ha van benne vessző, az már gyanús (mint a 30/728214,30/01) -> Kuka
    if ',' in str(p_str):
        return "nincs tel. szám"
    
    # Csak a számokat és a perjelet hagyjuk meg
    nums_only = re.sub(r'[^0-9/]', '', str(p_str))
    
    # Ha túl rövid (pl csak egy körzetszám maradt meg), akkor is inkább töröljük
    if len(re.sub(r'[^0-9]', '', nums_only)) < 8:
        return "nincs tel. szám"
        
    return nums_only

def process_name_and_address(raw_name, raw_addr):
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    name_text = re.sub(r'^[aA]\s+', '', raw_name.strip())
    name_text = name_text.replace('–', '-').replace('—', '-')
    
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
        if len(word) > 0 and word[0].islower() and (word.capitalize() + "." not in allowed_prefixes):
            moved_to_address.append(word)
            continue
        clean_name_words.append(word)

    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name.strip(), final_addr

def parse_interfood(pdf_file):
    all_data = []
    # Szigorú rendelés minta: szám-betűk és opcionális * vagy +
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                found = False
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w)
                        found = True
                        break
                if not found: lines[y] = [w]

            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                full_line_text = " ".join([w['text'] for w in line_words])
                
                # Sorszám keresés a sor elején
                s_match = re.search(r'^(\d+)', full_line_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                # Telefonszám kinyerése MIELLŐTT a ragasztás történne
                # Keressük a tipikus 06/ vagy 20/ 30/ 70/ mintát
                tel_match = re.search(r'(\d{2}/\d{6,7}(?:,\d{2}/\d{2,7})?)', full_line_text.replace(" ", ""))
                raw_tel = tel_match.group(0) if tel_match else " - "
                final_tel = clean_phone(raw_tel)

                # --- RENDELÉS KEZELÉS ---
                # Ha a telefonszám "nincs tel. szám", akkor a sorból töröljük a gyanús töredékeket
                search_text = full_line_text
                if final_tel == "nincs tel. szám" and tel_match:
                    search_text = search_text.replace(tel_match.group(0), " ")

                # Összeragasztjuk a szétcsúszott kódokat (pl "1 - M" -> "1-M")
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', search_text)
                
                found_orders = re.findall(order_pat, search_text)
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    qty = int(re.match(r'^(\d+)', o).group(1))
                    if qty < 20: # Védelem a belecsúszó egyéb számok ellen
                        if o not in clean_orders:
                            clean_orders.append(o)
                            total_qty += qty

                if total_qty == 0: continue

                # Oszlopok (Ügyintéző és Cím hely
