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

VERZIO = "v203.65-FINAL-FULL-FIX"
WEIGHTS_FILE = "client_weights.csv"

# Napi leképezés a kért formátumban
NAP_MAP = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

# --- BETŰKÉSZLET ÉS SÚLYOZÁS ---
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
    st.success("Sorrend (súlyozás) sikeresen elmentve!")

# --- ADATFELDOLGOZÁS ---
def parse_interfood_pro(pdf_file):
    rows = []
    # Prefix keresés (H, K, S, C, P, Z)
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
                    
                    # NÉV TISZTÍTÁSA: Levágjuk a név végére ragadt telefonszám-foszlányokat (20, 30, 70)
                    name_parts = [w['text'] for w in line_words if 340 <= w['x0'] < 535]
                    raw_name = " ".join(name_parts).split('/')[0].strip()
                    clean_name = re.sub(r'\s*(20|30|70|#)$', '', raw_name)
                    clean_name = re.split(r'\d{2}/|\d{7}| -', clean_name)[0].strip()
                    
                    # CÍM TISZTÍTÁSA: Csak ha 4 jegyű számmal (bármilyen irányítószám) kezdődik
                    addr_parts = [w['text'] for w in line_words if 150 <= w['x0'] < 340]
                    clean_addr = " ".join(addr_parts).strip()
                    if not re.match(r'^\d{4}', clean_addr):
                        clean_addr = "" 

                    phone_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                    
                    # PÉNZ KERESÉSE (mélyebb keresés a sorok alatt)
                    found_money = 0
                    m_match = re.search(money_pat, text_ws)
                    if m_match:
                        try: found_money = int(re.sub(r'[^\d\-]', '', m_match.group(1)))
                        except: pass
                    else:
                        for next_idx in range(1, 5):
                            if i + next_idx < len(sorted_y):
                                next_text = " ".join([w['text'] for w in lines_dict[sorted_y[i+next_idx]]])
                                if re.search(u_code_pat, next_text): break
                                m_sub = re.search(money_pat, next_text)
                                if m_sub:
                                    try: found_money = int(re.sub(r'[^\d\-]', '', m_sub.group(1)))
                                    except: pass
                                    break
                    
                    current_orders = re.findall(order_pat, text_ws)
                    
                    rows.append({
                        "ID": str(uid), "Ügyintéző": clean_name, "Telefon": phone_m.group(0) if phone_m else "",
                        "Cím": clean_addr, "Rendelés": current_orders, "Pénz": found_money, "Nap": nap_szep
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
        
        # Sorszám és ID
        p.setFont(f_reg, 7)
        p.drawString(x + 5*mm, y + label_h - 4*mm, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - 5*mm, y + label_h - 4*mm, f"ID: {r['ID']}")
        
        # Név
        p.setFont(f_bold, 9)
        p.drawString(x + 5*mm, y + label_h - 9*mm, str(r['Ügyintéző'])[:26])
        
        # Cím és Telefon
        p.setFont(f_reg, 7.5)
        if r['Cím']:
            p.drawString(x + 5*mm, y + label_h - 13*mm, str(r['Cím'])[:42])
        p.setFont(f_bold, 8)
        p.drawRightString(x + label_w - 5*mm, y + label_h - 17*mm, str(r['Telefon']))
        
        # RENDELÉSEK: Nap csak egyszer a sor elején
        p.setFont(f_bold, 8.5)
        rendeles_txt = f"{r['Nap']}: " + ", ".join(r['Rendelés'])
        p.drawString(x + 5*mm, y + 16*mm, rendeles_txt[:65])
        
        # Összesítés és Fizetendő
        p.setFont(f_bold, 10)
        p.drawRightString(x + label_w - 5*mm, y + 8*mm, f"{r['Össz db']} db")
        if int(r['Pénz']) > 0:
            p.drawString(x + 5*mm, y + 8*mm, f"FIZET: {r['Pénz']} Ft")
        
        # Elválasztó és Futár infó
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.1)
        p.line(x + 5*mm, y + 6*mm, x + label_w - 5*mm, y + 6*mm)
        p.setFont(f_reg, 6)
        p.drawCentredString(x + label_w/2, y + 3*mm, f"Futár: {f_name} | {f_phone}")
        
    p.save(); buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")
c1, c2 = st.columns(2)
with c1: f_nev = st.text_input("Futár neve", "Szűcs István")
with c2: f_tel = st.text_input("Telefonszám", "+36 20 886 8971")

files = st.file_uploader("Menetterv PDF feltöltése", accept_multiple_files=True)

if files and st.button("📊 FELDOLGOZÁS"):
    all_raw = []
    for f in files: all_raw.extend(parse_interfood_pro(f))
    
    if all_raw:
        df_raw = pd.DataFrame(all_raw)
        # Csoportosítás (Péntek+Szombat összevonás itt történik az ID alapján)
        df = df_raw.groupby('ID').agg({
            'Ügyintéző': 'first',
            'Telefon': 'first',
            'Cím': 'first',
            'Rendelés': lambda x: [i for s in x for i in s],
            'Pénz': 'sum',
            'Nap': lambda x: "+".join(sorted(list(set(x))))
        }).reset_index()
        
        df['Össz db'] = df['Rendelés'].apply(len)
        
        # Súlyozás (fix sorrend) alkalmazása
        weights = load_weights()
        df['Weight'] = df['ID'].map(weights).fillna(999).astype(int)
        df = df.sort_values(by=['Weight', 'ID']).reset_index(drop=True)
        df['Sorrend'] = range(1, len(df)+1)
        
        st.session_state.mdf = df
        st.rerun()

if 'mdf' in st.session_state:
    st.info("Itt módosíthatod a sorrendet vagy a pénzösszeget.")
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("💾 SORREND MENTÉSE"):
            save_weights(edited)
    with col_b2:
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            pdf_out = create_label_pdf(edited, f_nev, f_tel)
            st.download_button("PDF Mentése", pdf_out, "etikettek.pdf", "application/pdf")
