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

# --- FONT BEÁLLÍTÁS ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- TISZTÍTÁS ÉS KERESÉS ---
def extract_phone(text):
    m = re.search(r'\d{2}/\d{6,7}', str(text).replace(" ", ""))
    return m.group(0) if m else ""

def extract_money(text):
    # Keresünk "Ft" előtti számokat, figyelembe véve a negatív előjelet is
    m = re.search(r'(-?\d[\d\s]*)\s*Ft', str(text))
    if m:
        num = re.sub(r'[^\d-]', '', m.group(1))
        return int(num)
    return 0

# --- PDF FELDOLGOZÁS ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"day": "Ismeretlen"}
    id_pat = r'([PZ])-(\d{5,7})'
    
    with pdfplumber.open(pdf_file) as pdf:
        first_page = pdf.pages[0].extract_text() or ""
        day_match = re.search(r'Nap:\s*([^ ]+)', first_page)
        if day_match: meta["day"] = day_match.group(1).replace(',', '')
        route_match = re.search(r'(\d{4})\.\s*járat', first_page)
        meta["route"] = route_match.group(1) if route_match else "N/A"

        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            for row in table:
                full_row_text = " ".join([str(c) for c in row if c])
                id_match = re.search(id_pat, full_row_text)
                
                if id_match:
                    prefix, uid = id_match.groups()
                    # A név és cím kinyerése óvatosabban
                    clean_text = re.sub(id_pat, '', full_row_text)
                    clean_text = re.sub(r'\d{2}/\d{6,7}', '', clean_text)
                    clean_text = re.sub(r'-?\d[\d\s]*\s*Ft', '', clean_text)
                    
                    rows.append({
                        "ID": uid,
                        "Prefix": prefix,
                        "Ügyintéző": str(row[2]).split('\n')[0].strip() if len(row) > 2 else "Ismeretlen",
                        "Cím": str(row[1]).replace('\n', ' ').strip() if len(row) > 1 else "",
                        "Telefon": extract_phone(full_row_text),
                        "Rendelés": (re.search(r'(\d+-[A-Z0-9+*]+)', full_row_text) or [None, ""])[1],
                        "Pénz": extract_money(full_row_text),
                        "Járat": meta["route"]
                    })
    return rows, meta

