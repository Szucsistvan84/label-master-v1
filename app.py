import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import requests
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# --- FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        # Próbáld meg betölteni a rendszerről vagy a mappa mellől a fontot
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- 1. ÉTLAP KEZELÉSE (CSILLAGOS ÉTELEK FIXÁLÁSA) ---
def get_live_menu(year, week, day_name):
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    menu_map = {}
    
    day_to_col = {'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6}
    target_col = day_to_col.get(day_name, 3) 

    try:
        response = requests.get(excel_url, headers=headers, timeout=15)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), engine='openpyxl')
            current_category = "Egyéb"
            
            for i in range(len(df)):
                row = df.iloc[i]
                col_a = str(row.iloc[0]).strip()
                
                if col_a and col_a != 'nan' and " - " in col_a:
                    parts = col_a.split(" - ")
                    code = parts[0].strip()
                    current_category = parts[1].strip()
                    
                    name_on_day = str(row.iloc[target_col]).strip()
                    
                    if name_on_day and name_on_day != 'nan' and len(name_on_day) > 2:
                        try:
                            next_row = df.iloc[i+1]
                            price_on_day = str(next_row.iloc[target_col]).strip()
                            p_str = re.sub(r'[^\d]', '', price_on_day)
                            
                            if p_str:
                                menu_map[code] = {
                                    'nev': name_on_day[:60],
                                    'ar': int(p_str),
                                    'kategoria': current_category,
                                    'excel_order': i 
                                }
                        except: continue
    except: pass
    return menu_map

# --- 2. PDF PARSER (JÁRATSZÁM KINYERÉSSEL) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {'year': None, 'week': None, 'day': None, 'jarat': "????"}
    
    with pdfplumber.open(pdf_file) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ""
        # Járatszám kinyerése: Első számsor az első pontig (pl: 4002. járat -> 4002)
        jarat_m = re.search(r'^(\d+)\.', first_page_text)
        if jarat_m: meta['jarat'] = jarat_m.group(1)
        
        y_m = re.search(r'Év:\s*(\d{4})', first_page_text)
        w_m = re.search(r'Hét:\s*(\d{1,2})', first_page_text)
        d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', first_page_text)
        if y_m: meta['year'] = y_m.group(1)
        if w_m: meta['week'] = w_m.group(1)
        if d_m: meta['day'] = d_m.group(1)

        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines:
                    if abs(y - ey) < 3: lines[ey].append(w); break
                else: lines[y] = [w]
            
            sorted_y = sorted(lines.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                
                # Ügyfélkód keresése (S-123456 formátum)
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                uid = str(u_code_m.group(0).split('-')[-1]) # Az ügyfélkód a kötőjel utáni rész
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3
                
                money_val = "0 Ft"
                if i + 1 < len(sorted_y):
                    next_t = " ".join([w['text'] for w in sorted(lines[sorted_y[i+1]], key=lambda x: x['x0'])])
                    m_match = re.search(r'(-?\s?\d[\d\s]*\s*Ft)', next_t)
                    if m_match: money_val = m_match.group(1).strip()
                
                # Rendelések kinyerése (pl: 1-R2K*)
                raw_orders = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "ID": uid, "Járat": meta['jarat'], "Ügyintéző": clean_name, 
                        "Cím": address, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": money_val, "Összesen": sq
                    })
    return rows, meta

# --- 3. UI ÉS LOGIKA ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")

# Session state inicializálás
if 'weights' not in st.session_state: st.session_state.weights = {}
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'live_menu' not in st.session_state: st.session_state.live_menu = {}

