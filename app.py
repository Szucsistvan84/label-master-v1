import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v163.0 - Precision Surgery", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == " - ": return "nincs tel. szám"
    if ',' in str(p_str): return "nincs tel. szám"
    nums_only = re.sub(r'[^0-9/]', '', str(p_str))
    if len(re.sub(r'[^0-9]', '', nums_only)) < 8: return "nincs tel. szám"
    return nums_only

def process_name_and_address(raw_name, raw_addr):
    # Radikális tisztítás
    name_clean = re.sub(r'^[ \.\,a-z0-9]+', '', raw_name.strip())
    # Levágjuk a név végére ragadt kód-töredékeket
    name_clean = re.sub(r'[ \-][A-Z0-9]$', '', name_clean)
    
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    words = name_clean.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        if len(word) == 1 and word != 'É':
            moved_to_address.append(word)
            continue
        clean_word_comp = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]', '', word).lower()
        if clean_word_comp in [x.lower() for x in to_move] or (word.isupper() and 2 <= len(word) <= 4):
            moved_to_address.append(word)
            continue
        clean_name_words.append(word)

    final_name = " ".join(clean_name_words)
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', final_name).strip()
    
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name, final_addr

def parse_interfood(pdf_file):
    all_data = []
    # Rendelés minta: darabszám(1-2 számjegy)-Kód(betűvel kezdődik)
    order_pat = r'(\d{1,2}-[A-Z][A-Z0-9*+]*)'

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
                
                s_match = re.search(r'^(\d+)', full_line_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                # --- TELEFON KIIRTÁSA A SZÖVEGBŐL ---
                # Megkeressük a telefonszám-szerűségeket
                tel_candidates = re.findall(r'(\d{2}/\d{2,7}(?:,\d{2}/\d{2,7})?)', full_line_text.replace(" ", ""))
                final_tel = "nincs tel. szám"
                search_text = full_line_text
                
                if tel_candidates:
                    # Az elsőt elmentjük (ha értelmes), a többit csak töröljük a kereséshez
                    final_tel = clean_phone(tel_candidates[0])
                    for cand in tel_candidates:
                        # Szóközökre cseréljük a telefonszámot a szövegben, hogy ne ragadjon a rendeléshez
                        pattern = re.compile(re.escape(cand), re.IGNORECASE)
                        search_text = pattern.sub('   ', search_text)

                # --- RENDELÉS KERESÉS A TISZTA SZÖVEGBEN ---
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', search_text)
                found_orders = re.findall(order_pat, search_text)
                
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    qty_parts = o.split('-')
                    qty = int(qty_parts[0])
                    # Ha a darabszám 0-val kezdődik (pl 01), de a maradék 1, akkor javítjuk
                    if qty_parts[0].startswith('0'):
                        qty = int(qty_parts[0].lstrip('0') or 0)
                        o = f"{qty}-{qty_parts[1]}"
                    
                    if 1 <= qty < 20:
                        clean_orders.append(o)
                        total_qty += qty

                # Ha van sorszám, mindenképpen rögzítjük (Julianna ne vesszen el!)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 330])
                b4 = " ".join([w['text'] for w in line_words if 330 <= w['x0'] < 480])

                u_nev, u_cim = process_name_and_address(b4, b3)
                u_code_m = re.search(r'([HKSCPZ]-\d{5,7})', full_line_text)
                u_code = u_code_m.group(0) if u_code_m else ""

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": final_tel,
                    "Rendelés": ", ".join(clean_orders) if clean_orders else "HIÁNYZIK",
                    "Összesen": f"{total_qty} db"
                })

    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v163.0 - Precision Surgery")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = parse_interfood(f)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_final.csv")
