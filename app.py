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

# --- 1. ALAPBEÁLLÍTÁSOK ÉS FONTOS ADATOK ---

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
                            price_on_day = str(df.iloc[i+1].iloc[target_col]).strip()
                            p_str = re.sub(r'[^\d]', '', price_on_day)
                            if p_str:
                                menu_map[code] = {
                                    'nev': name_on_day[:60],
                                    'ar': int(p_str),
                                    'kategoria': current_category,
                                    'excel_order': i 
                                }
                        except: continue
    except Exception as e:
        st.sidebar.error(f"Excel hiba: {e}")
    return menu_map

# --- 3. PDF FELDOLGOZÁS (NAP JELÖLÉSSEL) ---

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*\s*Ft)' 
    
    with pdfplumber.open(pdf_file) as pdf:
        first_text = pdf.pages[0].extract_text()
        if first_text:
            y_m = re.search(r'Év:\s*(\d{4})', first_text)
            w_m = re.search(r'Hét:\s*(\d{1,2})', first_text)
            d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', first_text)
            if y_m: metadata['year'] = y_m.group(1)
            if w_m: metadata['week'] = w_m.group(1)
            if d_m: metadata['day'] = d_m.group(1)

        nap_rovid = metadata['day'][:3] if metadata['day'] else ""

        for page in pdf.pages:
            words = page.extract_words(); lines = {}
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
                addr_m = re.search(r'(\d{4})', b3); address = b3[addr_m.start():].strip() if addr_m else b3
                
                # Pénz keresése a következő sorban
                money_val = "0 Ft"
                # (Itt az egyszerűség kedvéért a text_ws-ből is próbáljuk, ha ott van)
                m_match = re.search(money_pat, text_ws)
                if m_match: money_val = m_match.group(1).strip()

                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{nap_rovid}: {q}-{o.split('-')[1]}"); sq += q
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
    # ID szerinti összevonás (több nap esetén)
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        all_orders = []
        total_money = 0
        for _, r in group.iterrows():
            all_orders.append(r['Rendelés'])
            m_val = int(re.sub(r'[^\d-]', '', str(r['Pénz'])) or 0)
            total_money += m_val
        
        base['Rendelés_Full'] = " | ".join(all_orders)
        base['Összesen'] = group['Összesen'].sum()
        base['Pénz'] = f"{total_money} Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
    
    res = pd.DataFrame(merged)
    if 'weights' in st.session_state:
        res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999.0).astype(float)
    else:
        res['Sorrend'] = range(1, len(res) + 1)
        res['Sorrend'] = res['Sorrend'].astype(float)
    return res.sort_values('Sorrend')

# --- 4. PDF GENERÁLÁS (ETIKETT ÉS MENETTERV) ---

