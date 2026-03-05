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

st.set_page_config(page_title="Interfood Logisztika v203.12", layout="wide")

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- PARSER (Pénzügyek nélkül) ---
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
                
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                final_tel = tel_m.group(0) if tel_m else ""
                
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                raw_orders = re.findall(order_pat, text_ws)
                valid_o, sq = [], 0
                for o in raw_orders:
                    parts = o.split('-')
                    q_val = int(re.sub(r'\D', '', parts[0])[-1])
                    valid_o.append(f"{q_val}-{parts[1]}")
                    sq += q_val
                
                if valid_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": final_tel, 
                        "Rendelés": ", ".join(valid_o), "Összesen": sq
                    })
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        if any(p in ['P', 'Z'] for p in group['Prefix']):
            base = group.iloc[0].copy().to_dict()
            p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
            z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
            order_str = ""
            # Bold tag-ek beillesztése a P: és SZ: elé
            if p_items: order_str += f"<b>P:</b> {', '.join(p_items)}"
            if z_items:
                if order_str: order_str += " | "
                order_str += f"<b>SZ:</b> {', '.join(z_items)}"
            base['Rendelés'] = order_str
            base['Összesen'] = group['Összesen'].sum()
            merged.append(base)
        else:
            row = group.iloc[0].copy().to_dict()
            row['Rendelés'] = f"<b>{row['Prefix']}:</b> {row['Rendelés']}"
            merged.append(row)
    return merged

# --- ETIKETT ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2 + 1*mm, (h - 7*lh)/2 
    
    order_style = ParagraphStyle('LabelOrder', fontName=f_reg, fontSize=7, leading=8, allowOverlap=0)
    
    for i in range(math.ceil(len(df)/21)*21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        
        if i < len(df):
            r = df.iloc[i]
            p.setLineWidth(0.2)
            p.rect(x+4*mm, y+3*mm, lw-8*mm, lh-6*mm)
            
            p.setFont(f_bold, 9); p.drawString(x+7*mm, y+36*mm, f"#{int(float(r['Sorrend']))}")
            p.setFont(f_reg, 7); p.drawRightString(x+lw-8*mm, y+36*mm, f"ID: {r['ID']}")
            # Név és telefon betűméret csökkentve
            p.setFont(f_bold, 8); p.drawString(x+7*mm, y+32*mm, str(r['Ügyintéző'])[:28])
            p.setFont(f_reg, 7); p.drawRightString(x+lw-8*mm, y+32*mm, str(r['Telefon']))
            
            p.setFont(f_reg, 7); p.drawString(x+7*mm, y+28.5*mm, str(r['Cím'])[:45])
            
            para = Paragraph(str(r['Rendelés']), order_style)
            para.wrapOn(p, lw-14*mm, 15*mm)
            para.drawOn(p, x+7*mm, y+13*mm)
            
            p.setFont(f_reg, 7); p.drawRightString(x+lw-8*mm, y+7*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4.5*mm, f"Futár: {fn} ({ft})")
    p.save(); buf.seek(0)
    return buf

# --- MENETTERV ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    # 25 sor / oldal beállítása
    rows_per_page = 25
    total_p = math.ceil(len(df)/rows_per_page)
    
    styles = getSampleStyleSheet()
    # Cellán belüli stílusok a tördeléshez
    cell_style = ParagraphStyle('CellStyle', fontName=f_reg, fontSize=7, leading=8)
    bold_cell_style = ParagraphStyle('BoldCellStyle', fontName=f_bold, fontSize=7, leading=8)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(15*mm, h-12*mm, f"MENETTERV - {fn}")
        y_table_top = h - 18*mm
        
        # Header checkbox oszloppal
        data = [["[ ]", "SOR", "NÉV / CÍM", "TELEFON", "RENDELÉS", "DB"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        
        for _, r in subset.iterrows():
            name_addr = Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", cell_style)
            orders = Paragraph(r['Rendelés'], cell_style)
            data.append(["[  ]", f"#{int(float(r['Sorrend']))}", name_addr, r['Telefon'], orders, r['Összesen']])
        
        # Oszlopszélességek finomhangolva
        t = Table(data, colWidths=[10*mm, 12*mm, 58*mm, 28*mm, 70*mm, 10*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('FONTSIZE', (0,0), (-1,-1), 7),
            ('GRID', (0,0), (-1,-1), 0.8, colors.black), # VASTAGABB RÁCS
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (1,-1), 'CENTER'),
            ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
            ('LEFTPADDING', (0,0), (-1,-1), 2),
            ('RIGHTPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        
        tw, th = t.wrap(w - 20*mm, h - 30*mm)
        t.drawOn(p, 10*mm, y_table_top - th)
        
        p.setFont(f_reg, 7); p.drawCentredString(w/2, 8*mm, f"{p_idx+1} / {total_p} oldal")
        if p_idx < total_p - 1: p.showPage()
        
    p.save(); buf.seek(0)
    return buf

# --- UI ---
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("🚚 Beállítások")
    fn = st.text_input("Futár neve", "Szűcs István")
    ft = st.text_input("Telefonszáma", "+36208868971")

st.title("🏷️ Interfood Logisztika v203.12")
up_files = st.file_uploader("PDF feltöltése", accept_multiple_files=True)

if up_files:
    f_order_data = [{"Sorrend": float(i+1), "Fájl": f.name} for i, f in enumerate(up_files)]
    f_order = st.data_editor(f_order_data, hide_index=True)
    if st.button("FELDOLGOZÁS"):
        raw = []
        for name in pd.DataFrame(f_order).sort_values("Sorrend")["Fájl"]:
            fobj = next(f for f in up_files if f.name == name)
            raw.extend(parse_interfood_pro(fobj))
        mdf = pd.DataFrame(merge_data_flexible(raw))
        mdf.insert(0, "Sorrend", range(1, len(mdf)+1))
        st.session_state.mdf = mdf.astype({"Sorrend": float})
        st.rerun()

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    if st.button("🔄 LISTA FRISSÍTÉSE"):
        new_df = edited_df.sort_values("Sorrend").copy()
        new_df["Sorrend"] = range(1, len(new_df) + 1)
        st.session_state.mdf = new_df.astype({"Sorrend": float})
        st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 ETIKETTEK"):
            pdf = create_label_pdf(edited_df.sort_values("Sorrend"), fn, ft)
            st.download_button("Mentés (etikett)", pdf, "etikettek.pdf")
    with c2:
        if st.button("📋 MENETTERV"):
            pdf = create_manifest_pdf(edited_df.sort_values("Sorrend"), fn)
            st.download_button("Mentés (menetterv)", pdf, "menetterv.pdf")
