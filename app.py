import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# 1. Betűtípus regisztrálása - A MAGYAR ÉKEZETEKÉRT
font_path = "Roboto-Regular.ttf"
font_bold_path = "Roboto-Bold.ttf"

if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    MAIN_FONT = "Roboto"
    BOLD_FONT = "Roboto-Bold"
else:
    MAIN_FONT = "Helvetica"
    BOLD_FONT = "Helvetica-Bold"

st.set_page_config(page_title="Interfood Etikett", layout="wide")
st.title("🚚 Interfood Menetterv Generátor")

# Futár adatok a sidebarban
st.sidebar.header("Beállítások")
f_nev = st.sidebar.text_input("Név:", value="", placeholder="Ebéd Elek")
f_tel = st.sidebar.text_input("Tel:", value="", placeholder="+36207654321")

def extract_logic(pdf_file):
    reader = PdfReader(pdf_file)
    data = []
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        c_id, c_nev, c_cim, c_info = "", "", "", ""
        c_rendeles = []

        for line in lines:
            # Fejlécek és dátumok kiszűrése (ezek okozták a szemét matricákat)
            if any(x in line for x in ["Nyomtatta:", "Oldal", "Járatszám", "Menetterv", "Sor", "Ügyfél"]):
                continue
            if re.search(r'\d{4}\.\s\d{2}\.\s\d{2}\.', line): # Dátum formátum szűrése
                continue

            # Új ügyfél felismerése
            id_match = re.match(r'^(\d+)$', line) # Csak egy szám (pl. "10")
            full_match = re.match(r'^(\d+)\s+([PZ]-\d+)', line) # Szám + Kód (pl. "10 P-428867")
            kod_only = re.search(r'([PZ]-\d+)', line) # Csak kód valahol

            if id_match or full_match or kod_only:
                # Mentjük az előzőt, ha volt
                if c_nev and c_cim:
                    data.append({
                        'id': c_id, 'nev': c_nev, 'cim': c_cim,
                        'rend': ", ".join(c_rendeles), 'info': c_info
                    })
                
                # Reset és új adatok
                if full_match:
                    c_id = full_match.group(1)
                    c_nev = line.split(full_match.group(2))[-1].strip()
                elif id_match:
                    c_id = id_match.group(1)
                    c_nev = ""
                elif kod_only:
                    c_nev = line.split(kod_only.group(1))[-1].strip()
                
                c_cim, c_info = "", ""
                c_rendeles = []
            
            elif "Debrecen" in line:
                c_cim = line
            elif re.search(r'\d-[A-Z0-9]', line):
                codes = re.findall(r'\d-[A-Z0-9]+', line)
                for c in codes:
                    if c not in c_rendeles and len(c) < 10: c_rendeles.append(c)
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs', 'porta']):
                c_info += " " + line
            elif len(line) > 5 and not c_cim:
                c_nev = line if not c_nev else c_nev + " " + line

        # Utolsó elem mentése
        if c_nev and c_cim:
            data.append({'id': c_id, 'nev': c_nev, 'cim': c_cim, 'rend': ", ".join(c_rendeles), 'info': c_info})
    return data

uploaded_file = st.file_uploader("Válaszd ki a PDF menettervet", type="pdf")

if uploaded_file:
    if not f_nev or not f_tel:
        st.info("💡 Kérlek, írd be a Neved és a Számod a bal oldalon, hogy rákerüljön a matricára!")
    else:
        results = extract_logic(uploaded_file)
        if results:
            st.success(f"✅ {len(results)} db etikett beolvasva!")
            
            output = io.BytesIO()
            c = canvas.Canvas(output, pagesize=A4)
            w, h = A4
            cw, ch = (w-20)/3, (h-40)/7
            
            for i, item in enumerate(results):
                if i > 0 and i % 21 == 0: c.showPage()
                col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
                x, y = 10 + col * cw, 20 + row * ch
                
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x+2, y+2, cw-4, ch-4)
                
                c.setFillColorRGB(0, 0, 0)
                c.setFont(BOLD_FONT, 9)
                c.drawString(x+8, y+ch-18, f"{item['id']}. {item['nev'][:30]}")
                
                c.setFont(MAIN_FONT, 8)
                t_cim = item['cim'].replace("4031 Debrecen, ", "").replace("4002 Debrecen, ", "")
                c.drawString(x+8, y+ch-28, f"{t_cim[:38]}")
                
                if item['info']:
                    c.setFillColorRGB(0.8, 0, 0)
                    c.setFont(BOLD_FONT, 7)
                    c.drawString(x+8, y+ch-38, f"INFÓ: {item['info'].strip()[:40]}")
                    c.setFillColorRGB(0, 0, 0)
                
                c.setFont(BOLD_FONT, 14)
                c.drawString(x+8, y+30, f"{item['rend'][:25]}")
                
                c.setFont(MAIN_FONT, 7)
                c.drawString(x+8, y+12, f"{f_nev} | {f_tel}")
                c.drawRightString(x+cw-10, y+12, "JÓ ÉTVÁGYAT!")

            c.save()
            st.download_button("📥 MATRICÁK LETÖLTÉSE", output.getvalue(), "interfood_kesz.pdf")
