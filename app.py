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

# --- 1. ALAPFUNKCIÓK ---

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

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

# --- 2. ÉTLAP KEZELÉSE ---

def get_live_menu(year, week, day_name):
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    menu_map = {}
    day_to_col = {'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6}
    target_col = day_to_col.get(day_name, 3) 

    try:
        response = requests.get(excel_url, headers=headers, timeout=15)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), engine='openpyxl')
            for i in range(len(df)):
                row = df.iloc[i]
                col_a = str(row.iloc[0]).strip()
                if col_a and " - " in col_a:
                    code = col_a.split(" - ")[0].strip()
                    name_on_day = str(row.iloc[target_col]).strip()
                    if name_on_day and name_on_day != 'nan' and len(name_on_day) > 2:
                        try:
                            p_str = re.sub(r'[^\d]', '', str(df.iloc[i+1].iloc[target_col]))
                            if p_str:
                                menu_map[code] = {
                                    'nev': name_on_day[:60],
                                    'ar': int(p_str),
                                    'kategoria': col_a.split(" - ")[1].strip(),
                                    'excel_order': i 
                                }
                        except: continue
    except: pass
    return menu_map

# --- 3. PDF PARSER ---

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*\s*Ft)' 
    
    with pdfplumber.open(pdf_file) as pdf:
        first_page_text = pdf.pages[0].extract_text()
        if first_page_text:
            y_m = re.search(r'Év:\s*(\d{4})', first_page_text)
            w_m = re.search(r'Hét:\s*(\d{1,2})', first_page_text)
            d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', first_page_text)
            if y_m: metadata['year'] = y_m.group(1)
            if w_m: metadata['week'] = w_m.group(1)
            if d_m: metadata['day'] = d_m.group(1)

        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines:
                    if abs(y - ey) < 3: lines[ey].append(w); break
                else: lines[y] = [w]
            
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                prefix = u_code_m.group(0).split('-')[0]
                uid = u_code_m.group(0).split('-')[-1]
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3
                
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": address, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": "0 Ft", "Összesen": sq
                    })
    return rows, metadata

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        has_weekend = False
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items: 
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
                if pfix == 'Z': has_weekend = True
        
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Hétvégi'] = has_weekend 
        base['Pénz'] = "0 Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
    
    res = pd.DataFrame(merged).dropna(subset=['ID'])
    if 'weights' in st.session_state:
        res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999.0).astype(float)
    else:
        res['Sorrend'] = range(1, len(res) + 1)
    return res.sort_values('Sorrend')

# --- 4. PDF GENERÁLÁS (ETIKETTEK) ---

def create_label_pdf(df, fn, ft):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    inner_m = 5.5*mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    note_s = ParagraphStyle('Note', fontName=f_bold, fontSize=7, leading=8, textColor=colors.red)
    
    for i in range(math.ceil(len(df) / 21) * 21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
            # --- SZÜRKE KIEMELÉS ---
            if r.get('Hétvégi') == True:
                p.saveState()
                p.setFillColor(colors.lightgrey)
                p.rect(x + 1*mm, top_y - 9.5*mm, lw - 2*mm, 7*mm, fill=1, stroke=0)
                p.restoreState()
            
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{i+1}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            if str(r.get('Megjegyzés')).strip() and str(r.get('Megjegyzés')) != 'None':
                pn = Paragraph(f"<b>INFÓ: {r['Megjegyzés']}</b>", note_s)
                pn.wrap(lw - 2*inner_m, 5*mm); pn.drawOn(p, x + inner_m, top_y - 17*mm)
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 3*mm, f"{r['Összesen']} db")
            p.setLineWidth(0.2); p.line(x + inner_m, y + inner_m + 2*mm, x + lw - inner_m, y + inner_m + 2*mm)
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + inner_m - 1.5*mm, f"Futár: {fn} | {ft}")

    p.save(); buf.seek(0); return buf