# --- ADAT ÖSSZEVONÁS ÉS SORREND ---
def prepare_data(raw_rows):
    if not raw_rows: return pd.DataFrame()
    df = pd.DataFrame(raw_rows)
    merged = []
    
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        
        # Péntek és Szombat tételek külön válogatása
        p_items = group[group['Prefix'] == 'P']['Rendelés'].unique()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].unique()
        
        orders = []
        if len(p_items) > 0: orders.append(f"Pé: {', '.join(p_items)}")
        if len(z_items) > 0: orders.append(f"Szo: {', '.join(z_items)}")
        
        base['Rendelés_Full'] = " | ".join(orders)
        base['Összesen'] = sum([int(r.split('-')[0]) for r in group['Rendelés'] if '-' in r])
        base['Pénz_Total'] = group['Pénz'].sum()
        base['Pénz_Megjelenit'] = f"{base['Pénz_Total']} Ft" if base['Pénz_Total'] != 0 else "0 Ft"
        
        # Sorrend és Megjegyzés visszatöltése session-ből
        base['Sorrend'] = int(st.session_state.weights.get(str(uid), 999))
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
        
    return pd.DataFrame(merged).sort_values('Sorrend').reset_index(drop=True)

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
            p.rect(x+m, y+27.5*mm, lw-2*m, 5*mm, fill=1, stroke=0)
        
        p.setFillColor(colors.black)
        p.setFont(f_reg, 7); p.drawString(x+m, y+lh-7*mm, f"#{i+1}"); p.drawRightString(x+lw-m, y+lh-7*mm, f"ID: {r['ID']}")
        p.setFont(f_bold, 9); p.drawString(x+m, y+28.5*mm, str(r['Ügyintéző'])[:24])
        p.setFont(f_reg, 8); p.drawRightString(x+lw-m, y+28.5*mm, r['Telefon'])
        p.setFont(f_reg, 7.5); p.drawString(x+m, y+24.5*mm, str(r['Cím'])[:45])
        
        para = Paragraph(r['Rendelés_Full'], ParagraphStyle('o', fontName=f_reg, fontSize=7, leading=8))
        para.wrap(lw-2*m, 12*mm); para.drawOn(p, x+m, y+11*mm)
        
        if r['Pénz_Total'] != 0:
            p.setFont(f_bold, 10); p.drawString(x+m, y+7.5*mm, r['Pénz_Megjelenit'])
        p.setFont(f_bold, 9); p.drawRightString(x+lw-m, y+7.5*mm, f"{r['Összesen']} db")
        p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4*mm, f"Futár: {fn} ({ft}) | Járat: {r['Járat']}")
        
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    y = h - 20*mm
    p.setFont(f_bold, 12); p.drawString(10*mm, y, f"MENETTERV - {fn} ({meta['day']})"); y -= 15*mm

    data = [[Paragraph("<b>#</b>", ParagraphStyle('p', fontName=f_bold, fontSize=8, alignment=1)), 
             Paragraph("<b>NÉV / CÍM</b>", ParagraphStyle('p', fontName=f_bold, fontSize=8)),
             "TEL", "PÉNZ", "RENDELÉS", "DB"]]
    
    for i, r in df.iterrows():
        data.append([
            f"#{i+1}",
            Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", ParagraphStyle('p', fontName=f_reg, fontSize=8)),
            r['Telefon'],
            r['Pénz_Megjelenit'] if r['Pénz_Total'] != 0 else "",
            Paragraph(r['Rendelés_Full'], ParagraphStyle('p', fontName=f_reg, fontSize=7)),
            r['Összesen']
        ])
    
    t = Table(data, colWidths=[10*mm, 60*mm, 25*mm, 25*mm, 60*mm, 10*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.2, colors.grey), ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    tw, th = t.wrap(w-20*mm, h)
    t.drawOn(p, 10*mm, y - th); y -= (th + 20*mm)
    
    # Raklista összesítő a végén
    if y < 40*mm: p.showPage(); y = h - 20*mm
    total_m = df['Pénz_Total'].sum()
    p.setFont(f_bold, 12); p.drawString(10*mm, y, "PÉNZÜGYI ÖSSZESÍTŐ")
    p.setFont(f_reg, 10); y -= 10*mm
    p.drawString(10*mm, y, f"Összes beszedendő: {total_m:,} Ft".replace(',', ' '))
    p.drawString(10*mm, y-5*mm, f"Jutalék (13%): {round(total_m*0.13):,} Ft".replace(',', ' '))
    p.setFont(f_bold, 11); p.drawString(10*mm, y-12*mm, f"LEADANDÓ: {round(total_m*0.87):,} Ft".replace(',', ' '))

    p.save(); buf.seek(0); return buf

# --- STREAMLIT UI ---
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
        st.session_state.mdf = prepare_data(all_raw)
        st.rerun()

if st.session_state.mdf is not None:
    # A táblázat szerkesztése
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    if st.button("🔄 SORREND ÉS ADATOK MENTÉSE"):
        st.session_state.weights = dict(zip(edited['ID'].astype(str), edited['Sorrend']))
        st.session_state.notes = dict(zip(edited['ID'].astype(str), edited['Megjegyzés']))
        # Újrarendezés a friss súlyok alapján
        st.session_state.mdf = prepare_data(st.session_state.mdf.to_dict('records'))
        st.success("Mentve és újrarendezve!")
        st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1: st.download_button("🏷️ ETIKETTEK", create_label_pdf(edited, f_name, f_tel), "etikettek.pdf")
    with c2: st.download_button("📋 MENETTERV", create_manifest_pdf(edited, f_name, st.session_state.meta), "menetterv.pdf")
    with c3: st.download_button("💾 CSV MENTÉS", edited.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), "mentes.csv")
