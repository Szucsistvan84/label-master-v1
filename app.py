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

# --- ALAPBEÁLLÍTÁSOK ---
VERZIO = "v203.59"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")
st.title(f"Interfood Logisztika {VERZIO} - Stabil verzió")

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERÉS (VISSZAÁLLÍTVA A RÉGI STABILRA) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    # Régi, bevált pénzkereső minta
    money_pat = r'(\d[\d\s]*)\s*Ft'

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
            
            for y in sorted(lines_dict.keys()):
                line_words = sorted(lines_dict[y], key=lambda x: x['x0'])
                full_text = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', full_text)
                
                if u_code_m:
                    prefix, uid = u_code_m.group(0).split('-')[0], u_code_m.group(0).split('-')[-1]
                    b3_addr = " ".join([w['text'] for w in line_words if 160 <= w['x0'] < 355])
                    b4_name = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                    
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4_name).strip()
                    tel_m = re.search(phone_pat, full_text.replace(" ", ""))
                    money_m = re.search(money_pat, full_text)

                    v_o, sq = [], 0
                    for o in re.findall(order_pat, full_text):
                        try:
                            q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                            v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                        except: continue
                    
                    if v_o:
                        rows.append({
                            "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                            "Cím": " ".join(b3_addr.split()), "Telefon": tel_m.group(0) if tel_m else "", 
                            "Rendelés": ", ".join(v_o), "Összesen": sq, 
                            "Pénz": money_m.group(0) if money_m and "0 Ft" not in money_m.group(0) else "",
                            "Kapukód": "" # Ideiglenesen kikapcsolva a bonyolult vadászat
                        })
    return rows

def merge_data(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            if not day_group.empty:
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(day_group['Rendelés'].tolist())}")
        base['Rendelés'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        m_vals = [m for m in group['Pénz'].unique() if m]
        base['Pénz'] = m_vals[0] if m_vals else ""
        merged.append(base)
    return merged

# --- PDF GENERÁLÁS ---
def create_manifest_pdf(df, futar_nev):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=9.5, leading=10.5)
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8.5, leading=10)

    rows_per_page = 24
    m_top, m_bot = 18*mm, 15*mm
    avail_h = h - m_top - m_bot - 10*mm
    row_h = (avail_h - 8*mm) / rows_per_page

    total_pages = math.ceil(len(df)/rows_per_page)
    for p_idx in range(total_pages):
        p.setFont(f_bold, 11); p.drawString(10*mm, h-12*mm, f"MENETTERV - {futar_nev}")
        p.setFont(f_reg, 8); p.drawRightString(w-10*mm, h-12*mm, f"{p_idx+1}/{total_pages} oldal")
        
        data = [["SOR", "ÜGYFÉL / CÍM", "[ ]", "TELEFON", "RENDELÉS", "DB", "PÉNZ"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        
        for _, r in subset.iterrows():
            client_p = Paragraph(f"{r['Ügyintéző']}<br/><font size=8>{r['Cím']}</font>", name_s)
            data.append([f"#{int(r['Sorrend'])}", client_p, "[ ]", r['Telefon'], Paragraph(r['Rendelés'], order_s), r['Összesen'], r['Pénz']])
        
        t = Table(data, colWidths=[10*mm, 62*mm, 8*mm, 24*mm, 62*mm, 8*mm, 18*mm], rowHeights=[8*mm] + [row_h]*len(subset))
        t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,0),f_bold),('GRID',(0,0),(-1,-1),0.4,colors.black),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(0,0),(0,-1),'CENTER'),('ALIGN',(-2,0),(-1,-1),'CENTER'),('LEFTPADDING',(1,0),(1,-1),3)]))
        t.wrapOn(p, w-10*mm, avail_h); t.drawOn(p, 5*mm, h - m_top - (len(subset)+1)*row_h)
        p.showPage()
    p.save(); buf.seek(0); return buf

def create_label_pdf(df, futar_nev, futar_tel):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 64*mm, 39*mm
    margin_x, margin_y = 7*mm, 6*mm
    gap_x, gap_y = 3*mm, 1.5*mm
    
    for i in range(math.ceil(len(df)/21)*21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = margin_x + col * (lw + gap_x), margin_y + row_i * (lh + gap_y)

        if i < len(df):
            p.setStrokeColor(colors.black); p.setLineWidth(0.3); p.rect(x, y, lw, lh)
            r = df.iloc[i]
            p.setFont(f_bold, 9); p.drawString(x+3*mm, y+34*mm, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 7); p.drawRightString(x+lw-3*mm, y+34*mm, f"{futar_nev} {futar_tel}")
            p.setFont(f_bold, 9); p.drawString(x+3*mm, y+29*mm, str(r['Ügyintéző'])[:35])
            p.setFont(f_reg, 8); p.drawRightString(x+lw-3*mm, y+29*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x+3*mm, y+25*mm, str(r['Cím'])[:45])
            p.setFont(f_reg, 7); p.drawString(x+3*mm, y+13*mm, str(r['Rendelés'])[:120])
            if r['Pénz']: p.setFont(f_bold, 9); p.drawString(x+3*mm, y+6*mm, f"FIZETENDŐ: {r['Pénz']}")
            p.setFont(f_bold, 8); p.drawRightString(x+lw-3*mm, y+6*mm, f"{r['Összesen']} db")
    p.save(); buf.seek(0); return buf

# --- UI ---
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    f_nev = st.text_input("Futár neve", "Szűcs István")
    f_tel = st.text_input("Futár telefonszáma", "+3620/886-89-71")
    if st.button("💾 SORREND MENTÉSE") and st.session_state.mdf is not None:
        st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
        st.success("Mentve!")

up = st.file_uploader("PDF feltöltése", accept_multiple_files=True)
if up and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up: raw.extend(parse_interfood_pdf(f))
    if raw:
        mdf = pd.DataFrame(merge_data(raw))
        if os.path.exists("user_prefs.csv"):
            prefs = pd.read_csv("user_prefs.csv").drop_duplicates(subset='ID')
            mdf['ID'] = mdf['ID'].astype(str); prefs['ID'] = prefs['ID'].astype(str)
            mdf = mdf.merge(prefs[['ID', 'Sorrend']], on='ID', how='left')
            mdf['Sorrend'] = mdf['Sorrend'].fillna(999.0)
        else: mdf['Sorrend'] = range(1, len(mdf) + 1)
        mdf = mdf.sort_values(by=['Sorrend', 'ID']).reset_index(drop=True)
        mdf['Sorrend'] = [float(i+1) for i in range(len(mdf))]
        st.session_state.mdf = mdf
        st.rerun()

if st.session_state.mdf is not None:
    st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    with c1: st.download_button("📋 MENETTERV PDF", create_manifest_pdf(st.session_state.mdf, f_nev), "menetterv.pdf")
    with c2: st.download_button("📥 ETIKETTEK PDF", create_label_pdf(st.session_state.mdf, f_nev, f_tel), "etikettek.pdf")
