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
    name = str(name).replace('\n', ' ')
    return re.sub(r'^[HKSCPZ]-\d+\s*', '', name).strip()

# --- PDF PARSER (P és Z sorok precíz kezelése) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"year": None, "week": None, "day": "", "route": ""}
    # Módosított minta: felismeri a P- és Z- kezdetű kódokat is
    id_pat = r'([PZ])-(\d{5,7})'
    
    with pdfplumber.open(pdf_file) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        meta["route"] = (re.search(r'(\d{4})\.\s*járat', first_text) or [None, "N/A"])[1]
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
                    money_match = re.search(r'(-?\d[\d\s]*)\s*Ft', txt)
                    money = int(re.sub(r'\s', '', money_match.group(1))) if money_match else 0
                    
                    # FIX: Biztonságos Regex keresés (IndexError elkerülése)
                    tel_match = re.search(r'\d{2}/\d{6,7}', txt.replace(" ", ""))
                    tel = tel_match.group(0) if tel_match else ""
                    
                    rendeles_match = re.search(r'(\d+-[A-Z0-9+*]+)', txt)
                    rendeles = rendeles_match.group(1) if rendeles_match else ""
                    
                    rows.append({
                        "ID": str(uid),
                        "Prefix": prefix,
                        "Ügyintéző": clean_customer_name(row[2]) if len(row)>2 else "Ismeretlen",
                        "Cím": str(row[1]).replace('\n', ' ') if len(row)>1 else "",
                        "Telefon": tel,
                        "Rendelés": rendeles,
                        "Pénz": money,
                        "Járat": meta["route"]
                    })
    return rows, meta

# --- ADAT ÖSSZEVONÁS (Péntek + Szombat azonos ID-re) ---
def merge_orders(raw_rows):
    if not raw_rows: return pd.DataFrame()
    temp_df = pd.DataFrame(raw_rows)
    merged = []
    
    for uid, group in temp_df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        
        p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
        
        o_parts = []
        if p_items: o_parts.append(f"Pé: {', '.join(p_items)}")
        if z_items: o_parts.append(f"Szo: {', '.join(z_items)}")
        
        base['Rendelés_Full'] = " | ".join(o_parts)
        # Darabszám összegzése a kódok elejéről (pl: "1-AK" -> 1)
        total_db = 0
        for r_str in group['Rendelés']:
            try: total_db += int(r_str.split('-')[0])
            except: pass
            
        base['Összesen'] = total_db
        base['Pénz_Total'] = group['Pénz'].sum()
        base['Pénz_Megjelenit'] = f"{base['Pénz_Total']} Ft" if base['Pénz_Total'] != 0 else "0 Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        
        # Sorszám kezelése: ha van mentett, azt kapja, ha nincs, marad 999 (lista vége)
        base['Sorrend'] = int(st.session_state.weights.get(str(uid), 999))
        merged.append(base)
        
    res = pd.DataFrame(merged)
    # Kényszerített sorrendezés a Sorrend oszlop alapján
    return res.sort_values(by=['Sorrend', 'ID']).reset_index(drop=True)

