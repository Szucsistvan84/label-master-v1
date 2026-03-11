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
from reportlab.platypus import Paragraph, Table, TableStyle, SimpleDocTemplate, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- FONT ÉS ÉKEZET FIX (Ű betűhöz) ---
def register_fonts():
    try:
        # Ehhez a DejaVuSans.ttf fájlnak a mappában kell lennie a szerveren!
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERÉS (Pénz szűrés: csak ha ott a Ft!) ---
def parse_interfood_stable(pdf_file):
    rows = []
    money_pat = r'(\d[\d\s]*)\s*Ft'
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    
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
                
                u_match = re.search(r'([HKSCPZ])-(\d{5,7})', text_ws)
                if not u_match: continue
                
                prefix, uid = u_match.group(1), u_match.group(2)
                
                # Pénz keresése szigorúan (csak Ft-al)
                money = 0
                search_area = ""
                for next_idx in range(i, min(i + 4, len(sorted_y))):
                    search_area += " " + " ".join([w['text'] for w in lines[sorted_y[next_idx]]])
                
                m_match = re.search(money_pat, search_area)
                if m_match:
                    val = re.sub(r'[^\d]', '', m_match.group(1))
                    money = int(val) if val else 0

                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
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
                        "Pénz": money, "Összesen": sq
                    })
    return rows

def merge_rows(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    day_map = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        days = []
        for p in ['H', 'K', 'S', 'C', 'P', 'Z']:
            d_grp = group[group['Prefix'] == p]
            if not d_grp.empty:
                days.append(f"{day_map[p]}: {', '.join(d_grp['Rendelés'].tolist())}")
        base['Rendelés_Full'] = " | ".join(days)
        base['Pénz'] = group['Pénz'].sum()
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- PDF GENERÁLÓK (Label + Manifest) ---
def create_labels_v4(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm
    m = 5*mm
    for i, r in df.iterrows():
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        p.setFont(f_bold, 7); p.drawString(x + m, y + lh - 4*mm, f"#{int(r['Sorrend'])}")
        p.drawRightString(x + lw - m, y + lh - 4*mm, f"ID: {r['ID']}")
        p.setFont(f_bold, 8.5); p.drawString(x + m, y + lh - 8*mm, str(r['Ügyintéző'])[:30])
        p.setFont(f_reg, 7.5); p.drawString(x + m, y + lh - 11.5*mm, str(r['Cím'])[:45])
        para = Paragraph(r['Rendelés_Full'], ParagraphStyle('R', fontName=f_reg, fontSize=7.5, leading=8.5))
        para.wrap(lw - 2*m, 15*mm); para.drawOn(p, x + m, y + 11*mm)
        p.setFont(f_bold, 9.5); p_text = f"FIZET: {int(r['Pénz'])} Ft"
        p.drawString(x + m, y + 6*mm, p_text)
        p.drawRightString(x + lw - m, y + 6*mm, f"{r['Összesen']} db")
        p.setLineWidth(0.5); p.line(x + m, y + 4.5*mm, x + lw - m, y + 4.5*mm)
        p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + 1.5*mm, f"Futár: {fn} | {ft}")
    p.save(); buf.seek(0); return buf

def create_manifest_v4(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, margin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    chunks = [df[i:i + 25] for i in range(0, len(df), 25)]
    for idx, chunk in enumerate(chunks):
        elements.append(Paragraph(f"<b>MENETTERV - Futár: {fn}</b>", styles['Title']))
        data = [["#", "NÉV / CÍM", "TELEFON", "RENDELÉS", "PÉNZ", "DB"]]
        for _, r in chunk.iterrows():
            data.append([f"#{int(r['Sorrend'])}", Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", ParagraphStyle('S', fontName=f_reg, fontSize=8)), r['Telefon'], Paragraph(r['Rendelés_Full'], ParagraphStyle('S', fontName=f_reg, fontSize=7)), f"{int(r['Pénz'])} Ft", r['Összesen']])
        t = Table(data, colWidths=[10*mm, 55*mm, 25*mm, 65*mm, 20*mm, 10*mm])
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTNAME', (0,0), (-1,0), f_bold), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        elements.append(t); elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph(f"<para align='right'><b>{idx+1} / {len(chunks)} oldal</b></para>", styles['Normal']))
        if idx < len(chunks) - 1: elements.append(PageBreak())
    doc.build(elements); buf.seek(0); return buf

# --- UI ---
st.title("Interfood Logisztika v203.86")

if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+36 20 886 8971")
    up_files = st.file_uploader("Interfood PDF-ek", accept_multiple_files=True)

if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_stable(f))
    if raw:
        st.session_state.mdf = pd.DataFrame(merge_rows(raw))
        st.session_state.mdf['Sorrend'] = range(1, len(st.session_state.mdf) + 1)
        st.rerun()

if st.session_state.mdf is not None:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    if st.button("💾 MÓDOSÍTÁSOK MENTÉSE"):
        st.session_state.mdf = edited
        st.success("Mentve!")

    c1, c2, c3 = st.columns(3)
    with c1: st.download_button("📥 ETIKETTEK (PDF)", create_labels_v4(edited, fn_in, ft_in), "etikettek.pdf", use_container_width=True)
    with c2: st.download_button("📋 MENETTERV (PDF)", create_manifest_v4(edited, fn_in), "menetterv.pdf", use_container_width=True)
    with c3:
        csv = edited.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV EXPORT", csv, "mentes.csv", use_container_width=True)