# --- 5. PDF GENERÁLÁS (MENETTERV + RAKLISTA) ---

def create_manifest_pdf(df, fn):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cleaned_addrs = [clean_addr(a) for a in df['Cím'].tolist()]
    
    rows_per_page = 25 
    total_p = math.ceil(len(df) / rows_per_page)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=8, alignment=1)
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=9, leading=10)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=7, leading=8)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(10*mm, h - 12*mm, f"MENETTERV - {fn}")
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM / INFÓ</b>", head_s), Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>TEL</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        t_style = [('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]
        for i, (_, r) in enumerate(subset.iterrows()):
            c_cleaned = clean_addr(r['Cím']); g_count = cleaned_addrs.count(c_cleaned)
            warn = f"▲ <b>CSOPORT ({g_count})</b><br/>" if g_count > 1 else ""
            data.append([f"#{p_idx*rows_per_page+i+1}", Paragraph(f"{warn}{r['Ügyintéző']}<br/><font size='7'>{r['Cím']}</font>", name_s), "[ ]", Paragraph(str(r['Telefon']), cell_s), Paragraph(str(r['Rendelés_Full']), cell_s), r['Összesen']])
            if g_count > 1: t_style.append(('BACKGROUND', (1, i+1), (1, i+1), colors.Color(0.92, 0.92, 0.92)))
        
        t = Table(data, colWidths=[10*mm, 70*mm, 10*mm, 25*mm, 65*mm, 10*mm])
        t.setStyle(TableStyle(t_style))
        t.wrapOn(p, 10*mm, 20*mm); h_t = t.wrap(w - 20*mm, h - 35*mm)[1]
        t.drawOn(p, 10*mm, h - 22*mm - h_t)
        p.showPage()

    all_codes = []
    for r in df['Rendelés_Full']: 
        all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    counts = {}
    for c, code in all_codes: counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    ordered_codes = sorted([c for c in counts.keys() if c in menu], key=lambda x: menu[x]['excel_order'])
    last_cat = None
    for code in ordered_codes:
        info = menu[code]
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<b>--- {info['kategoria']} ---</b>", cell_s), ""])
            last_cat = info['kategoria']
        sum_rows.append([Paragraph(f"<b>{code}</b> - {info['nev']}", cell_s), Paragraph(f"{counts[code]} db", head_s)])

    p.setFont(f_bold, 12); p.drawString(10*mm, h - 15*mm, "RAKODÁSI LISTA")
    st_t = Table([[Paragraph("ÉTEL", head_s), Paragraph("DB", head_s)]] + sum_rows, colWidths=[150*mm, 30*mm])
    st_t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
    st_t.wrapOn(p, 10*mm, 20*mm); h_st = st_t.wrap(180*mm, 260*mm)[1]
    st_t.drawOn(p, 10*mm, h - 25*mm - h_st)

    p.save(); buf.seek(0); return buf

# --- 6. UI ---

st.set_page_config(page_title="Logisztika", layout="wide")
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'live_menu' not in st.session_state: st.session_state.live_menu = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    c_n = st.text_input("Név", "Szűcs István")
    c_p = st.text_input("Tel", "+36 20 886 8971")
    up_files = st.file_uploader("PDF-ek", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        last_meta = None
        for f in up_files: 
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows)
            if meta['year']: last_meta = meta
        if raw:
            if last_meta: st.session_state.live_menu = get_live_menu(last_meta['year'], last_meta['week'], last_meta['day'])
            st.session_state.mdf = merge_data(raw)
            st.rerun()

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    if st.button("💾 MENTÉS"):
        st.session_state.mdf = edited_df
        st.rerun()
    
    col1, col2 = st.columns(2)
    col1.download_button("📄 ETIKETTEK", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf")
    col2.download_button("📋 MENETTERV + RAKLISTA", create_manifest_pdf(edited_df, c_n), "menetterv.pdf")
