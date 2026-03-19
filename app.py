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

# --- 1. ALAPFUNKCIÓK & BETŰTÍPUSOK ---

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

# --- 2. PDF PARSER & ADATKEZELÉS ---

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None}
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    with pdfplumber.open(pdf_file) as pdf:
        text = pdf.pages[0].extract_text()
        if text:
            y_m = re.search(r'Év:\s*(\d{4})', text)
            w_m = re.search(r'Hét:\s*(\d{1,2})', text)
            d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', text)
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
        base['Megjegyzés'] = ""
        merged.append(base)
    res = pd.DataFrame(merged)
    res['Sorrend'] = range(1, len(res) + 1)
    res['Sorrend'] = res['Sorrend'].astype(float)
    # SORREND AZ ELSŐ OSZLOPBA
    cols = ['Sorrend'] + [c for c in res.columns if c != 'Sorrend']
    return res[cols]

# --- 3. ETIKETT MODUL (FIXÁLT & VÉDETT) ---

def create_label_pdf(df, fn, ft):
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    inner_m = 5.5*mm
    
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    note_s = ParagraphStyle('Note', fontName=f_bold, fontSize=7, leading=8, textColor=colors.red)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1)
    
    total_labels = math.ceil(len(df) / 21) * 21
    
    for i in range(total_labels):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            if r.get('Hétvégi'):
                p.saveState()
                p.setFillColor(colors.lightgrey)
                p.rect(x + 1*mm, top_y - 8.5*mm, lw - 2*mm, 4.5*mm, fill=1, stroke=0)
                p.restoreState()
            
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{int(r['Sorrend'])}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            if r.get('Megjegyzés'):
                pn = Paragraph(f"<b>INFÓ: {r['Megjegyzés']}</b>", note_s)
                pn.wrap(lw - 2*inner_m, 5*mm); pn.drawOn(p, x + inner_m, top_y - 17*mm)
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm); para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 3*mm, f"{r['Összesen']} db")
            p.setLineWidth(0.2); p.line(x + inner_m, y + inner_m + 2*mm, x + lw - inner_m, y + inner_m + 2*mm)
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + inner_m - 1.5*mm, f"Futár: {fn} | {ft}")
        else:
            # MARKETING (KERET NÉLKÜL - VÉDETT)
            m_text = (f"<font size='10.5'><b>15% kedvezmény* 3 hétig</b></font><br/>Új Ügyfeleink részére!<br/><br/>"
                      f"<b>Rendelés leadás:</b><br/><b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                      f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető<br/>területi képviselőnk által</b></font>")
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw - 6*mm, lh - 6*mm)
            para.drawOn(p, x + (lw - pw)/2, y + (lh - ph)/2)
    p.save(); buf.seek(0); return buf

# --- 4. MENETTERV MODUL (PÉNZ OSZZLOPPAL) ---

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
    
    p.save(); buf.seek(0); return buf

# --- 5. UI ---

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
    # A táblázatban a Sorrend az első oszlop, és engedi a tizedeseket
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
        st.success("Sorrend rögzítve!")
        st.rerun()
    
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.download_button("📄 ETIKETTEK (PDF)", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf")
    c2.download_button("📋 MENETTERV + PÉNZ (PDF)", create_manifest_pdf(edited_df, c_n), "menetterv.pdf")
    csv = edited_df.to_csv(index=False).encode('utf-8-sig')
    c3.download_button("📊 CSV EXPORT", csv, "napi_sorrend.csv", "text/csv")