with st.sidebar:
    st.header("👤 Beállítások")
    futar_nev = st.text_input("Futár neve", "Szűcs István")
    f_tel = st.text_input("Telefonszám", "+36 20 886 8971")
    
    st.divider()
    csv_file = st.file_uploader("Előző napi CSV betöltése (sorrendhez)", type="csv")
    if csv_file:
        try:
            imp_df = pd.read_csv(csv_file)
            # ID-t stringre, Sorrendet floatra kényszerítjük az egyezéshez
            st.session_state.weights = dict(zip(imp_df['ID'].astype(str), imp_df['Sorrend'].astype(float)))
            if 'Megjegyzés' in imp_df.columns:
                st.session_state.notes = dict(zip(imp_df['ID'].astype(str), imp_df['Megjegyzés'].fillna("")))
            st.success("✅ Sorrend és megjegyzések betöltve!")
        except: st.error("❌ Hiba a CSV beolvasásakor!")

    pdf_files = st.file_uploader("Napi PDF-ek feltöltése", accept_multiple_files=True)
    if pdf_files and st.button("📊 FELDOLGOZÁS"):
        all_raw = []
        for f in pdf_files:
            rows, meta = parse_interfood_pdf(f)
            all_raw.extend(rows)
            if meta['year']:
                st.session_state.live_menu = get_live_menu(meta['year'], meta['week'], meta['day'])
        
        if all_raw:
            df = pd.DataFrame(all_raw)
            merged = []
            for uid, group in df.groupby("ID", sort=False):
                base = group.iloc[0].copy().to_dict()
                base['Rendelés_Full'] = ", ".join(group['Rendelés'].astype(str).tolist())
                base['Összesen'] = group['Összesen'].sum()
                m_list = [int(re.sub(r'[^\d-]', '', str(m)) or 0) for m in group['Pénz'].tolist()]
                base['Pénz'] = f"{sum(m_list)} Ft"
                
                # Súlyozás (sorrend) keresése
                uid_str = str(uid).strip()
                base['Sorrend'] = st.session_state.weights.get(uid_str, 999.0)
                base['Megjegyzés'] = st.session_state.notes.get(uid_str, "")
                merged.append(base)
            
            # Alapértelmezett sorrend: Súly, majd Járatszám
            st.session_state.mdf = pd.DataFrame(merged).sort_values(['Sorrend', 'Járat'])
            st.rerun()

# --- FŐ TÁBLÁZAT MEGJELENÍTÉSE ---
if st.session_state.mdf is not None:
    st.subheader("📍 Menetlevél szerkesztése")
    
    # Oszloprend: Sorrend az első
    cols = ['Sorrend', 'ID', 'Járat', 'Ügyintéző', 'Cím', 'Rendelés_Full', 'Összesen', 'Pénz', 'Megjegyzés']
    
    edited_df = st.data_editor(
        st.session_state.mdf[cols],
        hide_index=True,
        use_container_width=True,
        column_config={
            "Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f"),
            "ID": st.column_config.TextColumn("Ügyfélkód", disabled=True),
            "Járat": st.column_config.TextColumn("Járat", disabled=True),
            "Rendelés_Full": st.column_config.TextColumn("Rendelés", disabled=True),
        }
    )

    if st.button("✅ SORREND ÉS INFÓK MENTÉSE (ÚJRASORSZÁMOZÁS)"):
        # 1. Rendezés a beírt súlyok alapján
        final_df = edited_df.sort_values(by='Sorrend').reset_index(drop=True)
        # 2. Újrasorszámozás 1, 2, 3...
        final_df['Sorrend'] = range(1, len(final_df) + 1)
        final_df['Sorrend'] = final_df['Sorrend'].astype(float)
        
        # 3. Mentés sessionbe (hogy exportnál is ez legyen)
        for _, row in final_df.iterrows():
            uid_str = str(row['ID']).strip()
            st.session_state.weights[uid_str] = row['Sorrend']
            st.session_state.notes[uid_str] = row['Megjegyzés']
        
        st.session_state.mdf = final_df
        st.success("Mentve és újrasorszámozva!")
        st.rerun()

    # --- PDF GENERÁLÁS (Etikett és Raklista - Rövidített logika) ---
    # Ide jönnének a create_label_pdf és create_manifest_pdf függvények a korábbiak alapján
    # ...
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    with c3:
        csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 CSV EXPORT (Tegnapi adathoz)", csv_data, "napi_mentes.csv", use_container_width=True)
