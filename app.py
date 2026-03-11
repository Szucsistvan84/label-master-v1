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
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# --- KONFIGURÁCIÓ ---
VERZIO = "v203.75-FINAL-FIX"
DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

# --- BETŰTÍPUS ÉS ÉKEZET KEZELÉS ---
def register_fonts():
    # Megpróbáljuk betölteni a magyar ékezeteket ismerő betűtípust
    # Ha a fájl mellett van a .ttf, azt használja, ha nincs, marad a Helvetica (de az ékezetes lesz)
    try:
        if os.path.exists("DejaVuSans.ttf"):
            pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
            pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
            return "DejaVu", "DejaVu-Bold"
    except:
        pass
    return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERÉS (v203.40 STABIL LOGIKA + PÉNZ) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    
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
                
                u_code_m = re.search(r'([HKSCPZ])-([0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                prefix = u_code_m.group(1)
                uid = u_code_m.group(2)
                
                # Koordináta alapú kinyerés (v203.40)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                
                # Pénzösszeg kinyerése
                money = 0
                m_match = re.search(money_pat, text_ws)
                if m_match:
                    try: money = int(re.sub(r'[^\d\-]', '', m_match.group(1)))
                    except: pass

                addr_m = re.search(r'(\d{4})', b3)
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
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, 
                        "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), 
                        "Pénz": money, "Összesen": sq, "Original_Order": y
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
        base['Pénz'] = group['Pénz'].sum()
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- ETIKETT 5MM MARGÓVAL ÉS ÉKEZETTEL ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm
    m = 5*mm # FIX 5MM BELSŐ MARGÓ

    order_style = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        r = df.iloc[i]

        # Sorszám és ID (Felső margó)
        p.setFont(f_bold, 8)
        p.drawString(x + m, y + lh - m, f"#{int(r['Sorrend'])}")
        p.setFont(f_reg, 7)
        p.drawRightString(x + lw - m, y + lh - m, f"ID: {r['ID']}")

        # Név és Telefon
        p.setFont(f_bold, 9)
        p.drawString(x + m, y + lh - m - 5*mm, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 8)
        p.drawRightString(x + lw - m, y + lh - m - 5*mm, str(r['Telefon']))

        # Cím
        p.setFont(f_reg, 8)
        p.drawString(x + m, y + lh - m - 10*mm, str(r['Cím'])[:45])

        # Rendelés közép tájon
        para = Paragraph(r['Rendelés_Full'], order_style)
        para.wrap(lw - 2*m, 12*mm)
        para.drawOn(p, x + m, y + m + 7*mm)

        # Alsó sor (Alsó margó)
        if int(r['Pénz']) > 0:
            p.setFont(f_bold, 10)
            p.drawString(x + m, y + m + 2*mm, f"FIZET: {int(r['Pénz'])} Ft")
        
        p.setFont(f_bold, 9)
        p.drawRightString(x + lw - m, y + m + 2*mm, f"{r['Összesen']} db")

        p.setFont(f_reg, 6)
        p.drawCentredString(x + lw/2, y + m - 3*mm, f"Futár: {fn} | {ft}")

    p.save(); buf.seek(0); return buf

# --- MENETTERV GENERÁLÓ ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    style = ParagraphStyle('TableText', fontName=f_reg, fontSize=8)
    
    data = [["SOR", "NÉV / CÍM", "TELEFON", "RENDELÉS", "PÉNZ", "DB"]]
    for _, r in df.iterrows():
        name_cell = Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", style)
        data.append([f"#{int(r['Sorrend'])}", name_cell, r['Telefon'], r['Rendelés_Full'], f"{int(r['Pénz'])} Ft", r['Összesen']])
    
    t = Table(data, colWidths=[12*mm, 60*mm, 25*mm, 60*mm, 20*mm, 10*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTNAME', (0,0), (-1,0), f_bold), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    
    tw, th = t.wrap(w-20*mm, h-40*mm)
    t.drawOn(p, 10*mm, h - 20*mm - th)
    p.save(); buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+36 20 886 8971")

up_files = st.file_uploader("PDF feltöltés", accept_multiple_files=True)

if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_pro(f))
    if raw:
        mdf = pd.DataFrame(merge_data_flexible(raw))
        mdf['Sorrend'] = range(1, len(mdf) + 1)
        st.session_state.mdf = mdf
        st.rerun()

if st.session_state.get('mdf') is not None:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("📥 ETIKETTEK"):
            st.download_button("PDF Mentése", create_label_pdf(edited, fn_in, ft_in), "etikettek.pdf")
    with c2:
        if st.button("📋 MENETTERV"):
            st.download_button("PDF Mentése", create_manifest_pdf(edited, fn_in), "menetterv.pdf")
    with c3:
        if st.button("💾 SORREND MENTÉSE"):
            edited[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
            st.success("Mentve!")
