import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import re

st.set_page_config(page_title="Interfood Etikett", layout="wide")

# Futár adatok a sidebarban
st.sidebar.header("Beállítások")
futar_nev = st.sidebar.text_input("Név:", "Ebéd Elek")
futar_tel = st.sidebar.text_input("Tel:", "+36 20 886 8971")

def extract_simple(pdf_file):
    reader = PdfReader(pdf_file)
    data = []
    
    for page in reader.pages:
        text = page.extract_text()
        # Tisztítás: a táblázat fejléceit és az oldalszámokat kivesszük
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 2]
        
        current_id = ""
        current_nev = ""
        current_cim = ""
        current_rendeles = []
        current_info = ""

        for line in lines:
            # Sorszám keresése az elején (pl. "1", "10", "21")
            id_match = re.match(r'^(\d+)$', line)
            # Ügyfélkód keresése (pl. "P-428867")
            kod_match = re.search(r'([PZ]-\d+)', line)

            if id_match or kod_match:
                # Ha már van adatunk, mentsük el az előzőt
                if current_nev:
                    data.append({
                        'id': current_id,
                        'nev': current_nev,
                        'cim': current_cim,
                        'rendeles': ", ".join(current_rendeles),
                        'info': current_info
                    })
                
                # Új kezdése
                if id_match: current_id = id_match.group(1)
                current_nev = line if not id_match else ""
                current_cim = ""
                current_rendeles = []
                current_info = ""
            
            elif "Debrecen" in line:
                current_cim = line
            elif re.search(r'\d-[A-Z0-9]', line):
                codes = re.findall(r'\d-[A-Z0-9]+', line)
                if codes: current_rendeles.extend(codes)
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs']):
                current_info += " " + line
            elif not current_cim and len(line) > 5:
                if not current_nev: current_nev = line
                else: current_nev += " " + line

        # Utolsó elem
        if current_nev:
            data.append({'id': current_id, 'nev': current_nev, 'cim': current_cim, 'rendeles': ", ".join(current_rendeles), 'info': current_info})
            
    return data

uploaded_file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if uploaded_file:
    extracted = extract_simple(uploaded_file)
    if extracted:
        st.success(f"{len(extracted)} etikett generálható!")
        
        output = io.BytesIO()
        c = canvas.Canvas(output, pagesize=A4)
        width, height = A4
        
        # 3 oszlop, 7 sor
        c_w, c_h = (width-20)/3, (height-40)/7
        
        for i, item in enumerate(extracted):
            if i > 0 and i % 21 == 0: c.showPage()
            col, row_idx = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * c_w, 20 + row_idx * c_h
            
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.rect(x+2, y+2, c_w-4, c_h-4)
            
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x+8, y+c_h-15, f"{item['id']}. {item['nev'][:30]}")
            
            c.setFont("Helvetica", 8)
            c.drawString(x+8, y+c_h-25, f"{item['cim'][:35]}")
            
            if item['info']:
                c.setFillColorRGB(0.8, 0, 0)
                c.setFont("Helvetica-Bold", 7)
                c.drawString(x+8, y+c_h-35, f"INFÓ: {item['info'].strip()[:40]}")
                c.setFillColorRGB(0, 0, 0)
            
            c.setFont("Helvetica-Bold", 12)
            c.drawString(x+8, y+30, f"{item['rendeles'][:25]}")
            
            c.setFont("Helvetica", 7)
            c.drawString(x+8, y+12, f"{futar_nev} | {futar_tel}")

        c.save()
        st.download_button("LETÖLTÉS", output.getvalue(), "etikettek.pdf")
