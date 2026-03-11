import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle, SimpleDocTemplate, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- KONFIGURÁCIÓ ---
VERZIO = "v203.80-FINAL-FIX"
DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

# --- BETŰTÍPUS ---
def register_fonts():
    try:
        if os.path.exists("DejaVuSans.ttf"):
            pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
            pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
            return "DejaVu", "DejaVu-Bold"
    except: pass
    return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERÉS JAVÍTVA (Pénz keresése új sorban) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    
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
                
                u_code_m = re.search(r'([HKSCPZ])-([0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                prefix, uid = u_code_m.group(1), u_code_m.group(2)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                
                # PÉNZ KERESÉSE (ugyanabban a sorban VAGY a következő 2 sorban)
                money = 0
                search_text = text_ws
                if i + 1 < len(sorted_y):
                    search_text += " " + " ".join([w['text'] for w in lines[sorted_y[i+1]]])
                if i + 2 < len(sorted_y):
                    search_text += " " + " ".join([w['text'] for w in lines[sorted_y[i+2]]])
                
                m_match = re.search(money_pat, search_text)
                if m_match:
                    try: money = int(re.sub(r'[^\d\-]', '', m_match.group(1)))
                    except: pass

                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, 
                        "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), 
                        "Pénz": money, "Összesen": sq, "Original_Order": y
                    })
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            if not day_group.empty:
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(day_group['Rendelés'].tolist())}")
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Pénz'] = group['Pénz'].sum()
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- ETIKETT JAVÍTOTT MARGÓKKAL ÉS ELVÁLASZTÓVAL ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm
    m = 6*mm # Megemelt margó a köztes sorok átfolyása ellen

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        r = df.iloc[i]

        p.setFont(f_bold, 8)
        p.drawString(x + m, y + lh - m, f"#{int(r['Sorrend'])}")
        p.setFont(f_reg, 7)
        p.drawRightString(x + lw - m, y + lh - m, f"ID: {r['ID']}")

        p.setFont(f_bold, 9)
        p.drawString(x + m, y + lh - m - 5*mm, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 8)
        p.drawRightString(x + lw - m, y + lh - m - 5*mm, str(r['Telefon']))

        p.setFont(f_reg, 8)
        p.drawString(x + m, y + lh - m - 10*mm, str(r['Cím'])[:45])

        # Rendelés
        order_style = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
        para = Paragraph(r['Rendelés_Full'], order_style)
        para.wrap(lw - 2*m, 10*mm)
        para.drawOn(p, x + m, y + m + 8*mm)

        # FEKETE ELVÁLASZTÓ VONAL A FUTÁR ADATAI FÖLÉ
        p.setLineWidth(0.5)
        p.line(x + m, y + m + 6*mm, x + lw - m, y + m + 6*mm)

        if int(r['Pénz']) > 0:
            p.setFont(f_bold, 10)
            p.drawString(x + m, y + m + 1.5*mm, f"FIZET: {int(r['Pénz'])} Ft")
        
        p.setFont(f_bold, 9)
        p.drawRightString(x + lw - m, y + m + 1.5*mm, f"{r['Összesen']} db")

        p.setFont(f_reg, 6)
        p.drawCentredString(x + lw/2, y + 2*mm, f"Futár: {fn} | {ft}")

    p.save(); buf.seek(0); return buf

# --- MENETTERV TÖBBOLDALAS JAVÍTÁS ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    header = Paragraph(f"<b>MENETTERV - Futár: {fn}</b>", styles['Title'])
    elements.append(header); elements.append(Spacer(1, 5*mm))
    
    data = [["SOR", "NÉV / CÍM", "TELEFON", "RENDELÉS", "PÉNZ", "DB"]]
    cell_style = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=10)
    
    for _, r in df.iterrows():
        data.append([
            f"#{int(r['Sorrend'])}",
            Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", cell_style),
            r['Telefon'],
            Paragraph(r['Rendelés_Full'], cell_style),
            f"{int(r['Pénz'])} Ft",
            r['Összesen']
        ])
    
    t = Table(data, colWidths=[12*mm, 55*mm, 25*mm, 65*mm, 20*mm, 10*mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('FONTNAME', (0,0), (-1,0), f_bold),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+36 20 886 8971")
    up_files = st.file_uploader("PDF feltöltés", accept_multiple_files=True)

if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_pro(f))
    if raw:
        st.session_state.mdf = pd.DataFrame(merge_data_flexible(raw))
        st.session_state.mdf['Sorrend'] = range(1, len(st.session_state.mdf) + 1)
        st.rerun()

if st.session_state.mdf is not None:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 ETIKETTEK (PDF)", create_label_pdf(edited, fn_in, ft_in), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 MENETTERV (PDF)", create_manifest_pdf(edited, fn_in), "menetterv.pdf", use_container_width=True)
