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

VERZIO = "v203.67-MARGIN-FIX"
WEIGHTS_FILE = "client_weights.csv"
NAP_MAP = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

# --- PDF FELDOLGOZÁS (CÍMMENTŐ LOGIKÁVAL) ---
def parse_interfood_pro(pdf_file):
    rows = []
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
                line_text = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(u_code_pat, line_text)
                
                if u_code_m:
                    uid = u_code_m.group(2)
                    nap_prefix = u_code_m.group(1) if u_code_m.group(1) else "S"
                    
                    # Környezet elemzése a hiányzó adatokhoz
                    context = []
                    for off in range(-3, 3):
                        if 0 <= i + off < len(sorted_y):
                            context.append(" ".join([w['text'] for w in lines_dict[sorted_y[i+off]]]))
                    full_ctx = " ".join(context)
                    
                    # NÉV (ha a saját sorában nincs, keresünk a context-ben)
                    name_parts = [w['text'] for w in line_words if 340 <= w['x0'] < 550]
                    clean_name = " ".join(name_parts).split('/')[0].strip()
                    if len(clean_name) < 3:
                        n_match = re.search(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-z-áéíóöőúüű]+\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-áéíóöőúüű]+)', full_ctx)
                        clean_name = n_match.group(1) if n_match else "Név nem található"

                    # CÍM (Irányítószám alapú keresés a környezetben)
                    addr_match = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][^,]+[^,]{5,})', full_ctx)
                    clean_addr = addr_match.group(1).strip() if addr_match else "Cím hiányzik"

                    phone_m = re.search(r'(\d{2}/\d{6,7})', full_ctx.replace(" ", ""))
                    money_m = re.search(money_pat, full_ctx)
                    money = int(re.sub(r'[^\d\-]', '', money_m.group(1))) if money_m else 0
                    
                    rows.append({
                        "ID": uid, "Ügyintéző": clean_name, "Telefon": phone_m.group(0) if phone_m else "",
                        "Cím": clean_addr, "Rendelés": list(set(re.findall(order_pat, full_ctx))),
                        "Pénz": money, "Nap": NAP_MAP.get(nap_prefix, "Sze"), "Original_Order": i
                    })
    return rows

# --- ETIKETT GENERÁLÁS (5MM MARGÓVAL) ---
def create_label_pdf(df, f_name, f_phone):
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    label_w, label_h = 70.0 * mm, 42.428 * mm
    m = 5*mm # 5mm margó minden oldalról

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = float(col * label_w), float(row_i * label_h)
        r = df.iloc[i]
        
        # Sorszám és ID (Margón belül)
        p.setFont("Helvetica", 7)
        p.drawString(x + m, y + label_h - m, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - m, y + label_h - m, f"ID: {r['ID']}")
        
        # Név és Telefon (Margón belül)
        p.setFont("Helvetica-Bold", 9)
        p.drawString(x + m, y + label_h - m - 5*mm, str(r['Ügyintéző'])[:22])
        p.setFont("Helvetica", 8)
        p.drawRightString(x + label_w - m, y + label_h - m - 5*mm, str(r['Telefon']))
        
        # Cím (Margón belül)
        p.setFont("Helvetica", 8)
        p.drawString(x + m, y + label_h - m - 9*mm, str(r['Cím'])[:42])
        
        # Rendelés
        p.setFont("Helvetica-Bold", 8.5)
        rend_txt = f"{r['Nap']}: {', '.join(r['Rendelés'])}"
        p.drawString(x + m, y + m + 10*mm, rend_txt[:60])
        
        # Fizetendő és darabszám (Az alsó margó felett)
        p.setFont("Helvetica-Bold", 10)
        p.drawRightString(x + label_w - m, y + m + 4*mm, f"{r['Össz db']} db")
        if int(r['Pénz']) > 0:
            p.drawString(x + m, y + m + 4*mm, f"FIZET: {r['Pénz']} Ft")
            
        # Futár infó (Legalul a margón belül)
        p.setFont("Helvetica", 6)
        p.drawCentredString(x + label_w/2, y + m - 2*mm, f"Futár: {f_name} | {f_phone}")
        
    p.save(); buf.seek(0); return buf

# --- UI LOGIKA ---
def load_weights():
    if os.path.exists(WEIGHTS_FILE):
        try: return pd.read_csv(WEIGHTS_FILE, dtype={'ID': str}).set_index('ID')['Weight'].to_dict()
        except: return {}
    return {}

st.title(f"Interfood Logisztika {VERZIO}")
c1, c2 = st.columns(2)
with c1: f_nev = st.text_input("Futár neve", "Szűcs István")
with c2: f_tel = st.text_input("Telefonszám", "+36 20 886 8971")

files = st.file_uploader("PDF feltöltése", accept_multiple_files=True)

if files and st.button("📊 FELDOLGOZÁS"):
    all_data = []
    for f in files: all_data.extend(parse_interfood_pro(f))
    
    if all_data:
        df = pd.DataFrame(all_data).drop_duplicates(subset=['ID', 'Nap'])
        df = df.groupby('ID').agg({
            'Ügyintéző': 'first', 'Telefon': 'first', 'Cím': 'first',
            'Rendelés': lambda x: [i for s in x for i in s],
            'Pénz': 'sum', 'Nap': lambda x: "+".join(sorted(list(set(x)))),
            'Original_Order': 'min'
        }).reset_index()
        
        df['Össz db'] = df['Rendelés'].apply(len)
        weights = load_weights()
        
        # Sorrend: Mentett súly vagy PDF sorrend
        df['Weight'] = df['ID'].map(weights).fillna(df['Original_Order'] + 1000).astype(int)
        df = df.sort_values(by='Weight').reset_index(drop=True)
        df['Sorrend'] = range(1, len(df) + 1)
        
        st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Rendelés', 'Pénz', 'Nap', 'Össz db']]

if 'mdf' in st.session_state:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("💾 SORREND MENTÉSE"):
            weights_df = edited[['ID', 'Sorrend']].rename(columns={'Sorrend': 'Weight'})
            weights_df.to_csv(WEIGHTS_FILE, index=False)
            st.success("Mentve!")
    with col_b:
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            pdf = create_label_pdf(edited, f_nev, f_tel)
            st.download_button("PDF Mentése", pdf, "etikettek.pdf")
    with col_c:
        csv = edited.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📝 EXPORT (CSV)", csv, "menetterv.csv")
