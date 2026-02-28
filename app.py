import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import re

st.set_page_config(page_title="Interfood Etikett Generátor", layout="wide")
st.title("🚚 Interfood Menetterv Generátor")

st.sidebar.header("Futár adatai")
futar_nev = st.sidebar.text_input("Saját neved:", placeholder="pl. Ebéd Elek")
futar_tel = st.sidebar.text_input("Telefonszámod:", placeholder="pl. +36 20 123 4567")

def extract_data(pdf_file):
    reader = PdfReader(pdf_file)
    rows = []
    current_row = None
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            # Fejléc és felesleges infók kiszűrése
            if not line or any(x in line for x in ["Nyomtatta:", "Oldal", "Sor", "Ügyfél"]):
                continue
            
            # Új ügyfél felismerése (Sorszám + Kód: pl. "1 P-428867" vagy "10 Z-465258")
            # Ez a rész most már nem dob hibát, ha nincs egyezés
            match = re.search(r'^(\d+)\s+([PZ]-\d+)', line)
            
            if match:
                if current_row:
                    rows.append(current_row)
                
                # Kinyerjük a nevet a kód utáni részből
                name_part = line[match.end():].strip()
                current_row = {
                    'id': match.group(1),
                    'nev': name_part,
                    'cim': '',
                    'rendeles': '',
                    'kapukod': ''
                }
            elif current_row:
                # Adatok szétválogatása tartalom alapján
                if "Debrecen" in line:
                    current_row['cim'] = line
                elif any(x in line.lower() for x in ['kcs', 'kód', 'kk:', 'kapukód', 'kulcs', 'kapu', 'itthon']):
                    current_row['kapukod'] += " " + line
                elif re.search(r'\d-[A-Z0-9]', line):
                    # Ételkódok gyűjtése (pl. 1-L1K)
                    codes = re.findall(r'\d-[A-Z0-9]{1,4}', line)
                    if codes:
                        current_row['rendeles'] += " " + " ".join(codes)
                elif len(line) > 3 and not current_row['cim']:
                    # Ha se nem cím, se nem kód, akkor valószínűleg a név folytatása
                    current_row['nev'] += " " + line

    if current_row:
        rows.append(current_row)
    return rows

uploaded_file = st.file_uploader("Húzd ide a menetterv PDF-et", type="pdf")

if uploaded_file and futar_nev and futar_tel:
    try:
        data = extract_data(uploaded_file)
        if not data:
            st.warning("Nem találtam felismerhető adatot. Ellenőrizd a PDF-et!")
        else:
            st.success(f"Siker! {len(data)} etikett beolvasva.")
            
            output = io.BytesIO()
            c = canvas.Canvas(output, pagesize=A4)
            width, height = A4
            cols, rows_per_page = 3, 7
            cell_w, cell_h = (width-20)/cols, (height-40)/rows_per_page
            
            for i, item in enumerate(data):
                if i > 0 and i % 21 == 0: c.showPage()
                col = (i % 21) % cols
                row = rows_per_page - 1 - ((i % 21) // cols)
                x, y = 10 + col * cell_w, 20 + row * cell_h
                
                # Keret és szöveg
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x+2, y+2, cell_w-4, cell_h-4)
                c.setFillColorRGB(0, 0, 0)
                
                # Adatok elhelyezése
                c.setFont("Helvetica-Bold", 10)
                c.drawString(x+10, y+cell_h-18, f"{item['id']}. {item['nev'][:28]}")
                c.setFont("Helvetica", 8)
                c.drawString(x+10, y+cell_h-28, f"{item['cim'][:40]}")
                
                if item['kapukod']:
                    c.setFillColorRGB(0.8, 0, 0)
                    c.setFont("Helvetica-Bold", 7)
                    c.drawString(x+10, y+cell_h-38, f"INFÓ: {item['kapukod'].strip()[:42]}")
                    c.setFillColorRGB(0, 0, 0)
                
                c.setFont("Helvetica-Bold", 13)
                c.drawString(x+10, y+35, f"{item['rendeles'].strip()[:25]}")
                
                c.setFont("Helvetica", 7)
                c.drawString(x+10, y+12, f"{futar_nev} | {futar_tel}")
                c.drawRightString(x+cell_w-12, y+12, "JÓ ÉTVÁGYAT!")

            c.save()
            st.download_button("📥 Etikettek Letöltése", output.getvalue(), "etikettek.pdf", "application/pdf")
            
    except Exception as e:
        st.error(f"Hiba történt: {e}")
