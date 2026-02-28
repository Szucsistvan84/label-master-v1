import streamlit as st
from pypdf import PdfReader
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import re

# Oldalbeállítás
st.set_page_config(page_title="Interfood Etikett Generátor", layout="wide")

st.title("🚚 Interfood Menetterv Generátor")

# Sidebar adatok
st.sidebar.header("Futár adatai")
futar_nev = st.sidebar.text_input("Saját neved:", placeholder="pl. Ebéd Elek")
futar_tel = st.sidebar.text_input("Telefonszámod:", placeholder="pl. +36 20 123 4567")

def extract_data(pdf_file):
    reader = PdfReader(pdf_file)
    rows = []
    current_row = None
    
    for page in reader.pages:
        text = page.extract_text()
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or "Nyomtatta:" in line or "Oldal" in line:
                continue
            
            # Új ügyfél kezdődik (Sorszám + Kód, pl: 10 P-465258)
            match = re.match(r'^(\d+)\s+([PZ]-\d+)\s*(.*)', line)
            if match:
                if current_row:
                    rows.append(current_row)
                current_row = {
                    'id': match.group(1),
                    'kod': match.group(2),
                    'nev': match.group(3).strip(),
                    'cim': '',
                    'rendeles': '',
                    'kapukod': ''
                }
            elif current_row:
                # Cím keresése (Irányítószám + Város)
                if re.search(r'\d{4}\s+Debrecen', line):
                    current_row['cim'] = line
                # Kapukód keresése
                elif any(x in line.lower() for x in ['kcs', 'kód', 'kk:', 'kapukód', 'kulcs']):
                    current_row['kapukod'] += " " + line
                # Rendelés keresése (pl: 1-L1K)
                elif re.search(r'\d-[A-Z0-9]', line):
                    # Csak az ételkódokat tartjuk meg
                    codes = re.findall(r'\d-[A-Z0-9]+', line)
                    if codes:
                        current_row['rendeles'] += " " + ", ".join(codes)
                # Ha még nincs cím és nem rendelés, akkor a név folytatása
                elif not current_row['cim'] and len(line) > 3:
                    current_row['nev'] += " " + line

    if current_row:
        rows.append(current_row)
    return rows

uploaded_file = st.file_uploader("Húzd ide a menetterv PDF-et", type="pdf")

if uploaded_file and futar_nev and futar_tel:
    try:
        data = extract_data(uploaded_file)
        if not data:
            st.warning("Nem találtam adatokat. Biztos jó PDF-et töltöttél fel?")
        else:
            st.success(f"Siker! {len(data)} etikett készen áll.")
            
            output = io.BytesIO()
            c = canvas.Canvas(output, pagesize=A4)
            width, height = A4
            
            # 3x7-es elrendezés
            cols, rows_per_page = 3, 7
            cell_w, cell_h = (width-20)/cols, (height-40)/rows_per_page
            
            for i, item in enumerate(data):
                if i > 0 and i % 21 == 0: c.showPage()
                
                col = (i % 21) % cols
                row = rows_per_page - 1 - ((i % 21) // cols)
                x, y = 10 + col * cell_w, 20 + row * cell_h
                
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x+2, y+2, cell_w-4, cell_h-4)
                
                # Név és Sorszám
                c.setFont("Helvetica-Bold", 10)
                c.drawString(x+10, y+cell_h-20, f"{item['id']}. {item['nev'][:25]}")
                
                # Cím
                c.setFont("Helvetica", 8)
                c.drawString(x+10, y+cell_h-32, f"{item['cim'][:40]}")
                
                # Kapukód (Kiemelve)
                if item['kapukod']:
                    c.setFillColorRGB(0.7, 0, 0)
                    c.setFont("Helvetica-Bold", 7)
                    c.drawString(x+10, y+cell_h-42, f"INFO: {item['kapukod'][:45]}")
                    c.setFillColorRGB(0, 0, 0)
                
                # Rendelés (Nagybetűvel)
                c.setFont("Helvetica-Bold", 12)
                c.drawString(x+10, y+35, f"{item['rendeles'][:30]}")
                
                # Alsó sáv
                c.setFont("Helvetica", 7)
                c.drawString(x+10, y+15, f"{futar_nev} | {futar_tel}")
                c.drawRightString(x+cell_w-10, y+15, "Jó étvágyat!")

            c.save()
            st.download_button("📥 Etikettek Letöltése", output.getvalue(), "etikettek.pdf", "application/pdf")
            
    except Exception as e:
        st.error(f"Hiba történt a feldolgozás során: {e}")
