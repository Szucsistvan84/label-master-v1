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

# --- FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- ADATTISZTÍTÁS ---
def clean_val(val):
    return str(val).replace('\n', ' ').strip() if val else ""

def parse_money(val):
    if not val: return 0
    # Csak a számokat és az esetleges negatív jelet tartjuk meg
    num = re.sub(r'[^\d-]', '', str(val))
    return int(num) if num else 0

# --- PDF PARSER ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"day": "N/A", "route": "N/A", "week": ""}
    id_pat = r'([PZ])-(\d{5,7})'
    
    with pdfplumber.open(pdf_file) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        # Alapadatok kinyerése a fejlécből
        route_m = re.search(r'(\d{4})\.\s*járat', first_text)
        if route_m: meta["route"] = route_m.group(1)
        day_m = re.search(r'Nap:\s*([^ ]+)', first_text)
        if day_m: meta["day"] = day_m.group(1).replace(',', '')
        week_m = re.search(r'Hét:\s*(\d+)', first_text)
        if week_m: meta["week"] = week_m.group(1)

        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                if not row or len(row) < 5: continue
                # Az Interfood táblázat szerkezete alapján:
                # row[1] tartalmazza az ID-t és a címet
                # row[2] az ügyintézőt
                # row[3] a telefont, pénzt és rendelést
                
                content_1 = clean_val(row[1])
                id_match = re.search(id_pat, content_1)
                
                if id_match:
                    prefix, uid = id_match.groups()
                    content_3 = clean_val(row[3])
                    
                    # Telefonszám (szóközök nélkül keresve)
                    tel = (re.search(r'\d{2}/\d{6,7}', content_3.replace(" ","")) or [None, ""])[1]
                    # Pénzösszeg keresése
                    money_str = re.search(r'-?\d[\d\s]*Ft', content_3)
                    money = parse_money(money_str.group(0)) if money_str else 0
                    # Rendelés kódja (pl. 1-AK)
                    rend_m = re.search(r'(\d+-[A-Z0-9+*]+)', content_3)
                    rendeles = rend_m.group(1) if rend_m else ""

                    rows.append({
                        "ID": uid,
                        "Prefix": prefix,
                        "Ügyintéző": clean_val(row[2]),
                        "Cím": content_1.split(f"{prefix}-{uid}")[0].strip(),
                        "Telefon": tel,
                        "Rendelés": rendeles,
                        "Pénz": money,
                        "Járat": meta["route"]
                    })
    return rows, meta

# --- LOGIKA: ÖSSZEVONÁS ÉS RENDEZÉS ---
def process_data(raw_rows):
    if not raw_rows: return pd.DataFrame()
    df = pd.DataFrame(raw_rows)
    merged = []
    
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        
        # Péntek (P) és Szombat (Z) rendelések összefűzése
        p_items = group[group['Prefix'] == 'P']['Rendelés'].unique()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].unique()
        
        o_parts = []
        if len(p_items) > 0: o_parts.append(f"Pé: {', '.join(p_items)}")
        if len(z_items) > 0: o_parts.append(f"Szo: {', '.join(z_items)}")
        
        base['Rendelés_Full'] = " | ".join(o_parts)
        # Darabszám összegzése
        total_db = 0
        for r in group['Rendelés']:
            try: total_db += int(r.split('-')[0])
            except: pass
        base['Összesen'] = total_db
        base['Pénz_Total'] = group['Pénz'].sum()
        
        # Állapotmentés (Session State)
        base['Sorrend'] = int(st.session_state.weights.get(str(uid), 999))
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
        
    return pd.DataFrame(merged).sort_values(['Sorrend', 'ID']).reset_index(drop=True)

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
            p.setFillColor(colors.lightgrey); p.rect(x+m, y+27*mm, lw-2*m, 5*mm, fill=1, stroke=0)
        
        p.setFillColor(colors.black)
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-7*mm, f"#{i+1}"); p.drawRightString(x+lw-m, y+lh-7*mm, f"ID: {r['ID']}")
        p.setFont(f_bold, 9); p.drawString(x+m, y+28*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 8); p.drawRightString(x+lw-m, y+28*mm, str(r['Telefon']))
        p.setFont(f_reg, 7); p.drawString(x+m, y+24*mm, str(r['Cím'])[:45])
        
        para = Paragraph(r['Rendelés_Full'], ParagraphStyle('o', fontName=f_reg, fontSize=7, leading=8))
        para.wrap(lw-2*m, 12*mm); para.drawOn(p, x+m, y+11*mm)
        
        if r['Pénz_Total'] > 0:
            p.setFont(f_bold, 10); p.drawString(x+m, y+7*mm, f"FIZET: {r['Pénz_Total']} Ft")
        p.setFont(f_bold, 9); p.drawRightString(x+lw-m, y+7*mm, f"{r['Összesen']} db")
        p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4*mm, f"Futár: {fn} | Járat: {r['Járat']}")
        
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    # 1. MENETTERV OLDALAK
    y = h - 20*mm
    p.setFont(f_bold, 12); p.drawString(10*mm, y, f"MENETTERV - {fn} ({meta['day']})"); y -= 10*mm
    
    data = [["#", "NÉV / CÍM", "TELEFON", "PÉNZ", "RENDELÉS", "DB"]]
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
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.2, colors.grey),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE')
    ]))
    
    tw, th = t.wrap(w-20*mm, h-40*mm)
    t.drawOn(p, 10*mm, y - th); y -= (th + 20*mm)
    
    # 2. RAKODÁSI ÉS PÉNZÜGYI ÖSSZESÍTŐ (Új oldalon)
    p.showPage()
    y = h - 20*mm
    p.setFont(f_bold, 14); p.drawString(10*mm, y, "RAKODÁSI LISTA ÉS ÖSSZESÍTŐ"); y -= 15*mm
    
    # Pénzügyi rész
    total_money = df['Pénz_Total'].sum()
    jutalek = round(total_money * 0.13)
    netto = total_money - jutalek
    
    p.setFont(f_reg, 11)
    p.drawString(10*mm, y, f"Beszedett bruttó készpénz: {total_money:,} Ft".replace(',',' '))
    p.drawString(10*mm, y-7*mm, f"Jutalék (13%): {jutalek:,} Ft".replace(',',' '))
    p.setFont(f_bold, 12)
    p.drawString(10*mm, y-16*mm, f"LEADANDÓ NETTÓ: {netto:,} Ft".replace(',',' '))
    
    p.save(); buf.seek(0); return buf

