import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import datetime
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle, PageBreak
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
    name = re.sub(r'^[HKSCPZ]-\d+\s*', '', name)
    name = re.sub(r'\s*[HKSCPZ]-\d+$', '', name)
    return name.strip()

# --- ADATKEZELÉS & CSV ---
def save_to_csv(df):
    return df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')

# --- PDF PARSER (Metaadatokkal) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"year": None, "week": None, "day": "", "route": ""}
    with pdfplumber.open(pdf_file) as pdf:
        first_page = pdf.pages[0].extract_text() or ""
        first_line = first_page.split('\n')[0]
        meta["route"] = (re.search(r'(\d{4})\.\s*járat', first_line) or [None, ""])[1]
        meta["year"] = int((re.search(r'Év:\s*(\d{4})', first_line) or [None, 0])[1])
        meta["week"] = int((re.search(r'Hét:\s*(\d{1,2})', first_line) or [None, 0])[1])
        meta["day"] = (re.search(r'Nap:\s*([^ ]+)', first_line) or [None, ""])[1].replace(',', '').strip()

        for page in pdf.pages:
            # Itt a korábban kidolgozott részletes sor-alapú feldolgozó futna...
            # (A rövidség kedvéért a logikát a korábbi válaszokból emeljük át)
            pass 
    return rows, meta

# --- ETIKETT GENERÁLÁS (5mm MARGÓ + SZOMBATI SZÜRKE) ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    m = 5*mm # Biztonsági margó
    
    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        r = df.iloc[i]
        is_saturday = "Szo:" in str(r['Rendelés_Full'])

        # 1. Szombati kiemelés (Szürke sáv a név alatt)
        if is_saturday:
            p.setFillColor(colors.lightgrey)
            p.rect(x + m, y + lh - 12.5*mm, lw - 2*m, 4.5*mm, fill=1, stroke=0)

        p.setFillColor(colors.black)
        # 2. Fejléc adatok (Kicsinyített méret)
        p.setFont(f_reg, 7); p.drawString(x + m, y + lh - m - 2*mm, f"#{i+1}")
        p.drawRightString(x + lw - m, y + lh - m - 2*mm, f"ID: {r['ID']}")
        
        # 3. Név és Telefon (Erősebb kiemelés)
        p.setFont(f_bold, 8.5)
        p.drawString(x + m, y + lh - 11.5*mm, clean_customer_name(str(r['Ügyintéző']))[:24])
        p.setFont(f_reg, 7.5)
        p.drawRightString(x + lw - m, y + lh - 11.5*mm, str(r['Telefon']))
        
        # 4. Cím (Margón belül)
        p.setFont(f_reg, 7); p.drawString(x + m, y + lh - 16*mm, str(r['Cím'])[:38])
        
        # 5. Rendelés (Kisebb betű, hogy ne lógjon ki)
        o_style = ParagraphStyle('Order', fontName=f_reg, fontSize=7, leading=8)
        para = Paragraph(str(r['Rendelés_Full']), o_style)
        para.wrap(lw - 2*m, 14*mm)
        para.drawOn(p, x + m, y + 10*mm)
        
        # 6. Alsó sor
        if "0 Ft" not in str(r['Pénz']):
            p.setFont(f_bold, 9); p.drawString(x + m, y + 6*mm, f"FIZET: {r['Pénz']}")
        p.setFont(f_bold, 8); p.drawRightString(x + lw - m, y + 6*mm, f"{r['Összesen']} db")
        
        # Futár adatok legalsó sorban
        p.setFont(f_reg, 5.5); p.drawCentredString(x + lw/2, y + 2*mm, f"Futár: {fn} | Járat: {r.get('Járat', 'N/A')}")
    
    p.save(); buf.seek(0); return buf

# --- MENETTERV CSOPORTOSÍTÁSSAL & RAKLISTA OLDALTÖRÉSSEL ---
def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    # Csoportosítás cím alapján
    df['Addr_Key'] = df['Cím'].apply(lambda x: str(x).split(',')[0].strip())
    
    # --- MENETTERV OLDALAK ---
    # (Itt a korábbi táblázatos generáló fut, de kiegészítve a csoportosító logikával)
    # A lényeg: groupby('Addr_Key') -> ha len > 1, akkor BACKGROUND=lightgrey, BOX=1.5
    
    # --- RAKLISTA (Oldaltörés kezelése) ---
    p.showPage()
    y_pos = h - 20*mm
    p.setFont(f_bold, 14); p.drawString(10*mm, y_pos, "RAKODÁSI LISTA")
    y_pos -= 10*mm
    
    # Tételek listázása (Példa ciklus az oldaltöréshez)
    for i in range(100): # Tegyük fel, hogy sok tétel van
        if y_pos < 30*mm:
            p.showPage()
            y_pos = h - 20*mm
        p.setFont(f_reg, 9); p.drawString(15*mm, y_pos, f"Étel kód {i} - Megnevezés...")
        y_pos -= 6*mm
        
    p.save(); buf.seek(0); return buf

# --- UI ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")

# Állapotkezelés
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta' not in st.session_state: st.session_state.meta = {}

with st.sidebar:
    st.header("📂 Adatok")
    
    # 1. CSV VISSZATÖLTÉS
    prev_csv = st.file_uploader("Tegnapi sorrend betöltése (CSV)", type="csv")
    if prev_csv:
        old_df = pd.read_csv(prev_csv)
        st.session_state.weights = dict(zip(old_df['ID'].astype(str), old_df['Sorrend']))
        st.sidebar.success("Sorrend betöltve!")

    st.divider()
    runner_name = st.text_input("Futár", "Szűcs István")
    runner_tel = st.text_input("Telefon", "+36 20 886 8971")
    
    files = st.file_uploader("Napi PDF-ek", accept_multiple_files=True)
    if files and st.button("📊 FELDOLGOZÁS"):
        # Itt futna a beolvasás...
        st.session_state.mdf = pd.DataFrame() # Példa
        st.rerun()

# FŐOLDAL GOMBOK
if st.session_state.mdf is not None:
    # 1. SZERKESZTHETŐ TÁBLÁZAT
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.download_button("🏷️ ETIKETTEK (PDF)", 
                           create_label_pdf(edited_df, runner_name, runner_tel), 
                           "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 MENETTERV + RAKLISTA", 
                           create_manifest_pdf(edited_df, runner_name, st.session_state.meta), 
                           "menetterv.pdf", use_container_width=True)
    with c3:
        # 2. CSV EXPORT (Hogy holnap vissza tudd tölteni)
        csv_data = save_to_csv(edited_df)
        st.download_button("💾 SORREND MENTÉSE (CSV)", 
                           csv_data, 
                           f"mentes_{datetime.date.today()}.csv", 
                           "text/csv", use_container_width=True)
