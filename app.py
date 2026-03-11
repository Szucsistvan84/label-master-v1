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
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

# --- KONFIGURÁCIÓ ---
VERZIO = "v203.70-STABLE-MARGIN"
DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

def register_fonts():
    try:
        # Ha vannak saját betűtípusaid, itt regisztrálhatod őket
        return "Helvetica", "Helvetica-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- STABIL ADATKINYERÉS (v203.40 ALAPJÁN) ---
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
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w); break
                else: lines[y] = [w]
            
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                
                # ID keresés: S-123456 formátum
                u_code_m = re.search(r'([HKSCPZ])-([0-9]{6})', text_ws)
                if not u_code_m: continue
                
                prefix = u_code_m.group(1)
                uid = u_code_m.group(2)
                
                # Koordináta alapú kinyerés (ahogy a v203.40-ben működött)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                
                # Irányítószám alapú cím (szóközökkel határolt 4 számjegy)
                addr_m = re.search(r'(\s\d{4}\s)', " " + b3 + " ")
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q_str = re.sub(r'\D', '', o.split('-')[0])
                        q = int(q_str[-1]) if q_str else 1
                        v_o.append(f"{q}-{o.split('-')[1]}")
                        sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, 
                        "ID": uid, 
                        "Ügyintéző": clean_name, 
                        "Cím": clean_addr, 
                        "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), 
                        "Összesen": sq,
                        "Original_Order": y
                    })
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        base['HasSaturday'] = any(p == 'Z' for p in group['Prefix'])
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            if not day_group.empty:
                items = day_group['Rendelés'].tolist()
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- ETIKETT GENERÁLÁS 5MM-ES BELSŐ MARGÓVAL ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    # Etikett fizikai méretei (3x7-es rács A4-en)
    lw, lh = 70*mm, 42.4*mm
    # A BIZTONSÁGI MARGÓ (minden adat ezen belül marad)
    m = 5*mm 

    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9, alignment=0)

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col = idx % 3
        row_i = 6 - (idx // 3)
        
        x = col * lw
        y = row_i * lh
        
        r = df.iloc[i]
        
        # Keret (opcionális, de segít a vágásnál)
        p.setLineWidth(0.1)
        p.setStrokeColor(colors.lightgrey)
        p.rect(x, y, lw, lh)

        # 1. SOR: Sorszám balra, ID jobbra (Margón belül)
        p.setFont(f_bold, 8)
        p.drawString(x + m, y + lh - m, f"#{int(r['Sorrend'])}")
        p.setFont(f_reg, 7)
        p.drawRightString(x + lw - m, y + lh - m, f"ID: {r['ID']}")
        
        # 2. SOR: Név balra, Telefon jobbra
        p.setFont(f_bold, 9)
        p.drawString(x + m, y + lh - m - 5*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 8)
        p.drawRightString(x + lw - m, y + lh - m - 5*mm, str(r['Telefon']))
        
        # 3. SOR: Cím
        p.setFont(f_reg, 8)
        p.drawString(x + m, y + lh - m - 10*mm, str(r['Cím'])[:40])
        
        # 4. SOR: Rendelések (Paragraph a tördeléshez)
        para = Paragraph(r['Rendelés_Full'], order_s)
        para.wrap(lw - 2*m, 12*mm) # A szélesség a margók miatt csökkentve
        para.drawOn(p, x + m, y + m + 6*mm)
        
        # ALSÓ SOR: Összesen és Futár
        p.setFont(f_bold, 9)
        p.drawRightString(x + lw - m, y + m + 2*mm, f"{r['Összesen']} db")
        
        p.setFont(f_reg, 6)
        p.drawString(x + m, y + m - 2*mm, f"Futár: {fn} | {ft}")

    p.save()
    buf.seek(0)
    return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+36 20 886 8971")
    if st.button("💾 SORREND MENTÉSE"):
        if st.session_state.mdf is not None:
            st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
            st.success("Mentve!")

up_files = st.file_uploader("Menetterv PDF feltöltés", accept_multiple_files=True)

if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_pro(f))
    if raw:
        merged_data = merge_data_flexible(raw)
        mdf = pd.DataFrame(merged_data)
        
        # Sorrend kezelése
        if os.path.exists("user_prefs.csv"):
            prefs = pd.read_csv("user_prefs.csv", dtype={'ID': str}).drop_duplicates(subset='ID')
            mdf = mdf.merge(prefs, on='ID', how='left')
            mdf['Sorrend'] = mdf['Sorrend'].fillna(999).astype(float)
        else:
            mdf['Sorrend'] = range(1, len(mdf) + 1)
            mdf['Sorrend'] = mdf['Sorrend'].astype(float)
            
        mdf = mdf.sort_values(by=['Sorrend', 'Original_Order']).reset_index(drop=True)
        mdf['Sorrend'] = range(1, len(mdf) + 1)
        
        st.session_state.mdf = mdf
        st.rerun()

if st.session_state.get('mdf') is not None:
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    if st.button("📥 ETIKETTEK LETÖLTÉSE (5mm margóval)"):
        pdf = create_label_pdf(edited_df, fn_in, ft_in)
        st.download_button("PDF Mentése", pdf, "etikettek_javitott.pdf")
