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

# --- 1. ALAPBEÁLLÍTÁSOK ÉS FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        # A korábban mentett font név használata
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def clean_customer_name(name):
    if not name: return ""
    name = re.sub(r'^[HKSCPZ]-\d+\s*', '', name)
    name = re.sub(r'\s*[HKSCPZ]-\d+$', '', name)
    return name.strip()

# --- 2. ÉTLAP LETÖLTÉS AZ API-RÓL ---
def get_live_menu(year, week, day_name):
    clean_day = day_name.replace(',', '').strip()
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    menu_map = {}
    day_to_col = {'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6}
    target_col = day_to_col.get(clean_day, 5) 

    try:
        resp = requests.get(excel_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if resp.status_code == 200:
            df = pd.read_excel(BytesIO(resp.content), engine='openpyxl')
            current_cat = "Egyéb"
            for i in range(len(df)):
                row = df.iloc[i]
                col_a = str(row.iloc[0]).strip()
                if col_a and col_a != 'nan' and " - " in col_a:
                    parts = col_a.split(" - ")
                    code = parts[0].strip()
                    current_cat = parts[1].strip()
                    val = str(row.iloc[target_col]).strip()
                    if val and val != 'nan' and len(val) > 2:
                        try:
                            price = re.sub(r'\D', '', str(df.iloc[i+1].iloc[target_col]))
                            menu_map[code] = {
                                'nev': val[:60], 
                                'ar': int(price or 0), 
                                'kategoria': current_cat, 
                                'excel_order': i
                            }
                        except: pass
    except: pass
    return menu_map

# --- 3. PDF FELDOLGOZÁS ---
def parse_interfood_pdf(pdf_file):
    rows = []
    meta = {"year": None, "week": None, "day": "", "route": ""}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*\s*Ft)'

    with pdfplumber.open(pdf_file) as pdf:
        # Metaadatok kinyerése az első sorból
        first_page_text = pdf.pages[0].extract_text() or ""
        first_line = first_page_text.split('\n')[0]
        meta["route"] = (re.search(r'(\d{4})\.\s*járat', first_line) or [None, ""])[1]
        meta["year"] = int((re.search(r'Év:\s*(\d{4})', first_line) or [None, 0])[1])
        meta["week"] = int((re.search(r'Hét:\s*(\d{1,2})', first_line) or [None, 0])[1])
        meta["day"] = (re.search(r'Nap:\s*([^ ]+)', first_line) or [None, ""])[1].replace(',', '').strip()

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
                full_text = " ".join([w['text'] for w in line_words])
                
                u_m = re.search(r'([HKSCPZ])-(\d{5,7})', full_text)
                if not u_m: continue
                
                prefix, uid = u_m.groups()
                # Név és cím keresése koordináta alapján
                addr = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 350])
                name_raw = " ".join([w['text'] for w in line_words if 350 <= w['x0'] < 500])
                
                tel = (re.search(phone_pat, full_text.replace(" ", "")) or [None, ""])[1]
                
                money = "0 Ft"
                if i + 1 < len(sorted_y):
                    next_text = " ".join([w['text'] for w in sorted(lines[sorted_y[i+1]], key=lambda x: x['x0'])])
                    m_m = re.search(money_pat, next_text)
                    if m_m: money = m_m.group(1).strip()

                orders = re.findall(order_pat, full_text)
                if orders:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": name_raw if name_raw else "Ismeretlen",
                        "Cím": addr, "Telefon": tel, "Rendelés": ", ".join(orders), 
                        "Pénz": money, "Járat": meta["route"]
                    })
    return rows, meta

# --- 4. ADATOK ÖSSZEFŰZÉSE ---
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
            if items: o_p.append(f"{DAY_MAP.get(pfix)}: {', '.join(items)}")
            for m_str in day_group['Pénz']:
                num = int(re.sub(r'[^\d-]', '', str(m_str)) or 0)
                if num != 0: m_list.append(num)
        
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Rendelés'].apply(lambda x: sum([int(c.split('-')[0]) for c in x.split(', ') if '-' in c])).sum()
        base['Pénz'] = f"{sum(m_list)} Ft"
        base['Megjegyzés'] = st.session_state.notes.get(str(uid), "")
        merged.append(base)
    
    res = pd.DataFrame(merged)
    res['Sorrend'] = res['ID'].astype(str).map(st.session_state.weights).fillna(999).astype(float)
    if all(res['Sorrend'] == 999): res['Sorrend'] = range(1, len(res) + 1)
    return res.sort_values('Sorrend')

