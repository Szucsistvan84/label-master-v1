import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import Counter

st.set_page_config(page_title="Interfood v180.0 - A Tökéletesített", layout="wide")

def clean_phone(p_str):
    if not p_str or p_str == " - ": return "nincs tel. szám"
    nums_only = re.sub(r'[^0-9/]', '', str(p_str))
    return nums_only if len(nums_only) >= 8 else "nincs tel. szám"

def clean_name_strict(name_str):
    if not name_str: return ""
    name_str = re.sub(r'\s*-[A-Z0-9+*]+\s*$', '', name_str)
    name_str = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', name_str)
    return name_str.strip()

def clean_address_strict(addr_str):
    if not addr_str: return ""
    match = re.search(r'(\d{4})', addr_str)
    if not match: return addr_str.strip()
    addr = addr_str[match.start():].strip()
    addr = re.sub(r'\d{2,3}-[A-Z][A-Z0-9*+]*', '', addr).strip()
    return addr

def parse_interfood(pdf_file):
    page_data = []
    # Javított rendelés minta: elkerüljük, hogy a tel.szám vége (pl. 23) belekerüljön
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
                
                if any(x in full_line_text for x in ["Nyomtatta", "Oldal:", "Összesen"]): continue
                u_code_m = re.search(r'([HKSCPZ]-\d{5,7})', full_line_text)
                if not u_code_m: continue
                
                # Oszlopok pontos meghatározása
                raw_addr_block = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                raw_name_block = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                # Telefon kinyerése (gyakran a 480-as koordináta után kezdődik)
                tel_search = re.search(r'(\d{2}/\d{6,7})', full_line_text.replace(" ", ""))
                final_tel = clean_phone(tel_search.group(0) if tel_search else " - ")

                # Rendelés tisztítása a "Czinege-szindróma" ellen
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                found_orders = re.findall(order_pat, search_text)
                
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    # Ha a talált rendelés mennyisége irreálisan nagy (pl. a telefonszám vége ragadt oda)
                    qty_match = re.match(r'^(\d+)', o)
                    if qty_match:
                        qty = int(qty_match.group(1))
                        # Ha a szám 10-nél nagyobb, valószínűleg a telefonszám vége. 
                        # Ilyenkor csak az utolsó számjegyet vesszük (pl. 23-SP1 -> 3-SP1)
                        if qty >= 10:
                            actual_qty = int(str(qty)[-1])
                            actual_code = o.split('-', 1)[1]
                            o = f"{actual_qty}-{actual_code}"
                            qty = actual_qty
                        
                        if qty < 50:
                            clean_orders.append(o)
                            total_qty += qty

                if total_qty == 0: continue

                page_data.append({
                    "Járat": pdf_file.name,
                    "Ügyfélkód": u_code_m.group(0),
                    "Ügyintéző": clean_name_strict(raw_name_block),
                    "Cím": clean_address_strict(raw_addr_block),
                    "Telefon": final_tel,
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": total_qty
                })
    return page_data

# --- UI ---
st.title("🛡️ Interfood v180.0 - Teljes Adatvédelem")

files = st.file_uploader("PDF feltöltése", type="pdf", accept_multiple_files=True)

if files:
    # Járat sorrendező
    file_info = [{"Sorrend": i+1, "Fájl": f.name} for i, f in enumerate(files)]
    file_order = st.data_editor(pd.DataFrame(file_info), hide_index=True)
    
    if st.button("Beolvasás"):
        sorted_files = file_order.sort_values("Sorrend")
        all_data = []
        for _, row in sorted_files.iterrows():
            f_obj = next(f for f in files if f.name == row["Fájl"])
            all_data.extend(parse_interfood(f_obj))
        
        df = pd.DataFrame(all_data)
        df.insert(0, "Új Sorrend", [str(i+1) for i in range(len(df))])
        st.session_state.working_df = df

if 'working_df' in st.session_state and st.session_state.working_df is not None:
    st.divider()
    edited_df = st.data_editor(st.session_state.working_df, num_rows="fixed", use_container_width=True, hide_index=True)

    # Tizedesvesszős mentés/rendezés
    if not edited_df.equals(st.session_state.working_df):
        def safe_f(x):
            try: return float(str(x).replace(',', '.'))
            except: return 999.0
        edited_df['sort'] = edited_df['Új Sorrend'].apply(safe_f)
        edited_df = edited_df.sort_values('sort').drop(columns=['sort'])
        edited_df['Új Sorrend'] = [str(i+1) for i in range(len(edited_df))]
        st.session_state.working_df = edited_df
        st.rerun()

    st.download_button("💾 Végleges CSV (Telefonnal és Javítva)", edited_df.to_csv(index=False).encode('utf-8-sig'), "interfood_v180_fix.csv")
