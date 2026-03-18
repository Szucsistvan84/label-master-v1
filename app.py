import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import requests
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# --- 1. ÉTLAP KEZELÉSE (JAVÍTOTT KERESÉSSEL) ---

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
                        except: continue
            st.sidebar.success(f"✅ Étlap OK: {len(menu_map)} tétel")
    except Exception as e:
        st.sidebar.error(f"Excel hiba: {e}")
    return menu_map

# --- PDF PARSER (JÁRATSZÁM KINYERÉSSEL) ---

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jarat': "Ismeretlen"}
    
    with pdfplumber.open(pdf_file) as pdf:
        first_page_text = pdf.pages[0].extract_text()
        if first_page_text:
            # Járatszám kinyerése: Első számsor az első pontig
            jarat_m = re.search(r'^(\d+)\.', first_page_text)
            if jarat_m: metadata['jarat'] = jarat_m.group(1)
            
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
                
                uid = u_code_m.group(0).split('-')[-1]
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3
                
                money_val = "0 Ft"
                if i + 1 < len(sorted_y):
                    next_t = " ".join([w['text'] for w in sorted(lines[sorted_y[i+1]], key=lambda x: x['x0'])])
                    m_match = re.search(r'(-?\s?\d[\d\s]*\s*Ft)', next_t)
                    if m_match: money_val = m_match.group(1).strip()
                
                # Rendelések kinyerése (megtartjuk az eredeti kódot a * miatt)
                raw_orders = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "ID": str(uid), "Járat": metadata['jarat'], "Ügyintéző": clean_name, 
                        "Cím": address, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": money_val, "Összesen": sq
                    })
    return rows, metadata

# --- ADATOK ÖSSZEFÉSÜLÉSE (INTELLIGENS SORREND) ---

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    
    # Csoportosítás ID alapján, de megtartva a Járat infót
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        items = group['Rendelés'].tolist()
        base['Rendelés_Full'] = ", ".join(items)
        base['Összesen'] = group['Összesen'].sum()
        
        m_list = []
        for m_str in group['Pénz']:
            num = int(re.sub(r'[^\d-]', '', str(m_str)) or 0)
            if num != 0: m_list.append(num)
        base['Pénz'] = f"{sum(m_list) if m_list else 0} Ft"
        
        # CSV-ből jövő adatok visszaírása
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        
        # Sorrend kezelése: ha van elmentett súly, azt kapja, ha nincs, marad 999.0
        saved_weight = st.session_state.weights.get(str(uid))
        base['Sorrend'] = float(saved_weight) if saved_weight is not None else 999.0
        
        merged.append(base)
    
    res = pd.DataFrame(merged)
    # Ha nincs megadva sorrend (999.0), akkor a Járatszám + beolvasási sorrend legyen az alap
    res = res.sort_values(['Sorrend', 'Járat'], ascending=[True, True])
    return res

# --- PDF GENERÁLÁS (JÁRAT ÉS CSILLAG KEZELÉS) ---

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
    inner_m = 5.5*mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    
    for i in range(math.ceil(len(df) / 21) * 21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{i+1}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            
            # Alsó sáv: Járatszám + Futár adatai
            p.setFont(f_bold, 6.5)
            p.drawCentredString(x + lw/2, y + inner_m - 1.5*mm, f"[{r['Járat']}] Futár: {fn} | {ft}")
            
            # Pénz és darab
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            if m_val != "0":
                p.setFont(f_bold, 10); p.drawString(x + inner_m, y + inner_m + 3*mm, f"FIZET: {r['Pénz']}")
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 3*mm, f"{r['Összesen']} db")

    p.save(); buf.seek(0); return buf

# --- RAKODÁSI LISTA (CSILLAGOS KERESÉSSEL) ---

def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=7, leading=8)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=8, alignment=1)

    # --- RAKODÁSI LISTA SZÁMÍTÁSA ---
    all_codes = []
    for r in df['Rendelés_Full']: 
        all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    
    counts = {}
    for c, code in all_codes: 
        counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    
    # Itt a trükk: a keresésnél levágjuk a csillagot, de a kódot megtartjuk
    ordered_codes = sorted(counts.keys())

    last_cat = None
    for code in ordered_codes:
        lookup_code = code.replace('*', '') # Excelben csillag nélkül keressük
        info = menu.get(lookup_code, {'nev': 'Ismeretlen étel', 'ar': 0, 'kategoria': 'Egyéb', 'excel_order': 999})
        
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<br/><b>--- {info['kategoria']} ---</b>", cell_s), ""])
            last_cat = info['kategoria']
            
        sum_rows.append([Paragraph(f"<b>{code}</b> - {info['nev']}", cell_s), Paragraph(f"{counts[code]} db", head_s)])

    # Generálás (egyszerűsített Raklista kimenet)
    p.setFont(f_bold, 12); p.drawString(10*mm, h - 15*mm, f"RAKODÁSI LISTA - {fn}")
    t = Table([[Paragraph("ÉTEL", head_s), "DB"]] + sum_rows, colWidths=[150*mm, 30*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black)]))
    t.wrapOn(p, 10*mm, 20*mm); t.drawOn(p, 10*mm, h - 40*mm - (len(sum_rows)*5*mm))
    
    p.save(); buf.seek(0); return buf

# --- UI ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'weights' not in st.session_state: st.session_state.weights = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("👤 Futár")
    c_n = st.text_input("Név", "Szűcs István")
    c_p = st.text_input("Tel", "+36 20 886 8971")
    
    st.divider()
    old_csv = st.file_uploader("Előző napi adatok (CSV)", type="csv")
    if old_csv:
        db_df = pd.read_csv(old_csv)
        # Kényszerítjük a String típust az ID-nél, hogy a keresés tuti legyen
        st.session_state.weights = dict(zip(db_df['ID'].astype(str), db_df['Sorrend'].astype(float)))
        if 'Megjegyzés' in db_df.columns: 
            st.session_state.notes = dict(zip(db_df['ID'].astype(str), db_df['Megjegyzés'].fillna("")))
        st.success("✅ CSV betöltve!")

    up_files = st.file_uploader("Napi PDF-ek (akár több is)", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in up_files: 
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows)
            if meta['year'] and meta['week']:
                st.session_state.live_menu = get_live_menu(meta['year'], meta['week'], meta['day'])
        
        st.session_state.mdf = merge_data(raw)
        st.rerun()

if st.session_state.mdf is not None:
    st.subheader("📍 Menetlevél szerkesztése")
    # Tizedesvesszős sorrend engedélyezése a NumberColumn-nal
    edited_df = st.data_editor(
        st.session_state.mdf, hide_index=True, use_container_width=True,
        column_config={
            "Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f"),
            "ID": st.column_config.TextColumn("ID", disabled=True),
            "Járat": st.column_config.TextColumn("Járat", disabled=True),
        }
    )
    
    if st.button("✅ SORREND ÉS INFÓK MENTÉSE"):
        st.session_state.weights = dict(zip(edited_df['ID'].astype(str), edited_df['Sorrend']))
        st.session_state.notes = dict(zip(edited_df['ID'].astype(str), edited_df['Megjegyzés']))
        st.session_state.mdf = edited_df.sort_values('Sorrend')
        st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("📄 ETIKETTEK", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 MENETTERV", create_manifest_pdf(edited_df, c_n), "menetterv.pdf", use_container_width=True)
    with c3:
        csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 EXPORT CSV", csv_data, "adatok_mentese.csv", use_container_width=True)
