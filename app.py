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
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- Betűk és stílusok ---
def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

def get_p_style(font_name, size, leading):
    return ParagraphStyle('Custom', fontName=font_name, fontSize=size, leading=leading)

# --- PDF PARSER (Kiegészítve összeggel és megjegyzéssel) ---
def parse_interfood_pro(pdf_file):
    rows = []
    # Keressük az összeget is (pl. "12 500 Ft" vagy "0 Ft")
    price_pat = r'(\d[\d\s]*)\s*Ft'
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            # Egyszerűsített logika a stabilabb működésért
            lines = text.split('\n')
            for line in lines:
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', line)
                if u_code_m:
                    uid = u_code_m.group(0).split('-')[-1]
                    prefix = u_code_m.group(0).split('-')[0]
                    
                    # Összeg keresése
                    price_m = re.search(price_pat, line)
                    price_str = price_m.group(0) if price_m else "0 Ft"
                    
                    # Ez csak egy alap kinyerés, a táblázatos PDF-nél a koordinátás (korábbi) jobb
                    # De a sortörés miatt a tárolás módja változik
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": "Név keresés...", 
                        "Cím": "Cím keresés...", "Telefon": "", 
                        "Rendelés": "Rendelés...", "Összesen": 1, "Ár": price_str
                    })
    # MEGJEGYZÉS: Itt a korábbi v203.8-as koordináta alapú parsert érdemes megtartani, 
    # csak az 'Ár' mezőt hozzáadni a 'price_pat' segítségével.
    return rows

# --- ETIKETT GENERÁLÓ (Sortöréssel és Kyocera margóval) ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    # KYOCERA KORREKCIÓ: Beljebb tolt margók
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2 + 1*mm, (h - 7*lh)/2 # +1mm eltolás jobbra a biztonságért
    
    styles = getSampleStyleSheet()
    order_style = ParagraphStyle('OrderStyle', fontName=f_bold, fontSize=8, leading=9)
    
    total_labels = len(df)
    total_slots = math.ceil(total_labels / 21) * 21
    
    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        
        if i < total_labels:
            r = df.iloc[i]
            # BELSŐ KERET - picit beljebb húzva (3mm helyett 4mm-re a szélétől)
            p.setLineWidth(1.2 if str(r.get('Prefix','')) == 'Z' else 0.2)
            p.rect(x+3*mm, y+2.5*mm, lw-6*mm, lh-5*mm)
            
            p.setFont(f_bold, 10); p.drawString(x+6*mm, y+36*mm, f"#{int(float(r['Sorrend']))}")
            p.setFont(f_reg, 8); p.drawRightString(x+lw-7*mm, y+36*mm, f"ID: {r['ID']}")
            
            p.setFont(f_bold, 9); p.drawString(x+6*mm, y+31*mm, str(r['Ügyintéző'])[:24])
            p.setFont(f_reg, 7.5); p.drawRightString(x+lw-7*mm, y+31*mm, str(r['Telefon']))
            
            # CÍM
            p.setFont(f_reg, 7); p.drawString(x+6*mm, y+27*mm, str(r['Cím'])[:48])
            
            # RENDELÉS - SORTÖRÉSSEL (Paragraph használata)
            order_text = str(r['Rendelés'])
            para = Paragraph(order_text, order_style)
            # A szélességet korlátozzuk, hogy ne lógjon át
            para.wrapOn(p, lw-12*mm, 15*mm)
            para.drawOn(p, x+6*mm, y+16*mm)
            
            # PÉNZÜGY ÉS ÖSSZESEN
            p.setFont(f_bold, 8); p.drawRightString(x+lw-7*mm, y+11*mm, f"Fizetendő: {r.get('Ár', '0 Ft')}")
            p.setFont(f_reg, 7); p.drawRightString(x+lw-7*mm, y+7*mm, f"Össz: {r['Összesen']} db")
            
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4*mm, f"Futár: {fn} | Jó étvágyat! :)")
        else:
            # MARKETING CÍMKE - KERET NÉLKÜL
            m_lines = ["15% kedvezmény* 3 hétig", "Új Ügyfeleink részére!", "Rendelés leadás:", f"{fn}, tel: {ft}", "* a kedvezmény telefonon leadott rendelésekre", "érvényesíthető területi képviselőnk által"]
            p.setFont(f_bold, 9.5); p.drawCentredString(x+lw/2, y+34*mm, m_lines[0])
            p.setFont(f_reg, 9); p.drawCentredString(x+lw/2, y+29*mm, m_lines[1])
            p.setFont(f_bold, 8); p.drawCentredString(x+lw/2, y+23*mm, m_lines[2])
            p.setFont(f_reg, 8.5); p.drawCentredString(x+lw/2, y+18*mm, m_lines[3])
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+10*mm, m_lines[4]); p.drawCentredString(x+lw/2, y+7*mm, m_lines[5])
            
    p.save(); buf.seek(0)
    return buf