# --- STREAMLIT UI ---
st.set_page_config(layout="wide", page_title="Interfood Master")

if 'weights' not in st.session_state: st.session_state.weights = {}
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("⚙️ Beállítások")
    f_csv = st.file_uploader("Előző mentés (CSV) betöltése", type="csv")
    if f_csv:
        odf = pd.read_csv(f_csv)
        st.session_state.weights = dict(zip(odf['ID'].astype(str), odf['Sorrend']))
        st.session_state.notes = dict(zip(odf['ID'].astype(str), odf['Megjegyzés'].fillna("")))
        st.success("Sorrend és megjegyzések betöltve!")

    f_name = st.text_input("Futár neve", "Szűcs István")
    f_tel = st.text_input("Telefonszám", "+36 20 886 8971")
    pdf_files = st.file_uploader("Interfood PDF-ek (Péntek/Szombat)", accept_multiple_files=True)
    
    if pdf_files and st.button("📊 ADATOK FELDOLGOZÁSA"):
        all_rows = []
        for f in pdf_files:
            rows, meta = parse_interfood_pdf(f)
            all_rows.extend(rows)
            st.session_state.meta = meta
        st.session_state.mdf = process_data(all_rows)
        st.rerun()

if st.session_state.mdf is not None:
    st.subheader("📝 Napi Menetterv Szerkesztése")
    # Megjelenítés és szerkesztés
    edited = st.data_editor(
        st.session_state.mdf, 
        column_order=["Sorrend", "ID", "Ügyintéző", "Cím", "Telefon", "Rendelés_Full", "Összesen", "Pénz_Total", "Megjegyzés"],
        use_container_width=True, 
        hide_index=True
    )
    
    if st.button("🔄 SORREND FRISSÍTÉSE ÉS RENDEZÉS"):
        st.session_state.weights = dict(zip(edited['ID'].astype(str), edited['Sorrend']))
        st.session_state.notes = dict(zip(edited['ID'].astype(str), edited['Megjegyzés']))
        st.session_state.mdf = process_data(st.session_state.mdf.to_dict('records'))
        st.rerun()

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("🏷️ ETIKETTEK (PDF)", create_label_pdf(edited, f_name, f_tel), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 MENETTERV + RAKLISTA", create_manifest_pdf(edited, f_name, st.session_state.meta), "menetterv.pdf", use_container_width=True)
    with c3:
        st.download_button("💾 ADATOK MENTÉSE (CSV)", edited.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), "napi_export.csv", use_container_width=True)