# --- 5. ETIKETT GENERÁLÁS (5MM MARGÓ + SZOMBATI SZÜRKE + EMELT ALSÓ SOR) ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    m = 5*mm # Biztonsági margó
    
    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        r = df.iloc[i]
        
        # Szombati kiemelés (Név sáv mögött)
        if "Szo:" in str(r['Rendelés_Full']):
            p.setFillColor(colors.lightgrey)
            p.rect(x + m, y + 26.5*mm, lw - 2*m, 5*mm, fill=1, stroke=0)

        p.setFillColor(colors.black)
        p.setFont(f_reg, 7); p.drawString(x + m, y + lh - m - 2*mm, f"#{i+1}")
        p.drawRightString(x + lw - m, y + lh - m - 2*mm, f"ID: {r['ID']}")
        
        p.setFont(f_bold, 9)
        p.drawString(x + m, y + 27.5*mm, clean_customer_name(str(r['Ügyintéző']))[:24])
        p.setFont(f_reg, 8); p.drawRightString(x + lw - m, y + 27.5*mm, str(r['Telefon']))
        
        p.setFont(f_reg, 7); p.drawString(x + m, y + 23.5*mm, str(r['Cím'])[:40])
        
        o_style = ParagraphStyle('O', fontName=f_reg, fontSize=7, leading=8)
        para = Paragraph(str(r['Rendelés_Full']), o_style)
        para.wrap(lw - 2*m, 12*mm)
        para.drawOn(p, x + m, y + 11*mm)
        
        # Alsó sorok (Emelve a vágás miatt)
        if "0 Ft" not in str(r['Pénz']):
            p.setFont(f_bold, 9); p.drawString(x + m, y + 7.5*mm, f"FIZET: {r['Pénz']}")
        p.setFont(f_bold, 8.5); p.drawRightString(x + lw - m, y + 7.5*mm, f"{r['Összesen']} db")
        
        # Futár adatok legalsó sorban (biztonságos 4mm-en)
        p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + 4*mm, f"Futár: {fn} ({ft}) | Járat: {r.get('Járat', 'N/A')}")
    
    p.save(); buf.seek(0); return buf

