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

# --- 1. ALAPBEÁLLÍTÁSOK ÉS BETŰTÍPUSOK ---

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def clean_addr(addr):
    if not addr: return ""
    return str(addr).strip().lower().replace('.', '').replace('  ', ' ')

# --- 2. ADATKINYERÉS AZ EREDETI PDF-BŐL ---

def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {'year': '?', 'week': '?', 'day': '?'}
    with pdfplumber.open(pdf_file) as pdf:
        full_text = ""
        for page in pdf.pages[:1]:
            full_text += page.extract_text() or ""
        
        if full_text:
            y_m = re.search(r'Év:\s*(\d{4})', full_text)
            w_m = re.search(r'Hét:\s*(\d{1,2})', full_text)
            d_m = re.search(r'Nap:\s*([a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]+)', full_text)
            if y_m: meta['year'] = y_m.group(1)
            if w_m: meta['week'] = w_m.group(1)
            if d_m: meta['day'] = d_m.group(1)
        
        nap_prefix = meta['day'][:3] if meta['day'] != '?' else ""
        
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
                line = sorted(lines[y], key=lambda x: x['x0'])
                t = " ".join([w['text'] for w in line])
                u_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', t)
                if u_m:
                    uid = u_m.group(0).split('-')[-1]
                    b3 = " ".join([w['text'] for w in line if 150 <= w['x0'] < 355])
                    b4 = " ".join([w['text'] for w in line if 355 <= w['x0'] < 490])
                    addr_m = re.search(r'(\d{4})', b3)
                    orders = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', t)
                    rows.append({
                        "ID": uid, 
                        "Ügyintéző": re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip(),
                        "Cím": b3[addr_m.start():].strip() if addr_m else b3,
                        "Telefon": (re.search(r'(\d{2}/\d{6,7})', t.replace(" ","")) or re.match("","")).group(0),
                        "Rendelés": ", ".join([f"{nap_prefix}: {o}" for o in orders]), 
                        "Pénz": (re.search(r'(-?\d[\d\s]*Ft)', t) or re.match("","0 Ft")).group(0),
                        "Összesen": sum([int(o.split('-')[0][-1]) for o in orders])
                    })
    return rows, meta

# --- 3. MENETTERV PDF GENERÁLÁS ---

def create_manifest_pdf(df, fn, f_tel, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    df = df.sort_values('Sorrend')
    c_addrs = [clean_addr(a) for a in df['Cím'].tolist()]
    
    date_label = f"Év: {meta['year']}  Hét: {meta['week']}  Nap: {meta['day']}"
    r_per_p = 28
    total_p = math.ceil(len(df)/r_per_p)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 12)
        p.drawString(10*mm, h-10*mm, f"MENETTERV - {fn} ({f_tel})")
        p.setFont(f_reg, 10)
        p.drawString(10*mm, h-15*mm, date_label)
        p.drawRightString(w-10*mm, h-10*mm, f"{p_idx+1} / {total_p}. oldal")
        
        header = [Paragraph(f"<b>{x}</b>", ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)) 
                  for x in ["#", "NÉV / CÍM / INFÓ", "[]", "TEL", "PÉNZ", "RENDELÉS", "DB"]]
        data = [header]
        t_styles = [('GRID',(0,0),(-1,-1),0.3,colors.black), ('VALIGN',(0,0),(-1,-1),'TOP'), ('ALIGN',(2,0),(2,-1),'CENTER')]
        
        page_df = df.iloc[p_idx*r_per_p : (p_idx+1)*r_per_p]
        for i, (_, r) in enumerate(page_df.iterrows()):
            addr_clean = clean_addr(r['Cím'])
            is_g = c_addrs.count(addr_clean) > 1
            if is_g:
                t_styles.append(('BACKGROUND', (0, i+1), (-1, i+1), colors.Color(0.97, 0.97, 0.97)))
                t_styles.append(('LINEBEFORE', (0, i+1), (0, i+1), 1.5, colors.black))
                t_styles.append(('LINEAFTER', (-1, i+1), (-1, i+1), 1.5, colors.black))
                is_start = (i == 0) or (clean_addr(page_df.iloc[i-1]['Cím']) != addr_clean)
                if is_start: t_styles.append(('LINEABOVE', (0, i+1), (-1, i+1), 1.5, colors.black))
                is_end = (i == len(page_df)-1) or (i < len(page_df)-1 and clean_addr(page_df.iloc[i+1]['Cím']) != addr_clean)
                if is_end: t_styles.append(('LINEBELOW', (0, i+1), (-1, i+1), 1.5, colors.black))

            info_html = f"{'▲ ' if is_g else ''}<b>{r['Ügyintéző']}</b><br/><font size='7'>{r['Cím']}</font>"
            if r.get('Megjegyzés'): info_html += f"<br/><font color='red' size='7'>{r['Megjegyzés']}</font>"

            data.append([
                f"#{int(float(r['Sorrend']))}",
                Paragraph(info_html, ParagraphStyle('N', fontName=f_reg, fontSize=9, leading=10)),
                "[]",
                Paragraph(str(r['Telefon']), ParagraphStyle('C', fontName=f_reg, fontSize=7)),
                Paragraph(f"<b>{r['Pénz']}</b>" if "0 Ft" not in r['Pénz'] else "", ParagraphStyle('C', fontName=f_bold, fontSize=7)),
                Paragraph(r['Rendelés_Full'], ParagraphStyle('C', fontName=f_reg, fontSize=7, leading=8)),
                r['Összesen']
            ])
        
        t = Table(data, colWidths=[15*mm, 75*mm, 8*mm, 20*mm, 18*mm, 42*mm, 10*mm])
        t.setStyle(TableStyle(t_styles))
        t.wrapOn(p, 10*mm, 20*mm); t.drawOn(p, 10*mm, h - 22*mm - t._height)
        p.showPage()
    p.save(); buf.seek(0); return buf

