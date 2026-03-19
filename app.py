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

# --- 1. ALAPFUNKCIÓK & FONT ---

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

# --- 2. ONLINE ÉTLAP ÉS PDF OLVASÓ ---

def get_live_menu_data(meta_list):
    """Próbálunk nevet és árat párosítani a kódokhoz az Interfood API-ból"""
    menu_map = {}
    if not meta_list: return menu_map
    
    year = meta_list[0].get('year')
    week = meta_list[0].get('week')
    if not year or not week: return menu_map

    url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            df = pd.read_excel(BytesIO(resp.content), engine='openpyxl')
            # Itt egy egyszerűsített logika a kódok és nevek kinyerésére
            for i in range(len(df)):
                cell = str(df.iloc[i, 0])
                if " - " in cell:
                    parts = cell.split(" - ")
                    code = parts[0].strip()
                    name = parts[1].strip()
                    # Ár keresése (általában a név alatti vagy melletti cellában van szám)
                    price = 0
                    for j in range(1, 7):
                        val = str(df.iloc[i+1, j])
                        p_search = re.sub(r'\D', '', val)
                        if p_search: 
                            price = int(p_search)
                            break
                    menu_map[code] = {"nev": name, "ar": price}
    except: pass
    return menu_map

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jarat': None}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    
    with pdfplumber.open(pdf_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            p_text = page.extract_text() or ""
            full_text += p_text + "\n"
            
            # Fejléc adatok kinyerése minden oldalon próbálkozva
            if not metadata['jarat']:
                j_m = re.search(r'(\d{4})\.\s*járat', p_text)
                if j_m: metadata['jarat'] = j_m.group(1)
            if not metadata['year']:
                y_m = re.search(r'Év:\s*(\d{4})', p_text)
                if y_m: metadata['year'] = y_m.group(1)
            if not metadata['week']:
                w_m = re.search(r'Hét:\s*(\d{1,2})', p_text)
                if w_m: metadata['week'] = w_m.group(1)
            if not metadata['day']:
                d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű, ]+)', p_text)
                if d_m: metadata['day'] = d_m.group(1).split('InterFood')[0].strip()

        # Sorok feldolgozása (szavak alapján a pontosabb pozicionálásért)
        for page in pdf.pages:
            lines = page.extract_text().split('\n')
            for line in lines:
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', line)
                if not u_code_m: continue
                
                uid = u_code_m.group(0).split('-')[-1]
                prefix = u_code_m.group(0).split('-')[0]
                tel_m = re.search(phone_pat, line.replace(" ", ""))
                
                # Egyszerűsített cím és név kinyerés a sorból
                raw_orders = re.findall(order_pat, line)
                if raw_orders:
                    v_o, sq = [], 0
                    for o in raw_orders:
                        try:
                            q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                            v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                        except: continue
                    
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": "Beolvasott Ügyfél", 
                        "Cím": "Cím helye", "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": "0 Ft", "Összesen": sq
                    })
    return rows, metadata

# --- 3. MENETTERV (JAVÍTOTT TÖLTÖTTSÉG ÉS PÉNZ) ---

def create_manifest_pdf(df, fn, meta_list):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cleaned_addrs = [clean_addr(a) for a in df['Cím'].tolist()]
    
    jaratok = ", ".join(sorted(list(set([m['jarat'] for m in meta_list if m['jarat']]))))
    datum = meta_list[0]['day'] if meta_list else "Ismeretlen dátum"
    
    rows_per_page = 28  # Megemelt sorzám a jobb kihasználtságért
    total_p = math.ceil(len(df) / rows_per_page)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=8, alignment=1)
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=8, leading=9)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=7, leading=8)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 10); p.drawString(10*mm, h - 10*mm, f"MENETTERV - Járat: {jaratok} | {datum}")
        p.setFont(f_reg, 8); p.drawRightString(w - 10*mm, h - 10*mm, f"Futár: {fn} | Oldal: {p_idx+1}/{total_p}")
        
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM / INFÓ</b>", head_s), Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>TEL</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        
        for i, (_, r) in enumerate(subset.iterrows()):
            c_cleaned = clean_addr(r['Cím']); g_count = cleaned_addrs.count(c_cleaned)
            warn = f"▲ <b>CSOPORT ({g_count})</b><br/>" if g_count > 1 else ""
            penz_val = "" if str(r['Pénz']).strip().lower() in ["0 ft", "0", ""] else str(r['Pénz'])
            
            data.append([
                f"{int(r['Sorrend'])}", 
                Paragraph(f"{warn}{r['Ügyintéző']}<br/><font size='6'>{r['Cím']}</font>", name_s), 
                "[ ]", 
                Paragraph(f"<b>{penz_val}</b>", head_s),
                Paragraph(str(r['Telefon']), cell_s), 
                Paragraph(str(r['Rendelés_Full']), cell_s), 
                r['Összesen']
            ])
        
        t = Table(data, colWidths=[8*mm, 58*mm, 8*mm, 20*mm, 24*mm, 62*mm, 8*mm])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.3, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('LEFTPADDING', (0,0), (-1,-1), 2),
            ('RIGHTPADDING', (0,0), (-1,-1), 2),
        ]))
        t.wrapOn(p, 10*mm, 15*mm); t.drawOn(p, 10*mm, h - 20*mm - (len(data)*8.5*mm))
        p.showPage()
    
    p.save(); buf.seek(0); return buf