# --- 6. MENETTERV ÉS RAKLISTA (CSOPORTOSÍTÁSSAL ÉS OLDALTÖRÉSSEL) ---
def create_manifest_pdf(df, fn, meta):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    header_info = f"{meta.get('year')}. {meta.get('week')}. hét - {meta.get('day')}"
    
    # --- MENETTERV CSOPORTOSÍTÁSSAL ---
    df['Addr_Key'] = df['Cím'].apply(lambda x: str(x).split(',')[0].strip())
    y_pos = h - 20*mm
    p.setFont(f_bold, 12); p.drawString(10*mm, y_pos, f"MENETTERV - {fn} ({header_info})")
    y_pos -= 10*mm

    cell_s = ParagraphStyle('C', fontName=f_reg, fontSize=7.5, leading=9)
    head_s = ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)

    # Táblázat fejléce
    header = [Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM</b>", head_s), "[ ]", Paragraph("<b>TEL</b>", head_s), Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]
    
    for addr, group in df.groupby('Addr_Key', sort=False):
        data = []
        is_group = len(group) > 1
        for i, (_, r) in enumerate(group.iterrows()):
            p_val = f"<b>{r['Pénz']}</b>" if "0 Ft" not in str(r['Pénz']) else ""
            data.append([
                f"#{i+1 if is_group else ''}",
                Paragraph(f"<b>{clean_customer_name(r['Ügyintéző'])}</b><br/>{r['Cím']}", cell_s),
                "[ ]", r['Telefon'], Paragraph(p_val, cell_s), Paragraph(r['Rendelés_Full'], cell_s), r['Összesen']
            ])
        
        t = Table(data, colWidths=[10*mm, 55*mm, 8*mm, 25*mm, 22*mm, 58*mm, 10*mm])
        style = [('GRID', (0,0), (-1,-1), 0.2, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]
        if is_group:
            style.append(('BACKGROUND', (0,0), (-1,-1), colors.lightgrey))
            style.append(('BOX', (0,0), (-1,-1), 1.5, colors.black))
        
        t.setStyle(TableStyle(style))
        tw, th = t.wrap(w-20*mm, h)
        if y_pos - th < 20*mm: p.showPage(); y_pos = h - 20*mm
        t.drawOn(p, 10*mm, y_pos - th)
        y_pos -= (th + 2*mm)

    # --- RAKLISTA OLDALTÖRÉSSEL ---
    p.showPage()
    p.setFont(f_bold, 14); p.drawString(10*mm, h - 20*mm, f"RAKODÁSI LISTA ({header_info})")
    
    all_codes = []
    for r in df['Rendelés_Full']:
        all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    
    counts = {}
    for c, code in all_codes: counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_data = [[Paragraph("<b>ÉTEL</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
    
    ordered_codes = sorted([c for c in counts.keys() if c in menu], key=lambda x: menu[x]['excel_order'])
    last_cat = None
    for code in ordered_codes:
        info = menu[code]
        if info['kategoria'] != last_cat:
            sum_data.append([Paragraph(f"<b>--- {info['kategoria']} ---</b>", cell_s), ""])
            last_cat = info['kategoria']
        sum_data.append([f"{code} - {info['nev']}", f"{counts[code]} db"])
    
    # Raklista táblázat darabolása oldalakra
    rows_per_page = 35
    for i in range(0, len(sum_data), rows_per_page):
        if i > 0: p.showPage()
        chunk = sum_data[i : i + rows_per_page]
        st_t = Table(chunk, colWidths=[150*mm, 30*mm])
        st_t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9)]))
        st_t.wrapOn(p, 10*mm, 20*mm)
        st_t.drawOn(p, 10*mm, h - 30*mm - (len(chunk)*6.5*mm))

    p.save(); buf.seek(0); return buf

# --- 7. UI ÉS STREAMLIT LOGIKA ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")

if 'notes' not in st.session_state: st.session_state.notes = {}
if 'weights' not in st.session_state: st.session_state.weights = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("📂 Beállítások")
    
    # CSV VISSZATÖLTÉS
    csv_up = st.file_uploader("Előző napi sorrend (CSV)", type="csv")
    if csv_up:
        old_df = pd.read_csv(csv_up)
        st.session_state.weights = dict(zip(old_df['ID'].astype(str), old_df['Sorrend']))
        st.session_state.notes = dict(zip(old_df['ID'].astype(str), old_df['Megjegyzés'].fillna("")))
        st.success("Adatok betöltve!")

    st.divider()
    f_name = st.text_input("Futár neve", "Szűcs István")
    f_tel = st.text_input("Telefonszám", "+36 20 886 8971")
    
    up_files = st.file_uploader("Interfood PDF-ek", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in up_files:
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows)
            st.session_state.meta = meta
        
        if raw:
            st.session_state.live_menu = get_live_menu(meta['year'], meta['week'], meta['day'])
            st.session_state.mdf = merge_data(raw)
            st.rerun()

if st.session_state.mdf is not None:
    st.subheader("📋 Kiszállítási lista")
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    if st.button("🔄 SORREND ÉS MEGYJEGYZÉSEK FRISSÍTÉSE"):
        st.session_state.weights = dict(zip(edited_df['ID'].astype(str), edited_df['Sorrend']))
        st.session_state.notes = dict(zip(edited_df['ID'].astype(str), edited_df['Megjegyzés']))
        st.session_state.mdf = merge_data(st.session_state.mdf.to_dict('records'))
        st.success("Módosítások mentve!")
        st.rerun()

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("🏷️ ETIKETTEK", create_label_pdf(edited_df, f_name, f_tel), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 MENETTERV + RAKLISTA", create_manifest_pdf(edited_df, f_name, st.session_state.meta), "menetterv.pdf", use_container_width=True)
    with c3:
        csv_data = edited_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button("💾 SORREND MENTÉSE (CSV)", csv_data, f"export_{datetime.date.today()}.csv", use_container_width=True)
