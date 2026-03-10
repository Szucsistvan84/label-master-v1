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
VERZIO = "v203.56"
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
    """Fejlesztett kapukód felismerő"""
    if not text: return None
    # Keresünk rácsos kódot (12#3456) vagy konkrét kulcsszavas kódot
    pattern = r'(?i)(?:kapukód[:\s]*(\d+)|(\d{1,4}\s*#\s*\d{1,4}))'
    match = re.search(pattern, text)
    if match:
        res = match.group(1) if match.group(1) else match.group(2)
        return res.strip()
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
                full_text = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', full_text)
                
                if u_code_m:
                    prefix, uid = u_code_m.group(0).split('-')[0], u_code_m.group(0).split('-')[-1]
                    # Megjegyzés és Ügyfél részek (b2 a megjegyzés/kapukód helye)
                    b2_text = " ".join([w['text'] for w in line_words if 40 <= w['x0'] < 160])
                    b3 = " ".join([w['text'] for w in line_words if 160 <= w['x0'] < 355])
                    b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                    
                    gate_code = extract_gate_code(b2_text) or extract_gate_code(full_text)

                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                    tel_m = re.search(phone_pat, full_text.replace(" ", ""))
                    money_m = re.search(money_pat, full_text)

                    raw_money = ""
                    if money_m:
                        raw_money = money_m.group(0)
                    
                    addr_m = re.search(r'(\d{4})', b3)
                    clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                    v_o, sq = [], 0
                    for o in re.findall(order_pat, full_text):
                        try:
                            q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                            v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                        except: continue
                    
                    if v_o:
                        rows.append({
                            "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                            "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                            "Rendelés": ", ".join(v_o), "Összesen": sq, 
                            "Pénz": raw_money, "Kapukód": gate_code
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
        # Pénz összefűzése (ha van több napra tartozás)
        money_vals = [m for m in group['Pénz'].unique() if m and m != "0 Ft"]
        base['Pénz'] = money_vals[0] if money_vals else ""
        g_codes = [g for g in group['Kapukód'].unique() if g]
        base['Kapukód'] = g_codes[0] if g_codes else ""
        merged.append(base)
    return merged

# --- PDF GENERÁLÁS ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=10.5, leading=12)
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=9, leading=11)
    phone_s = ParagraphStyle('Phone', fontName=f_reg, fontSize=7.5, leading=9)

    rows_per_page = 25
    margin_top = 20*mm
    margin_bottom = 15*mm
    available_height = h - margin_top - margin_bottom - 10*mm # -10mm a fejlécnek
    
    # Kiszámolt sormagasság a margók figyelembevételével
    header_h = 8*mm
    row_h = (available_height - header_h) / rows_per_page

    total_pages = math.ceil(len(df)/rows_per_page)

    for p_idx in range(total_pages):
        p.setFont(f_bold, 12); p.drawString(10*mm, h-12*mm, f"MENETTERV - {fn}")
        p.setFont(f_reg, 9); p.drawRightString(w-10*mm, h-12*mm, f"{p_idx+1}. oldal / {total_pages}")
        
        data = [["SOR", "ÜGYFÉL / CÍM", "[ ]", "TELEFON", "RENDELÉS", "DB", "PÉNZ"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        
        for _, r in subset.iterrows():
            k_kod = f" <b>[{r['Kapukód']}]</b>" if r['Kapukód'] else ""
            client_p = Paragraph(f"{r['Ügyintéző']}{k_kod}<br/><font size=8.5>{r['Cím']}</font>", name_s)
            data.append([
                f"#{int(r['Sorrend'])}", 
                client_p, 
                "[  ]", 
                Paragraph(r['Telefon'], phone_s), 
                Paragraph(r['Rendelés'], order_s), 
                r['Összesen'], 
                r['Pénz']
            ])
        
        t = Table(data, colWidths=[10*mm, 62*mm, 10*mm, 22*mm, 62*mm, 8*mm, 18*mm], 
                  rowHeights=[header_h] + [row_h]*len(subset))
        
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (0,-1), 'CENTER'),
            ('ALIGN', (2,0), (2,-1), 'CENTER'),
            ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
            ('LEFTPADDING', (1,0), (1,-1), 4),
        ]))
        
        tw, th = t.wrap(w-10*mm, available_height)
        t.drawOn(p, 5*mm, h - margin_top - th)
        p.showPage()
        
    p.save(); buf.seek(0); return buf

# --- UI (Változatlan szerkezet) ---
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
    c1, c2 = st.columns(2)
    with c1: st.download_button("📋 MENETTERV LETÖLTÉSE", create_manifest_pdf(st.session_state.mdf, fn_in), "menetterv.pdf")
    # Etikett generáló függvényt itt a helytakarékosság miatt nem ismétlem meg, de a kódban benne maradna
