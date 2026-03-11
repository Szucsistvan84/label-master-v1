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

# --- FONT ÉS ALAPOK ---
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

# --- PDF PARSER (ADATKINYERÉS) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*\s*Ft)' 
    
    with pdfplumber.open(pdf_file) as pdf:
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
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
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
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": money_val, "Összesen": sq
                    })
    return rows

def merge_data(raw_rows):
    if not raw_rows: return None
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            items = group[group['Prefix'] == pfix]['Rendelés'].tolist()
            if items: o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        total_m = 0
        for m_str in group['Pénz']:
            num_part = re.sub(r'[^\d-]', '', str(m_str))
            if num_part and num_part != "-": total_m += int(num_part)
        base['Pénz'] = f"{total_m} Ft"
        merged.append(base)
    return pd.DataFrame(merged)

# --- PDF GENERÁLÁS ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
    inner_m = 5*mm # A kért 5mm-es védőtávolság
    
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1)

    total_labels = math.ceil(len(df) / 21) * 21
    for i in range(total_labels):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            
            # FELSŐ RÉSZ (Név, ID, Sorszám) - 5mm-rel lejjebb kezdve
            top_y = y + lh - inner_m
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{int(r.get('Sorrend', i+1))}")
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            # KÖZÉPSŐ RÉSZ (Rendelés)
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            pw, ph = para.wrap(lw - 2*inner_m, 10*mm)
            # Úgy helyezzük el, hogy ne lógjon bele az alsó szekcióba
            para.drawOn(p, x + inner_m, y + inner_m + 12*mm)
            
            # ALSÓ RÉSZ (Pénz, Darab, Futár) - Szigorúan az alsó 5mm felett
            base_y = y + inner_m 
            
            # Pénz és darabszám (5mm margó felett)
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            if m_val != "0" and m_val != "":
                p.setFont(f_bold, 10); p.drawString(x + inner_m, base_y + 6*mm, f"FIZET: {r['Pénz']}")
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, base_y + 6*mm, f"{r['Összesen']} db")
            
            # Elválasztó vonal (pontosan a futár adatai felett, margón belül)
            p.setStrokeColor(colors.black); p.setLineWidth(0.2)
            p.line(x + inner_m, base_y + 4.5*mm, x + lw - inner_m, base_y + 4.5*mm)
            
            # Futár adatai (közvetlenül az alsó 5mm-es határvonalon)
            p.setFont(f_reg, 6.5)
            p.drawCentredString(x + lw/2, base_y + 1*mm, f"Futár: {fn} | {ft}")

        else:
            # MARKETING (itt is 5mm margóval)
            m_text = f"<font size='10.5'><b>15% kedvezmény* 3 hétig</b></font><br/>Új Ügyfeleinknek!<br/><br/><b>Rendelés leadás:</b><br/><b>{fn}</b>, tel: <b>{ft}</b><br/><br/><font size='5.5'><b>* kedvezmény területi képviselőnknél érhető el</b></font>"
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw - 2*inner_m, lh - 2*inner_m)
            para.drawOn(p, x + (lw-pw)/2, y + (lh-ph)/2)
            
            p.setStrokeColor(colors.lightgrey); p.rect(x, y, lw, lh, stroke=1, fill=0)

    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    rows_per_page = 25 
    total_p = math.ceil(len(df) / rows_per_page)
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=9, leading=10)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=10)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=7, alignment=1) # Kisebb fejléc
    
    for p_idx in range(total_p):
        # Fejléc és oldalszám
        p.setFont(f_bold, 11); p.drawString(10*mm, h - 12*mm, f"MENETTERV - {fn}")
        p.setFont(f_reg, 8); p.drawRightString(w - 10*mm, h - 12*mm, f"{p_idx+1} / {total_p} oldal")
        
        data = [[
            Paragraph("<b>#</b>", head_s), 
            Paragraph("<b>[ ]</b>", head_s), 
            Paragraph("<b>NÉV / CÍM</b>", head_s), 
            Paragraph("<b>TEL</b>", head_s), 
            Paragraph("<b>PÉNZ</b>", head_s), 
            Paragraph("<b>RENDELÉS</b>", head_s), 
            Paragraph("<b>DB</b>", head_s)
        ]]
        
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        for _, r in subset.iterrows():
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            m_disp = str(r['Pénz']) if m_val != "0" and m_val != "" else ""
            data.append([
                f"#{int(r.get('Sorrend', 0))}",
                "[  ]", # Egyszerű checkbox
                Paragraph(f"<b>{r['Ügyintéző']}</b><br/><font size='7'>{r['Cím']}</font>", name_s),
                Paragraph(f"<font size='7'>{r['Telefon']}</font>", cell_s),
                Paragraph(f"<b>{m_disp}</b>", cell_s),
                Paragraph(str(r['Rendelés_Full']), cell_s),
                r['Összesen']
            ])
            
        # Oszlopszélességek optimalizálása: Név/Cím (70mm), Telefon/Pénz lecsökkentve
        t = Table(data, colWidths=[10*mm, 10*mm, 70*mm, 22*mm, 20*mm, 53*mm, 8*mm])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.2, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (1,-1), 'CENTER'),
            ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
        ]))
        tw, th = t.wrap(w - 15*mm, h - 35*mm)
        t.drawOn(p, 7*mm, (h - 20*mm) - th)
        p.showPage()
    p.save(); buf.seek(0); return buf

# --- UI ---
st.set_page_config(page_title="Interfood Logisztika", layout="wide")
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("Beállítások")
    c_n = st.text_input("Futár neve", "Szűcs István")
    c_p = st.text_input("Telefonszáma", "+36 20 886 8971")
    up_files = st.file_uploader("PDF feltöltés", accept_multiple_files=True)
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in up_files: raw.extend(parse_interfood_pdf(f))
        if raw:
            mdf = merge_data(raw)
            mdf['Sorrend'] = range(1, len(mdf) + 1)
            st.session_state.mdf = mdf
            st.rerun()

if st.session_state.mdf is not None:
    st.session_state.mdf = st.data_editor(st.session_state.mdf, hide_index=True)
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 ETIKETTEK (Fix Margók)", create_label_pdf(st.session_state.mdf, c_n, c_p), "etikettek.pdf", use_container_width=True)
    with col2:
        st.download_button("📋 MENETTERV (Széles oszlop)", create_manifest_pdf(st.session_state.mdf, c_n), "menetterv.pdf", use_container_width=True)

