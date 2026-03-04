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

st.set_page_config(page_title="Interfood v198.9", layout="wide")

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- PDF PARSER (v198.9 - Tisztított kódokkal) ---
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
                text_ns = "".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                f_code = u_code_m.group(0)
                prefix, uid = f_code.split('-')[0], f_code.split('-')[-1]
                
                tel_m = re.search(phone_pat, text_ns)
                final_tel = tel_m.group(0) if tel_m else ""
                
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                orders = re.findall(order_pat, text_ns)
                valid_o, sq = [], 0
                for o in orders:
                    parts = o.split('-')
                    if len(parts) < 2: continue
                    q_str = parts[0]
                    # Csak az utolsó számjegyet vesszük, hogy ne vigyük tovább a sorvégi darabszámot
                    q = int(q_str[-1]) 
                    valid_o.append(f"{q}-{parts[1]}")
                    sq += q
                
                if sq > 0:
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

# --- ETIKETT GENERÁTOR (Fix marketinggel) ---
def create_label_pdf(df, fn, ft, marketing_raw):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2, (h - 7*lh)/2
    
    # Marketing szöveg behelyettesítése
    m_lines = [line.replace("[futár neve]", fn).replace("[futár telefonszáma]", ft) for line in marketing_raw.split('\n')]

    for i in range(math.ceil(len(df)/21)*21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        p.setLineWidth(0.2); p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
        
        if i < len(df):
            r = df.iloc[i]
            p.setLineWidth(1.2 if r['Prefix'] == 'Z' else 0.2); p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
            p.setFont(f_bold, 10); p.drawString(x+5*mm, y+36*mm, f"#{r['Sorrend']}")
            p.drawRightString(x+lw-5*mm, y+36*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x+5*mm, y+31*mm, str(r['Ügyintéző'])[:24])
            p.setFont(f_reg, 7.5); p.drawRightString(x+lw-5*mm, y+31*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x+5*mm, y+27*mm, str(r['Cím'])[:45])
            
            p.setFont(f_bold, 7)
            r_text = str(r['Rendelés'])
            if " | " in r_text:
                pts = r_text.split(" | ")
                p.drawString(x+5*mm, y+20*mm, pts[0][:50])
                p.drawString(x+5*mm, y+16*mm, pts[1][:50])
            else:
                p.drawString(x+5*mm, y+18*mm, r_text[:50])
            
            p.setFont(f_bold, 8); p.drawRightString(x+lw-5*mm, y+10*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+5*mm, f"Futár: {fn} ({ft})")
        else:
            p.setFont(f_bold, 10); p.drawCentredString(x+lw/2, y+34*mm, m_lines[0])
            p.setFont(f_reg, 9); p.drawCentredString(x+lw/2, y+30*mm, m_lines[1])
            p.setFont(f_bold, 8); p.drawCentredString(x+lw/2, y+24*mm, m_lines[2])
            p.setFont(f_reg, 8); p.drawCentredString(x+lw/2, y+19*mm, m_lines[3])
            p.setFont(f_reg, 6)
            for j, extra in enumerate(m_lines[4:]):
                p.drawCentredString(x+lw/2, y+13*mm-(j*3*mm), extra)

    p.save(); buf.seek(0)
    return buf

# --- TÁBLÁZATOS MENETTERV FIX LÁBLÉCCEL ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    rows_per_page = 28 # Kevesebb sor = biztosabb lábléc
    total_p = math.ceil(len(df)/rows_per_page)

    for p_idx in range(total_p):
        p.setFont(f_bold, 12); p.drawString(15*mm, h-15*mm, f"MENETTERV - {fn}")
        y = h - 25*mm
        # Fejléc fix oszlopszélességekkel
        p.setFont(f_bold, 7.5)
        p.drawString(15*mm, y, "SOR"); p.drawString(28*mm, y, "NÉV / CÍM"); p.drawString(82*mm, y, "TELEFON"); p.drawString(108*mm, y, "RENDELÉS"); p.drawRightString(w-15*mm, y, "DB")
        y -= 2*mm; p.line(15*mm, y, w-15*mm, y); y -= 5*mm
        
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        for _, r in subset.iterrows():
            p.setFont(f_bold, 8); p.drawString(15*mm, y, f"#{r['Sorrend']}")
            p.setFont(f_reg, 8); p.drawString(28*mm, y, str(r['Ügyintéző'])[:25])
            p.drawString(82*mm, y, str(r['Telefon']))
            p.setFont(f_bold, 7); p.drawString(108*mm, y, str(r['Rendelés'])[:60])
            p.drawRightString(w-15*mm, y, str(r['Összesen']))
            y -= 4*mm
            p.setFont(f_reg, 7); p.setStrokeColor(colors.lightgrey)
            p.drawString(28*mm, y, str(r['Cím'])[:80])
            y -= 1.5*mm; p.line(15*mm, y, w-15*mm, y); y -= 4*mm
            p.setStrokeColor(colors.black)
        
        # FIX LÁBLÉC
        p.setFont(f_reg, 7); p.drawCentredString(w/2, 12*mm, f"- {p_idx+1} / {total_p} oldal -")
        if p_idx < total_p - 1: p.showPage()
        
    p.save(); buf.seek(0)
    return buf

# --- UI ---
with st.sidebar:
    st.header("🚚 Kiszállítási adatok")
    fn = st.text_input("Futár neve", "Szűcs István")
    ft = st.text_input("Telefonszáma", "+36208868971")
    st.divider()
    m_raw = st.text_area("Marketing szöveg", 
        "15% kedvezmény* 3 hétig\nÚj Ügyfeleink részére!\nRendelés leadás:\n[futár neve], tel: [futár telefonszáma]\n* a kedvezmény telefonon leadott rendelésekre\nérvényesíthető területi képviselőnk által", 
        height=180)

st.title("🏷️ Interfood Logisztika v198.9")
up_files = st.file_uploader("Feltöltés", accept_multiple_files=True)

if up_files:
    # Fájlok sorrendezése táblázatban
    f_order = st.data_editor([{"Sorrend": i+1, "Fájl": f.name} for i, f in enumerate(up_files)], hide_index=True)
    if st.button("FELDOLGOZÁS"):
        raw = []
        for name in pd.DataFrame(f_order).sort_values("Sorrend")["Fájl"]:
            fobj = next(f for f in up_files if f.name == name)
            raw.extend(parse_interfood_pro(fobj))
        st.session_state.mdf = pd.DataFrame(merge_weekend_data(raw))
        st.session_state.mdf.insert(0, "Sorrend", range(1, len(st.session_state.mdf)+1))
        st.rerun()

if st.session_state.get('mdf') is not None:
    st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            pdf = create_label_pdf(st.session_state.mdf, fn, ft, m_raw)
            num_pages = math.ceil(len(st.session_state.mdf) / 21)
            st.warning(f"🖨️ Helyezz be {num_pages} lapot címkével LEFELÉ!")
            st.download_button("Mentés (PDF)", pdf, "etikettek_v198.pdf")
    with c2:
        if st.button("📋 MENETTERV LETÖLTÉSE"):
            pdf = create_manifest_pdf(st.session_state.mdf, fn)
            st.download_button("Mentés (PDF)", pdf, "menetterv_v198.pdf")
