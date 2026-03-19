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
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
import requests

# --- ALAPFUNKCIÓK & ÉTLAP (Változatlan) ---

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
                                menu_map[code] = {'nev': name_on_day[:60], 'ar': int(p_str), 'kategoria': col_a.split(" - ")[1].strip(), 'excel_order': i}
                        except: continue
    except: pass
    return menu_map

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

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
    if 'weights' in st.session_state:
        res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999.0).astype(float)
    else:
        res['Sorrend'] = range(1, len(res) + 1)
    return res.sort_values('Sorrend')

# --- JAVÍTOTT PDF GENERÁLÁS ---

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
            
            # --- SZÜRKE KIEMELÉS JAVÍTÁSA ---
            # Itt ellenőrizzük, hogy van-e szombati (Z) tétel
            if r.get('Hétvégi') == True:
                p.saveState()
                p.setFillColor(colors.lightgrey) # Standard világosszürke
                # A téglalap a név és a telefon sorát takarja (top_y-tól lefelé)
                # x + 1mm-től indul, szélessége lw-2mm, magassága 7mm
                p.rect(x + 1*mm, top_y - 9*mm, lw - 2*mm, 6.5*mm, fill=1, stroke=0)
                p.restoreState()
            
            # Szövegek (A szürke sáv után rajzoljuk, hogy felül legyen)
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{i+1}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            if str(r.get('Megjegyzés', '')).strip() and str(r.get('Megjegyzés')) != 'None':
                pn = Paragraph(f"<b>INFÓ: {r['Megjegyzés']}</b>", note_s)
                pn.wrap(lw - 2*inner_m, 5*mm); pn.drawOn(p, x + inner_m, top_y - 17*mm)
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            
            base_y = y + inner_m 
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, base_y + 3*mm, f"{r['Összesen']} db")
            p.setLineWidth(0.2); p.line(x + inner_m, base_y + 2*mm, x + lw - inner_m, base_y + 2*mm)
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, base_y - 1.5*mm, f"Futár: {fn} | {ft}")

    p.save(); buf.seek(0); return buf

# --- create_manifest_pdf és a többi rész változatlanul marad ---
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

    all_codes = []
    for r in df['Rendelés_Full']: 
        all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    
    counts = {}
    for c, code in all_codes: 
        counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    total_val, total_items = 0, 0
    
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

    footer_rows = [[Paragraph(f"<b>ÖSSZESEN: {total_items} db étel</b>", cell_s), Paragraph(f"<b>{total_val} Ft</b>", head_s)],
                   [Paragraph(f"<b>VÁRHATÓ JUTALÉK (13%):</b>", cell_s), Paragraph(f"<b>{round(total_val*0.13)} Ft</b>", head_s)]]

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

# --- UI (Változatlanul hagyva a legutóbbi működő állapotot) ---

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

if st.session_state.mdf is not None:
    cols = ['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Rendelés_Full', 'Összesen', 'Pénz', 'Megjegyzés']
    display_df = st.session_state.mdf[[c for c in cols if c in st.session_state.mdf.columns]]
    st.subheader("📍 Menetlevél szerkesztése")
    edited_df = st.data_editor(display_df, hide_index=True, use_container_width=True,
                               column_config={"Sorrend": st.column_config.NumberColumn("Sorrend", step=1, format="%d"),
                                             "ID": st.column_config.TextColumn("Azonosító", disabled=True)})
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
