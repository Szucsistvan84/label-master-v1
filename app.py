import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v173.0 - Szabad Rendelés", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == " - ": return "nincs tel. szám"
    nums_only = re.sub(r'[^0-9/]', '', str(p_str))
    if len(re.sub(r'[^0-9]', '', nums_only)) < 8: return "nincs tel. szám"
    return nums_only

def process_name_and_address(raw_name, raw_addr):
    # Tisztítások: kódok és szemét eltávolítása a névből
    name_clean = re.sub(r'[HS]-\d+', '', raw_name).strip()
    name_clean = re.sub(r'^[a-z \.\,]+', '', name_clean)
    name_clean = re.sub(r'\s*-\s*[A-Z0-9+*]+$', '', name_clean)

    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    words = name_clean.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        if word.isdigit() or (len(word) == 1 and word != 'É'):
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
                
                # 1. SZABÁLY: Kulcsszó-tiltás (Fejléc/Lábjegyzet elkerülése)
                if any(x in full_line_text for x in ["Nyomtatta", "Oldal:", "Összesen"]):
                    continue

                s_match = re.search(r'^(\d+)', full_line_text.strip())
                if not s_match: continue
                s_id = int(s_match.group(1))

                # 3. SZABÁLY: Ügyfélkód kényszerítése (Ez a legfontosabb szűrő)
                u_code_m = re.search(r'([HKSCPZ]-\d{5,7})', full_line_text)
                if not u_code_m: 
                    continue # Ha nincs kód, ez biztosan nem ügyfél-sor
                u_code = u_code_m.group(0)

                # Telefonszám és Rendelés kinyerése
                tel_search = re.search(r'(\d{2}/\d{6,7})', full_line_text.replace(" ", ""))
                final_tel = clean_phone(tel_search.group(0) if tel_search else " - ")

                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                found_orders = re.findall(order_pat, search_text)
                
                # Itt már NINCS tétel-limit, jöhet bármennyi kaja!
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    qty_m = re.match(r'^(\d+)', o)
                    if qty_m:
                        qty = int(qty_m.group(1))
                        # Csak a gyanúsan nagy (50+) darabszámokat korlátozzuk, 
                        # mert az valószínűleg elírás vagy koordináta-hiba
                        if qty < 50:
                            clean_orders.append(o)
                            total_qty += qty

                if total_qty == 0: continue

                # Név és cím oszlopok
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])

                u_nev, u_cim = process_name_and_address(b4, b3)

                page_data.append({
                    "Járat": pdf_file.name.replace(".pdf", "").replace("menetterv ", ""),
                    "Sorszám": s_id, "Ügyfélkód": u_code, "Ügyintéző": u_nev,
                    "Cím": u_cim, "Telefon": final_tel, "Rendelés": ", ".join(clean_orders),
                    "Összesen": f"{total_qty} db"
                })
    return page_data

# UI
st.title("🚀 Interfood v173.0 - Korlátlan Rendelés & Tiszta Lista")
uploaded_files = st.file_uploader("PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if uploaded_files:
    all_data = []
    for f in uploaded_files:
        all_data.extend(parse_interfood(f))
            
    if all_data:
        df = pd.DataFrame(all_data).sort_values(by=["Járat", "Sorszám"])
        st.dataframe(df, use_container_width=True)
        st.download_button("💾 CSV Mentése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v173.csv")