# --- PDF GENERÁLÁS ---
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
            p.rect(x+m, y+27.5*mm, lw-2*m, 4.5*mm, fill=1, stroke=0)
        
        p.setFillColor(colors.black)
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-m-2*mm, f"#{i+1}"); p.drawRightString(x+lw-m, y+lh-m-2*mm, f"ID: {r['ID']}")
        p.setFont(f_bold, 9); p.drawString(x+m, y+28*mm, r['Ügyintéző'][:24])
        p.setFont(f_reg, 7.5); p.drawRightString(x+lw-m, y+28*mm, r['Telefon'])
        p.setFont(f_reg, 7); p.drawString(x+m, y+24.5*mm, r['Cím'][:42])
        
        o_s = ParagraphStyle('o', fontName=f_reg, fontSize=7, leading=8)
        para = Paragraph(r['Rendelés_Full'], o_s)
        para.wrap(lw-2*m, 12*mm); para.drawOn(p, x+m, y+11*mm)
        
        p.setFont(f_bold, 9); p.drawString(x+m, y+7.5*mm, r['Pénz_Megjelenit'] if r['Pénz_Total'] > 0 else "")
        p.drawRightString(x+lw-m, y+7.5*mm, f"{r['Összesen']} db")
        p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4*mm, f"Futár: {fn} ({ft}) | Járat: {r['Járat']}")
        
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    # Menetterv (Nincs üres oldal az elején)
    y = h - 15*mm
    p.setFont(f_bold, 12); p.drawString(10*mm, y, f"MENETTERV - {fn} ({meta['day']})"); y -= 10*mm
    
    df['Addr_Key'] = df['Cím'].apply(lambda x: str(x).split(',')[0].strip())
    for _, group in df.groupby('Addr_Key', sort=False):
        is_group = len(group) > 1
        data = []
        for i, r in group.iterrows():
            # Valódi sorszám a listában: i+1
            data.append([f"#{i+1}", Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", ParagraphStyle('p', fontName=f_reg, fontSize=8)), r['Pénz_Megjelenit'], Paragraph(r['Rendelés_Full'], ParagraphStyle('p', fontName=f_reg, fontSize=7)), r['Összesen']])
        
        t = Table(data, colWidths=[12*mm, 63*mm, 25*mm, 75*mm, 15*mm])
        style = [('GRID', (0,0), (-1,-1), 0.2, colors.grey), ('VALIGN',(0,0),(-1,-1),'MIDDLE')]
        if is_group:
            style.append(('BACKGROUND', (0,0), (-1,-1), colors.lightgrey))
            style.append(('BOX', (0,0), (-1,-1), 1.2, colors.black))
        t.setStyle(TableStyle(style))
        tw, th = t.wrap(w-20*mm, h)
        if y - th < 20*mm: p.showPage(); y = h - 20*mm
        t.drawOn(p, 10*mm, y - th); y -= (th + 2*mm)

    # RAKLISTA ÉS ÖSSZESÍTŐ
    p.showPage(); y = h - 20*mm
    p.setFont(f_bold, 14); p.drawString(10*mm, y, "RAKODÁSI LISTA ÉS ÖSSZESÍTŐ"); y -= 15*mm
    
    total_money = df['Pénz_Total'].sum()
    commission = total_money * 0.13
    
    p.setFont(f_bold, 11)
    p.drawString(10*mm, y, f"Összes beszedendő készpénz: {total_money:,} Ft".replace(',', ' '))
    p.drawString(10*mm, y-7*mm, f"Jutalék (13%): {round(commission):,} Ft".replace(',', ' '))
    p.setFont(f_bold, 13)
    p.drawString(10*mm, y-16*mm, f"LEADANDÓ NETTÓ: {round(total_money - commission):,} Ft".replace(',', ' '))
    
    p.save(); buf.seek(0); return buf

# --- UI ---
st.set_page_config(page_title="Interfood Label Master", layout="wide")

if 'weights' not in st.session_state: st.session_state.weights = {}
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("Beállítások")
    f_csv = st.file_uploader("CSV visszatöltés (Sorrendhez)", type="csv")
    if f_csv:
        odf = pd.read_csv(f_csv)
        st.session_state.weights = dict(zip(odf['ID'].astype(str), odf['Sorrend']))
        st.session_state.notes = dict(zip(odf['ID'].astype(str), odf['Megjegyzés'].fillna("")))
    
    f_name = st.text_input("Futár neve", "Szűcs István")
    f_tel = st.text_input("Telefonszám", "+36 20 886 8971")
    pdf_files = st.file_uploader("Interfood PDF-ek feltöltése", accept_multiple_files=True)
    
    if pdf_files and st.button("📊 ADATOK FELDOLGOZÁSA"):
        all_raw = []
        for f in pdf_files:
            rows, meta = parse_interfood_pdf(f)
            all_raw.extend(rows)
            st.session_state.meta = meta
        st.session_state.mdf = merge_orders(all_raw)
        st.rerun()

if st.session_state.mdf is not None:
    st.subheader("Szerkeszthető Menetterv")
    # Megjelenítjük a táblázatot
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    if st.button("🔄 SORREND FRISSÍTÉSE ÉS ÚJRARENDEZÉS"):
        # Frissítjük a session state-et a táblázat aktuális értékeivel
        st.session_state.weights = dict(zip(edited['ID'].astype(str), edited['Sorrend']))
        st.session_state.notes = dict(zip(edited['ID'].astype(str), edited['Megjegyzés']))
        # Újraépítjük a DataFrame-et a mentett súlyok alapján
        st.session_state.mdf = merge_orders(st.session_state.mdf.to_dict('records'))
        st.success("Sorrend elmentve és táblázat frissítve!")
        st.rerun()

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1: st.download_button("🏷️ ETIKETTEK LETÖLTÉSE", create_label_pdf(edited, f_name, f_tel), "etikettek.pdf", use_container_width=True)
    with c2: st.download_button("📋 MENETTERV + ÖSSZESÍTŐ", create_manifest_pdf(edited, f_name, st.session_state.meta), "menetterv.pdf", use_container_width=True)
    with c3: st.download_button("💾 ADATOK MENTÉSE (CSV)", edited.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), "napi_mentes.csv", use_container_width=True)
