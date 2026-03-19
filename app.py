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
    # Tisztítjuk a nap nevét (pl. "Péntek," -> "Péntek")
    clean_day = day_name.replace(',', '').strip()
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    menu_map = {}
    day_to_col = {'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6}
    target_col = day_to_col.get(clean_day, 3) 

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
                                menu_map[code] = {'nev': name_on_day[:60], 'ar': int(p_str), 'kategoria': current_category, 'excel_order': i}
                        except: continue
            st.sidebar.success(f"✅ Étlap betöltve: {clean_day}")
    except Exception as e: st.sidebar.error(f"Excel hiba: {e}")
    return menu_map

# --- ALAPFUNKCIÓK ---
def register_fonts():
    try:
        # A korábban mentett információ alapján DejaVu betűtípust használunk
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def clean_customer_name(name):
    """Eltávolítja a technikai kódokat (pl. P-493505) a névből."""
    if not name: return ""
    # Eltávolítja a magányos betű-szám kódokat az elejéről vagy végéről
    name = re.sub(r'^[HKSCPZ]-\d+\s*', '', name)
    name = re.sub(r'\s*[HKSCPZ]-\d+$', '', name)
    return name.strip()

# --- PDF PARSER ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"year": None, "week": None, "day": "", "route": ""}
    
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*\s*Ft)' 
    
    with pdfplumber.open(pdf_file) as pdf:
        # 1. FEJLÉC ADATOK KINYERÉSE
        first_page_text = pdf.pages[0].extract_text() or ""
        first_line = first_page_text.split('\n')[0]
        
        route_m = re.search(r'(\d{4})\.\s*járat', first_line)
        if route_m: meta["route"] = route_m.group(1)
        
        year_m = re.search(r'Év:\s*(\d{4})', first_line)
        if year_m: meta["year"] = int(year_m.group(1))
        
        week_m = re.search(r'Hét:\s*(\d{1,2})', first_line)
        if week_m: meta["week"] = int(week_m.group(1))
        
        day_m = re.search(r'Nap:\s*([^ ]+)', first_line)
        if day_m: meta["day"] = day_m.group(1).replace(',', '').strip()

        # 2. TARTALOM FELDOLGOZÁSA
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w); break
                else: lines[y] = [w]
            
            sorted_y = sorted(lines.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                prefix = u_code_m.group(0).split('-')[0]
                uid = u_code_m.group(0).split('-')[-1]
                
                # Oszlopok koordináta alapján
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355]) # Cím
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490]) # Ügyintéző
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                if not clean_name:
                    b2 = " ".join([w['text'] for w in line_words if 40 <= w['x0'] < 150])
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b2).replace(prefix, "").strip()

                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                
                money_val = "0 Ft"
                if i + 1 < len(sorted_y):
                    next_line_text = " ".join([w['text'] for w in sorted(lines[sorted_y[i+1]], key=lambda x: x['x0'])])
                    m_match = re.search(money_pat, next_line_text)
                    if m_match: money_val = m_match.group(1).strip()

                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q_part = o.split('-')[0]
                        q = int(re.sub(r'\D', '', q_part)) if re.sub(r'\D', '', q_part) else 1
                        v_o.append(f"{q}-{o.split('-')[-1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": money_val, "Összesen": sq,
                        "Járat": meta["route"]
                    })
    return rows, meta

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p, m_list = [], []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items: o_p.append(f"{DAY_MAP.get(pfix, 'Nap')}: {', '.join(items)}")
            for m_str in day_group['Pénz']:
                num = int(re.sub(r'[^\d-]', '', str(m_str)) or 0)
                if num != 0: m_list.append(num)
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Pénz'] = f"{sum(m_list) if m_list else 0} Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
    
    res = pd.DataFrame(merged)
    if 'weights' in st.session_state and st.session_state.weights:
        res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999.0).astype(float)
    else: res['Sorrend'] = range(1, len(res) + 1)
    return res.sort_values('Sorrend')

