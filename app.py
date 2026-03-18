import streamlit as st
import pdfplumber
import pandas as pd
import re
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
import requests

# --- 1. ERŐFORRÁSOK ---

def register_fonts():
    try:
        # Próbáld meg betölteni a DejaVu-t az ékezetek miatt
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def clean_addr(addr):
    if not addr: return ""
    return str(addr).strip().lower().replace('.', '').replace('  ', ' ')

# --- 2. ADATKINYERÉS ---

def get_live_menu(year, week, day_name):
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    menu_map = {}
    day_to_col = {'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6}
    target_col = day_to_col.get(day_name, 3) 

    try:
        response = requests.get(excel_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), engine='openpyxl')
            current_category = "Egyéb"
            for i in range(len(df)):
                row = df.iloc[i]
                col_a = str(row.iloc[0]).strip()
                if col_a and col_a != 'nan' and " - " in col_a:
                    parts = col_a.split(" - ", 1)
                    code = parts[0].strip()
                    current_category = parts[1].strip()
                    name_on_day = str(row.iloc[target_col]).strip()
                    if name_on_day and name_on_day != 'nan' and len(name_on_day) > 2:
                        p_val = str(df.iloc[i+1].iloc[target_col])
                        p_str = re.sub(r'[^\d]', '', p_val)
                        menu_map[code] = {'nev': name_on_day[:65], 'ar': int(p_str or 0), 'kategoria': current_category, 'excel_order': i}
    except: pass
    return menu_map

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None}
    with pdfplumber.open(pdf_file) as pdf:
        text = pdf.pages[0].extract_text()
        if text:
            y_m = re.search(r'Év:\s*(\d{4})', text); w_m = re.search(r'Hét:\s*(\d{1,2})', text)
            d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', text)
            metadata.update({'year': y_m.group(1) if y_m else None, 'week': w_m.group(1) if w_m else None, 'day': d_m.group(1) if d_m else None})
        
        nap_prefix = metadata['day'][:3] if metadata['day'] else ""
        for page in pdf.pages:
            words = page.extract_words(); lines = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines:
                    if abs(y - ey) < 3: lines[ey].append(w); break
                else: lines[y] = [w]
            
            for y in sorted(lines.keys()):
                line = sorted(lines[y], key=lambda x: x['x0'])
                t = " ".join([w['text'] for w in line])
                u_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', t)
                if u_m:
                    uid = u_m.group(0).split('-')[-1]
                    b3 = " ".join([w['text'] for w in line if 150 <= w['x0'] < 355])
                    b4 = " ".join([w['text'] for w in line if 355 <= w['x0'] < 490])
                    addr_m = re.search(r'(\d{4})', b3)
                    orders = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', t)
                    v_o = [f"{nap_prefix}: {o}" for o in orders]
                    rows.append({
                        "ID": uid, "Ügyintéző": re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip(),
                        "Cím": b3[addr_m.start():].strip() if addr_m else b3,
                        "Telefon": (re.search(r'(\d{2}/\d{6,7})', t.replace(" ","")) or re.match("","")).group(0),
                        "Rendelés": ", ".join(v_o), "Pénz": (re.search(r'(-?\d[\d\s]*Ft)', t) or re.match("","0 Ft")).group(0),
                        "Összesen": sum([int(o.split('-')[0][-1]) for o in orders])
                    })
    return rows, metadata

# --- 3. ÖSSZEFÉSÜLÉS ---

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        base['Rendelés_Full'] = " | ".join(group['Rendelés'].tolist())
        base['Összesen'] = group['Összesen'].sum()
        m_vals = [int(re.sub(r'[^\d-]', '', str(p)) or 0) for p in group['Pénz']]
        base['Pénz'] = f"{sum(m_vals)} Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
    
    res = pd.DataFrame(merged)
    res['Sorrend'] = res['ID'].astype(str).map(st.session_state.get('weights', {})).fillna(999.0).astype(float)
    return res.sort_values('Sorrend')

