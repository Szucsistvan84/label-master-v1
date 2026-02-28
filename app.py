import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# 1. Betűtípusok
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v4.8", layout="wide")
st.title("🚚 Interfood Végleges Etikett v4.8")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="+36201234567")

def extract_all_data(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {} 
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        last_id = None
        current_day = None
        
        for line in lines:
            # Nap és ügyfélkód keresése
            match = re.search(r'([HKSCPZ])-(\d+)', line)
            if match:
                current_day, last_id = match.group(1), match.group(2)
                if last_id not in customers:
                    name_p = line.split(match.group(0))[-1].strip()
                    name_p = re.sub(r'^[?. ]+', '', name_p)
                    customers[last_id] = {
                        'nev': name_p, 'cim': '', 
                        'P_rend': [], 'Z_rend': [], # Külön gyűjtjük
                        'kk': '', 'napok': {current_day}
                    }
                else:
                    customers[last_id]['napok'].add(current_day)
            
            elif last_id:
                # Cím (4 számjegy)
                if re.match(r'^\d{4}\s+', line):
                    customers[last_id]['cim'] = line
                # Kapukód
                elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'kcs', 'kulcs']):
                    if line not in customers[last_id]['kk']:
                        customers[last_id]['kk'] = (customers[last_id]['kk'] + " " + line).strip()
                
                # Ételkódok (pl. 1-A, 1-L1K) vadászata minden sorban
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
                if codes:
                    # Ha épp egy P- vagy Z- sor alatt vagyunk, oda tesszük
                    target_key = 'Z_rend' if current_day == 'Z' else 'P_rend'
                    customers[last_id][target_key].extend(codes)
    
    return [c for c in customers.values() if len(c['nev']) > 1]

uploaded_file = st.file_uploader("Menetterv feltöltése", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_all_data(uploaded_file)
    if data:
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        cw, ch = (A4[0]-20)/3, (A4[1]-40)/7

        for i in range(((len(data)-1)//21+1)*21):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            p.setStrokeColorRGB(0, 0, 0)
            p.rect(x+2, y+2, cw-4, ch-4)

            if i < len(data):
                # --- ÜGYFÉL CÍMKE ---
                item = data[i]
                p.setFillColorRGB(0, 0, 0)
                p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                p.setFillColorRGB(1, 1, 1)
                p.setFont(B_FONT, 9)
                
                n = item['napok']
                header = "Péntek + Szombat!" if ('P' in n and 'Z' in n) else ("Péntek" if 'P' in n else ("Szombat" if 'Z' in n else "INTERFOOD"))
                p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:32])
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                if item['kk']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    p.drawString(x+8, y+ch-45, f"KCS: {item['kk']}"[:45])
                
                # Rendelés összesítő (P és Z bontásban)
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                total = len(p_list) + len(z_list)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+26, f"Összesen: {total} tétel")
                
                rend_str = ""
                if p_list: rend_str += f"P: {', '.join(p_list)}"
                if z_list: rend_str += f" | Sz: {', '.join(z_list)}"
                
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+16, rend_str[:38])
                
                # Lábléc
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+13, x+cw-10, y+13)
                p.drawString(x+8, y+5.5, f"{input_nev} | {input_tel}")
                p.drawRightString(x+cw-10, y+5.5, "JÓ ÉTVÁGYAT!")
            else:
                # --- MARKETING CÍMKE (LETISZTÍTVA) ---
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 13)
                p.drawCentredString(x+cw/2, y+ch-25, "15% kedvezmény* 3 hétig")
                p.setFont(B_FONT, 11)
                p.drawCentredString(x+cw/2, y+ch-40, "Új Ügyfeleink részére!")
                
                p.setFont(M_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch/2 - 2, "Rendelés leadás:")
                p.setFont(B_FONT, 10.5)
                p.drawCentredString(x+cw/2, y+ch/2 - 15, f"{input_nev}, tel: {input_tel}")
                
                p.setFont(M_FONT, 5.5)
                p.drawCentredString(x+cw/2, y+18, "* a kedvezmény telefonon leadott rendelésekre")
                p.drawCentredString(x+cw/2, y+12, "érvényesíthető területi képviselőnk által")

        p.save()
        st.download_button("📥 KÉSZ PDF LETÖLTÉSE", output.getvalue(), "interfood_final_v4.8.pdf")
