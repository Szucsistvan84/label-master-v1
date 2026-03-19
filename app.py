import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
import requests

# --- FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

def clean_customer_name(name):
    if not name: return ""
    return re.sub(r'^[HKSCPZ]-\d+\s*', '', str(name)).strip()

# --- PDF PARSER (P és Z sorok kezelése) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"year": None, "week": None, "day": "", "route": ""}
    # Módosított minta: felismeri a P- és Z- kezdetű kódokat is
    id_pat = r'([PZ])-(\d{5,7})'
    
    with pdfplumber.open(pdf_file) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        meta["route"] = (re.search(r'(\d{4})\.\s*járat', first_text) or [None, ""])[1]
        meta["year"] = (re.search(r'Év:\s*(\d{4})', first_text) or [None, ""])[1]
        meta["day"] = (re.search(r'Nap:\s*([^ ]+)', first_text) or [None, ""])[1].replace(',', '')

        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                if not row or len(row) < 3: continue
                txt = " ".join([str(c) for c in row if c])
                match = re.search(id_pat, txt)
                if match:
                    prefix, uid = match.groups()
                    # Rendelés és Pénz kinyerése (Interfood formátum)
                    money_match = re.search(r'(-?\d[\d\s]*)\s*Ft', txt)
                    money = int(re.sub(r'\s', '', money_match.group(1))) if money_match else 0
                    
                    rows.append({
                        "ID": uid,
                        "Prefix": prefix, # P vagy Z
                        "Ügyintéző": row[2] if len(row)>2 else "Ismeretlen",
                        "Cím": row[1] if len(row)>1 else "",
                        "Telefon": (re.search(r'\d{2}/\d{6,7}', txt) or [None, ""])[1],
                        "Rendelés": (re.search(r'(\d+-[A-Z0-9+*]+)', txt) or [None, ""])[1],
                        "Pénz": money,
                        "Járat": meta["route"]
                    })
    return rows, meta

# --- ADAT ÖSSZEVONÁS (Péntek + Szombat egybe) ---
def merge_orders(raw_rows):
    if not raw_rows: return pd.DataFrame()
    df = pd.DataFrame(raw_rows)
    merged = []
    
    for uid, group in df.groupby("ID", sort=False):
        # Alapadatok az első sorból
        base = group.iloc[0].copy().to_dict()
        
        p_orders = group[group['Prefix'] == 'P']['Rendelés'].tolist()
        z_orders = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
        
        o_str = []
        if p_orders: o_str.append(f"Pé: {', '.join(p_orders)}")
        if z_orders: o_str.append(f"Szo: {', '.join(z_orders)}")
        
        base['Rendelés_Full'] = " | ".join(o_str)
        base['Összesen'] = len(p_orders) + len(z_orders)
        base['Pénz_Total'] = group['Pénz'].sum()
        base['Pénz_Megjelenit'] = f"{base['Pénz_Total']} Ft" if base['Pénz_Total'] != 0 else "0 Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        base['Sorrend'] = st.session_state.weights.get(str(uid), 999)
        merged.append(base)
        
    res = pd.DataFrame(merged)
    return res.sort_values('Sorrend').reset_index(drop=True)

