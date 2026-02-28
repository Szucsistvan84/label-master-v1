import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Betűtípusok
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v5.2", layout="wide")
st.title("🚚 Interfood Etikett v5.2")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Pl: Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="Pl: +36201234567")

def extract_v52(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {}
    current_id = None
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 0]
        
        for line in lines:
            # 1. Ügyfélkód és Nap kinyerése (P-123456)
            id_match = re.search(r'([HKSCPZ])-(\d{6})', line)
            if id_match:
                day, code = id_match.group(1), id_match.group(2)
                current_id = code
                if current_id not in customers:
                    customers[current_id] = {
                        'kod': code, 'nev': '', 'cim': '', 'P_rend': [], 'Z_rend': [], 
                        'kk': '', 'napok': {day}, 'tel': '', 'penz': ''
                    }
                else:
                    customers[current_id]['napok'].add(day)
            
            if current_id:
                # 2. Cím keresése (4 számjegy + Város)
                if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line) and not customers[current_id]['cim']:
                    customers[current_id]['cim'] = line
                
                # 3. Név kinyerése (A minta alapján az Ügyintéző/Név oszlopból)
                # Itt a nevet próbáljuk elkapni, ami nem az ID-s sorban van
                if not customers[current_id]['nev'] and not id_match and not re.search(r'\d{4}', line):
                    if len(line) > 3 and not any(x in line.lower() for x in ['kód', 'ft', 'rend']):
                        customers[current_id]['nev'] = line

                # 4. Tel és Pénz
                tel_match = re.search(r'(\d{2}/\d{7}|\d{10,11})', line)
                if tel_match: customers[current_id]['tel'] = tel_match.group(1)
                
                money_match = re.search(r'(\d[\d\s]*\s?Ft)', line)
                if money_match: customers[current_id]['penz'] = money_match.group(1)

                # 5. Ételkódok nap szerint
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
                if codes:
                    target = 'Z_rend' if 'Z' in customers[current_id]['napok'] else 'P_rend'
                    customers[current_id][target].extend(codes)
                
                if any(x in line.lower() for x in ['kód', 'kcs', 'kulcs']):
                    customers[current_id]['kk'] = line.strip()

    return [c for c in customers.values() if c['kod']]

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.2)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v52(uploaded_file)
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
                item = data[i]
                n = item['napok']
                
                # Fejléc (csak ha van szombat)
                if 'Z' in n:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    header = "Péntek + Szombat!" if 'P' in n else "Szombat"
                    p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                # --- 1. SOR: NÉV (balra) és KÓD (jobbra) ---
                p.setFont(B_FONT, 10)
                display_name = item['nev'] if item['nev'] else "Ügyfél"
                p.drawString(x+8, y+ch-25, display_name[:25])
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # --- 2. SOR: CÍM ---
                p.setFont(M_FONT, 9)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                # Tel és Pénz
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-46, f"Tel: {item['tel']}" if item['tel'] else "")
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 11)
                    p.drawRightString(x+cw-10, y+ch-46, item['penz'])
                
                if item['kk']:
                    p.setFont(B_FONT, 7.5)
                    p.setFillColorRGB(0.8, 0, 0)
                    p.drawString(x+8, y+ch-55, item['kk'][:45])
                
                # Rendelés
                p.setFillColorRGB(0, 0, 0)
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+30, f"Összesen: {len(p_list)+len(z_list)} tétel")
                
                rend_y = 19
                p.setFont(B_FONT, 10)
                if p_list:
                    p.drawString(x+8, rend_y, f"P: {', '.join(p_list)}"[:40])
                    rend_y -= 10
                if z_list:
                    p.drawString(x+8, 19 if not p_list else 10, f"Sz: {', '.join(z_list)}"[:40])

                # Lábléc
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+13 if not z_list else y+5, x+cw-10, y+13 if not z_list else y+5)
                p.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
                p.drawRightString(x+cw-10, y+4, "JÓ ÉTVÁGYAT!")
            else:
                # MARKETING (BEBETONOZVA)
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
                p.drawCentredString(x+cw/2, y+20, "* a kedvezmény telefonon leadott rendelésekre")
                p.drawCentredString(x+cw/2, y+14, "érvényesíthető területi képviselőnk által")

        p.save()
        st.download_button("📥 PDF LETÖLTÉSE (V5.2)", output.getvalue(), "interfood_v52.pdf")
