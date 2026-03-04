import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Interfood v185.0 - Hétvégi Címke", layout="wide")

# --- UI: KÖTELEZŐ FUTÁR ADATOK ---
st.sidebar.title("🚚 Futár adatai")
futar_nev = st.sidebar.text_input("Futár neve (KÖTELEZŐ)")
futar_tel = st.sidebar.text_input("Futár telefonszáma (KÖTELEZŐ)")

# --- LOGIKA ---
def parse_interfood_weekend(pdf_file):
    page_data = []
    # Keressük a P- vagy Z- kezdetű kódokat
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # (Itt a korábbi stabil sor-feldolgozó logikád fut)
            # Példa egy kinyert sorra:
            raw_data = {
                "FullCode": "P-456123", # Vagy Z-456123
                "Nev": "Minta János",
                "Cim": "4024 Debrecen, Piac u. 1.",
                "Tel": "30/1234567",
                "Rendeles": "1-L2K, 1-BK"
            }
            # Kód tisztítása: P-456123 -> 456123
            clean_id = raw_data["FullCode"].split('-')[-1]
            nap_prefix = raw_data["FullCode"].split('-')[0]
            
            page_data.append({
                "ID": clean_id,
                "Prefix": nap_prefix,
                "Nev": raw_data["Nev"],
                "Cim": raw_data["Cim"],
                "Tel": raw_data["Tel"],
                "Rendeles": raw_data["Rendeles"],
                "Qty": 2 # Összesen db
            })
    return page_data

# --- FŐ FOLYAMAT ---
if not futar_nev or not futar_tel:
    st.warning("⚠️ Kérlek, add meg a futár nevét és telefonszámát a bal oldali sávban a folytatáshoz!")
else:
    st.title("🏷️ 3x7-es Hétvégi Etikett Generátor")
    files = st.file_uploader("Menetterv PDF feltöltése (Péntek/Szombat)", type="pdf", accept_multiple_files=True)

    if files:
        if st.button("Adatok feldolgozása"):
            raw_list = []
            for f in files:
                raw_list.extend(parse_interfood_weekend(f))
            
            # Ügyfélkód szerinti csoportosítás az összevonáshoz
            grouped = defaultdict(list)
            for item in raw_list:
                grouped[item["ID"]].append(item)
            
            final_rows = []
            for uid, items in grouped.items():
                # Itt dől el: ha van P és Z is, egy címkére kerülnek-e vagy külön?
                # A kérésed alapján: "pénteki és szombati tétel... ügyfélkód azonos lesz"
                for entry in items:
                    final_rows.append(entry)
            
            df = pd.DataFrame(final_rows)
            df.insert(0, "Sorszám", range(1, len(df) + 1))
            st.session_state.working_df = df

    if 'working_df' in st.session_state:
        # A sorrendezés utáni sorszám frissítése
        df = st.session_state.working_df
        st.subheader("📍 Véglegesített sorrend és adatok")
        edited_df = st.data_editor(df, use_container_width=True, hide_index=True)

        # --- ETIKETT ELŐNÉZET ---
        st.divider()
        st.subheader("🖨️ 3x7-es Etikett Tervezet")
        
        if not edited_df.empty:
            sample = edited_df.iloc[0]
            nap_jelzo = "SZOMBAT" if sample['Prefix'] == 'Z' else "PÉNTEK"
            
            with st.container(border=True):
                # 1. SOR: #Sorszám + Ügyfélkód + Nap
                c1, c2 = st.columns([1, 1])
                c1.write(f"**#{sample['Sorszám']}** {sample['ID']}")
                c2.markdown(f"<p style='text-align: right;'><b>{nap_jelzo}</b></p>", unsafe_allow_html=True)
                
                # 2. SOR: Név + Tel
                c3, c4 = st.columns([2, 1])
                c3.write(f"{sample['Nev']}")
                c4.markdown(f"<p style='text-align: right;'>{sample['Tel']}</p>", unsafe_allow_html=True)
                
                # 3. SOR: Cím
                st.write(f"{sample['Cim']}")
                
                # 4. SOR: Rendelés + Összesen
                c5, c6 = st.columns([3, 1])
                c5.write(f"📦 {sample['Rendeles']}")
                c6.markdown(f"<p style='text-align: right;'>Össz: {sample['Qty']} db</p>", unsafe_allow_html=True)
                
                # ALJA: Futár + Üzenet
                st.divider()
                st.caption(f"Futár: {futar_nev} | {futar_tel} | Jó étvágyat kívánunk! :)")

        st.button("📥 PDF letöltése nyomtatáshoz (3x7 ív)")