# --- PDF GENERÁLÁS ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    inner_m = 4*mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    
    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        r = df.iloc[i]
        
        p.setFillColor(colors.black)
        p.setFont(f_reg, 9)
        p.drawString(x + inner_m, y + lh - 6*mm, f"#{i+1}")
        p.drawRightString(x + lw - inner_m, y + lh - 6*mm, f"ID: {r['ID']}")
        
        p.setFont(f_bold, 10)
        p.drawString(x + inner_m, y + lh - 11.5*mm, clean_customer_name(str(r['Ügyintéző']))[:28])
        p.setFont(f_reg, 9)
        p.drawRightString(x + lw - inner_m, y + lh - 11.5*mm, str(r['Telefon']))
        
        p.setFont(f_reg, 8)
        p.drawString(x + inner_m, y + lh - 17*mm, str(r['Cím'])[:45])
        
        para = Paragraph(str(r['Rendelés_Full']), order_s)
        para.wrap(lw - 2*inner_m, 15*mm)
        para.drawOn(p, x + inner_m, y + 10*mm)
        
        m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
        if m_val != "0" and m_val != "":
            p.setFont(f_bold, 10); p.drawString(x + inner_m, y + 5*mm, f"FIZET: {r['Pénz']}")
        p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + 5*mm, f"{r['Összesen']} db")
        
        p.setLineWidth(0.1*mm); p.setStrokeColor(colors.grey)
        p.line(x + inner_m, y + 3.5*mm, x + lw - inner_m, y + 3.5*mm)
        p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + 1*mm, f"Futár: {fn} | Járat: {r.get('Járat', 'N/A')}")
    
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    # Fejléc szöveg összeállítása a PDF-ből kinyert adatokkal
    header_info = f"{meta.get('year', '')}. {meta.get('week', '')}. hét - {meta.get('day', '')}"
    
    rows_per_page = 22 
    total_p = math.ceil(len(df) / rows_per_page)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=8, alignment=1)
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=9, leading=10)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=7, leading=8)

    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(10*mm, h - 12*mm, f"MENETTERV - {fn} ({header_info})")
        p.drawRightString(w - 10*mm, h - 12*mm, f"{p_idx + 1}/{total_p}. oldal")
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM</b>", head_s), Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>TEL</b>", head_s), Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        for i, (_, r) in enumerate(subset.iterrows()):
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            m_disp = f"<b>{r['Pénz']}</b>" if m_val != "0" and m_val != "" else ""
            data.append([f"#{p_idx*rows_per_page+i+1}", Paragraph(f"{r['Ügyintéző']}<br/><font size='7'>{r['Cím']}</font>", name_s), "[ ]", Paragraph(str(r['Telefon']), cell_s), Paragraph(m_disp, cell_s), Paragraph(str(r['Rendelés_Full']), cell_s), r['Összesen']])
        t = Table(data, colWidths=[10*mm, 60*mm, 8*mm, 25*mm, 22*mm, 55*mm, 10*mm]); t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        t.wrapOn(p, 7*mm, 20*mm); h_t = t.wrap(w - 14*mm, h - 35*mm)[1]; t.drawOn(p, 7*mm, h - 22*mm - h_t); p.showPage()
    
    # RAKODÁSI LISTA (ugyanúgy, mint korábban)
    all_codes = []
    for r in df['Rendelés_Full']: 
        found = re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r))
        all_codes.extend(found)
    counts = {}
    for c, code in all_codes: counts[code] = counts.get(code, 0) + int(c)
    menu = st.session_state.get('live_menu', {})
    sum_rows = []; total_val, total_items = 0, 0
    ordered_codes = sorted([c for c in counts.keys() if c in menu], key=lambda x: menu[x]['excel_order'])
    last_cat = None
    for code in ordered_codes:
        info = menu[code]; count = counts[code]; total_val += (count * info['ar']); total_items += count
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<br/><b>--- {info['kategoria']} ---</b>", cell_s), ""])
            last_cat = info['kategoria']
        sum_rows.append([Paragraph(f"<b>{code}</b> - {info['nev']}", cell_s), Paragraph(f"{count} db", head_s)])
    
    p.setFont(f_bold, 12); p.drawString(10*mm, h - 15*mm, f"RAKODÁSI LISTA ({header_info})")
    st_t = Table([[Paragraph("ÉTEL", head_s), "DB"]] + sum_rows, colWidths=[150*mm, 30*mm]); st_t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black)]))
    st_t.wrapOn(p, 10*mm, 20*mm); h_st = st_t.wrap(180*mm, 260*mm)[1]; st_t.drawOn(p, 10*mm, h - 25*mm - h_st)
    p.save(); buf.seek(0); return buf

# --- UI ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'live_menu' not in st.session_state: st.session_state.live_menu = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta' not in st.session_state: st.session_state.meta = {}
if 'weights' not in st.session_state: st.session_state.weights = {}

with st.sidebar:
    st.header("👤 Beállítások")
    c_n = st.text_input("Név", "Szűcs István"); c_p = st.text_input("Tel", "+36 20 886 8971"); st.divider()
    up_files = st.file_uploader("Interfood Napi PDF-ek", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in up_files: 
            rows, meta = parse_interfood_pdf(f); raw.extend(rows)
            if meta['year']: st.session_state.meta = meta # Az utolsó fájl metaadatait mentjük
        
        if raw:
            m = st.session_state.meta
            st.session_state.live_menu = get_live_menu(m['year'], m['week'], m['day'])
            st.session_state.mdf = merge_data(raw); st.rerun()

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    if st.button("✅ MÓDOSÍTÁSOK MENTÉSE"):
        st.session_state.weights = dict(zip(edited_df['ID'].astype(str), edited_df['Sorrend']))
        st.session_state.notes = dict(zip(edited_df['ID'].astype(str), edited_df['Megjegyzés']))
        st.session_state.mdf = merge_data(st.session_state.mdf.to_dict('records')); st.rerun()
    
    ca, cb = st.columns(2)
    with ca: st.download_button("🏷️ ETIKETTEK", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf", use_container_width=True)
    with cb: st.download_button("📋 MENETTERV", create_manifest_pdf(edited_df, c_n, st.session_state.meta), "menetterv.pdf", use_container_width=True)
