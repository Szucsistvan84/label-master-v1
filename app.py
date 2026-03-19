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

# --- STABIL FONT KEZELÉS ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- AZ EREDETI, JÓL MŰKÖDŐ PDF PARSER (Változatlanul) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"day": "N/A", "route": "N/A"}
    with pdfplumber.open(pdf_file) as pdf:
        first_page = pdf.pages[0].extract_text() or ""
        route_m = re.search(r'(\d{4})\.\s*járat', first_page)
        if route_m: meta["route"] = route_m.group(1)
        day_m = re.search(r'Nap:\s*([^ ]+)', first_page)
        if day_m: meta["day"] = day_m.group(1).replace(',', '')

        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                if not row or len(row) < 5: continue
                
                # Visszatérés a régi, stabil oszlop-indexekhez
                raw_client = str(row[1]).replace('\n', ' ')
                id_match = re.search(r'([PZ])-(\d{5,7})', raw_client)
                
                if id_match:
                    prefix, uid = id_match.groups()
                    raw_content = str(row[3]).replace('\n', ' ')
                    
                    # Régi, bevált regexek
                    tel = (re.search(r'\d{2}/\d{6,7}', raw_content.replace(" ","")) or [None, ""])[1]
                    money_m = re.search(r'(-?\d[\d\s]*)\s*Ft', raw_content)
                    money = int(re.sub(r'[^\d-]', '', money_m.group(1))) if money_m else 0
                    order_m = re.search(r'(\d+-[A-Z0-9+*]+)', raw_content)
                    
                    rows.append({
                        "ID": uid,
                        "Prefix": prefix,
                        "Ügyintéző": str(row[2]).strip(),
                        "Cím": raw_client.split(f"{prefix}-{uid}")[0].strip(),
                        "Telefon": tel,
                        "Rendelés": order_m.group(1) if order_m else "",
                        "Pénz": money,
                        "Járat": meta["route"]
                    })
    return rows, meta

# --- LOGIKA: P+Z ÖSSZEVONÁS (A fejlődés iránya) ---
def consolidate_data(raw_rows):
    if not raw_rows: return pd.DataFrame()
    df = pd.DataFrame(raw_rows)
    final_data = []
    
    for uid, group in df.groupby("ID", sort=False):
        # Az alap adatokat az első sorból vesszük
        base = group.iloc[0].copy().to_dict()
        
        # Rendelések összefűzése napok szerint
        p_items = group[group['Prefix'] == 'P']['Rendelés'].unique()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].unique()
        
        o_list = []
        if len(p_items) > 0: o_list.append(f"Pé: {', '.join(p_items)}")
        if len(z_items) > 0: o_list.append(f"Szo: {', '.join(z_items)}")
        
        base['Rendelés_Full'] = " | ".join(o_list)
        base['Összesen'] = sum([int(r.split('-')[0]) for r in group['Rendelés'] if '-' in str(r)])
        base['Pénz_Total'] = group['Pénz'].sum()
        
        # Sorszám és Megjegyzés megtartása
        base['Sorrend'] = int(st.session_state.weights.get(str(uid), 999))
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        final_data.append(base)
        
    return pd.DataFrame(final_data).sort_values('Sorrend').reset_index(drop=True)

