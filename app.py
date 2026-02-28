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

st.set_page_config(page_title="Interfood Profi v5.7", layout="wide")
st.title("🚚 Interfood Etikett v5.7")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Pl: Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="Pl: +36208868971")

def extract_v57(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 0]
        
        current_id = None
        for i, line in enumerate(lines):
            # 1. Ügyfélkód és Nap (P-428867)
            id_match = re.search(r'([PZSC])-(\d{6})', line)
            if id_match:
                day, code = id_match.group(1), id_match.group(2)
                current_id = code
                if current_id not in customers:
                    customers[current_id] = {
                        'kod': code, 'nev': '', 'cim': '', 'tel': '', 
                        'penz': '0 Ft', 'P_rend': [], 'Z_rend': [], 'napok': {day}
                    }
                else:
                    customers[current_id]['napok'].add(day)

                # NÉV KERESÉSE: Az eredeti PDF-ben a név (Tőkés István) 
                # gyakran ugyanabban a sorban van a kód után, vagy a rákövetkező sorban.
                # Megtisztítjuk a sort a cégnevektől (Csokimax, Harro Höfliger stb.)
                potential_name = line.split(id_match.group(0))[-1].strip()
                if "/" in potential_name: potential_name = potential_name.split("/")[-1].strip()
                
                # Ha a sorban nem volt név, nézzük a következő sort
                if len(potential_name) < 3 and i+1 < len(lines):
                    potential_name = lines[i+1]
                
                if not customers[current_id]['nev']:
                    customers[current_id]['nev'] = potential_name.split('403')[0].strip()

            if current_id:
                # 2. Cím keresése (Irányítószám alapján)
                if '40' in line and 'Debrecen' in line and not customers[current_id]['cim']:
                    customers[current_id]['cim'] = line

                # 3. Telefon és Fizetendő
                if '/' in line and re.search(r'\d{7}', line):
                    customers[current_id]['tel'] = re.search(r'(\d{2}/\d{7})', line).group(1)
                if 'Ft' in line:
                    customers[current_id]['penz'] = re.search(r'(\d[\d\s]*\s?Ft)', line).group(1)

                # 4. Rendelési kódok (pl. 1-L1K)
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
                if codes:
                    target = 'Z_rend' if 'Z' in customers[current_id]['napok'] else 'P_rend'
                    customers[current_id][target].extend(codes)

    # Tisztítás: Csak azokat tartjuk meg, ahol van kód
    return [c for c in customers.values() if c['kod']]

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.7)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v57(uploaded_file)
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
                
                # FEJLÉC (Péntek/Szombat megkülönböztetés)
                if 'Z' in item['napok']:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    header_txt = "Péntek + Szombat!" if 'P' in item['napok'] or 'S' in item['napok'] else "Szombat"
                    p.drawCentredString(x+cw/2, y+ch-9, header_txt)
                
                p.setFillColorRGB(0, 0, 0)
                # 1. SOR: NÉV (balra) | ÜGYFÉLKÓD (jobbra)
                p.setFont(B_FONT, 10.5)
                clean_name = item['nev'].replace("Csokimax Mo.kft./", "").strip()
                p.drawString(x+8, y+ch-25, clean_name[:24])
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # 2. SOR: CÍM (tisztán)
                p.setFont(M_FONT, 9)
                clean_cim = item['cim'].split('Ügy')[0].strip()
                p.drawString(x+8, y+ch-36, clean_cim[:42])
                
                # TEL és PÉNZ
                p.setFont(M_FONT, 8.5)
                p.drawString(x+8, y+ch-46, f"Tel: {item['tel']}")
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 11)
                    p.drawRightString(x+cw-10, y+ch-46, item['penz'])

                # RENDELÉS (Napokra bontva)
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+30, f"Összesen: {len(p_list)+len(z_list)} tétel")
                
                p.setFont(B_FONT, 10)
                if p_list: p.drawString(x+8, 20, f"P: {', '.join(p_list)}"[:40])
                if z_list: p.drawString(x+8, 10 if p_list else 20, f"Sz: {', '.join(z_list)}"[:40])

                # LÁBLÉC
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+6, x+cw-10, y+6)
                p.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
                p.drawRightString(x+cw-10, y+4, "JÓ ÉTVÁGYAT!")
            else:
                # MARKETING
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
        st.download_button("📥 PDF LETÖLTÉSE (V5.7)", output.getvalue(), "interfood_v5.7.pdf")
