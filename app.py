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

# --- 2. ÉTLAP ÉS PDF PARSER (Változatlan) ---

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

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    with pdfplumber.open(pdf_file) as pdf:
        text = pdf.pages[0].extract_text()
        if text:
            y_m, w_m, d_m = re.search(r'Év:\s*(\d{4})', text), re.search(r'Hét:\s*(\d{1,2})', text), re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', text)
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
                uid = u_code_m.group(0).split('-')[-1]
                prefix = u_code_m.group(0).split('-')[0]
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m, addr_m = re.search(phone_pat, text_ws.replace(" ", "")), re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                if v_o:
                    rows.append({"Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": address, "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), "Pénz": "0 Ft", "Összesen": sq})
    return rows, metadata

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p, has_weekend = [], False
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
        base['Megjegyzés'] = ""
        merged.append(base)
    res = pd.DataFrame(merged)
    res['Sorrend'] = range(1, len(res) + 1)
    res['Sorrend'] = res['Sorrend'].astype(float)
    # SORREND AZ ELSŐ HELYRE
    cols = ['Sorrend'] + [c for c in res.columns if c != 'Sorrend']
    return res[cols]

# --- 4. PDF GENERÁLÁS (MENETTERV FIZETÉSSEL) ---

def create_manifest_pdf(df, fn):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cleaned_addrs = [clean_addr(a) for a in df['Cím'].tolist()]
    
    rows_per_page = 22 
    total_p = math.ceil(len(df) / rows_per_page)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=8, alignment=1)
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=8, leading=9)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=7, leading=8)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(10*mm, h - 12*mm, f"MENETTERV - {fn} ({p_idx+1}/{total_p})")
        # FEJLÉC: Sorrend, Név/Cím, [ ], PÉNZ, Tel, Rendelés, Db
        data = [[Paragraph("<b>#</b>", head_s), Paragraph("<b>NÉV / CÍM / INFÓ</b>", head_s), Paragraph("<b>[ ]</b>", head_s), Paragraph("<b>PÉNZ</b>", head_s), Paragraph("<b>TEL</b>", head_s), Paragraph("<b>RENDELÉS</b>", head_s), Paragraph("<b>DB</b>", head_s)]]
        
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        t_style = [('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]
        
        for i, (_, r) in enumerate(subset.iterrows()):
            c_cleaned = clean_addr(r['Cím']); g_count = cleaned_addrs.count(c_cleaned)
            warn = f"▲ <b>CSOPORT ({g_count})</b><br/>" if g_count > 1 else ""
            m_text = f"<font color='red'><b>{r['Megjegyzés']}</b></font>" if r['Megjegyzés'] else ""
            
            data.append([
                f"{int(r['Sorrend'])}", 
                Paragraph(f"{warn}{r['Ügyintéző']}<br/><font size='7'>{r['Cím']}</font><br/>{m_text}", name_s), 
                "[ ]", 
                Paragraph(str(r['Pénz']), head_s),
                Paragraph(str(r['Telefon']), cell_s), 
                Paragraph(str(r['Rendelés_Full']), cell_s), 
                r['Összesen']
            ])
            if g_count > 1: t_style.append(('BACKGROUND', (1, i+1), (1, i+1), colors.Color(0.95, 0.95, 0.95)))
        
        t = Table(data, colWidths=[10*mm, 60*mm, 10*mm, 20*mm, 25*mm, 55*mm, 10*mm])
        t.setStyle(TableStyle(t_style))
        t.wrapOn(p, 10*mm, 20*mm); h_t = t.wrap(w - 20*mm, h - 35*mm)[1]
        t.drawOn(p, 10*mm, h - 22*mm - h_t)
        p.showPage()
    
    # Rakodási lista rész (Ugyanaz marad)
    p.save(); buf.seek(0); return buf

# --- UI ---

st.set_page_config(page_title="Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    c_n = st.text_input("Név", "Szűcs István")
    c_p = st.text_input("Tel", "+36 20 886 8971")
    up_files = st.file_uploader("PDF-ek", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in up_files: 
            rows, meta = parse_interfood_pdf(f)
            raw.extend(rows)
        if raw:
            st.session_state.mdf = merge_data(raw)
            st.rerun()

if st.session_state.mdf is not None:
    # A táblázatban a Sorrend az első oszlop
    edited_df = st.data_editor(
        st.session_state.mdf, 
        hide_index=True, 
        use_container_width=True,
        column_config={
            "Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f", step=0.1),
            "Pénz": st.column_config.TextColumn("Pénz (Fizetés)")
        }
    )
    
    if st.button("💾 MENTÉS ÉS ÚJRASORSZÁMOZÁS"):
        new_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
        new_df['Sorrend'] = range(1, len(new_df) + 1)
        new_df['Sorrend'] = new_df['Sorrend'].astype(float)
        st.session_state.mdf = new_df
        st.success("Sorrend véglegesítve!")
        st.rerun()
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    # Itt használjuk az új menetterv generátort
    c1.download_button("📋 MENETTERV + PÉNZ (PDF)", create_manifest_pdf(edited_df, c_n), "menetterv_penzzel.pdf")
    csv = edited_df.to_csv(index=False).encode('utf-8-sig')
    c2.download_button("📊 CSV EXPORT", csv, "napi_sorrend.csv", "text/csv")
