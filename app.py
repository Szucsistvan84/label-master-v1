import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v170.0 - Multi-PDF Feldolgozó", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == " - ": return "nincs tel. szám"
    nums_only = re.sub(r'[^0-9/]', '', str(p_str))
    if len(re.sub(r'[^0-9]', '', nums_only)) < 8: return "nincs tel. szám"
    return nums_only

def process_name_and_address(raw_name, raw_addr):
    # Ügyfélkód eltávolítása a névből
    name_clean = re.sub(r'[HS]-\d+', '', raw_name).strip()
    # Magányos kisbetűk/pontok az elejéről
    name_clean = re.sub(r'^[a-z \.\,]+', '', name_clean)
    # Név végére ragadt rendelés-kód (-M, -AK)
    name_clean = re.sub(r'\s*-\s*[A-Z0-9+*]+$', '', name_clean)

    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    words = name_clean.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        if word.isdigit():
            moved_to_address.append(word)
            continue
        if len(word) == 1 and word != 'É':
            moved_to_address.append(word)
            continue
        clean_word_comp = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]', '', word).lower()
        if clean_word_comp in [x.lower() for x in to_move]:
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
    page_data = []
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
                
                s_match = re.search(r'^(\d+)', full_line_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                tel_search = re.search(r'(\d{2}/\d{6,7})', full_line_text.replace(" ", ""))
                final_tel = clean_phone(tel_search.group(0) if tel_search else " - ")

                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                found_orders = re.findall(order_pat, search_text)
                
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    qty_m = re.match(r'^(\d+)', o)
                    if qty_m:
                        qty = int(qty_m.group(1))
                        if qty > 9: 
                            qty_str = str(qty)
                            qty = int(qty_str[-1])
                            o = f"{qty}-{o.split('-', 1)[1]}"
                        if qty < 50:
                            clean_orders.append(o)
                            total_qty += qty

                if total_qty == 0: continue

                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])

                u_nev, u_cim = process_name_and_address(b4, b3)
                u_code_m = re.search(r'([HKSCPZ]-\d{5,7})', full_line_text)
                u_code = u_code_m.group(0) if u_code_m else ""

                page_data.append({
                    "Forrásfájl": pdf_file.name, # Látjuk, melyik fájlból jött
                    "Sorszám": s_id, "Ügyfélkód": u_code, "Ügyintéző": u_nev,
                    "Cím": u_cim, "Telefon": final_tel, "Rendelés": ", ".join(clean_orders),
                    "Összesen": f"{total_qty} db"
                })
    return page_data

# --- Streamlit UI ---
st.title("🚀 Interfood v170.0 - Multi-PDF Daráló")
st.info("Húzz be több PDF fájlt egyszerre, és a program összefűzi őket egyetlen CSV-be!")

uploaded_files = st.file_uploader("PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if uploaded_files:
    all_extracted_data = []
    
    with st.spinner(f'{len(uploaded_files)} fájl feldolgozása folyamatban...'):
        for f in uploaded_files:
            data = parse_interfood(f)
            all_extracted_data.extend(data)
            
    if all_extracted_data:
        df = pd.DataFrame(all_extracted_data)
        # Rendezés: először fájlnév, aztán sorszám szerint
        df = df.sort_values(by=["Forrásfájl", "Sorszám"])
        
        st.success(f"Kész! Összesen {len(df)} sor kinyerve.")
        st.dataframe(df, use_container_width=True)
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 Összesített CSV Mentése", csv, "interfood_osszesitett.csv")
