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

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- ETIKETT GENERÁLÁS (3x7 elrendezés, fix 5mm belső margóval) ---
def create_label_pdf(df, courier_name, courier_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    # A4 mérete: 210 x 297 mm
    # 3 oszlop, 7 sor elrendezés
    lw = 210 * mm / 3
    lh = 297 * mm / 7
    
    # Fix belső margó az etiketten belül
    inner_m = 5 * mm 

    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)

    for i in range(len(df)):
        idx = i % 21  # 3 oszlop * 7 sor = 21 etikett / lap
        if idx == 0 and i > 0:
            p.showPage()
        
        col = idx % 3
        row_i = 6 - (idx // 3) # Fentről lefelé 0-6 indexelés
        
        x = col * lw
        y = row_i * lh
        
        r = df.iloc[i]
        
        # --- TARTALOM POZICIONÁLÁSA A BELSŐ MARGÓN BELÜL ---
        
        # Sorszám és ID (Felső sor a belső margótól indítva)
        p.setFont(f_bold, 10)
        p.drawString(x + inner_m, y + lh - inner_m - 4*mm, f"#{int(r['Sorrend'])}")
        p.setFont(f_reg, 8)
        p.drawRightString(x + lw - inner_m, y + lh - inner_m - 4*mm, f"ID: {r['ID']}")
        
        # Ügyintéző és Cím
        p.setFont(f_bold, 9)
        p.drawString(x + inner_m, y + lh - inner_m - 10*mm, str(r['Ügyintéző'])[:32])
        p.setFont(f_reg, 8)
        p.drawString(x + inner_m, y + lh - inner_m - 14*mm, str(r['Cím'])[:45])
        
        # Rendelés (Középre tördelve, belső margók között)
        para = Paragraph(str(r['Rendelés']), order_s)
        # Rendelkezésre álló szélesség: etikett szélesség - 2 * belső margó
        para.wrap(lw - 2*inner_m, 15*mm)
        para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
        
        # Pénz és darabszám
        p.setFont(f_bold, 9)
        p.drawString(x + inner_m, y + inner_m + 4*mm, f"FIZET: {r['Pénz']}")
        p.drawRightString(x + lw - inner_m, y + inner_m + 4*mm, f"{r['Összesen']} db")
        
        # Futár adatok (Legalul a margón belül)
        p.setFont(f_reg, 7)
        p.drawCentredString(x + lw/2, y + inner_m, f"{courier_name} | {courier_phone}")

    p.save()
    buf.seek(0)
    return buf

# --- MENETTERV (25 sor/oldal + Oldalszámozás) ---
def create_manifest_pdf(df, courier_name):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    rows_per_page = 25
    total_pages = math.ceil(len(df) / rows_per_page)
    cell_style = ParagraphStyle('CellStyle', fontName=f_reg, fontSize=8.5, leading=10.5)
    
    for p_idx in range(total_pages):
        # Fejléc adatok
        p.setFont(f_bold, 12)
        p.drawString(10*mm, h - 15*mm, f"MENETTERV - {courier_name}")
        p.setFont(f_reg, 9)
        p.drawRightString(w - 10*mm, h - 15*mm, f"{p_idx + 1} / {total_pages}. oldal")
        
        data = [["SOR", "NÉV / CÍM", "TELEFON / PÉNZ", "RENDELÉS", "DB"]]
        subset = df.iloc[p_idx * rows_per_page : (p_idx + 1) * rows_per_page]
        
        for _, r in subset.iterrows():
            name_box = Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", cell_style)
            order_box = Paragraph(str(r['Rendelés']), cell_style)
            data.append([
                f"#{int(r['Sorrend'])}",
                name_box,
                f"{r['Telefon']}\n<b>{r['Pénz']}</b>",
                order_box,
                r['Összesen']
            ])
            
        t = Table(data, colWidths=[12*mm, 60*mm, 35*mm, 78*mm, 10*mm])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.2, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('ALIGN', (0,0), (0,-1), 'CENTER'),
            ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
        ]))
        
        tw, th = t.wrap(w - 10*mm, h - 40*mm)
        t.drawOn(p, 5*mm, (h - 20*mm) - th)
        p.showPage()
        
    p.save()
    buf.seek(0)
    return buf

# --- UI ---
if 'mdf' in st.session_state and st.session_state.mdf is not None:
    st.subheader("Nyomtatandó dokumentumok")
    
    courier_n = st.text_input("Futár neve", "Szűcs István")
    courier_p = st.text_input("Telefonszám", "+36 20 886 8971")

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "📥 ETIKETTEK (3x7 elrendezés)", 
            create_label_pdf(st.session_state.mdf, courier_n, courier_p), 
            "etikettek_3x7.pdf",
            use_container_width=True
        )
    with col2:
        st.download_button(
            "📋 MENETTERV (25 sor/oldal)", 
            create_manifest_pdf(st.session_state.mdf, courier_n), 
            "menetterv_25sor.pdf",
            use_container_width=True
        )
