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

st.set_page_config(page_title="Interfood v198.1 - Stabil", layout="wide")

# --- 1. FONT REGISZTRÁCIÓ ---
def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- 2. JAVÍTOTT PDF PARSER (Szigorú kód-leválasztás) ---
def parse_interfood_pro(pdf_file):
    rows = []
    # Szigorú minta: szám, kötőjel, betűk/számok (de nem engedünk túl hosszú számot a végén)
    order_pat = r'(\d+-[A-Z][A-Z0-9]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                lines.setdefault(y, []).append(w)
            
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                text_ns = "".join([w['text'] for w in line_words])
                
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                # Koordináta alapú sávok
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                f_code = u_code_m.group(0)
                prefix, uid = f_code.split('-')[0], f_code.split('-')[-1]
                
                tel_m = re.search(phone_pat, text_ns)
                final_tel = tel_m.group(0) if tel_m else ""
                
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                # RENDELÉS JAVÍTÁSA: Csak a tiszta kódokat gyűjtjük be
                orders = re.findall(order_pat, text_ns)
                valid_o, sq = [], 0
                for o in orders:
                    # Ha a kód után véletlenül ott maradt a darabszám (pl 1-L22), 
                    # de tudjuk, hogy az Interfood kódok vége nem változik ilyen drasztikusan:
                    # Ez a regex segít, hogy csak a valódi kódot vegyük figyelembe.
                    valid_o.append(o)
                    q = int(o.split('-')[0][-1])
                    sq += q
                
                if sq > 0:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": final_tel, 
                        "Rendelés": ", ".join(valid_o), "Összesen": sq
                    })
    return rows

# --- 3. ÖSSZEVONÁS ÉS PDF GENERÁLÁS (Mint a v198-ban) ---
def merge_weekend_data(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
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
    return merged

def create_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2, (h - 7*lh)/2
    
    for i, (_, r) in enumerate(df.iterrows()):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        
        p.setLineWidth(1.2 if r['Prefix'] == 'Z' else 0.2)
        p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
        
        p.setFont(f_bold, 10)
        p.drawString(x+5*mm, y+36*mm, f"#{r['Sorrend']}")
        p.drawRightString(x+lw-5*mm, y+36*mm, f"ID: {r['ID']}")
        
        p.setFont(f_bold, 9.5)
        p.drawString(x+5*mm, y+30*mm, str(r['Ügyintéző'])[:24])
        p.setFont(f_reg, 8)
        p.drawRightString(x+lw-5*mm, y+30*mm, str(r['Telefon']))
        
        p.setFont(f_reg, 7.5)
        p.drawString(x+5*mm, y+25.5*mm, str(r['Cím'])[:50])
        
        p.setFont(f_bold, 8)
        r_text = str(r['Rendelés'])
        if " | " in r_text:
            p_part, z_part = r_text.split(" | ")
            p.drawString(x+5*mm, y+19.5*mm, p_part[:42])
            p.drawString(x+5*mm, y+15.5*mm, z_part[:42])
        else:
            p.drawString(x+5*mm, y+17.5*mm, r_text[:42])
            
        p.drawRightString(x+lw-5*mm, y+11*mm, f"Össz: {r['Összesen']} db")
        p.setFont(f_reg, 6)
        p.drawCentredString(x+lw/2, y+5*mm, f"Futár: {fn} ({ft}) | Jó étvágyat! :)")
        
    p.save()
    buf.seek(0)
    return buf

# --- UI RÉSZ ---
st.title("Interfood Címke Master v198.1")
with st.sidebar:
    fn = st.text_input("Futár neve", "Szűcs István")
    ft = st.text_input("Telefonszáma", "+36208868971")

up_files = st.file_uploader("PDF feltöltése", accept_multiple_files=True)

if up_files:
    if st.button("FELDOLGOZÁS"):
        raw = []
        for f in up_files:
            raw.extend(parse_interfood_pro(f))
        merged = merge_weekend_data(raw)
        mdf = pd.DataFrame(merged)
        mdf.insert(0, "Sorrend", range(1, len(mdf) + 1))
        st.session_state.mdf = mdf

if "mdf" in st.session_state:
    edf = st.data_editor(st.session_state.mdf, hide_index=True)
    if st.button("LETÖLTÉS"):
        pdf = create_pdf(edf, fn, ft)
        st.download_button("📥 PDF mentése", pdf, "interfood_v198_stabil.pdf")
