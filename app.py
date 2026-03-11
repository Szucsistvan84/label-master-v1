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
VERZIO = "v203.85-FINAL-FIX"
DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

# --- BETŰTÍPUS ÉS ÉKEZET KEZELÉS ---
def register_fonts():
    # Megpróbáljuk betölteni a DejaVu betűtípust, ami biztosan kezeli az Ű és Ő karaktereket
    try:
        if os.path.exists("DejaVuSans.ttf"):
            pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
            pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
            return "DejaVu", "DejaVu-Bold"
    except: pass
    return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERÉS JAVÍTVA (Pénz: szám + szóköz + Ft keresése) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    # Kifejezett keresés: számjegyek, szóköz, majd "Ft"
    money_pat = r'(\d[\d\s]*)\s+Ft'
    
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
                
                # PÉNZ KERESÉSE a következő sorokban
                money = 0
                search_area = ""
                for next_idx in range(i, min(i + 4, len(sorted_y))):
                    search_area += " " + " ".join([w['text'] for w in lines[sorted_y[next_idx]]])
                
                m_match = re.search(money_pat, search_area)
                if m_match:
                    try: 
                        val = m_match.group(1).replace(" ", "")
                        money = int(val)
                    except: pass

                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        parts = o.split('-')
                        q = int(re.sub(r'\D', '', parts[0])[-1])
                        v_o.append(f"{q}-{parts[1]}"); sq += q
                    except: continue
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, 
                        "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), 
                        "Pénz": money, "Összesen": sq
                    })
    return rows

def merge_rows(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        days = []
        for p in ['H', 'K', 'S', 'C', 'P', 'Z']:
            d_grp = group[group['Prefix'] == p]
            if not d_grp.empty:
                days.append(f"{DAY_MAP[p]}: {', '.join(d_grp['Rendelés'].tolist())}")
        base['Rendelés_Full'] = " | ".join(days)
        base['Pénz'] = group['Pénz'].sum()
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- ETIKETT JAVÍTOTT VONALLAL ---
def create_labels(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm
    m = 5*mm

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        r = df.iloc[i]

        # Fejléc
        p.setFont(f_bold, 8)
        p.drawString(x + m, y + lh - m, f"#{int(r['Sorrend'])}")
        p.setFont(f_reg, 7)
        p.drawRightString(x + lw - m, y + lh - m, f"ID: {r['ID']}")

        # Név és Tel
        p.setFont(f_bold, 9)
        p.drawString(x + m, y + lh - m - 5*mm, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 8)
        p.drawRightString(x + lw - m, y + lh - m - 5*mm, str(r['Telefon']))

        # Cím
        p.setFont(f_reg, 8)
        p.drawString(x + m, y + lh - m - 10*mm, str(r['Cím'])[:45])

        # Rendelés
        para = Paragraph(r['Rendelés_Full'], ParagraphStyle('O', fontName=f_reg, fontSize=8, leading=9))
        para.wrap(lw - 2*m, 12*mm)
        para.drawOn(p, x + m, y + m + 10*mm)

        # Fizetési adatok (Vonal felett)
        if int(r['Pénz']) > 0:
            p.setFont(f_bold, 10)
            p.drawString(x + m, y + m + 4.5*mm, f"FIZET: {int(r['Pénz'])} Ft")
        
        p.setFont(f_bold, 9)
        p.drawRightString(x + lw - m, y + m + 4.5*mm, f"{r['Összesen']} db")

        # FEKETE ELVÁLASZTÓ VONAL (Fizetés alatt, Futár felett)
        p.setLineWidth(0.5)
        p.setStrokeColor(colors.black)
        p.line(x + m, y + m + 3.5*mm, x + lw - m, y + m + 3.5*mm)

        # Futár adatok (Vonal alatt)
        p.setFont(f_reg, 6.5)
        p.drawCentredString(x + lw/2, y + 1.2*mm, f"Futár: {fn} | {ft}")

    p.save(); buf.seek(0); return buf

# --- MENETTERV OLDALSZÁMOZÁSSAL ÉS JAVÍTOTT ÉKEZETTEL ---
def create_manifest(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_reg, 8)
        page_num = f"{doc.page} / {st.session_state.total_pages if 'total_pages' in st.session_state else '?'}"
        canvas.drawRightString(200*mm, 10*mm, f"{page_num} oldal")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, margin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    title = Paragraph(f"<b>MENETTERV - Futár: {fn}</b>", styles['Title'])
    elements.append(title); elements.append(Spacer(1, 5*mm))
    
    data = [["SOR", "NÉV / CÍM", "TELEFON", "RENDELÉS", "PÉNZ", "DB"]]
    cell_style = ParagraphStyle('C', fontName=f_reg, fontSize=8, leading=10)
    
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
    
    # Először legeneráljuk, hogy tudjuk az oldalszámot (egyszerűsített megoldás)
    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")

if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+36 20 886 8971")
    up_files = st.file_uploader("Interfood PDF-ek", accept_multiple_files=True)

if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_pro(f))
    if raw:
        st.session_state.mdf = pd.DataFrame(merge_rows(raw))
        st.session_state.mdf['Sorrend'] = range(1, len(st.session_state.mdf) + 1)
        st.rerun()

if st.session_state.mdf is not None:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 ETIKETTEK NYOMTATÁSA", create_labels(edited, fn_in, ft_in), "etikettek.pdf", use_container_width=True)
    with col2:
        st.download_button("📋 MENETTERV LETÖLTÉSE", create_manifest(edited, fn_in), "menetterv.pdf", use_container_width=True)
