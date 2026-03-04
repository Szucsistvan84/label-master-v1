import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

# --- ALAPVETŐ TISZTÍTÓK ---
def clean_address(raw_addr):
    match = re.search(r'(\d{4})', str(raw_addr))
    if match: return raw_addr[match.start():].strip()
    return str(raw_addr).strip()

# --- PARSER ---
def parse_weekend_pdf(files):
    all_data = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    
    for file in files:
        with pdfplumber.open(file) as pdf:
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
                    u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', full_line_text)
                    if not u_code_m: continue
                    
                    # Prefix és tiszta ID szétválasztása (P-123456 -> Prefix: P, ID: 123456)
                    full_code = u_code_m.group(0)
                    prefix = full_code.split('-')[0]
                    clean_id = full_code.split('-')[-1]

                    b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                    b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                    
                    # Rendelés kinyerése és Czinege-fix
                    found_orders = re.findall(order_pat, full_line_text.replace(" ", ""))
                    clean_orders = []
                    total_qty = 0
                    for o in found_orders:
                        qty = int(o.split('-')[0])
                        if qty >= 10: qty = int(str(qty)[-1])
                        if qty < 50:
                            clean_orders.append(f"{qty}-{o.split('-')[1]}")
                            total_qty += qty

                    if total_qty > 0:
                        all_data.append({
                            "Prefix": prefix,
                            "ID": clean_id,
                            "Ügyintéző": re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip(),
                            "Cím": clean_address(b3),
                            "Telefon": re.search(r'(\d{2}/\d{6,7})', full_line_text.replace(" ", "")).group(0) if re.search(r'(\d{2}/\d{6,7})', full_line_text.replace(" ", "")) else "nincs",
                            "Rendelés": ", ".join(clean_orders),
                            "Összesen": total_qty
                        })
    return all_data

# --- UI LOGIKA ---
st.sidebar.title("🚚 Szállítási adatok")
f_nev = st.sidebar.text_input("Futár neve", key="f_nev")
f_tel = st.sidebar.text_input("Futár telefonszáma", key="f_tel")

if not f_nev or not f_tel:
    st.warning("👈 Kérlek, töltsd ki a futár adatait a bal oldalon!")
    st.stop()

st.title("🏷️ Interfood Címke Master v188")

# Session state inicializálás
if 'df' not in st.session_state:
    st.session_state.df = None

uploaded_files = st.file_uploader("1. PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if uploaded_files and st.button("Adatok beolvasása"):
    data = parse_weekend_pdf(uploaded_files)
    df = pd.DataFrame(data)
    df.insert(0, "Sorrend", [str(i+1) for i in range(len(df))])
    st.session_state.df = df

# TÁBLÁZAT ÉS SZERKESZTÉS
if st.session_state.df is not None:
    st.subheader("2. Sorrendezés és ellenőrzés")
    st.info("💡 A 'Sorrend' oszlopban tizedesvesszővel (pl. 1.5) szúrhatsz be címeket.")
    
    # Szerkeszthető táblázat
    edited_df = st.data_editor(
        st.session_state.df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed"
    )

    # Automatikus újrarendezés tizedesvesszőre
    if not edited_df.equals(st.session_state.df):
        def safe_sort(x):
            try: return float(str(x).replace(',', '.'))
            except: return 999.0
        
        edited_df['sort_val'] = edited_df['Sorrend'].apply(safe_sort)
        edited_df = edited_df.sort_values
