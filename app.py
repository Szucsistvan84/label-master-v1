import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# 1. Betűtípusok beállítása
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v4.9", layout="wide")
st.title("🚚 Interfood Végleges Etikett v4.9")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Pl: Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="Pl: +36201234567")

def clean_codes(code_list):
    """Tisztítja az ételkódokat a felesleges karakterektől."""
    cleaned = []
    for c in code_list:
        c = c.strip().strip(',').strip('.')
        if re.match(r'\d{1,2}-[A-Z0-9]+', c):
            cleaned.append(c)
    return cleaned

def extract_from_table_logic(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        current_id = None
        for line in lines:
            # Ügyfél azonosító keresése (pl: P-428867)
            id_match = re.search(r'([HKSCPZ])-(\d{5,6})', line)
            if id_match:
                day_type, id_num = id_match.group(1), id_match.group(2)
                current_id = id_num
                if current_id not in customers:
                    # Név kinyerése az ID utáni részből
                    name_part = line.split(id_match.group(0))[-1].strip()
                    name_part = re.sub(r'^[?. ]+', '', name_part)
                    customers[current_id] = {
                        'nev': name_part, 'cim': '', 'P_rend': [], 'Z_rend': [], 
                        'kk': '', 'napok': {day_type}
                    }
                else:
                    customers[current_id]['napok'].add(day_type)
            
            elif current_id:
                # Cím keresése (irányítószám alapján)
                if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line):
                    customers[current_id]['cim'] = line
                
                # Kapukód keresése
                if any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'kcs', 'kulcs']):
                    customers[current_id]['kk'] = line.strip()

                # Ételkódok keresése (a "Rendelése" oszlopból)
                # Keresünk minden szám-kötőjel-betű/szám kombinációt
                found_codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
                if found_codes:
                    # Megnézzük az utolsó azonosított napot az adott sornál
                    # (A PDF sorrendje szerint P jön előbb általában)
                    target = 'Z_rend' if 'Z' in customers[current_id]['napok'] and 'P' not in line else 'P_rend'
                    customers[current_id][target].extend(found_codes)

    return [c for c in customers.values() if len(c['nev']) > 1]

uploaded_file = st.file_uploader("Menetterv feltöltése (v4.9)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_from_table_logic(uploaded_file)
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
                p.rect(x+2, y+ch-12, cw-4, 10, fill=1) # Fekete fejléc
                p.setFillColorRGB(1, 1, 1)
                p.setFont(B_FONT, 9)
                
                n = item['napok']
                header = "Péntek + Szombat!" if ('P' in n and 'Z' in n) else ("Péntek" if 'P' in n else "Szombat")
                p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:30]) # Név
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-36, item['cim'][:42]) # Cím
                
                if item['kk']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    p.drawString(x+8, y+ch-46, f"KCS: {item['kk']}"[:45])
                
                # Rendelés adatok
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                total = len(p_list) + len(z_list)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+28, f"Összesen: {total} tétel")
                
                rend_text = ""
                if p_list: rend_text += f"P: {', '.join(p_list)}"
                if z_list: rend_text += (" | " if rend_text else "") + f"Sz: {', '.join(z_list)}"
                
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+17, rend_text[:38])
                
                # Lábléc ügyfélnek
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+13, x+cw-10, y+13)
                p.drawString(x+8, y+5.5, f"{input_nev} | {input_tel}")
                p.drawRightString(x+cw-10, y+5.5, "JÓ ÉTVÁGYAT!")
            else:
                # --- MARKETING CÍMKE (SZIGORÚAN A KÉRÉS SZERINT) ---
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
        st.download_button("📥 KÉSZ PDF LETÖLTÉSE (V4.9)", output.getvalue(), "interfood_javitott_v49.pdf")
