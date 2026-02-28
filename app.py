import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# 1. Betűtípus regisztrálása
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

# Futár adatok a sidebarban - Placeholder-rel
st.sidebar.header("Beállítások")
futar_nev = st.sidebar.text_input("Név:", value="", placeholder="Ebéd Elek")
futar_tel = st.sidebar.text_input("Tel:", value="", placeholder="+36207654321")

def extract_simple(pdf_file):
    reader = PdfReader(pdf_file)
    data = []
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 2]
        
        current_id, current_nev, current_cim, current_info = "", "", "", ""
        current_rendeles = []

        for line in lines:
            if any(x in line for x in ["Nyomtatta:", "Oldal", "Járatszám", "Menetterv", "Sor", "Ügyfél"]):
                continue

            id_match = re.match(r'^(\d+)$', line)
            kod_match = re.search(r'([PZ]-\d+)', line)

            if id_match or kod_match:
                if current_nev and current_cim:
                    data.append({
                        'id': current_id, 'nev': current_nev, 'cim': current_cim,
                        'rendeles': ", ".join(current_rendeles), 'info': current_info
                    })
                
                if id_match: current_id = id_match.group(1)
                current_nev = line if not kod_match else line.split(kod_match.group(1))[-1].strip()
                current_cim, current_info = "", ""
                current_rendeles = []
            
            elif "Debrecen" in line:
                current_cim = line
            elif re.search(r'\d-[A-Z0-9]', line):
                codes = re.findall(r'\d-[A-Z0-9]+', line)
                for c in codes:
                    if c not in current_rendeles: current_rendeles.append(c)
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs']):
                current_info += " " + line
            elif not current_cim and len(line) > 5:
                current_nev = line if not current_nev else current_nev + " " + line

        if current_nev and current_cim:
            data.append({'id': current_id, 'nev': current_nev, 'cim': current_cim, 'rendeles': ", ".join(current_rendeles), 'info': current_info})
    return data

uploaded_file = st.file_uploader("Húzd ide a menetterv PDF-et", type="pdf")

# LOGIKA ÉS MEGJELENÍTÉS
if uploaded_file:
    if not futar_nev or not futar_tel:
        st.warning("⚠️ Kérlek, add meg a Nevedet és a Telefonszámodat a bal oldali sávban!")
    else:
        extracted_data = extract_simple(uploaded_file)
        if extracted_data:
            st.success(f"Siker! {len(extracted_data)} etikett feldolgozva.")
            
            output = io.BytesIO()
            c = canvas.Canvas(output, pagesize=A4)
            width, height = A4
            c_w, c_h = (width-20)/3, (height-40)/7
            
            for i, item in enumerate(extracted_data):
                if i > 0 and i % 21 == 0: c.showPage()
                col, row_idx = (i % 21) % 3, 6 - ((i % 21) // 3)
                x, y = 10 + col * c_w, 20 + row_idx * c_h
                
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x+2, y+2, c_w-4, c_h-4)
                
                c.setFillColorRGB(0, 0, 0)
                c.setFont(BOLD_FONT, 10)
                c.drawString(x+8, y+c_h-18, f"{item['id']}. {item['nev'][:30]}")
                
                c.setFont(MAIN_FONT, 8)
                t_cim = item['cim'].replace("4031 Debrecen, ", "").replace("4002 Debrecen, ", "")
                c.drawString(x+8, y+c_h-28, f"{t_cim[:38]}")
                
                if item['info']:
                    c.setFillColorRGB(0.8, 0, 0)
                    c.setFont(BOLD_FONT, 7)
                    c.drawString(x+8, y+c_h-38, f"INFÓ: {item['info'].strip()[:42]}")
                    c.setFillColorRGB(0, 0, 0)
                
                c.setFont(BOLD_FONT, 14)
                c.drawString(x+8, y+35, f"{item['rendeles'][:25]}")
                
                c.setFont(MAIN_FONT, 7)
                c.drawString(x+8, y+12, f"{futar_nev} | {futar_tel}")
                c.drawRightString(x+c_w-10, y+12, "JÓ ÉTVÁGYAT!")

            c.save()
            st.download_button("📥 MATRICÁK LETÖLTÉSE", output.getvalue(), "interfood_matricak.pdf")
        else:
            st.error("Nem találtam feldolgozható adatot a PDF-ben.")