# --- 4. PDF GENERÁLÓK ---

def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    df = df.sort_values('Sorrend')
    c_addrs = [clean_addr(a) for a in df['Cím'].tolist()]
    datestr = f"{meta.get('year','')} Hét:{meta.get('week','')} Nap:{meta.get('day','')}"
    
    r_per_p = 20
    total_p = math.ceil(len(df)/r_per_p)
    for p_idx in range(total_p):
        p.setFont(f_bold, 12); p.drawString(10*mm, h-15*mm, f"MENETTERV - {fn}")
        p.setFont(f_reg, 9); p.drawString(10*mm, h-20*mm, datestr)
        p.drawRightString(w-10*mm, h-15*mm, f"{p_idx+1} / {total_p}. oldal")
        
        # FEJLÉC (Hozzáadva a Checkbox [] oszlop)
        header = [Paragraph(f"<b>{x}</b>", ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)) for x in ["#", "NÉV / CÍM / INFÓ", "[]", "TEL", "PÉNZ", "RENDELÉS", "DB"]]
        data = [header]
        t_styles = [('GRID',(0,0),(-1,-1),0.5,colors.black),('VALIGN',(0,0),(-1,-1),'TOP'), ('FONTNAME',(0,0),(-1,-1),f_reg), ('ALIGN',(2,0),(2,-1),'CENTER')]
        
        for i, (_, r) in enumerate(df.iloc[p_idx*r_per_p:(p_idx+1)*r_per_p].iterrows()):
            is_g = c_addrs.count(clean_addr(r['Cím'])) > 1
            warn = "▲ <b>CSOPORT</b><br/>" if is_g else ""
            if is_g: 
                t_styles.append(('BACKGROUND', (0, i+1), (-1, i+1), colors.Color(0.95, 0.95, 0.95)))
                t_styles.append(('LINEBELOW', (0, i+1), (-1, i+1), 1.2, colors.black))
            
            data.append([
                f"#{int(float(r['Sorrend']))}",
                Paragraph(f"{warn}{r['Ügyintéző']}<br/><font size='7'>{r['Cím']}</font><br/><font color='red' size='7'>{r.get('Megjegyzés','')}</font>", ParagraphStyle('N', fontName=f_bold, fontSize=9)),
                "[]",
                Paragraph(str(r['Telefon']), ParagraphStyle('C', fontName=f_reg, fontSize=8)),
                Paragraph(f"<b>{r['Pénz']}</b>" if "0 Ft" not in r['Pénz'] else "", ParagraphStyle('C', fontName=f_bold, fontSize=9)),
                Paragraph(r['Rendelés_Full'], ParagraphStyle('C', fontName=f_reg, fontSize=7)),
                r['Összesen']
            ])
        
        t = Table(data, colWidths=[10*mm, 60*mm, 10*mm, 25*mm, 22*mm, 53*mm, 10*mm])
        t.setStyle(TableStyle(t_styles))
        t.wrapOn(p, 10*mm, 20*mm); t.drawOn(p, 10*mm, h-35*mm-t._height); p.showPage()
    p.save(); buf.seek(0); return buf

