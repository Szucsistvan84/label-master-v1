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
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
import requests

# --- 1. ÉTLAP KEZELÉSE ---

def get_live_menu(year, week, day_name):
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    menu_map = {}
    
    day_to_col = {
        'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6
    }
    target_col = day_to_col.get(day_name, 3) 

    try:
        response = requests.get(excel_url, headers=headers, timeout=15)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), engine='openpyxl')
            current_category = "Egyéb"
            
            for i in range(len(df)):
                row = df.iloc[i]
                col_a = str(row.iloc[0]).strip()
                
                if col_a and col_a != 'nan' and " - " in col_a:
                    parts = col_a.split(" - ")
                    code = parts[0].strip()
                    current_category = parts[1].strip()
                    
                    name_on_day = str(row.iloc[target_col]).strip()
                    
                    if name_on_day and name_on_day != 'nan' and len(name_on_day) > 2:
                        try:
                            next_row = df.iloc[i+1]
                            price_on_day = str(next_row.iloc[target_col]).strip()
                            p_str = re.sub(r'[^\d]', '', price_on_day)
                            
                            if p_str:
                                menu_map[code] = {
                                    'nev': name_on_day[:60],
                                    'ar': int(p_str),
                                    'kategoria': current_category,
                                    'excel_order': i 
                                }
                        except:
                            continue
            st.sidebar.success(f"✅ Étlap: {len(menu_map)} tétel")
    except Exception as e:
        st.sidebar.error(f"Excel hiba: {e}")
    return menu_map

# --- ALAPFUNKCIÓK ---

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def clean_addr(addr):
    if not addr: return ""
    return str(addr).strip().lower().replace('.', '').replace('  ', ' ')

# --- PDF PARSER ---

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
            
            sorted_y = sorted(lines.keys())
            for i, y in enumerate(sorted_y):
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
                
                money_val = "0 Ft"
                if i + 1 < len(sorted_y):
                    next_t = " ".join([w['text'] for w in sorted(lines[sorted_y[i+1]], key=lambda x: x['x0'])])
                    m_match = re.search(money_pat, next_t)
                    if m_match: money_val = m_match.group(1).strip()
                
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
                        "Rendelés": ", ".join(v_o), "Pénz": money_val, "Összesen": sq
                    })
    return rows, metadata

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p, m_list = [], []
        has_weekend = False
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items: 
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
                if pfix == 'Z': has_weekend = True
            for m_str in day_group['Pénz']:
                num = int(re.sub(r'[^\d-]', '', str(m_str)) or 0)
                if num != 0: m_list.append(num)
        
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Hétvégi'] = has_weekend 
        base['Pénz'] = f"{sum(m_list) if m_list else 0} Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
    
    res = pd.DataFrame(merged).dropna(subset=['ID'])
    if 'weights' in st.session_state and st.session_state.weights:
        res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999.0).astype(float)
    else:
        res['Sorrend'] = range(1, len(res) + 1)
        res['Sorrend'] = res['Sorrend'].astype(float)
    return res.sort_values('Sorrend')

# --- PDF GENERÁLÁS ---