# --- PDF GENERÁLÁS (Etikett + Menetterv + Raklista) ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh, m = 70*mm, 42.42*mm, 5*mm
    
    for i, r in df.iterrows():
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        x, y = (idx % 3) * lw, (6 - (idx // 3)) * lh
        
        if "Szo:" in r['Rendelés_Full']:
            p.setFillColor(colors.lightgrey)
            p.rect(x+m, y+27*mm, lw-2*m, 5*mm, fill=1, stroke=0)
        
        p.setFillColor(colors.black)
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-m-2*mm, f"#{i+1}"); p.drawRightString(x+lw-m, y+lh-m-2*mm, f"ID: {r['ID']}")
        p.setFont(f_bold, 9); p.drawString(x+m, y+28*mm, clean_customer_name(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 7.5); p.drawRightString(x+lw-m, y+28*mm, str(r['Telefon']))
        p.setFont(f_reg, 7); p.drawString(x+m, y+24*mm, str(r['Cím'])[:45])
        
        # Rendelés
        o_style = ParagraphStyle('o', fontName=f_reg, fontSize=7, leading=8)
        para = Paragraph(r['Rendelés_Full'], o_style)
        para.wrap(lw-2*m, 12*mm); para.drawOn(p, x+m, y+11*mm)
        
        # Fizetendő (Emelt margó a vágás ellen)
        p.setFont(f_bold, 9); p.drawString(x+m, y+7.5*mm, r['Pénz_Megjelenit'] if r['Pénz_Total'] > 0 else "")
        p.drawRightString(x+lw-m, y+7.5*mm, f"{r['Összesen']} db")
        p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4*mm, f"Futár: {fn} ({ft}) | Járat: {r['Járat']}")
        
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    # Menetterv
    y = h - 15*mm
    p.setFont(f_bold, 12); p.drawString(10*mm, y, f"MENETTERV - {fn} ({meta['day']})"); y -= 10*mm
    
    df['Addr_Key'] = df['Cím'].apply(lambda x: str(x).split(',')[0].strip())
    for addr, group in df.groupby('Addr_Key', sort=False):
        is_group = len(group) > 1
        data = []
        for i, r in group.iterrows():
            data.append([f"#{i+1}", Paragraph(f"<b>{clean_customer_name(r['Ügyintéző'])}</b><br/>{r['Cím']}", ParagraphStyle('p', fontName=f_reg, fontSize=8)), r['Pénz_Megjelenit'], Paragraph(r['Rendelés_Full'], ParagraphStyle('p', fontName=f_reg, fontSize=7)), r['Összesen']])
        
        t = Table(data, colWidths=[10*mm, 65*mm, 25*mm, 75*mm, 15*mm])
        style = [('GRID', (0,0), (-1,-1), 0.2, colors.grey), ('VALIGN',(0,0),(-1,-1),'MIDDLE')]
        if is_group:
            style.append(('BACKGROUND', (0,0), (-1,-1), colors.lightgrey))
            style.append(('BOX', (0,0), (-1,-1), 1.2, colors.black))
        t.setStyle(TableStyle(style))
        tw, th = t.wrap(w-20*mm, h)
        if y - th < 20*mm: p.showPage(); y = h - 20*mm
        t.drawOn(p, 10*mm, y - th); y -= (th + 2*mm)

    # Raklista + Összesítő
    p.showPage(); y = h - 20*mm
    p.setFont(f_bold, 14); p.drawString(10*mm, y, "RAKODÁSI LISTA ÖSSZESÍTŐ"); y -= 15*mm
    
    total_money = df['Pénz_Total'].sum()
    commission = total_money * 0.13
    
    # Itt a raklista tételei jönnének...
    y -= 20*mm
    p.setFont(f_bold, 12)
    p.drawString(10*mm, y, f"Összes beszedendő: {total_money} Ft")
    p.drawString(10*mm, y-7*mm, f"Jutalék (13%): {round(commission)} Ft")
    p.drawString(10*mm, y-14*mm, f"Leadandó: {round(total_money - commission)} Ft")
    
    p.save(); buf.seek(0); return buf

# --- UI ---
st.set_page_config(layout="wide")
if 'weights' not in st.session_state: st.session_state.weights = {}
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("Beállítások")
    f_csv = st.file_uploader("CSV visszatöltés", type="csv")
    if f_csv:
        odf = pd.read_csv(f_csv)
        st.session_state.weights = dict(zip(odf['ID'].astype(str), odf['Sorrend']))
        st.session_state.notes = dict(zip(odf['ID'].astype(str), odf['Megjegyzés'].fillna("")))
    
    f_name = st.text_input("Futár", "Szűcs István")
    f_tel = st.text_input("Telefon", "+36 20 886 8971")
    pdf_files = st.file_uploader("PDF-ek", accept_multiple_files=True)
    
    if pdf_files and st.button("📊 FELDOLGOZÁS"):
        all_raw = []
        for f in pdf_files:
            rows, meta = parse_interfood_pdf(f)
            all_raw.extend(rows)
            st.session_state.meta = meta
        st.session_state.mdf = merge_orders(all_raw)
        st.rerun()

if st.session_state.mdf is not None:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    if st.button("🔄 SORREND FRISSÍTÉSE ÉS RENDEZÉS"):
        # Mentjük a módosított sorszámokat a session-be
        st.session_state.weights = dict(zip(edited['ID'].astype(str), edited['Sorrend']))
        st.session_state.notes = dict(zip(edited['ID'].astype(str), edited['Megjegyzés']))
        # Újrarendezzük az eredeti adatot
        st.session_state.mdf = merge_orders(st.session_state.mdf.to_dict('records'))
        st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1: st.download_button("🏷️ ETIKETTEK", create_label_pdf(edited, f_name, f_tel), "etikettek.pdf")
    with c2: st.download_button("📋 MENETTERV", create_manifest_pdf(edited, f_name, st.session_state.meta), "menetterv.pdf")
    with c3: st.download_button("💾 CSV MENTÉS", edited.to_csv(index=False).encode('utf-8-sig'), "mentes.csv")
