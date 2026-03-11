import streamlit as st
import pandas as pd
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

# --- FONT KEZELÉS ---
def register_fonts():
    try:
        # A mentett preferencia szerinti font használata
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ETIKETT (3x7, belső 5mm margó) ---
def create_label_pdf(df, c_name, c_phone):
    if df is None or df.empty:
        return None
    
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    # A4: 210x297mm -> 3x7 elrendezés
    label_w = 70 * mm
    label_h = 42.4 * mm # 297/7
    inner_m = 5 * mm 

    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0:
            p.showPage()
        
        col = idx % 3
        row = 6 - (idx // 3)
        
        x = col * label_w
        y = row * label_h
        
        r = df.iloc[i]
        
        # Sorszám + ID
        p.setFont(f_bold, 10)
        p.drawString(x + inner_m, y + label_h - inner_m - 3*mm, f"#{int(r.get('Sorrend', 0))}")
        p.setFont(f_reg, 8)
        p.drawRightString(x + label_w - inner_m, y + label_h - inner_m - 3*mm, f"ID: {r.get('ID','')}")
        
        # Név + Cím
        p.setFont(f_bold, 9)
        p.drawString(x + inner_m, y + label_h - inner_m - 9*mm, str(r.get('Ügyintéző', ''))[:30])
        p.setFont(f_reg, 7.5)
        p.drawString(x + inner_m, y + label_h - inner_m - 13*mm, str(r.get('Cím', ''))[:45])
        
        # Rendelés
        para = Paragraph(str(r.get('Rendelés', '')), order_s)
        para.wrap(label_w - 2*inner_m, 12*mm)
        para.drawOn(p, x + inner_m, y + inner_m + 8*mm)
        
        # Fizetendő + DB
        p.setFont(f_bold, 9)
        p.drawString(x + inner_m, y + inner_m + 4*mm, f"FIZET: {r.get('Pénz', '0 Ft')}")
        p.drawRightString(x + label_w - inner_m, y + inner_m + 4*mm, f"{r.get('Összesen', 1)} db")
        
        # Futár (Legalsó sor)
        p.setFont(f_reg, 6)
        p.drawCentredString(x + label_w/2, y + 2*mm, f"{c_name} | {c_phone}")

    p.save()
    buf.seek(0)
    return buf

# --- MENETTERV (25 sor, oldalszámozás) ---
def create_manifest_pdf(df, c_name):
    if df is None or df.empty:
        return None

    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    rows_per_page = 25
    total_p = math.ceil(len(df) / rows_per_page)
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=8, leading=10)
    
    for p_idx in range(total_p):
        p.setFont(f_bold, 11)
        p.drawString(10*mm, h - 12*mm, f"MENETTERV - {c_name}")
        p.setFont(f_reg, 8)
        p.drawRightString(w - 10*mm, h - 12*mm, f"{p_idx+1} / {total_p} oldal")
        
        data = [["#", "NÉV / CÍM", "TELEFON / PÉNZ", "RENDELÉS", "DB"]]
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        
        for _, r in subset.iterrows():
            n_box = Paragraph(f"<b>{r.get('Ügyintéző','')}</b><br/>{r.get('Cím','')}", cell_s)
            o_box = Paragraph(str(r.get('Rendelés','')), cell_s)
            data.append([
                f"#{int(r.get('Sorrend',0))}",
                n_box,
                f"{r.get('Telefon','')}\n<b>{r.get('Pénz','')}</b>",
                o_box,
                r.get('Összesen',1)
            ])
            
        t = Table(data, colWidths=[10*mm, 60*mm, 35*mm, 80*mm, 10*mm])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.2, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ]))
        
        tw, th = t.wrap(w - 15*mm, h - 30*mm)
        t.drawOn(p, 7*mm, (h - 18*mm) - th)
        p.showPage()
        
    p.save()
    buf.seek(0)
    return buf

# --- FŐ PROGRAM ---
st.title("Interfood PDF Segéd")

# Inicializálás, ha üres a session
if 'mdf' not in st.session_state:
    st.session_state.mdf = None

# Itt töltheted be az adatokat (v203-as heggesztett kóddal) vagy használhatod a meglévőt
# Ha az mdf üres, mutassunk egy üzenetet
if st.session_state.mdf is None:
    st.info("Kérlek, töltsd fel és dolgozd fel a PDF-et az adatok kinyeréséhez!")
else:
    # Ha van adat, megjelenítjük a szerkesztőt és a gombokat
    st.session_state.mdf = st.data_editor(st.session_state.mdf, hide_index=True)
    
    st.divider()
    c_n = st.text_input("Futár", "Szűcs István")
    c_p = st.text_input("Mobil", "+36 20 886 8971")
    
    col1, col2 = st.columns(2)
    
    # PDF generálás gombok hibafigyeléssel
    try:
        label_pdf = create_label_pdf(st.session_state.mdf, c_n, c_p)
        if label_pdf:
            col1.download_button("📥 ETIKETTEK (3x7)", label_pdf, "etikettek.pdf", use_container_width=True)
            
        manifest_pdf = create_manifest_pdf(st.session_state.mdf, c_n)
        if manifest_pdf:
            col2.download_button("📋 MENETTERV (25 sor)", manifest_pdf, "menetterv.pdf", use_container_width=True)
    except Exception as e:
        st.error(f"Hiba a PDF generálása közben: {e}")