# --- 4. RAKLISTA (OLDALTÖRÉSSEL, NEVEKKEL ÉS JUTALÉKKAL) ---

def create_raklista_pdf(df, jarat_info, menu_data):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    all_items = []
    for r in df['Rendelés_Full']: 
        all_items.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    
    counts = {}
    for c, code in all_items: counts[code] = counts.get(code, 0) + int(c)
    
    sorted_codes = sorted(counts.keys())
    total_revenue = 0
    
    # Adatok előkészítése táblázathoz
    table_data = [[Paragraph("<b>KÓD</b>", f_bold), Paragraph("<b>ÉTEL NEVE</b>", f_bold), Paragraph("<b>DB</b>", f_bold), Paragraph("<b>EGYSÉGÁR</b>", f_bold), Paragraph("<b>ÖSSZESEN</b>", f_bold)]]
    
    for code in sorted_codes:
        db = counts[code]
        info = menu_data.get(code, {"nev": "Ismeretlen étel", "ar": 0})
        subtotal = db * info['ar']
        total_revenue += subtotal
        table_data.append([
            code, 
            info['nev'][:40], 
            f"{db} db", 
            f"{info['ar']} Ft", 
            f"{subtotal} Ft"
        ])

    # Megjelenítés oldaltöréssel
    rows_per_page = 35
    for i in range(0, len(table_data), rows_per_page):
        p.setFont(f_bold, 14); p.drawString(10*mm, h - 15*mm, f"RAKODÁSI LISTA - Járat: {jarat_info}")
        subset = table_data[i:i+rows_per_page]
        if i > 0: subset = table_data[:1] + subset # Fejléc ismétlése
        
        t = Table(subset, colWidths=[20*mm, 80*mm, 20*mm, 30*mm, 35*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
        t.wrapOn(p, 10*mm, 30*mm); t.drawOn(p, 10*mm, h - 30*mm - (len(subset)*6*mm))
        
        if i + rows_per_page >= len(table_data): # Utolsó oldal alja
            curr_y = h - 40*mm - (len(subset)*6*mm)
            p.line(10*mm, curr_y, w-10*mm, curr_y)
            p.setFont(f_bold, 11)
            p.drawString(120*mm, curr_y - 10*mm, f"NAPI FORGALOM: {total_revenue} Ft")
            p.setFont(f_reg, 11)
            p.drawString(120*mm, curr_y - 17*mm, f"13% JUTALÉK: {round(total_revenue * 0.13)} Ft")
        
        p.showPage()
        
    p.save(); buf.seek(0); return buf

# --- 5. UI ÉS INDÍTÁS ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta_data' not in st.session_state: st.session_state.meta_data = []

with st.sidebar:
    st.header("⚙️ Beállítások")
    c_n = st.text_input("Futár Neve", "Szűcs István")
    c_p = st.text_input("Telefonszám", "+36 20 886 8971")
    up_files = st.file_uploader("PDF menettervek", accept_multiple_files=True)
    
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw, metas = [], []
        for f in up_files: 
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows)
            metas.append(meta)
        if raw:
            st.session_state.mdf = pd.DataFrame(raw) # Egyszerűsített merge
            # Itt elvégezzük a Sorrend kiosztást
            st.session_state.mdf['Sorrend'] = range(1, len(st.session_state.mdf) + 1)
            st.session_state.mdf['Rendelés_Full'] = st.session_state.mdf['Rendelés']
            st.session_state.meta_data = metas
            st.rerun()

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    
    j_str = ", ".join(list(set([m['jarat'] for m in st.session_state.meta_data if m['jarat']])))
    menu_info = get_live_menu_data(st.session_state.meta_data)
    
    c1.download_button("📋 MENETTERV", create_manifest_pdf(edited_df, c_n, st.session_state.meta_data), "menetterv.pdf")
    c2.download_button("📦 RAKLISTA + JUTALÉK", create_raklista_pdf(edited_df, j_str, menu_info), "raklista.pdf")
    c3.download_button("📊 CSV EXPORT", edited_df.to_csv(index=False).encode('utf-8-sig'), "adatok.csv")
