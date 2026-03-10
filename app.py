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
VERZIO = "v203.51"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")
st.title(f"Interfood Logisztika {VERZIO}")

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

def extract_gate_code(text):
    """Szigorított kapukód felismerés (pl. 14#2770 -> 14K2770)"""
    if not text: return None
    # Kifejezetten a szám-jel-szám mintát keressük
    # Elfogadja: 14#2770, 6k3589, 30kulcs1956
    pattern = r'(\d+)\s*(?:#|[Kk]|kulcs)\s*(\d+)'
    match = re.search(pattern, text)
    if match:
        return f"{match.group(1)}K{match.group(2)}"
    return None

# --- ADATFELDOLGOZÁS ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*)\s*Ft'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines_dict = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines_dict:
                    if abs(y - ey) < 3:
                        lines_dict[ey].append(w); break
                else: lines_dict[y] = [w]
            
            sorted_y = sorted(lines_dict.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines_dict[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                
                if u_code_m:
                    prefix, uid = u_code_m.group(0).split('-')[0], u_code_m.group(0).split('-')[-1]
                    # Az Ügyfél oszlop (b2) tartalmazza gyakran a megjegyzésbe írt kapukódot
                    b2 = " ".join([w['text'] for w in line_words if 40 <= w['x0'] < 150])
                    b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                    b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                    
                    gate_code = extract_gate_code(text_ws) # Keressük a teljes sorban
                    
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                    tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                    money_m = re.search(money_pat, text_ws)
                    
                    if not money_m and i + 1 < len(sorted_y):
                        next_text = " ".join([w['text'] for w in sorted(lines_dict[sorted_y[i+1]], key=lambda x: x['x0'])])
                        if not re.search(r'([HKSCPZ]-[0-9]{5,7})', next_text):
                            money_m = re.search(money_pat, next_text)
                            if not gate_code: gate_code = extract_gate_code(next_text)

                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(0))
                        if val_str: raw_money = int(val_str)
                    
                    addr_m = re.search(r'(\d{4})', b3)
                    clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                    v_o, sq = [], 0
                    for o in re.findall(order_pat, text_ws):
                        try:
                            q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                            v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                        except: continue
                    
                    if v_o:
                        rows.append({
                            "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                            "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                            "Rendelés": ", ".join(v_o), "Összesen": sq, 
                            "Pénz_Int": 5 * round(raw_money / 5), "Kapukód": gate_code
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
        base['Rendelés'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        total_m = group['Pénz_Int'].sum()
        base['Pénz'] = f"{total_m} Ft" if total_m != 0 else ""
        g_codes = [g for g in group['Kapukód'].unique() if g]
        base['Kapukód'] = g_codes[0] if g_codes else ""
        merged.append(base)
    return merged

# --- PDF GENERÁLÁS ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=10)
    rows_per_page = 25
    total_pages = math.ceil(len(df)/rows_per_page)

    for p_idx in range(total_pages):
        p.setFont(f_bold, 11); p.drawString(15*mm, h-12*mm, f"MENETTERV - {fn}")
        p.setFont(f_reg, 9); p.drawRightString(w-15*mm, h-12*mm, f"{p_idx+1}. oldal / {total_pages}")
        
        # Checkbox és adatok táblázata
        data = [["[ ]", "SOR", "ÜGYFÉL (KAPUKÓD) / CÍM", "TELEFON", "RENDELÉS", "DB", "FIZETENDŐ"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        for _, r in subset.iterrows():
            k_kod = f" <font color='blue'><b>[{r['Kapukód']}]</b></font>" if r['Kapukód'] else ""
            name_p = Paragraph(f"<b>{r['Ügyintéző']}</b>{k_kod}<br/>{r['Cím']}", cell_s)
            data.append(["[  ]", f"#{int(r['Sorrend'])}", name_p, r['Telefon'], Paragraph(r['Rendelés'], cell_s), r['Összesen'], r['Pénz']])
        
        t = Table(data, colWidths=[8*mm, 10*mm, 65*mm, 25*mm, 52*mm, 8*mm, 22*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (0,-1), 'CENTER'), # Checkbox középre
            ('ALIGN', (-1,0), (-1,-1), 'RIGHT')
        ]))
        tw, th = t.wrap(w-15*mm, h-35*mm)
        t.drawOn(p, 7*mm, (h-18*mm)-th)
        p.showPage()
    p.save(); buf.seek(0); return buf

# --- UI (A többi rész változatlan a v203.50-hez képest) ---
if 'mdf' not in st.session_state: st.session_state.mdf = None
with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+3620/886-89-71")
    if st.button("💾 SORREND MENTÉSE") and st.session_state.mdf is not None:
        st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False); st.success("Mentve!")

up_files = st.file_uploader("PDF feltöltése", accept_multiple_files=True)
if up_files and st.button("📊 FELDOLGOZÁS"):
    raw = []
    for f in up_files: raw.extend(parse_interfood_pro(f))
    if raw:
        mdf = pd.DataFrame(merge_data_flexible(raw))
        if os.path.exists("user_prefs.csv"):
            prefs = pd.read_csv("user_prefs.csv").drop_duplicates(subset='ID')
            mdf['ID'] = mdf['ID'].astype(str); prefs['ID'] = prefs['ID'].astype(str)
            mdf = mdf.merge(prefs[['ID', 'Sorrend']], on='ID', how='left')
            mdf['Sorrend'] = mdf['Sorrend'].fillna(9999.0)
        else: mdf['Sorrend'] = range(1, len(mdf) + 1)
        mdf = mdf.sort_values(by=['Sorrend', 'ID']).reset_index(drop=True)
        mdf['Sorrend'] = [float(i+1) for i in range(len(mdf))]
        st.session_state.mdf = mdf[['Sorrend', 'ID', 'Ügyintéző', 'Kapukód', 'Cím', 'Telefon', 'Rendelés', 'Összesen', 'Pénz']]
        st.rerun()

if st.session_state.mdf is not None:
    st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    st.download_button("📋 MENETTERV GENERÁLÁSA", create_manifest_pdf(st.session_state.mdf, fn_in), "menetterv.pdf")
