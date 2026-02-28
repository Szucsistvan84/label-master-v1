import streamlit as st
from pypdf import PdfReader
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Oldalbeállítás
st.set_page_config(page_title="Interfood Etikett Generátor", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #ff4b4b; color: white; }
    </style>
    """, unsafe_allow_html=True)

st.title("🚚 Interfood Menetterv Generátor")

# Sidebar adatok
st.sidebar.header("Futár adatai")
futar_nev = st.sidebar.text_input("Saját neved:", placeholder="pl. Ebéd Elek")
futar_tel = st.sidebar.text_input("Telefonszámod:", placeholder="pl. +36 20 123 4567")

def extract_data_from_pdf(pdf_file):
    reader = PdfReader(pdf_file)
    all_text = ""
    for page in reader.pages:
        all_text += page.extract_text() + "\n"
    
    # Adatok kinyerése regex-szel a többsoros szerkezet miatt
    rows = []
    # Keressük a sorszámmal kezdődő blokkokat
    pattern = re.compile(r'(\d+)\s+(P-|Z-)(\d+)\s+(.*?)\s+(\d{4}\s+Debrecen.*?)\s+(.*?)\s+(\d{2}/\d+.*?)\s+(.*?)\s+(\d+)', re.DOTALL)
    
    # Mivel a PDF-ek kaotikusak, egy robusztusabb sor-feldolgozót használunk
    lines = all_text.split('\n')
    current_row = None
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Ha sorszámmal és ügyfélkóddal kezdődik, új ügyfél
        match = re.match(r'^(\d+)\s+(P-|Z-)(\d+)\s+(.*)', line)
        if match:
            if current_row: rows.append(current_row)
            current_row = {
                'id': match.group(1),
                'kod': match.group(2) + match.group(3),
                'nev': match.group(4).split('/')[0].strip() if '/' in match.group(4) else match.group(4).strip(),
                'cim': '',
                'rendeles': '',
                'kapukod': ''
            }
        elif current_row:
            # Kapukód keresése
            if 'kcs' in line.lower() or 'kód' in line.lower() or 'kk:' in line.lower():
                current_row['kapukod'] = line
            # Cím keresése (Debrecen központú)
            elif 'Debrecen' in line:
                current_row['cim'] = line
            # Rendelés (ha van benne kötőjel és szám, pl 1-DK)
            elif re.search(r'\d-[A-Z]', line):
                current_row['rendeles'] += " " + line
            # Ha még nincs címe, az első pár sor valószínűleg a név folytatása vagy a cím kezdete
            elif not current_row['cim']:
                current_row['nev'] += " " + line

    if current_row: rows.append(current_row)
    return rows

uploaded_file = st.file_uploader("Húzd ide a menetterv PDF-et", type="pdf")

if uploaded_file and futar_nev and futar_tel:
    try:
        data = extract_data_from_pdf(uploaded_file)
        
        if not data:
            st.error("Nem sikerült adatokat kiolvasni a PDF-ből. Ellenőrizd a formátumot!")
        else:
            st.success(f"{len(data)} ügyfél feldolgozva!")
            
            # PDF Generálás
            output = io.BytesIO()
            c = canvas.Canvas(output, pagesize=A4)
            width, height = A4
            
            # Rács beállításai (3 oszlop, 7 sor)
            cols = 3
            rows_per_page = 7
            margin_x = 10
            margin_y = 20
            cell_w = (width - 2*margin_x) / cols
            cell_h = (height - 2*margin_y) / rows_per_page
            
            for i, item in enumerate(data):
                if i > 0 and i % (cols * rows_per_page) == 0:
                    c.showPage()
                
                idx = i % (cols * rows_per_page)
                col = idx % cols
                row = rows_per_page - 1 - (idx // cols)
                
                x = margin_x + col * cell_w
                y = margin_y + row * cell_h
                
                # Keret rajzolása
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x + 2, y + 2, cell_w - 4, cell_h - 4)
                
                # Tartalom írása
                c.setFillColorRGB(0, 0, 0)
                # Sorszám és Név
                c.setFont("Helvetica-Bold", 10)
                c.drawString(x + 10, y + cell_h - 20, f"{item['id']}. {item['nev'][:25]}")
                
                # Cím
                c.setFont("Helvetica", 9)
                c.drawString(x + 10, y + cell_h - 35, f"{item['cim'][:35]}")
                
                # Kapukód (ha van)
                if item['kapukod']:
                    c.setFillColorRGB(0.8, 0, 0)
                    c.setFont("Helvetica-Bold", 8)
                    c.drawString(x + 10, y + cell_h - 48, f"KÓD: {item['kapukod'][:35]}")
                    c.setFillColorRGB(0, 0, 0)
                
                # Rendelés
                c.setFont("Helvetica-Bold", 11)
                rendeles_tiszta = item['rendeles'].replace('#', '').strip()
                c.drawString(x + 10, y + 45, f"REND: {rendeles_tiszta[:30]}")
                
                # Marketing rész (Futár adatai)
                c.setDash(1, 2)
                c.line(x + 10, y + 35, x + cell_w - 10, y + 35)
                c.setDash()
                c.setFont("Helvetica", 7)
                c.drawString(x + 10, y + 25, f"Kiszállító: {futar_nev}")
                c.drawString(x + 10, y + 15, f"Tel: {futar_tel}")
                c.setFont("Helvetica-Bold", 7)
                c.drawString(x + cell_w - 60, y + 15, "JÓ ÉTVÁGYAT!")

            c.save()
            
            st.download_button(
                label="📥 Kész etikettek letöltése (PDF)",
                data=output.getvalue(),
                file_name="nyomtatando_etikettek.pdf",
                mime="application/pdf"
            )
            
    except Exception as e:
        st.error(f"Hiba történt: {e}")

elif not (futar_nev and futar_tel):
    st.info("Kérlek, add meg a neved és a telefonszámodat a bal oldali sávban!")
