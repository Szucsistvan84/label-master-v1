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

VERZIO = "v203.59-RESTORED"
WEIGHTS_FILE = "client_weights.csv"

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

# --- BETŰK ÉS SÚLYOZÁS ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def load_weights():
    if os.path.exists(WEIGHTS_FILE):
        return pd.read_csv(WEIGHTS_FILE, dtype={'ID': str}).set_index('ID')['Weight'].to_dict()
    return {}

def save_weights(df):
    weights_df = df[['ID', 'Sorrend']].rename(columns={'Sorrend': 'Weight'})
    weights_df.to_csv(WEIGHTS_FILE, index=False)
    st.success("Súlyozás (sorrend) elmentve a háttérbe!")

def smart_round(x):
    try:
        cleaned = str(x).replace(" ", "").replace("Ft", "").replace("-", "0")
        val = float(cleaned)
        return int(5 * round(val/5))
    except: return 0

# --- A TEGNAPI MŰKÖDŐ LOGIKA VISSZAÁLLÍTÁSA ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    money_pat = r'(-?\d[\d\s\.]*)\s*Ft'
    
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
                
                u_code_m = re.search(r'S-([0-9]{5,7})', text_ws)
                if u_code_m:
                    uid = u_code_m.group(1)
                    
                    # NÉV és CÍM tisztítás (sávok alapján)
                    name_parts = [w['text'] for w in line_words if 340 <= w['x0'] < 510]
                    clean_name = " ".join(name_parts).split('/')[0].strip()
                    clean_name = re.sub(r'\s*-[A-Z/ \d\-]+$', '', clean_name).strip() # Sallangok le
                    
                    addr_parts = [w['text'] for w in line_words if 150 <= w['x0'] < 340]
                    clean_addr = " ".join(addr_parts).strip()
                    
                    phone_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                    
                    # PÉNZ KERESÉSE (nézzük a következő 2 sort is, ahogy írtad!)
                    found_money = 0
                    money_in_line = re.search(money_pat, text_ws)
                    if money_in_line:
                        found_money = smart_round(money_in_line.group(1))
                    else:
                        # Ha nincs az adott sorban, nézzük a következő két sort
                        for next_idx in range(1, 3):
                            if i + next_idx < len(sorted_y):
                                next_text = " ".join([w['text'] for w in lines_dict[sorted_y[i+next_idx]]])
                                if "S-" in next_text: break # Megállunk, ha jön a köv. ügyfél
                                m_match = re.search(money_pat, next_text)
                                if m_match:
                                    found_money = smart_round(m_match.group(1))
                                    break
                    
                    rows.append({
                        "ID": str(uid), "Ügyintéző": clean_name, "Telefon": phone_m.group(0) if phone_m else "",
                        "Cím": clean_addr, "Rendelés": re.findall(order_pat, text_ws), 
                        "Pénz": found_money, "Össz db": len(re.findall(order_pat, text_ws))
                    })
    return rows

# --- ETIKETT KÉPE ---
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
        p.drawString(x + 5*mm, y + 21*mm, f"Sze: {', '.join(r['Rendelés'])}"[:55])
        
        p.setFont(f_bold, 10)
        p.drawRightString(x + label_w - 5*mm, y + 10*mm, f"{r['Össz db']} db")
        if int(r['Pénz']) > 0:
            p.drawString(x + 5*mm, y + 10*mm, f"FIZET: {r['Pénz']} Ft")
        
        p.setStrokeColor(colors.lightgrey); p.setLineWidth(0.1)
        p.line(x + 5*mm, y + 8*mm, x + label_w - 5*mm, y + 8*mm)
        p.setFont(f_reg, 7)
        p.drawCentredString(x + label_w/2, y + 4*mm, f"Futár: {f_name} | {f_phone}")
        
    p.save(); buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

col_f1, col_f2 = st.columns(2)
with col_f1: f_nev = st.text_input("Futár neve", "Szűcs István")
with col_f2: f_tel = st.text_input("Telefonszám", "+36 20 886 8971")

uploaded_files = st.file_uploader("PDF fájlok", accept_multiple_files=True)

if uploaded_files and st.button("📊 FELDOLGOZÁS"):
    all_rows = []
    for f in uploaded_files: all_rows.extend(parse_interfood_pro(f))
    
    df = pd.DataFrame(all_rows).groupby('ID').agg({
        'Ügyintéző': 'first', 'Telefon': 'first', 'Cím': 'first',
        'Rendelés': lambda x: [i for s in x for i in s],
        'Pénz': 'sum', 'Össz db': 'sum'
    }).reset_index()
    
    weights = load_weights()
    df['Weight'] = df['ID'].map(weights).fillna(999).astype(int)
    df = df.sort_values(by=['Weight', 'ID']).reset_index(drop=True)
    df['Sorrend'] = range(1, len(df)+1)
    
    # OSZLOPREND: Sorrend, ID, Ügyintéző, Telefon...
    st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Telefon', 'Cím', 'Rendelés', 'Össz db', 'Pénz']]

if 'mdf' in st.session_state:
    st.info("💡 Állítsd be a sorrendet, majd nyomj a '💾 SORREND MENTÉSE' gombra!")
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.session_state.mdf = edited

    if st.button("💾 SORREND MENTÉSE"):
        save_weights(edited)
        st.rerun()

    if st.button("📥 ETIKETTEK LETÖLTÉSE"):
        pdf = create_label_pdf(st.session_state.mdf, f_nev, f_tel)
        st.download_button("Kattints ide a PDF mentéséhez", pdf, "etikettek.pdf", "application/pdf")
