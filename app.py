import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
import math
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

st.set_page_config(page_title="Interfood Logisztika v203.7", layout="wide")

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- PDF PARSER (H-Z prefixek) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
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
                text_ws = " ".join([w['text'] for w in line_words])
                text_ns = "".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                prefix = u_code_m.group(0).split('-')[0]
                uid = u_code_m.group(0).split('-')[-1]
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                tel_m = re.search(phone_pat, text_ns)
                final_tel = tel_m.group(0) if tel_m else ""
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                raw_orders = re.findall(order_pat, text_ws)
                valid_o, sq = [], 0
                for o in raw_orders:
                    parts = o.split('-')
                    if len(parts) < 2: continue
                    q_val = int(re.sub(r'\D', '', parts[0])[-1])
                    code_part = parts[1]
                    if len(code_part) > 3 and code_part[-1].isdigit(): code_part = code_part[:-1]
                    valid_o.append(f"{q_val}-{code_part}")
                    sq += q_val
                if valid_o:
                    rows.append({"Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, "Telefon": final_tel, "Rendelés": ", ".join(valid_o), "Összesen": sq})
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        if any(p in ['P', 'Z'] for p in group['Prefix']):
            base = group.iloc[0].copy().to_dict()
            p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
            z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
            order_str = ""
            if p_items: order_str += f"P: {', '.join(p_items)}"
            if z_items:
                if order_str: order_str += " | "
                order_str += f"SZ: {', '.join(z_items)}"
                base['Prefix'] = 'Z'
            base['Rendelés'] = order_str
            base['Összesen'] = group['Összesen'].sum()
            merged.append(base)
        else:
            for _, row in group.iterrows(): merged.append(row.to_dict())
    return merged

# --- ETIKETT & MENETTERV GENERÁLÁS (Változatlan) ---
# ... (create_label_pdf és create_manifest_pdf függvények) ...
# (Itt a marketing etikett logika továbbra is benne van a v203.5 alapján)

# --- UI ---
with st.sidebar:
    st.header("🚚 Beállítások")
    fn = st.text_input("Futár neve", "Szűcs István")
    ft = st.text_input("Telefonszáma", "+36208868971")

st.title("🏷️ Interfood Logisztika v203.7")
up_files = st.file_uploader("PDF feltöltése", accept_multiple_files=True)

if up_files:
    # A fájlok sorrendjénél is engedünk tört számot a biztonság kedvéért
    f_order_data = [{"Sorrend": float(i+1), "Fájl": f.name} for i, f in enumerate(up_files)]
    f_order = st.data_editor(f_order_data, hide_index=True)
    
    if st.button("FELDOLGOZÁS"):
        raw = []
        for name in pd.DataFrame(f_order).sort_values("Sorrend")["Fájl"]:
            fobj = next(f for f in up_files if f.name == name)
            raw.extend(parse_interfood_pro(fobj))
        
        mdf = pd.DataFrame(merge_data_flexible(raw))
        # Itt FLOAT típusra kényszerítjük a Sorrend oszlopot!
        mdf.insert(0, "Sorrend", range(1, len(mdf)+1))
        st.session_state.mdf = mdf.astype({"Sorrend": float})
        st.rerun()

if st.session_state.get('mdf') is not None:
    st.subheader("📋 Ellenőrzés és Sorrendezés")
    st.write("Tipp: Beírhatsz tört számot (pl. 1.1), majd nyomd meg a 'LISTA FRISSÍTÉSE' gombot.")
    
    # Interaktív táblázat - Float típus engedélyezve
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    col_a, col_b = st.columns([1, 4])
    with col_a:
        if st.button("🔄 LISTA FRISSÍTÉSE"):
            # Sorba rendezzük a beírt (akár tört) számok alapján, majd újraindexeljük egészekre
            new_df = edited_df.sort_values("Sorrend").copy()
            new_df["Sorrend"] = range(1, len(new_df) + 1)
            st.session_state.mdf = new_df.astype({"Sorrend": float})
            st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        num_pages = math.ceil(len(st.session_state.mdf) / 21)
        st.info(f"🖨️ Nyomtatás: **{num_pages} lap** etikett.")
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            final_df = edited_df.sort_values("Sorrend")
            pdf = create_label_pdf(final_df, fn, ft)
            st.download_button("Mentés (etikett)", pdf, "etikettek.pdf")
    with c2:
        if st.button("📋 MENETTERV LETÖLTÉSE"):
            final_df = edited_df.sort_values("Sorrend")
            pdf = create_manifest_pdf(final_df, fn)
            st.download_button("Mentés (menetterv)", pdf, "menetterv.pdf")
