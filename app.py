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
st.set_page_config(page_title="Interfood Logisztika v203.41", layout="wide")
DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- ADATFELDOLGOZÁS (Pénzügyi adatok kinyerésével) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\d[\d\s]*)\s*Ft' # Összeg keresése

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
                
                # Pénzügyi adat kinyerése
                money_m = re.search(money_pat, text_ws)
                amount = money_m.group(0) if money_m else "0 Ft"
                
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
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Összesen": sq, "Pénz": amount
                    })
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
            day_group = group[group['Prefix'] == pfix]
            if not day_group.empty:
                items = day_group['Rendelés'].tolist()
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
        
        base['Rendelés'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        
        # Pénzösszegek szummázása
        total_money = 0
        for m_str in group['Pénz']:
            m_val = re.sub(r'[^-0-9]', '', str(m_str))
            if m_val: total_money += int(m_val)
        base['Pénz'] = f"{total_money} Ft"
        
        merged.append(base)
    return merged

# --- PDF GENERÁLÁS (ETIKETT) ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    lw, lh = 64*mm, 39*mm   # Címke méret
    margin_x, margin_y = 7*mm, 6*mm # Margók
    gap_x, gap_y = 3*mm, 1.5*mm # Hézagok
    
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=7.2, leading=8, alignment=0)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8.5, leading=10, alignment=1)

    for i in range(math.ceil(len(df)/21)*21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = margin_x + col * (lw + gap_x), margin_y + row_i * (lh + gap_y)
        
        p.setStrokeColor(colors.black); p.setLineWidth(0.5)
        
        if i < len(df):
            r = df.iloc[i]
            if r.get('HasSaturday', False): p.setLineWidth(1.6)
            p.rect(x, y, lw, lh)
            
            # Adatok
            p.setFont(f_bold, 9); p.drawString(x+3*mm, y+34*mm, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 7.5); p.drawRightString(x+lw-3*mm, y+34*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 8.2); p.drawString(x+3*mm, y+29*mm, str(r['Ügyintéző'])[:30])
            p.setFont(f_reg, 7.5); p.drawRightString(x+lw-3*mm, y+29*mm, str(r['Telefon']))
            p.setFont(f_reg, 7); p.drawString(x+3*mm, y+25*mm, str(r['Cím'])[:45])
            
            para = Paragraph(str(r['Rendelés']), order_s)
            para.wrap(lw-6*mm, 12*mm); para.drawOn(p, x+3*mm, y+11*mm)
            
            # Pénzügyi rész
            p.setFont(f_bold, 8.5); p.drawString(x+3*mm, y+6*mm, f"Fizetendő: {r['Pénz']}")
            p.setFont(f_bold, 7.5); p.drawRightString(x+lw-3*mm, y+6*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+2.5*mm, f"Futár: {fn} ({ft})")
        else:
            # MARKETING (Középre zárt, kiemelt)
            p.rect(x, y, lw, lh)
            m_text = (
                f"<font size='10.5'><b>15% kedvezmény* 3 hétig</b></font><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető<br/>területi képviselőnk által</b></font>"
            )
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw-6*mm, lh-6*mm); para.drawOn(p, x + (lw-pw)/2, y + (lh-ph)/2)
    p.save(); buf.seek(0); return buf

# --- PDF GENERÁLÁS (MENETTERV) ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    rows_per_page = 22
    total_p = math.ceil(len(df)/rows_per_page)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=10)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 11); p.drawString(15*mm, h-12*mm, f"MENETTERV - {fn}")
        data = [["SOR", "ÜGYFÉL / CÍM", "TELEFON", "RENDELÉS", "DB", "FIZETENDŐ"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        for _, r in subset.iterrows():
            name = Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", cell_s)
            data.append([f"#{int(r['Sorrend'])}", name, r['Telefon'], Paragraph(r['Rendelés'], cell_s), r['Összesen'], r['Pénz']])
        
        t = Table(data, colWidths=[12*mm, 65*mm, 25*mm, 55*mm, 10*mm, 25*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (-1,0), (-1,-1), 'RIGHT')
        ]))
        tw, th = t.wrap(w-20*mm, h-35*mm); t.drawOn(p, 10*mm, (h-18*mm)-th)
        p.showPage()
    p.save(); buf.seek(0); return buf

# --- STREAMLIT UI ---
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("⚙️ Beállítások")
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+3620/886-89-71")
    if st.button("💾 SORREND MENTÉSE"):
        if st.session_state.mdf is not None:
            st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
            st.success("Mentve!")

up_files = st.file_uploader("Interfood PDF-ek feltöltése", accept_multiple_files=True)

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
        cols = ['Sorrend'] + [c for c in mdf.columns if c != 'Sorrend']
        st.session_state.mdf = mdf[cols]; st.rerun()

if st.session_state.mdf is not None:
    edited_df = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    if st.button("🔄 SORREND FRISSÍTÉSE"):
        temp = edited_df.sort_values("Sorrend").reset_index(drop=True)
        temp["Sorrend"] = [float(i+1) for i in range(len(temp))]
        st.session_state.mdf = temp; st.rerun()

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            st.download_button("PDF Mentése", create_label_pdf(st.session_state.mdf, fn_in, ft_in), "etikettek_v203.41.pdf")
    with c2:
        if st.button("📋 MENETTERV LETÖLTÉSE"):
            st.download_button("PDF Mentése", create_manifest_pdf(st.session_state.mdf, fn_in), "menetterv_v203.41.pdf")
