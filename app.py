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

st.set_page_config(page_title="Interfood Profi v5.0", layout="wide")
st.title("🚚 Interfood Etikett v5.0")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Pl: Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="Pl: +36201234567")

def extract_v5(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {}
    current_id = None
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        # Fontos: a PDF sorait tisztítjuk, de megtartjuk a sorrendet
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 0]
        
        for line in lines:
            # 1. Ügyfél azonosítása (Horgony pont)
            id_match = re.search(r'([HKSCPZ])-(\d{5,6})', line)
            if id_match:
                day, num = id_match.group(1), id_match.group(2)
                current_id = num
                if current_id not in customers:
                    name_p = line.split(id_match.group(0))[-1].strip()
                    name_p = re.sub(r'^[?. ]+', '', name_p)
                    customers[current_id] = {
                        'nev': name_p, 'cim': '', 'rend': [], 'kk': '', 'napok': {day}
                    }
                else:
                    customers[current_id]['napok'].add(day)
            
            # 2. Adatok gyűjtése a horgonyhoz
            if current_id:
                # Cím keresése
                if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line):
                    customers[current_id]['cim'] = line
                
                # Kapukód keresése (KCS/KK)
                if any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'kcs', 'kulcs']):
                    customers[current_id]['kk'] = line.strip()

                # ÉTELKÓDOK KERESÉSE (A lényeg!)
                # Keresünk minden 'szám-betűk' mintát (pl: 1-L1K, 1-DK, 2-R2)
                # Olyanokat is, amik kötőjellel kezdődnek a sor elején a PDF hiba miatt
                codes = re.findall(r'(?:\d{1,2})?-[A-Z0-9]{1,4}\b|\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
                if codes:
                    # Nap megjelölése a kód elé (P- vagy Z-)
                    prefix = "P: " if any('P' in n for n in customers[current_id]['napok']) else "Sz: "
                    # Csak azokat adjuk hozzá, amik nem csak egy magányos kötőjel
                    for c in codes:
                        clean_c = c.strip()
                        if len(clean_c) > 1:
                            customers[current_id]['rend'].append(clean_c)

    return [c for c in customers.values() if len(c['nev']) > 1]

uploaded_file = st.file_uploader("Menetterv PDF (v5.0)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v5(uploaded_file)
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
                header = "Péntek + Szombat!" if ('P' in n and 'Z' in n) else ("Péntek" if 'P' in n else "Szombat")
                p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:30])
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                if item['kk']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    p.drawString(x+8, y+ch-46, item['kk'][:45])
                
                # RENDELÉS MEGJELENÍTÉSE
                all_codes = sorted(list(set(item['rend'])))
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+28, f"Összesen: {len(all_codes)} tétel")
                
                p.setFont(B_FONT, 10)
                # Egyszerűsített kiírás: minden kódot felsorolunk
                rend_line = ", ".join(all_codes)
                p.drawString(x+8, y+17, f"Rend: {rend_line}"[:40])
                
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
        st.download_button("📥 PDF LETÖLTÉSE (V5.0)", output.getvalue(), "interfood_v50.pdf")