# --- 4. RAKLISTA PDF GENERÁLÁS ---

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
    codes_in_order = sorted([c for c in counts.keys()], key=lambda x: menu.get(x, {}).get('excel_order', 999))
    
    last_cat = None
    for code in codes_in_order:
        info = menu.get(code, {'nev': 'Ismeretlen étel', 'ar': 0, 'kategoria': 'Egyéb'})
        count = counts[code]
        total_val += (count * info['ar']); total_items += count
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<b>--- {info['kategoria']} ---</b>", ParagraphStyle('Cat', fontName=f_bold, fontSize=10)), ""])
            last_cat = info['kategoria']
        sum_rows.append([Paragraph(f"<b>{code}</b> - {info['nev']}", ParagraphStyle('It', fontName=f_reg, fontSize=9)), f"{count} db"])

    it_per_p = 26
    pages = math.ceil(len(sum_rows)/it_per_p) if sum_rows else 1
    for i in range(pages):
        p.setFont(f_bold, 14); p.drawString(10*mm, h-15*mm, f"RAKODÁSI LISTA - {fn}")
        p_data = [[Paragraph("<b>Étel megnevezése</b>", ParagraphStyle('H', fontName=f_bold, fontSize=10)), "DB"]]
        p_data.extend(sum_rows[i*it_per_p : (i+1)*it_per_p])
        if i == pages - 1:
            p_data.append([Paragraph(f"<br/><b>ÖSSZESEN: {total_items} db</b>", ParagraphStyle('F', fontName=f_bold, fontSize=11)), f"\n{total_val} Ft"])
        t = Table(p_data, colWidths=[150*mm, 30*mm])
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.black),('FONTNAME',(0,0),(-1,-1),f_reg),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
        t.wrapOn(p, 10*mm, 20*mm); t.drawOn(p, 10*mm, h-25*mm-t._height)
        if i < pages - 1: p.showPage()
    p.save(); buf.seek(0); return buf

# --- 5. FELHASZNÁLÓI FELÜLET ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta' not in st.session_state: st.session_state.meta = {'year': '?', 'week': '?', 'day': '?'}
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'weights' not in st.session_state: st.session_state.weights = {}

with st.sidebar:
    st.header("👤 Beállítások")
    f_n = st.text_input("Futár neve", "Szűcs István")
    f_t = st.text_input("Futár telefonszáma", "+36 20 886 8971")
    st.divider()
    prev_csv = st.file_uploader("Előző napi CSV betöltése (Sorrendhez)", type="csv")
    if prev_csv:
        pdf_c = pd.read_csv(prev_csv)
        st.session_state.weights = dict(zip(pdf_c['ID'].astype(str), pdf_c['Sorrend'].astype(float)))
        if 'Megjegyzés' in pdf_c.columns:
            st.session_state.notes = dict(zip(pdf_c['ID'].astype(str), pdf_c['Megjegyzés'].fillna("")))

    up_files = st.file_uploader("Napi PDF menettervek", accept_multiple_files=True)
    if up_files and st.button("🚀 FELDOLGOZÁS"):
        all_raw = []
        for f in up_files:
            rows, meta = parse_interfood_pdf(f)
            all_raw.extend(rows)
            if meta['year'] != '?': st.session_state.meta = meta
        
        df_tmp = pd.DataFrame(all_raw)
        merged = []
        for uid, group in df_tmp.groupby("ID", sort=False):
            base = group.iloc[0].copy().to_dict()
            base['Rendelés_Full'] = " | ".join(group['Rendelés'].tolist())
            base['Összesen'] = group['Összesen'].sum()
            m_vals = [int(re.sub(r'[^\d-]', '', str(p)) or 0) for p in group['Pénz']]
            base['Pénz'] = f"{sum(m_vals)} Ft"; base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
            merged.append(base)
        
        res = pd.DataFrame(merged)
        res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999.0).astype(float)
        st.session_state.mdf = res.sort_values('Sorrend')
        st.rerun()

if st.session_state.mdf is not None:
    edited = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("💾 MENTÉS", use_container_width=True):
            st.session_state.weights = dict(zip(edited['ID'].astype(str), edited['Sorrend']))
            st.session_state.notes = dict(zip(edited['ID'].astype(str), edited['Megjegyzés']))
            st.session_state.mdf = edited.sort_values('Sorrend')
            st.success("Sorrend és megjegyzések mentve!")
    with c2:
        st.download_button("📄 MENETTERV PDF", create_manifest_pdf(edited, f_n, f_t, st.session_state.meta), "menetterv.pdf", use_container_width=True)
    with c3:
        st.download_button("🚚 RAKLISTA PDF", create_raklista_pdf(edited, f_n), "raklista.pdf", use_container_width=True)
    with c4:
        st.download_button("📥 CSV EXPORT", edited.to_csv(index=False).encode('utf-8-sig'), "lista.csv", use_container_width=True)