# --- PDF GENERÁLÁS: ETIKETTEK ---
def create_labels(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh, m = 70*mm, 42.42*mm, 5*mm
    
    for i, r in df.iterrows():
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        x, y = (idx % 3) * lw, (6 - (idx // 3)) * lh
        
        # Szombati jelölés (szürke háttér a név alatt)
        if "Szo:" in r['Rendelés_Full']:
            p.setFillColor(colors.lightgrey); p.rect(x+m, y+27.5*mm, lw-2*m, 5*mm, fill=1, stroke=0)
        
        p.setFillColor(colors.black)
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-7*mm, f"#{i+1}"); p.drawRightString(x+lw-m, y+lh-7*mm, f"ID: {r['ID']}")
        p.setFont(f_bold, 9); p.drawString(x+m, y+28.5*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 8); p.drawRightString(x+lw-m, y+28.5*mm, str(r['Telefon']))
        p.setFont(f_reg, 7.5); p.drawString(x+m, y+24.5*mm, str(r['Cím'])[:45])
        
        para = Paragraph(r['Rendelés_Full'], ParagraphStyle('o', fontName=f_reg, fontSize=7, leading=8))
        para.wrap(lw-2*m, 12*mm); para.drawOn(p, x+m, y+11*mm)
        
        if r['Pénz_Total'] > 0:
            p.setFont(f_bold, 10); p.drawString(x+m, y+7.5*mm, f"FIZET: {r['Pénz_Total']} Ft")
        p.setFont(f_bold, 9); p.drawRightString(x+lw-m, y+7.5*mm, f"{r['Összesen']} db")
        p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4*mm, f"Futár: {fn} ({ft}) | Járat: {r['Járat']}")
        
    p.save(); buf.seek(0); return buf

# --- PDF GENERÁLÁS: MENETTERV + RAKLISTA ---
def create_manifest(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    # Menetterv táblázat
    p.setFont(f_bold, 12); p.drawString(10*mm, h-15*mm, f"MENETTERV - {fn} ({meta['day']})")
    
    data = [["#", "NÉV / CÍM", "TEL", "PÉNZ", "RENDELÉS", "DB"]]
    for i, r in df.iterrows():
        data.append([
            f"#{i+1}",
            Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", ParagraphStyle('p', fontName=f_reg, fontSize=8)),
            r['Telefon'],
            f"{r['Pénz_Total']} Ft" if r['Pénz_Total'] > 0 else "0 Ft",
            Paragraph(r['Rendelés_Full'], ParagraphStyle('p', fontName=f_reg, fontSize=7)),
            r['Összesen']
        ])
    
    t = Table(data, colWidths=[10*mm, 60*mm, 25*mm, 25*mm, 60*mm, 10*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.2, colors.grey), ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    
    tw, th = t.wrap(w-20*mm, h-40*mm)
    t.drawOn(p, 10*mm, h - 20*mm - th)
    
    # Rakodási összesítő új oldalon
    p.showPage()
    p.setFont(f_bold, 14); p.drawString(10*mm, h-20*mm, "RAKODÁSI LISTA ÉS ÖSSZESÍTŐ")
    
    total = df['Pénz_Total'].sum()
    p.setFont(f_reg, 11)
    p.drawString(10*mm, h-35*mm, f"Összes beszedendő: {total:,} Ft".replace(',',' '))
    p.drawString(10*mm, h-42*mm, f"Jutalék (13%): {round(total*0.13):,} Ft".replace(',',' '))
    p.setFont(f_bold, 12)
    p.drawString(10*mm, h-52*mm, f"LEADANDÓ NETTÓ: {round(total*0.87):,} Ft".replace(',',' '))
    
    p.save(); buf.seek(0); return buf

# --- INTERFÉSZ ---
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
    pdfs = st.file_uploader("PDF-ek", accept_multiple_files=True)
    if pdfs and st.button("📊 FELDOLGOZÁS"):
        all_r = []
        for f in pdfs:
            rows, meta = parse_interfood_pdf(f)
            all_r.extend(rows)
            st.session_state.meta = meta
        st.session_state.mdf = consolidate_data(all_r)
        st.rerun()

if st.session_state.mdf is not None:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    if st.button("🔄 SORREND MENTÉSE"):
        st.session_state.weights = dict(zip(edited['ID'].astype(str), edited['Sorrend']))
        st.session_state.notes = dict(zip(edited['ID'].astype(str), edited['Megjegyzés']))
        st.session_state.mdf = consolidate_data(st.session_state.mdf.to_dict('records'))
        st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1: st.download_button("🏷️ ETIKETTEK", create_labels(edited, f_name, f_tel), "etikettek.pdf")
    with c2: st.download_button("📋 MENETTERV", create_manifest(edited, f_name, st.session_state.meta), "menetterv.pdf")
    with c3: st.download_button("💾 CSV MENTÉS", edited.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), "export.csv")
