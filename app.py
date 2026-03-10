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
from reportlab.lib.styles import ParagraphStyle

# --- ALAPBEÁLLÍTÁSOK ---
st.set_page_config(page_title="Interfood Logisztika v203.38", layout="wide")
DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- ADATFELDOLGOZÁS ---
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
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w); break
                else: lines[y] = [w]
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                prefix, uid = u_code_m.group(0).split('-')[0], u_code_m.group(0).split('-')[-1]
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                raw_orders = re.findall(order_pat, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                if v_o: rows.append({"Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", "Rendelés": ", ".join(v_o), "Összesen": sq})
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        base['HasSaturday'] = any(p == 'Z' for p in group['Prefix'])
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            items = group[group['Prefix'] == pfix]['Rendelés'].tolist()
            if items: o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
        base['Rendelés'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- PDF GENERÁLÁS (ETIKETT) ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    lw, lh = 70*mm, 42.4*mm 
    margin_x = 0.1*mm 
    margin_y = 0.5*mm
    
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=7.5, leading=8.5, alignment=0)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8.5, leading=10, alignment=1)

    for i in range(math.ceil(len(df)/21)*21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = margin_x + col*lw, margin_y + row_i*lh
        
        p.setStrokeColor(colors.black)
        p.setLineWidth(0.5)
        
        if i < len(df):
            r = df.iloc[i]
            if r.get('HasSaturday', False) or "Szo:" in str(r['Rendelés']):
                p.setLineWidth(1.6)
            
            p.rect(x+1.5*mm, y+1*mm, lw-3*mm, lh-2*mm)
            
            # Ügyfél adatok (Balra igazítva)
            p.setFont(f_bold, 9); p.drawString(x+4*mm, y+35*mm, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 7.5); p.drawRightString(x+lw-5*mm, y+35*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 8.5); p.drawString(x+4*mm, y+29*mm, str(r['Ügyintéző'])[:32])
            p.setFont(f_reg, 7.5); p.drawRightString(x+lw-5*mm, y+29*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x+4*mm, y+25*mm, str(r['Cím'])[:48])
            
            para = Paragraph(str(r['Rendelés']), order_s)
            para.wrap(lw-8*mm, 15*mm)
            para.drawOn(p, x+4*mm, y+11*mm)
            
            p.setFont(f_bold, 8); p.drawRightString(x+lw-5*mm, y+7*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6.5); p.drawCentredString(x+lw/2, y+3.5*mm, f"Futár: {fn} ({ft})")
        else:
            # MARKETING (Középre igazítva)
            p.rect(x+1.5*mm, y+1*mm, lw-3*mm, lh-2*mm)
            m_text = (
                f"<b>15% kedvezmény* 3 hétig</b><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"{fn}, tel: {ft}<br/><br/>"
                f"<font size='5.5'>* a kedvezmény telefonon leadott rendelésekre érvényesíthető<br/>területi képviselőnk által</font>"
            )
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw-8*mm, lh-8*mm)
            para.drawOn(p, x + (lw-pw)/2, y + (lh-ph)/2)

    p.save()
    buf.seek(0)
    return buf

# --- PDF GENERÁLÁS (MENETTERV) ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    rows_per_page = 25
    total_p = math.ceil(len(df)/rows_per_page)
    cell_style = ParagraphStyle('CellStyle', fontName=f_reg, fontSize=8.5, leading=11)
    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(15*mm, h-12*mm, f"MENETTERV - {fn}")
        p.setFont(f_reg, 8); p.drawCentredString(w/2, 10*mm, f"{p_idx + 1} / {total_p} oldal")
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
    p.save(); buf.seek(0); return buf

# --- FELHASZNÁLÓI FELÜLET ---
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("⚙️ Beállítások")
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+3620/886-89-71")
    st.divider()
    if st.button("💾 AKTUÁLIS SORREND MENTÉSE"):
        if st.session_state.mdf is not None:
            st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
            st.success("Sorrend rögzítve!")

up_files = st.file_uploader("PDF feltöltés", accept_multiple_files=True)

if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_pro(f))
    if raw:
        mdf = pd.DataFrame(merge_data_flexible(raw))
        if os.path.exists("user_prefs.csv"):
            prefs = pd.read_csv("user_prefs.csv").drop_duplicates(subset='ID')
            prefs['ID'] = prefs['ID'].astype(str); mdf['ID'] = mdf['ID'].astype(str)
            mdf = mdf.merge(prefs[['ID', 'Sorrend']], on='ID', how='left')
            mdf['Sorrend'] = mdf['Sorrend'].fillna(9999.0)
        else: mdf['Sorrend'] = range(1, len(mdf) + 1)
        
        mdf = mdf.sort_values(by=['Sorrend', 'ID']).reset_index(drop=True)
        mdf['Sorrend'] = [float(i+1) for i in range(len(mdf))]
        
        # OSZLOP SORREND KÉNYSZERÍTÉSE
        cols = ['Sorrend'] + [c for c in mdf.columns if c != 'Sorrend']
        st.session_state.mdf = mdf[cols]; st.rerun()

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True,
                               column_config={"Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f", step=0.1)})
    
    if st.button("🔄 SORREND FRISSÍTÉSE"):
        temp_df = edited_df.copy()
        temp_df["Sorrend"] = pd.to_numeric(temp_df["Sorrend"], errors='coerce').fillna(999.0)
        temp_df = temp_df.sort_values("Sorrend").reset_index(drop=True)
        temp_df["Sorrend"] = [float(i+1) for i in range(len(temp_df))]
        cols = ['Sorrend'] + [c for c in temp_df.columns if c != 'Sorrend']
        st.session_state.mdf = temp_df[cols]; st.rerun()

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 ETIKETTEK"):
            st.download_button("Letöltés", create_label_pdf(st.session_state.mdf, fn_in, ft_in), "etikettek.pdf")
    with c2:
        if st.button("📋 MENETTERV"):
            st.download_button("Letöltés", create_manifest_pdf(st.session_state.mdf, fn_in), "menetterv.pdf")