def create_raklista_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    all_codes = []
    for r in df['Rendelés_Full']: all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    counts = {}
    for c, code in all_codes: counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    total_val, total_items = 0, 0
    ordered_codes = sorted([c for c in counts.keys() if c in menu], key=lambda x: menu[x]['excel_order'])
    
    last_cat = None
    for code in ordered_codes:
        info = menu[code]; count = counts[code]
        total_val += (count * info['ar']); total_items += count
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<b>--- {info['kategoria']} ---</b>", ParagraphStyle('Cat', fontName=f_bold, fontSize=10)), ""])
            last_cat = info['kategoria']
        sum_rows.append([Paragraph(f"<b>{code}</b> - {info['nev']}", ParagraphStyle('It', fontName=f_reg, fontSize=9)), f"{count} db"])

    it_per_p = 26
    pages = math.ceil(len(sum_rows)/it_per_p) if sum_rows else 1
    for i in range(pages):
        p.setFont(f_bold, 14); p.drawString(10*mm, h-15*mm, f"RAKODÁSI LISTA - {fn}")
        p.setFont(f_reg, 9); p.drawRightString(w-10*mm, h-15*mm, f"{i+1}/{pages} oldal")
        p_data = [[Paragraph("<b>Étel megnevezése</b>", ParagraphStyle('H', fontName=f_bold, fontSize=10)), "DB"]]
        p_data.extend(sum_rows[i*it_per_p : (i+1)*it_per_p])
        
        if i == pages - 1:
            p_data.append([Paragraph(f"<br/><b>ÖSSZESEN: {total_items} db</b>", ParagraphStyle('F', fontName=f_bold, fontSize=11)), f"\n{total_val} Ft"])
            p_data.append([Paragraph(f"<b>JUTALÉK (13%):</b>", ParagraphStyle('F', fontName=f_bold, fontSize=11)), f"{round(total_val*0.13)} Ft"])

        t = Table(p_data, colWidths=[150*mm, 30*mm])
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.black),('FONTNAME',(0,0),(-1,-1),f_reg),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
        t.wrapOn(p, 10*mm, 20*mm); t.drawOn(p, 10*mm, h-25*mm-t._height)
        if i < pages - 1: p.showPage()
    p.save(); buf.seek(0); return buf

# --- 5. UI FELÜLET ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'weights' not in st.session_state: st.session_state.weights = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta' not in st.session_state: st.session_state.meta = {}

with st.sidebar:
    st.header("👤 Beállítások")
    f_n = st.text_input("Futár neve", "Szűcs István")
    f_p = st.text_input("Futár tel.", "+36 20 886 8971")
    st.divider()
    
    prev_csv = st.file_uploader("Előző napi CSV betöltése (Sorrend/Megjegyzés)", type="csv")
    if prev_csv:
        pdf = pd.read_csv(prev_csv)
        st.session_state.weights = dict(zip(pdf['ID'].astype(str), pdf['Sorrend'].astype(float)))
        if 'Megjegyzés' in pdf.columns:
            st.session_state.notes = dict(zip(pdf['ID'].astype(str), pdf['Megjegyzés'].fillna("")))
        st.success("Adatok beemelve!")

    up_files = st.file_uploader("Napi PDF-ek feltöltése", accept_multiple_files=True)
    if up_files and st.button("🚀 FELDOLGOZÁS"):
        all_raw = []
        for f in up_files:
            r, m = parse_interfood_pdf(f)
            all_raw.extend(r)
            if m['year']: 
                st.session_state.meta = m
                st.session_state.live_menu = get_live_menu(m['year'], m['week'], m['day'])
        st.session_state.mdf = merge_data(all_raw)
        st.rerun()

if st.session_state.mdf is not None:
    st.subheader("📍 Menetlevél és Sorrend")
    edited = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("💾 SORREND MENTÉSE", use_container_width=True):
            st.session_state.weights = dict(zip(edited['ID'].astype(str), edited['Sorrend']))
            st.session_state.notes = dict(zip(edited['ID'].astype(str), edited['Megjegyzés']))
            st.session_state.mdf = edited.sort_values('Sorrend')
            st.rerun()
    with c2:
        csv_data = edited.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 CSV EXPORT", csv_data, "menetlevel.csv", use_container_width=True)
    with c3:
        st.download_button("📄 MENETTERV PDF", create_manifest_pdf(edited, f_n, st.session_state.meta), "menetterv.pdf", use_container_width=True)
    with c4:
        st.download_button("🚚 RAKLISTA PDF", create_raklista_pdf(edited, f_n), "raklista.pdf", use_container_width=True)
