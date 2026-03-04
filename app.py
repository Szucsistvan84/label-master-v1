import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v155.0 - Absolute Truth", layout="wide")

def clean_phone(p_str):
    if not p_str: return " - "
    nums = re.sub(r'[^0-9]', '', str(p_str))
    if len(nums) < 9: return " - "
    return f"{nums[:2]}/{nums[2:]}"

def process_name_and_address(raw_name, raw_addr):
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    # Tisztítás
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

        if len(word) > 0 and word[0].islower():
            if (word.capitalize() + "." not in allowed_prefixes):
                moved_to_address.append(word)
                continue
        clean_name_words.append(word)

    # Végső név (számok és magányos kötőjelek nélkül)
    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')
    
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name.strip(), final_addr

def parse_interfood(pdf_file):
    all_data = []
    # SZIGORÚ REGEX: Kötelező a szám az elején! (pl. 1-M vagy 2-SP1)
    # Kezeli a szóközt is a kötőjel után: "1- M" -> "1-M"
    order_pat = r'(\d+-\s?[A-Z][A-Z0-9]*)'

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
                # Összeragasztjuk a szavakat, hogy az "1-" és az "M" találkozzon
                full_line_text = " ".join([w['text'] for w in line_words])
                # Speciális eset: ha a PDF-ben "1 - M" van, csináljunk belőle "1-M"-et a kereséshez
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                
                # Sorszám keresés
                s_match = re.search(r'^(\d+)', full_line_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                # Rendelések kinyerése a javított szövegből
                found_orders = re.findall(order_pat, search_text)
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    o_clean = o.replace(" ", "")
                    if o_clean not in clean_orders:
                        clean_orders.append(o_clean)
                        qty = int(re.match(r'^(\d+)', o_clean).group(1))
                        total_qty += qty

                # Ha nincs rendelés a sorban, átugorjuk (fejlécek kiszűrése)
                if total_qty == 0: continue

                # Oszlopok (Cím és Ügyintéző tartománya)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 330])
                b4 = " ".join([w['text'] for w in line_words if 330 <= w['x0'] < 480])

                u_nev, u_cim = process_name_and_address(b4, b3)
                
                # Ügyfélkód és Telefon
                u_code_m = re.search(r'([HKSCPZ]-\d{5,7})', full_line_text)
                u_code = u_code_m.group(0) if u_code_m else ""
                t_m = re.search(r'\d{2}/\d{6,7}', full_line_text.replace(" ",""))
                u_tel = clean_phone(t_m.group(0)) if t_m else " - "

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": u_tel,
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": f"{total_qty} db"
                })

    df = pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")
    return df

st.title("🛡️ Interfood v155.0 - Absolute Truth")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v155.csv")
