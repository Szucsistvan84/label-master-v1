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
VERZIO = "v203.48-MOD6"

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n):
            pdfmetrics.registerFont(TTFont('DejaVu', f_n))
            pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
            return "DejaVu", "DejaVu-Bold"
    except: pass
    return "Helvetica", "Helvetica-Bold"

# --- ADATFELDOLGOZÓ (PÉNZ + MEGJEGYZÉS) ---
def parse_interfood_source(pdf_file):
    rows = []
    # A tegnapi stabil minták
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    money_pat = r'(-?\s?\d[\d\s]*)\s*Ft'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            # Sorokra bontás és tisztítás
            lines = text.split('\n')
            for i, line in enumerate(lines):
                # Ügyfél kód keresése (H-12345 vagy S-12345)
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', line)
                if u_code_m:
                    # Alapadatok kinyerése
                    prefix = u_code_m.group(0).split('-')[0]
                    uid = u_code_m.group(0).split('-')[-1]
                    
                    # Pénz keresése az aktuális sorban
                    money_m = re.search(money_pat, line)
                    money_val = 0
                    if money_m:
                        money_val = int(re.sub(r'[^-0-9]', '', money_m.group(0)))

                    # Megjegyzés keresése: ha a következő sor nem új ügyfél és nem csak rendelés
                    note = ""
                    if i + 1 < len(lines):
                        next_l = lines[i+1].strip()
                        if not re.search(r'[HKSCPZ]-[0-9]{5,7}', next_l) and len(next_l) > 2:
                            note = next_l

                    rows.append({
                        "ID": uid, "Prefix": prefix, "Money": money_val, "Note": note,
                        "RawLine": line # Később a névhez/címhez
                    })
    return rows

# --- ETIKETT GENERÁLÁS (JAVÍTOTT RÁCS ÉS ADATOK) ---
def create_label_pdf(df, driver_name):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    # Paraméterek a kérésed szerint
    lw, lh = 60*mm, 32.43*mm
    inner_m = 5*mm
    
    for i, (_, r) in enumerate(df.iterrows()):
        idx_on_page = i % 21
        col = idx_on_page % 3
        row = 6 - (idx_on_page // 3)
        
        x = col * lw
        y = row * lh
        
        # CELLA KERET (Hogy lásd a vágást/határt)
        p.setStrokeColor(colors.lightgrey)
        p.setLineWidth(0.1*mm)
        p.rect(x, y, lw, lh)
        
        # TARTALOM (5mm belső margóval)
        p.setFillColor(colors.black)
        
        # Fejléc: Sorrend + Futár + ID
        p.setFont(f_bold, 8)
        p.drawString(x + inner_m, y + lh - 7*mm, f"#{r['Sorrend']}")
        p.setFont(f_reg, 6)
        p.drawCentredString(x + lw/2, y + lh - 7*mm, f"Futár: {driver_name[:15]}")
        p.drawRightString(x + lw - inner_m, y + lh - 7*mm, f"ID: {r['ID']}")
        
        # Név és Cím
        p.setFont(f_bold, 9)
        p.drawString(x + inner_m, y + lh - 12*mm, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 7)
        p.drawString(x + inner_m, y + lh - 16*mm, str(r['Cím'])[:45])
        
        # Rendelés
        order_s = ParagraphStyle('LabelOrder', fontName=f_reg, fontSize=7, leading=8)
        para = Paragraph(str(r['Rendelés']), order_s)
        para.wrap(lw - 2*inner_m, 10*mm)
        para.drawOn(p, x + inner_m, y + 10*mm)
        
        # Alsó sor: Pénz + Összesen db
        if r['Pénz']:
            p.setFont(f_bold, 9)
            p.drawString(x + inner_m, y + inner_m, f"FIZET: {r['Pénz']}")
        
        p.setFont(f_bold, 8)
        p.drawRightString(x + lw - inner_m, y + inner_m, f"{r['Összesen']} db")
        
        if (i + 1) % 21 == 0 and (i + 1) < len(df):
            p.showPage()
            
    p.save()
    buf.seek(0)
    return buf

# --- MENETTERV GENERÁLÁS (PIROS MEGJEGYZÉSSEL) ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    
    name_s = ParagraphStyle('Name', fontName=f_bold, fontSize=10, leading=11)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=9)

    rows_per_page = 25 
    total_pages = math.ceil(len(df)/rows_per_page)

    for p_idx in range(total_pages):
        p.setFont(f_bold, 11)
        p.drawString(15*mm, h-12*mm, f"MENETTERV - {fn} ({p_idx+1}/{total_pages} oldal)")
        
        data = [["SOR", "ÜGYFÉL / CÍM / MEGJEGYZÉS", "OK", "TELEFON", "RENDELÉS", "DB", "PÉNZ"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        
        for _, r in subset.iterrows():
            # Ügyfél info összeállítása
            note_html = f"<br/><font color='red' size=7><i>{r['Megjegyzés']}</i></font>" if r.get('Megjegyzés') else ""
            info = Paragraph(f"{r['Ügyintéző']}<br/><font size=7 color='#444444'>{r['Cím']}</font>{note_html}", name_s)
            
            data.append([
                f"#{int(r['Sorrend'])}", info, "[ ]", r['Telefon'], 
                Paragraph(r['Rendelés'], cell_s), r['Összesen'], r['Pénz']
            ])
        
        t = Table(data, colWidths=[10*mm, 70*mm, 8*mm, 25*mm, 47*mm, 8*mm, 22*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('GRID', (0,0), (-1,-1), 0.2, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
        ]))
        th = t.wrap(w-20*mm, h-35*mm)[1]
        t.drawOn(p, 10*mm, (h-16*mm)-th)
        p.showPage()
    
    p.save(); buf.seek(0); return buf

# --- UI (Változatlan indítás) ---
# ... (Streamlit kód marad a korábbi v203.48 struktúrában)

# --- UI ---
if 'mdf' not in st.session_state: st.session_state.mdf = None
with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+3620/886-89-71")
    if st.button("💾 SORREND MENTÉSE") and st.session_state.mdf is not None:
        st.session_state.mdf[['ID', 'Sorrend']].to_csv("user_prefs.csv", index=False)
        st.success("Mentve!")

up_files = st.file_uploader("Feltöltés", accept_multiple_files=True)
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
        st.session_state.mdf = mdf; st.rerun()

if st.session_state.mdf is not None:
    st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    with c1: st.download_button("📥 ETIKETTEK", create_label_pdf(st.session_state.mdf, fn_in, ft_in), "etikettek.pdf")
    with c2: st.download_button("📋 MENETTERV", create_manifest_pdf(st.session_state.mdf, fn_in), "menetterv.pdf")



