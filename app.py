import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

VERZIO = "v203.63-FULL-WEEK-ESZTETIK"
WEIGHTS_FILE = "client_weights.csv"

# --- KONFIGURÁCIÓ ÉS RÖVIDÍTÉSEK ---
NAP_MAP = {
    "H": "Hé",
    "K": "Ke",
    "S": "Sze",
    "C": "Csü",
    "P": "Pé",
    "Z": "Szo"
}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

# --- SEGÉDFÜGGVÉNYEK ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def load_weights():
    if os.path.exists(WEIGHTS_FILE):
        try:
            return pd.read_csv(WEIGHTS_FILE, dtype={'ID': str}).set_index('ID')['Weight'].to_dict()
        except: return {}
    return {}

def save_weights(df):
    weights_df = df[['ID', 'Sorrend']].rename(columns={'Sorrend': 'Weight'})
    weights_df.to_csv(WEIGHTS_FILE, index=False)
    st.success("Súlyozás (sorrend) elmentve a háttérbe!")

def smart_round(x):
    try:
        cleaned = re.sub(r'[^\d\-]', '', str(x))
        if not cleaned or cleaned == "-": return 0
        val = float(cleaned)
        return int(5 * round(val/5))
    except: return 0

# --- ADATFELDOLGOZÁS (MINDEN NAPRA) ---
def parse_interfood_pro(pdf_file):
    rows = []
    # Prefixek: H, K, S, C, P, Z
    u_code_pat = r'(?:([HKSCPZ])[-]?|ID:\s*)([0-9]{5,7})'
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines_dict = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines_dict:
                    if abs(y - ey) < 3:
                        lines_dict[ey].append(w); break
                else: lines_dict[y] = [w]
            
            sorted_y = sorted(lines_dict.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines_dict[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                
                u_code_m = re.search(u_code_pat, text_ws)
                if u_code_m:
                    nap_prefix = u_code_m.group(1) if u_code_m.group(1) else "S"
                    uid = u_code_m.group(2)
                    nap_szep = NAP_MAP.get(nap_prefix, nap_prefix)
                    
                    # NÉV és CÍM kinyerése (sávok alapján az elcsúszás ellen)
                    name_parts = [w['text'] for w in line_words if 340 <= w['x0'] < 520]
                    clean_name = " ".join(name_parts).split('/')[0].strip()
                    clean_name = re.sub(r'\s*-[A-Z0-9/ \-]+$', '', clean_name).strip()
                    
                    addr_parts = [w['text'] for w in line_words if 150 <= w['x0'] < 340]
                    clean_addr = " ".join(addr_parts).strip()
                    
                    phone_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                    
                    # PÉNZ: Keresés az aktuális és a következő 4 sorban
                    found_money = 0
                    m_match = re.search(money_pat, text_ws)
                    if m_match:
                        found_money = smart_round(m_match.group(1))
                    else:
                        for next_idx in range(1, 5):
                            if i + next_idx < len(sorted_y):
                                next_text = " ".join([w['text'] for w in lines_dict[sorted_y[i+next_idx]]])
                                if re.search(u_code_pat, next_text): break
                                m_sub = re.search(money_pat, next_text)
                                if m_sub:
                                    found_money = smart_round(m_sub.group(1))
                                    break
                    
                    current_orders = re.findall(order_pat, text_ws)
                    labeled_orders = [f"{nap_szep}: {o}" for o in current_orders]
                    
                    rows.append({
                        "ID": str(uid), "Ügyintéző": clean_name, "Telefon": phone_m.group(0) if phone_m else "",
                        "Cím": clean_addr, "Rendelés": labeled_orders, "Pénz": found_money, "Nap": nap_szep
                    })
    return rows

# --- ETIKETT GENERÁLÁS ---
def create_label_pdf(df, f_name, f_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    label_w, label_h = 70.0 * mm, 42.428 * mm

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = float(col * label_w), float(row_i * label_h)
        r = df.iloc[i]
        
        p.setFont(f_reg, 7)
        p.drawString(x + 5*mm, y + label_h - 5*mm, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - 5*mm, y + label_h - 5*mm, f"ID: {r['ID']}")
        
        p.setFont(f_bold, 8.5)
        p.drawString(x + 5*mm, y + label_h - 10*mm, str(r['Ügyintéző'])[:26])
        p.setFont(f_reg, 8)
        p.drawRightString(x + label_w - 5*mm, y + label_h - 10*mm, str(r['Telefon']))
        
        p.setFont(f_reg, 8)
        rendelesek_str = ", ".join(r['Rendelés'])
        p.drawString(x + 5*mm, y + 20*mm, f"{rendelesek_str}"[:60])
        
        p.setFont(f_bold, 10)
        p.drawRightString(x + label_w - 5*mm, y + 10*mm, f"{r['Össz db']} db")
        if int(r['Pénz']) > 0:
            p.drawString(x + 5*mm, y + 10*mm, f"FIZET: {r['Pénz']} Ft")
        
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.1)
        p.line(x + 5*mm, y + 8*mm, x + label_w - 5*mm, y + 8*mm)
        p.setFont(f_reg, 7)
        p.drawCentredString(x + label_w/2, y + 4*mm, f"Futár: {f_name} | {f_phone}")
        
    p.save(); buf.seek(0); return buf

# --- FELHASZNÁLÓI FELÜLET ---
st.title(f"Interfood Logisztika {VERZIO}")

c1, c2 = st.columns(2)
with c1: f_nev = st.text_input("Futár neve", "Szűcs István")
with c2: f_tel = st.text_input("Telefonszám", "+36 20 886 8971")

files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True)

if files and st.button("📊 FELDOLGOZÁS"):
    all_data = []
    for f in files: all_data.extend(parse_interfood_pro(f))
    
    if not all_data:
        st.error("Nem találtam adatokat!")
    else:
        df_raw = pd.DataFrame(all_data)
        
        # ÖSSZEVONÁS (Napok és Rendelések szerint)
        df = df_raw.groupby('ID').agg({
            'Ügyintéző': 'first',
            'Telefon': 'first',
            'Cím': 'first',
            'Rendelés': lambda x: sorted([i for s in x for i in s]),
            'Pénz': 'sum',
            'Nap': lambda x: "+".join(sorted(list(set(x))))
        }).reset_index()
        
        df['Össz db'] = df['Rendelés'].apply(len)
        
        # Súlyozás betöltése
        weights = load_weights()
        df['Weight'] = df['ID'].map(weights).fillna(999).astype(int)
        df = df.sort_values(by=['Weight', 'ID']).reset_index(drop=True)
        df['Sorrend'] = range(1, len(df)+1)
        
        st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Telefon', 'Cím', 'Rendelés', 'Össz db', 'Pénz', 'Nap']]

if 'mdf' in st.session_state:
    st.write("### Táblázatos nézet")
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.session_state.mdf = edited

    if st.button("💾 SORREND MENTÉSE"):
        save_weights(edited)
        st.rerun()

    if st.button("📥 ETIKETTEK LETÖLTÉSE"):
        pdf_out = create_label_pdf(st.session_state.mdf, f_nev, f_tel)
        st.download_button("PDF Mentése", pdf_out, "etikettek.pdf", "application/pdf")
