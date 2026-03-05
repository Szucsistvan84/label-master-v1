import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
import math
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

st.set_page_config(page_title="Interfood Logisztika v203.25", layout="wide")

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERÉS ÉS FELDOLGOZÁS ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                found = False
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w)
                        found = True
                        break
                if not found: lines[y] = [w]
            for y in sorted(lines.keys()):
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
                final_tel = tel_m.group(0) if tel_m else ""
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                raw_orders = re.findall(order_pat, text_ws)
                valid_o, sq = [], 0
                for o in raw_orders:
                    parts = o.split('-')
                    try:
                        q_val = int(re.sub(r'\D', '', parts[0])[-1])
                        valid_o.append(f"{q_val}-{parts[1]}")
                        sq += q_val
                    except: continue
                if valid_o:
                    rows.append({"Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, "Telefon": final_tel, "Rendelés": ", ".join(valid_o), "Összesen": sq})
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        has_saturday = any(p == 'Z' for p in group['Prefix'])
        base = group.iloc[0].copy().to_dict()
        base['HasSaturday'] = has_saturday
        
        if any(p in ['P', 'Z'] for p in group['Prefix']):
            p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
            z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
            order_str = ""
            if p_items: order_str += f"P: {', '.join(p_items)}"
            if z_items:
                if order_str: order_str += " | "
                order_str += f"SZ: {', '.join(z_items)}"
            base['Rendelés'] = order_str
            base['Összesen'] = group['Összesen'].sum()
            merged.append(base)
        else:
            row = group.iloc[0].copy().to_dict()
            pfix = "SZ:" if row['Prefix'] == 'Z' else f"{row['Prefix']}:"
            row['Rendelés'] = f"{pfix} {row['Rendelés']}"
            merged.append(row)
    return merged

# --- ETIKETT GENERÁLÁS ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2 + 1*mm, (h - 7*lh)/2 
    order_style = ParagraphStyle('LabelOrder', fontName=f_reg, fontSize=7, leading=8)
    promo_style = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, alignment=1, leading=11)
    
    total_labels = math.ceil(len(df)/21)*21
    for i in range(total_labels):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        
        if i < len(df):
            r = df.iloc[i]
            if r.get('HasSaturday', False) or "SZ:" in str(r['Rendelés']):
                p.setLineWidth(1.8) 
            else:
                p.setLineWidth(0.8) 
            p.rect(x+4*mm, y+3*mm, lw-8*mm, lh-6*mm)
            p.setFont(f_bold, 9); p.drawString(x+7*mm, y+36*mm, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 7); p.drawRightString(x+lw-8*mm, y+36*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 8); p.drawString(x+7*mm, y+28.5*mm, str(r['Ügyintéző'])[:30])
            p.setFont(f_reg, 7); p.drawRightString(x+lw-8*mm, y+28.5*mm, str(r['Telefon']))
            p.setFont(f_reg, 7); p.drawString(x+7*mm, y+25*mm, str(r['Cím'])[:45])
            para = Paragraph(str(r['Rendelés']), order_style)
            para.wrapOn(p, lw-14*mm, 15*mm); para.drawOn(p, x+7*mm, y+14*mm)
            p.setFont(f_reg, 7); p.drawRightString(x+lw-8*mm, y+10*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4.5*mm, f"Futár: {fn} ({ft})")
        else:
            promo_text = (
                f"<br/><br/><font size='9' face='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                f"Új Ügyfeleink részére!<br/>"
                f"Rendelés leadás:<br/>"
                f"<font size='8.5' face='{f_bold}'>{fn}</font><br/>"
                f"<font size='8.5' face='{f_bold}'>{ft}</font><br/><br/>"
                f"<font size='5'>* a kedvezmény telefonon leadott rendelésekre érvényesíthető területi képviselőnk által</font>"
            )
            para = Paragraph(promo_text, promo_style)
            para.wrapOn(p, lw-12*mm, lh-10*mm); para.drawOn(p, x+6*mm, y+8*mm)
    p.save(); buf.seek(0)
    return buf

# --- MENETTERV GENERÁLÁS OLDALSZÁMOZÁSSAL ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    rows_per_page = 25
    total_p = math.ceil(len(df)/rows_per_page)
    cell_style = ParagraphStyle('CellStyle', fontName=f_reg, fontSize=8.5, leading=11)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(15*mm, h-12*mm, f"MENETTERV - {fn}")
        
        # OLDALSZÁM HOZZÁADÁSA (Visszaállítva)
        p.setFont(f_reg, 8)
        p.drawCentredString(w/2, 10*mm, f"{p_idx + 1} / {total_p} oldal")
        
        data = [["SOR", "ÜGYFÉL NÉV / [ ] / CÍM", "TELEFON", "RENDELÉS", "DB"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        for _, r in subset.iterrows():
            name_box = Paragraph(f"<b>{r['Ügyintéző']}</b> [  ]<br/><font size='7'>{r['Cím']}</font>", cell_style)
            orders = Paragraph(str(r['Rendelés']), cell_style)
            data.append([f"#{int(r['Sorrend'])}", name_box, r['Telefon'], orders, r['Összesen']])
        t = Table(data, colWidths=[12*mm, 70*mm, 28*mm, 65*mm, 10*mm])
        t.setStyle(TableStyle([('FONTNAME', (0,0), (-1,0), f_bold), ('GRID', (0,0), (-1,-1), 0.5, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        tw, th = t.wrap(w - 20*mm, h - 35*mm); t.drawOn(p, 10*mm, (h-18*mm) - th)
        p.showPage()
    p.save(); buf.seek(0)
    return buf

# --- UI LOGIKA ---
if 'mdf' not in st.session_state: st.session_state.mdf = None
with st.sidebar:
    st.header("🚚 Szállítási adatok")
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+3620/886-89-71")

st.title("🏷️ Interfood Logisztika v203.25")
up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True)

if up_files:
    f_order_data = [{"Sorrend": float(i+1), "Fájl": f.name} for i, f in enumerate(up_files)]
    f_order = st.data_editor(f_order_data, hide_index=True)
    if st.button("📊 ADATOK FELDOLGOZÁSA"):
        raw = []
        sorted_files = pd.DataFrame(f_order).sort_values("Sorrend")["Fájl"]
        for name in sorted_files:
            fobj = next(f for f in up_files if f.name == name)
            raw.extend(parse_interfood_pro(fobj))
        mdf = pd.DataFrame(merge_data_flexible(raw))
        mdf.insert(0, "Sorrend", range(1, len(mdf)+1))
        st.session_state.mdf = mdf.astype({"Sorrend": float})

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True, key="main_editor")
    c_tools = st.columns([1, 1, 4])
    with c_tools[0]:
        if st.button("🔄 SORREND FRISSÍTÉSE"):
            new_df = edited_df.sort_values("Sorrend").reset_index(drop=True)
            new_df["Sorrend"] = range(1, len(new_df) + 1)
            st.session_state.mdf = new_df.astype({"Sorrend": float})
            st.rerun()
    c_dl = st.columns(2)
    with c_dl[0]:
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            pdf = create_label_pdf(st.session_state.mdf, fn_in, ft_in)
            st.download_button("Mentés: etikettek.pdf", pdf, "etikettek.pdf")
    with c_dl[1]:
        if st.button("📋 MENETTERV LETÖLTÉSE"):
            pdf = create_manifest_pdf(st.session_state.mdf, fn_in)
            st.download_button("Mentés: menetterv.pdf", pdf, "menetterv.pdf")
