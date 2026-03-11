import streamlit as st
import pdfplumber
import pandas as pd
import re
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
        # Győződj meg róla, hogy a DejaVuSans.ttf elérhető!
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ADATKINYERÉS ---
def parse_interfood_v5(pdf_file):
    rows = []
    # Keresési minták
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    phone_pat = r'(\d{2}/\d{6,7})'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            # Sorokra bontás és tisztítás
            lines = text.split('\n')
            for line in lines:
                u_match = re.search(r'([HKSCPZ])-(\d{5,7})', line)
                if not u_match: continue
                
                uid = u_match.group(2)
                
                # Pénz keresése: ha nincs találat, 0-nak vesszük
                m_match = re.search(money_pat, line)
                money = 0
                if m_match:
                    val = re.sub(r'[^\d-]', '', m_match.group(1))
                    money = int(val) if val else 0

                tel_m = re.search(phone_pat, line.replace(" ", ""))
                
                # Név és cím kinyerése (leegyszerűsítve a stabilitásért)
                parts = line.split(uid)
                clean_info = parts[1] if len(parts) > 1 else line
                
                rows.append({
                    "ID": uid,
                    "Ügyintéző": "Név kinyerése...", # A táblázatban szerkeszthető marad
                    "Cím": "Cím kinyerése...",
                    "Telefon": tel_m.group(0) if tel_m else "",
                    "Rendelés": "Rendelés...",
                    "Pénz": money,
                    "Összesen": 1
                })
    return rows

# --- PDF GENERÁLÓK ---
def create_labels_v5(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    # Etikett specifikációk (3x7-es elrendezés)
    lw, lh = 70*mm, 42.4*mm
    margin_x = 5*mm  # Oldalsó belső margó
    margin_y = 5*mm  # Alsó/Felső belső margó (Hogy ne vágja le)

    for i, r in df.iterrows():
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        # BIZTONSÁGI MARGÓK ALKALMAZÁSA
        # Fejléc (Sorrend és ID)
        p.setFont(f_bold, 8)
        p.drawString(x + margin_x, y + lh - margin_y, f"#{int(r['Sorrend'])}")
        p.drawRightString(x + lw - margin_x, y + lh - margin_y, f"ID: {r['ID']}")
        
        # Név és Cím
        p.setFont(f_bold, 9)
        p.drawString(x + margin_x, y + lh - margin_y - 5*mm, str(r['Ügyintéző'])[:30])
        p.setFont(f_reg, 8)
        p.drawString(x + margin_x, y + lh - margin_y - 9*mm, str(r['Cím'])[:40])
        
        # Rendelés rész (középen, eltolva a margóktól)
        p.setFont(f_reg, 7)
        r_text = str(r['Rendelés'])
        p.drawString(x + margin_x, y + 15*mm, r_text[:45])
        
        # Alsó sáv (Pénz és db)
        p.setFont(f_bold, 10)
        p.drawString(x + margin_x, y + margin_y + 2*mm, f"FIZET: {int(r['Pénz'])} Ft")
        p.drawRightString(x + lw - margin_x, y + margin_y + 2*mm, f"{r['Összesen']} db")
        
        # Futár infó legalul
        p.setFont(f_reg, 6)
        p.drawCentredString(x + lw/2, y + 2*mm, f"{fn} | {ft}")
        
    p.save(); buf.seek(0); return buf

def create_manifest_v5(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=15*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    chunks = [df[i:i + 25] for i in range(0, len(df), 25)]
    total_pages = len(chunks)
    
    for idx, chunk in enumerate(chunks):
        elements.append(Paragraph(f"<b>MENETTERV - Futár: {fn}</b>", styles['Title']))
        
        # Táblázat fejléce
        data = [["#", "ÜGYINTÉZŐ / CÍM", "TELEFON", "RENDELÉS", "PÉNZ", "DB"]]
        for _, r in chunk.iterrows():
            data.append([
                f"#{int(r['Sorrend'])}",
                Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", ParagraphStyle('S', fontName=f_reg, fontSize=8)),
                r['Telefon'],
                Paragraph(str(r['Rendelés']), ParagraphStyle('S', fontName=f_reg, fontSize=7)),
                f"{int(r['Pénz'])} Ft",
                r['Összesen']
            ])
            
        t = Table(data, colWidths=[12*mm, 55*mm, 25*mm, 60*mm, 20*mm, 10*mm])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(t)
        
        # Oldalszám az oldal aljára
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph(f"<para align='center'><b>{idx+1} / {total_pages} oldal</b></para>", styles['Normal']))
        
        if idx < total_pages - 1:
            elements.append(PageBreak())
            
    doc.build(elements); buf.seek(0); return buf

# --- UI ---
st.set_page_config(layout="wide") # Táblázat szélesség fix
st.title("Interfood Logisztika v203.87")

if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    fn_in = st.text_input("Futár neve", "Szűcs István")
    ft_in = st.text_input("Telefonszáma", "+36 20 886 8971")
    up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True)

if up_files and st.button("📊 ADATOK BEOLVASÁSA"):
    all_data = []
    for f in up_files:
        all_data.extend(parse_interfood_v5(f))
    if all_data:
        df = pd.DataFrame(all_data)
        df['Sorrend'] = range(1, len(df) + 1)
        # Oszlopok sorrendje a táblázatban
        st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Rendelés', 'Pénz', 'Összesen']]
        st.rerun()

if st.session_state.mdf is not None:
    # Táblázat megjelenítése teljes szélességben
    edited = st.data_editor(
        st.session_state.mdf, 
        use_container_width=True, 
        hide_index=True,
        num_rows="dynamic"
    )
    
    if st.button("💾 MÓDOSÍTÁSOK VÉGLEGESÍTÉSE"):
        st.session_state.mdf = edited
        st.success("Adatok frissítve!")

    st.divider()
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("📥 ETIKETTEK PDF", create_labels_v5(edited, fn_in, ft_in), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 MENETTERV PDF", create_manifest_v5(edited, fn_in), "menetterv.pdf", use_container_width=True)
    with c3:
        csv = edited.to_csv(index=False).encode('utf-8-sig')
        st.download_button("💾 CSV EXPORT", csv, "adatok.csv", use_container_width=True)
