import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import Counter

st.set_page_config(page_title="Interfood v174.0 - Logisztikai Tervező", layout="wide")

# --- SEGÉDFÜGGVÉNYEK ---
def clean_phone(p_str):
    if not p_str or p_str == " - ": return "nincs tel. szám"
    nums_only = re.sub(r'[^0-9/]', '', str(p_str))
    return nums_only if len(nums_only) >= 8 else "nincs tel. szám"

def extract_comment(raw_text):
    # Olyan szövegeket keresünk, amik nem névnek/címnek tűnnek (pl. kódok, instrukciók)
    keywords = ['kapu', 'kód', 'porta', 'csengő', 'emelet', 'lépcsőház', 'fszt', 'mögött', 'mellett']
    found = []
    for word in keywords:
        if word in raw_text.lower():
            # Kiemeljük a környezetét
            found.append(raw_text.strip())
            break
    return " | ".join(found) if found else ""

def process_name_and_address(raw_name, raw_addr):
    name_clean = re.sub(r'[HS]-\d+', '', raw_name).strip()
    name_clean = re.sub(r'^[a-z \.\,]+', '', name_clean)
    name_clean = re.sub(r'\s*-\s*[A-Z0-9+*]+$', '', name_clean)
    
    # Név tisztítása
    name_clean = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', name_clean).strip()
    return name_clean, raw_addr.strip()

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
                
                if any(x in full_line_text for x in ["Nyomtatta", "Oldal:", "Összesen"]): continue
                u_code_m = re.search(r'([HKSCPZ]-\d{5,7})', full_line_text)
                if not u_code_m: continue
                u_code = u_code_m.group(0)

                tel_search = re.search(r'(\d{2}/\d{6,7})', full_line_text.replace(" ", ""))
                final_tel = clean_phone(tel_search.group(0) if tel_search else " - ")

                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', full_line_text)
                found_orders = re.findall(order_pat, search_text)
                
                clean_orders = []
                total_qty = 0
                for o in found_orders:
                    qty = int(re.match(r'^(\d+)', o).group(1))
                    if qty < 50:
                        clean_orders.append(o)
                        total_qty += qty

                if total_qty == 0: continue

                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                u_nev, u_cim = process_name_and_address(b4, b3)
                u_comment = extract_comment(full_line_text)

                page_data.append({
                    "Járat": pdf_file.name.replace(".pdf", "").replace("menetterv ", ""),
                    "Ügyfélkód": u_code, "Ügyintéző": u_nev,
                    "Cím": u_cim, "Telefon": final_tel, "Rendelés": ", ".join(clean_orders),
                    "Megjegyzés": u_comment, "Összesen": total_qty
                })
    return page_data

# --- FELÜLET ---
st.title("🚚 Interfood v174.0 - Logisztikai Vezérlő")

if 'main_df' not in st.session_state:
    st.session_state.main_df = None

files = st.file_uploader("PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if files and st.button("Beolvasás"):
    all_data = []
    for f in files:
        all_data.extend(parse_interfood(f))
    st.session_state.main_df = pd.DataFrame(all_data)

if st.session_state.main_df is not None:
    df = st.session_state.main_df.copy()

    st.subheader("📍 Kiszállítási sorrend módosítása")
    st.info("Itt láthatod a beolvasott sorrendet. Használd a sorszámokat a rendezéshez!")
    
    # Drag & Drop szimuláció: Szerkeszthető Index oszlop
    df.insert(0, 'Új_Sorrend', range(1, len(df) + 1))
    edited_df = st.data_editor(df, num_rows="dynamic", hide_index=True, use_container_width=True)
    
    # Újrarendezés az 'Új_Sorrend' alapján
    final_df = edited_df.sort_values(by='Új_Sorrend').drop(columns=['Új_Sorrend'])

    # --- CIKKSZÁM ÖSSZESÍTŐ (A Rakodólista) ---
    st.divider()
    st.subheader("📦 Napi Rakodólista (Összesítve)")
    
    all_codes = []
    for r in final_df['Rendelés']:
        # Szétbontjuk a "1-L2K, 2-D5" formátumot
        items = r.split(', ')
        for item in items:
            match = re.match(r'(\d+)-(.*)', item)
            if match:
                qty, code = int(match.group(1)), match.group(2)
                all_codes.extend([code] * qty)
    
    counts = Counter(all_codes)
    summary_df = pd.DataFrame.from_dict(counts, orient='index', columns=['Összes db']).reset_index().rename(columns={'index': 'Étel kód'})
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.dataframe(summary_df.sort_values('Összes db', ascending=False), use_container_width=True)
    
    with col2:
        st.success(f"Összesen kiszállítandó: {sum(counts.values())} adag étel.")
        st.download_button("💾 Kiszállítási lista mentése (CSV)", final_df.to_csv(index=False).encode('utf-8-sig'), "kiszallitasi_terv.csv")