def create_label_pdf(df, fn, ft):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
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
            p.setFont(f_bold, 8); p.drawString(x + inner_m, top_y - 3*mm, f"#{int(float(r['Sorrend']))}") 
            p.setFont(f_reg, 7); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:22])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            if str(r.get('Megjegyzés', '')).strip() and str(r.get('Megjegyzés', '')) != 'None':
                pn = Paragraph(f"<b>INFÓ: {r['Megjegyzés']}</b>", note_s)
                pn.wrap(lw - 2*inner_m, 5*mm); pn.drawOn(p, x + inner_m, top_y - 17*mm)
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            p.setFont(f_bold, 10); p.drawString(x + inner_m, y + inner_m + 3*mm, f"FIZET: {r['Pénz']}" if "0 Ft" not in r['Pénz'] else "")
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 3*mm, f"{r['Összesen']} db")
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + inner_m - 1.5*mm, f"Futár: {fn} | {ft}")
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cleaned_addrs = [clean_addr(a) for a in df['Cím'].tolist()]
    
    # 1. MENETTERV OLDALAK (CSOPORTOSÍTÁS JELZÉSSEL)
    rows_per_page = 22
    total_p = math.ceil(len(df) / rows_per_page)
    for p_idx in range(total_p):
        p.setFont(f_bold, 12); p.drawString(10*mm, h - 15*mm, f"MENETTERV - {fn} ({p_idx+1}/{total_p})")
        data = [[Paragraph("<b>#</b>", ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)), 
                 Paragraph("<b>NÉV / CÍM / INFÓ</b>", ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)), 
                 "TEL", "PÉNZ", "RENDELÉS", "DB"]]
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        t_style = [('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]
        
        for i, (_, r) in enumerate(subset.iterrows()):
            c_cl = clean_addr(r['Cím']); g_count = cleaned_addrs.count(c_cl)
            is_group = g_count > 1
            warn = f"▲ <b>CSOPORT ({g_count})</b><br/>" if is_group else ""
            data.append([
                int(float(r['Sorrend'])),
                Paragraph(f"{warn}{r['Ügyintéző']}<br/><font size='7'>{r['Cím']}</font>", ParagraphStyle('N', fontName=f_bold, fontSize=9)),
                Paragraph(str(r['Telefon']), ParagraphStyle('C', fontName=f_reg, fontSize=8)),
                Paragraph(f"<b>{r['Pénz']}</b>" if "0 Ft" not in r['Pénz'] else "", ParagraphStyle('C', fontName=f_reg, fontSize=8)),
                Paragraph(str(r['Rendelés_Full']), ParagraphStyle('C', fontName=f_reg, fontSize=7)),
                r['Összesen']
            ])
            if is_group: t_style.append(('BACKGROUND', (1, i+1), (1, i+1), colors.Color(0.95, 0.95, 0.95)))
            
        t = Table(data, colWidths=[10*mm, 65*mm, 25*mm, 22*mm, 58*mm, 10*mm])
        t.setStyle(TableStyle(t_style))
        t.wrapOn(p, 10*mm, 20*mm); th = t.wrap(w-20*mm, h-40*mm)[1]
        t.drawOn(p, 10*mm, h - 25*mm - th)
        p.showPage()

    # 2. RAKODÁSI LISTA (KATEGÓRIÁK SZERINT)
    all_codes = []
    for r in df['Rendelés_Full']: all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    counts = {}
    for c, code in all_codes: counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    ordered_codes = sorted([c for c in counts.keys() if c in menu], key=lambda x: menu[x]['excel_order'])
    
    last_cat = None
    for code in ordered_codes:
        info = menu[code]
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<b>--- {info['kategoria']} ---</b>", ParagraphStyle('C', fontName=f_bold, fontSize=9)), ""])
            last_cat = info['kategoria']
        sum_rows.append([f"{code} - {info['nev']}", f"{counts[code]} db"])
    
    p.setFont(f_bold, 12); p.drawString(10*mm, h - 15*mm, "RAKODÁSI LISTA ÖSSZESÍTŐ")
    st_t = Table([[Paragraph("<b>Étel</b>", ParagraphStyle('H', fontName=f_bold, fontSize=9)), "DB"]] + sum_rows, colWidths=[150*mm, 30*mm])
    st_t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
    st_t.wrapOn(p, 10*mm, 20*mm); h_st = st_t.wrap(180*mm, 250*mm)[1]
    st_t.drawOn(p, 10*mm, h - 25*mm - h_st)

    p.save(); buf.seek(0); return buf

# --- 5. FELHASZNÁLÓI FELÜLET (UI) ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'live_menu' not in st.session_state: st.session_state.live_menu = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("👤 Beállítások")
    f_n = st.text_input("Futár neve", "Szűcs István")
    f_p = st.text_input("Telefonszáma", "+36 20 886 8971")
    st.divider()
    old_csv = st.file_uploader("CSV betöltése (Megjegyzések/Sorrend)", type="csv")
    if old_csv:
        db_df = pd.read_csv(old_csv)
        st.session_state.weights = dict(zip(db_df['ID'].astype(str), db_df['Sorrend'].astype(float)))
        if 'Megjegyzés' in db_df.columns: st.session_state.notes = dict(zip(db_df['ID'].astype(str), db_df['Megjegyzés'].fillna("")))
    
    up_files = st.file_uploader("Napi PDF-ek feltöltése", accept_multiple_files=True)
    if up_files and st.button("🚀 FELDOLGOZÁS"):
        all_raw = []
        last_meta = None
        for f in up_files:
            rows, meta = parse_interfood_pdf(f)
            all_raw.extend(rows)
            if meta['year']: last_meta = meta
        if all_raw:
            if last_meta: st.session_state.live_menu = get_live_menu(last_meta['year'], last_meta['week'], last_meta['day'])
            st.session_state.mdf = merge_data(all_raw)
            st.rerun()

if st.session_state.mdf is not None:
    st.subheader("📍 Menetlevél és Sorrend")
    edited = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 SORREND MENTÉSE"):
            final = edited.sort_values('Sorrend').reset_index(drop=True)
            final['Sorrend'] = range(1, len(final) + 1)
            st.session_state.weights = dict(zip(final['ID'].astype(str), final['Sorrend']))
            st.session_state.notes = dict(zip(final['ID'].astype(str), final['Megjegyzés'].fillna("")))
            st.session_state.mdf = final
            st.rerun()
    with c2:
        csv = edited.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 CSV EXPORT", csv, "mentes.csv", use_container_width=True)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📄 ETIKETTEK (PDF)", create_label_pdf(edited, f_n, f_p), "etikettek.pdf", use_container_width=True)
    with col2:
        st.download_button("📋 MENETTERV + RAKLISTA (PDF)", create_manifest_pdf(edited, f_n), "menetterv.pdf", use_container_width=True)
