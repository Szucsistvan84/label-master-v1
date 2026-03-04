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
from reportlab.platypus import Table, TableStyle

st.set_page_config(page_title="Interfood v203.1", layout="wide")

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- PDF PARSER (v199.1 bevált logika) ---
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
                text_ns = "".join([w['text'] for w in line_words])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                uid = u_code_m.group(0).split('-')[-1]
                prefix = u_code_m.group(0).split('-')[0]
                tel_m = re.search(phone_pat, text_ns)
                final_tel = tel_m.group(0) if tel_m else ""
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                raw_orders = re.findall(order_pat, text_ns)
                valid_o, sq = [], 0
                for o in raw_orders:
                    parts = o.split('-')
                    q_val = int(parts[0][-1])
                    code_part = parts[1]
                    if len(code_part) > 3 and code_part[-1].isdigit():
                        code_part = code_part[:-1]
                    valid_o.append(f"{q_val}-{code_part}")
                    sq += q_val
                if valid_o:
                    rows.append({"Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, "Telefon": final_tel, "Rendelés": ", ".join(valid_o), "Összesen": sq})
    return rows

def merge_weekend_data(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
        order_str = ""
        if p_items: order_str += f"P: {', '.join(p_items)}"
        if z_items:
            if order_str: order_str += " | "
            order_str += f"SZ: {', '.join(z_items)}"
            base['Prefix'] = 'Z'
        base['Rendelés'] = order_str
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- MENETTERV FIX LÁBLÉCCEL ÉS KEVESEBB CÍMMEL ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    rows_per_page = 22 # Csökkentett lapszám a biztonságos láblécért
    total_p = math.ceil(len(df)/rows_per_page)

    for p_idx in range(total_p):
        # Fejléc
        p.setFont(f_bold, 12)
        p.drawString(15*mm, h-15*mm, f"MENETTERV - {fn}")
        p.setFont(f_reg, 8)
        p.drawRightString(w-15*mm, h-15*mm, f"Összesen: {len(df)} cím")
        
        y_table_top = h - 25*mm
        
        data = [["SOR", "NÉV / CÍM", "TELEFON", "RENDELÉS", "DB"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        
        for _, r in subset.iterrows():
            name_addr = f"{r['Ügyintéző']}\n{r['Cím']}"
            data.append([f"#{r['Sorrend']}", name_addr, r['Telefon'], r['Rendelés'], r['Összesen']])
        
        # Oszlopszélességek: SOR(12), NÉV(65), TEL(28), REND(65), DB(10) -> Össz: 180mm (A4-en 15mm margókkal)
        t = Table(data, colWidths=[12*mm, 65*mm, 28*mm, 65*mm, 10*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('FONTSIZE', (0,0), (-1,0), 8),
            ('BOTTOMPADDING', (0,0), (-1,0), 4),
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,1), (-1,-1), f_reg),
            ('FONTSIZE', (0,1), (-1,-1), 7.5),
            ('GRID', (0,0), (-1,-1), 0.1, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (4,0), (4,-1), 'CENTER'),
        ]))
        
        tw, th = t.wrap(w - 30*mm, h - 50*mm)
        t.drawOn(p, 15*mm, y_table_top - th)
        
        # LÁBLÉC - Oldalszám fixen 15mm-re a lap aljától
        p.setFont(f_reg, 8)
        p.setStrokeColor(colors.black)
        p.line(15*mm, 20*mm, w-15*mm, 20*mm)
        p.drawCentredString(w/2, 12*mm, f"{p_idx+1} /
