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

st.set_page_config(page_title="Interfood Profi v5.1", layout="wide")
st.title("🚚 Interfood Etikett v5.1")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Pl: Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="Pl: +36201234567")

def extract_v51(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {}
    current_id = None
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 0]
        
        for line in lines:
            # 1. Ügyfél horgony (P-123456 vagy Z-123456)
            id_match = re.search(r'([HKSCPZ])-(\d{5,6})', line)
            if id_match:
                day, num = id_match.group(1), id_match.group(2)
                current_id = num
                if current_id not in customers:
                    name_p = line.split(id_match.group(0))[-1].strip()
                    name_p = re.sub(r'^[?. ]+', '', name_p)
                    customers[current_id] = {
                        'nev': name_p, 'cim': '', 'rend': [], 'kk': '', 
                        'napok': {day}, 'tel': '', 'penz': ''
                    }
                else:
                    customers[current_id]['napok'].add(day)
            
            if current_id:
                # Cím (4 számjegy + Város)
                if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line):
                    customers[current_id]['cim'] = line
                
                # Ügyfél telefonszáma (pl: 70/1234567 vagy 0620...)
                tel_match = re.search(r'(\d{2}/\d{7}|\d{10,11})', line)
                if tel_match and not customers[current_id]['tel']:
                    customers[current_id]['tel'] = tel_match.group(1)

                # Beszedendő pénz (pl: 11 555 Ft)
                money_match = re.search(r'(\d[\d\s]*\s?Ft)', line)
                if money_match:
                    customers[current_id]['penz'] = money_match.group(1)

                # Ételkódok
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
                if codes:
                    customers[current_id]['rend'].extend(codes)
                
                # Kapukód
                if any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'kcs', 'kulcs']):
                    customers[current_id]['kk'] = line.strip()

    return [c for c in customers.values() if len(c['nev']) > 1]

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.1)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v51(uploaded_file)
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
                n = item['napok']
                
                # Csak akkor van fejléc sáv, ha nem sima péntek
                if 'Z' in n:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    header = "Péntek + Szombat!" if 'P' in n else "Szombat"
                    p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                # Név és Ügyfél Tel
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:30])
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-34, f"Tel: {item['tel']}" if item['tel'] else "")
                # Cím
                p.drawString(x+8, y+ch-43, item['cim'][:42])
                
                # Pénz (Beszedendő)
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 11)
                    p.setFillColorRGB(0.7, 0, 0) # Pirosas szín a figyelemért
                    p.drawRightString(x+cw-10, y+ch-34, f"FIZETENDŐ: {item['penz']}")
                
                p.setFillColorRGB(0, 0, 0)
                if item['kk']:
                    p.setFont(B_FONT, 7.5)
                    p.drawString(x+8, y+ch-53, item['kk'][:45])
                
                # Rendelés
                all_codes = sorted(list(set(item['rend'])))
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+28, f"Összesen: {len(all_codes)} tétel")
                p.setFont(B_FONT, 11)
                p.drawString(x+8, y+17, f"Rend: {', '.join(all_codes)}"[:38])
                
                # Lábléc (Saját adatok)
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+13, x+cw-10, y+13)
                p.drawString(x+8, y+5.5, f"{input_nev} | {input_tel}")
                p.drawRightString(x+cw-10, y+5.5, "JÓ ÉTVÁGYAT!")
            else:
                # --- MARKETING CÍMKE (BEBETONOZVA) ---
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
        st.download_button("📥 JAVÍTOTT PDF LETÖLTÉSE (V5.1)", output.getvalue(), "interfood_profi_v51.pdf")