def create_label_pdf(df, fn, ft):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
    inner_m = 5.5*mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    note_s = ParagraphStyle('Note', fontName=f_bold, fontSize=7, leading=8, textColor=colors.red)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1)
    
    total_slots = math.ceil(len(df) / 21) * 21
    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            if r.get('Hétvégi', False):
                p.setFillColorRGB(0.92, 0.92, 0.92); p.rect(x + 1*mm, top_y - 4*mm, lw - 2*mm, 5*mm, fill=1, stroke=0)
                p.setFillColor(colors.black)
            
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{i+1}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            if str(r['Megjegyzés']).strip() and str(r['Megjegyzés']) != 'None':
                pn = Paragraph(f"<b>INFÓ: {r['Megjegyzés']}</b>", note_s)
                pn.wrap(lw - 2*inner_m, 5*mm); pn.drawOn(p, x + inner_m, top_y - 17*mm)
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            
            base_y = y + inner_m 
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            if m_val != "0" and m_val != "":
                p.setFont(f_bold, 10); p.drawString(x + inner_m, base_y + 3*mm, f"FIZET: {r['Pénz']}")
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, base_y + 3*mm, f"{r['Összesen']} db")
            p.setLineWidth(0.2); p.line(x + inner_m, base_y + 2*mm, x + lw - inner_m, base_y + 2*mm)
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, base_y - 1.5*mm, f"Futár: {fn} | {ft}")
        else:
            m_text = f"<font size='11'><b>15% kedvezmény* 3 hétig</b></font><br/>Új Ügyfeleinknek!<br/><br/><b>Rendelés:</b><br/><b>{fn}</b>, tel: <b>{ft}</b>"
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw - 2*inner_m, lh - 2*inner_m)
            para.drawOn(p, x + (lw - pw) / 2, y + (lh - ph) / 2)
    
    p.save(); buf.seek(0); return buf

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
    
    # --- MENETTERV OLDALAK ---
    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(10*mm, h - 12*mm, f"MENETTERV - {fn}")
        p.drawRightString(w - 10*mm, h - 12*mm, f"{p_idx + 1}/{total_p}. oldal")
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM / INFÓ</b>", head_s), Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>TEL</b>", head_s), Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        t_style = [('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]
        for i, (_, r) in enumerate(subset.iterrows()):
            c_cleaned = clean_addr(r['Cím']); g_count = cleaned_addrs.count(c_cleaned)
            is_group = g_count > 1; m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            m_disp = f"<b>{r['Pénz']}</b>" if m_val != "0" and m_val != "" else ""
            warn = f"▲ <b>CSOPORT ({g_count})</b><br/>" if is_group else ""
            data.append([f"#{p_idx*rows_per_page+i+1}", Paragraph(f"{warn}{r['Ügyintéző']}<br/><font size='7'>{r['Cím']}</font>", name_s), "[ ]", Paragraph(str(r['Telefon']), cell_s), Paragraph(m_disp, cell_s), Paragraph(str(r['Rendelés_Full']), cell_s), r['Összesen']])
            if is_group:
                t_style.append(('BACKGROUND', (1, i+1), (1, i+1), colors.Color(0.92, 0.92, 0.92)))
                t_style.append(('BOX', (1, i+1), (1, i+1), 1.2, colors.black))
        t = Table(data, colWidths=[11*mm, 64*mm, 9*mm, 25*mm, 22*mm, 54*mm, 10*mm])
        t.setStyle(TableStyle(t_style))
        t.wrapOn(p, 7*mm, 20*mm); h_t = t.wrap(w - 14*mm, h - 35*mm)[1]
        t.drawOn(p, 7*mm, h - 22*mm - h_t)
        p.showPage()

    # --- RAKODÁSI LISTA SZÁMÍTÁSA ---
    all_codes = []
    for r in df['Rendelés_Full']: 
        all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    
    counts = {}
    for c, code in all_codes: 
        counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    total_val, total_items = 0, 0
    
    # Sorbarendezés az Excel sorrendje alapján
    ordered_codes = sorted(
        [c for c in counts.keys() if c in menu],
        key=lambda x: menu[x]['excel_order']
    )

    last_cat = None
    for code in ordered_codes:
        info = menu[code]
        count = counts[code]
        total_val += (count * info['ar'])
        total_items += count
        
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<br/><b>--- {info['kategoria']} ---</b>", cell_s), ""])
            last_cat = info['kategoria']
            
        sum_rows.append([Paragraph(f"<b>{code}</b> - {info['nev']}", cell_s), Paragraph(f"{count} db", head_s)])

    unknown_codes = [c for c in counts.keys() if c not in menu]
    if unknown_codes:
        sum_rows.append([Paragraph("<br/><b>--- ISMERETLEN / MÁSIK NAP ---</b>", cell_s), ""])
        for code in sorted(unknown_codes):
            sum_rows.append([Paragraph(f"<b>{code}</b> - Ismeretlen étel", cell_s), Paragraph(f"{counts[code]} db", head_s)])

    footer_rows = [
        [Paragraph(f"<b>ÖSSZESEN: {total_items} db étel</b>", cell_s), Paragraph(f"<b>{total_val} Ft</b>", head_s)],
        [Paragraph(f"<b>VÁRHATÓ JUTALÉK (13%):</b>", cell_s), Paragraph(f"<b>{round(total_val*0.13)} Ft</b>", head_s)]
    ]

    # --- RAKODÁSI OLDALAK GENERÁLÁSA ---
    items_per_page = 30
    total_sum_pages = math.ceil(len(sum_rows) / items_per_page) if sum_rows else 1
    for sp_idx in range(total_sum_pages):
        p.setFont(f_bold, 12)
        p.drawString(10*mm, h - 15*mm, f"RAKODÁSI LISTA ÉS ÖSSZESÍTŐ ({sp_idx + 1}/{total_sum_pages})")
        page_data = [[Paragraph("<b>KÓD ÉS ÉTEL MEGNEVEZÉSE</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        page_data.extend(sum_rows[sp_idx * items_per_page : (sp_idx + 1) * items_per_page])
        if sp_idx == total_sum_pages - 1: page_data.extend(footer_rows)
            
        st_t = Table(page_data, colWidths=[150*mm, 30*mm])
        st_t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        st_t.wrapOn(p, 10*mm, 20*mm); h_st = st_t.wrap(180*mm, 260*mm)[1]
        st_t.drawOn(p, 10*mm, h - 25*mm - h_st)
        if sp_idx < total_sum_pages - 1: p.showPage()

    p.save(); buf.seek(0); return buf

# --- UI ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'live_menu' not in st.session_state: st.session_state.live_menu = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("👤 Futár")
    c_n = st.text_input("Név", "Szűcs István")
    c_p = st.text_input("Tel", "+36 20 886 8971")
    st.divider()
    
    st.header("🍴 Étlap")
    if st.session_state.live_menu:
        st.success(f"✅ {len(st.session_state.live_menu)} étel betöltve")
    
    st.divider()
    old_csv = st.file_uploader("CSV Betöltése", type="csv")
    if old_csv:
        db_df = pd.read_csv(old_csv)
        st.session_state.weights = dict(zip(db_df['ID'].astype(str), db_df['Sorrend'].astype(float)))
        if 'Megjegyzés' in db_df.columns: st.session_state.notes = dict(zip(db_df['ID'].astype(str), db_df['Megjegyzés'].fillna("")))

    up_files = st.file_uploader("Napi PDF-ek", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        last_meta = None
        for f in up_files: 
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows)
            if meta['year'] and meta['week']: last_meta = meta
        
        if raw:
            if last_meta:
                st.session_state.live_menu = get_live_menu(last_meta['year'], last_meta['week'], last_meta['day'])
            st.session_state.mdf = merge_data(raw)
            st.rerun()

# --- Megjelenítés ---

if st.session_state.mdf is not None:
    cols = ['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Rendelés_Full', 'Összesen', 'Pénz', 'Megjegyzés']
    display_df = st.session_state.mdf[[c for c in cols if c in st.session_state.mdf.columns]]

    st.subheader("📍 Menetlevél szerkesztése")
    edited_df = st.data_editor(
        display_df, hide_index=True, use_container_width=True,
        column_config={
            "Sorrend": st.column_config.NumberColumn("Sorrend", step=1, format="%d"),
            "ID": st.column_config.TextColumn("Azonosító", disabled=True),
        }
    )
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ SORREND MENTÉSE", use_container_width=True):
            temp_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
            temp_df['Sorrend'] = range(1, len(temp_df) + 1)
            st.session_state.weights = dict(zip(temp_df['ID'].astype(str), temp_df['Sorrend']))
            st.session_state.notes = dict(zip(temp_df['ID'].astype(str), temp_df['Megjegyzés'].fillna("")))
            st.session_state.mdf = temp_df
            st.rerun()
            
    with c2:
        csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 MENTÉS CSV-BE", csv_data, "adatok.csv", use_container_width=True)

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button("📄 ETIKETTEK", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf", use_container_width=True)
    with col_b:
        st.download_button("📋 MENETTERV + RAKLISTA", create_manifest_pdf(edited_df, c_n), "menetterv.pdf", use_container_width=True)
