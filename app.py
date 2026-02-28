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

st.set_page_config(page_title="Interfood Profi v5.6", layout="wide")
st.title("🚚 Interfood Etikett v5.6")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="+36201234567")

def extract_v56(pdf_file):
    reader = PdfReader(pdf_file)
    all_text = ""
    for page in reader.pages:
        all_text += page.extract_text() + "\n"
    
    # Ügyfélblokkokra bontás a sorszámok alapján (pl. "1 ", "2 ", "3 ")
    # A menettervben minden ügyfél egy sorszámmal kezdődik a bal szélen
    blocks = re.split(r'\n(?=\d{1,3}\n[PZSC]-)', all_text)
    
    customers = {}
    
    for block in blocks:
        # 1. Kód és Nap kinyerése
        id_match = re.search(r'([PZSC])-(\d{6})', block)
        if not id_match: continue
        
        day, code = id_match.group(1), id_match.group(2)
        
        # Ha új ügyfél, létrehozzuk az alap objektumot
        if code not in customers:
            # 2. Név kinyerése: Az "Ügyintéző" oszlopban lévő név a legtisztább
            # Általában a telefonszám előtt vagy a cím után van
            lines = [l.strip() for l in block.split('\n') if len(l.strip()) > 1]
            name = ""
            for line in lines:
                # Olyan sort keresünk, ami névnek tűnik és nem tartalmazza a várost vagy a kódot
                if re.match(r'^[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s[A-ZÁÉÍÓÖŐÚÜŰ]', line) and \
                   "Debrecen" not in line and "-" not in line and "Ft" not in line:
                    name = line
                    break
            
            # 3. Cím (4 számjegy + Debrecen)
            cim_match = re.search(r'(\d{4}\s+Debrecen,.*)', block)
            cim = cim_match.group(1).split('\n')[0] if cim_match else ""
            
            # 4. Telefon és Pénz
            tel_match = re.search(r'(\d{2}/\d{7,8}|\d{10,11})', block)
            money_match = re.search(r'(\d[\d\s]*\s?Ft)', block)
            
            customers[code] = {
                'kod': code, 'nev': name, 'cim': cim, 
                'tel': tel_match.group(1) if tel_match else "",
                'penz': money_match.group(1) if money_match else "0 Ft",
                'P_rend': [], 'Z_rend': [], 'napok': {day}
            }
        
        # 5. Rendelés kódok (csak az aktuális blokkból!)
        codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', block)
        if day == 'Z':
            customers[code]['Z_rend'].extend(codes)
            customers[code]['napok'].add('Z')
        else:
            customers[code]['P_rend'].extend(codes)
            customers[code]['napok'].add(day)

    return list(customers.values())

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.6)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v56(uploaded_file)
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
                
                # FEJLÉC
                if 'Z' in item['napok']:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    p.drawCentredString(x+cw/2, y+ch-9, "Péntek + Szombat!" if 'P' in item['napok'] else "Szombat")
                
                p.setFillColorRGB(0, 0, 0)
                # 1. SOR: NÉV (bal) | KÓD (jobb)
                p.setFont(B_FONT, 10.5)
                p.drawString(x+8, y+ch-25, item['nev'][:25] if item['nev'] else "Ügyfél")
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # 2. SOR: CÍM
                p.setFont(M_FONT, 9)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                # TEL és PÉNZ
                p.setFont(M_FONT, 8.5)
                p.drawString(x+8, y+ch-46, f"Tel: {item['tel']}" if item['tel'] else "")
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 11)
                    p.drawRightString(x+cw-10, y+ch-46, item['penz'])

                # RENDELÉS
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+30, f"Összesen: {len(p_list)+len(z_list)} tétel")
                
                p.setFont(B_FONT, 11)
                if p_list: p.drawString(x+8, 20, f"P: {', '.join(p_list)}"[:40])
                if z_list: p.drawString(x+8, 9 if p_list else 20, f"Sz: {', '.join(z_list)}"[:40])

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
                p.drawCentredString(x+cw/2, y+ch-40, "Új Ügyfeleink részére!")
                p.setFont(M_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch/2 - 2, "Rendelés leadás:")
                p.setFont(B_FONT, 10.5)
                p.drawCentredString(x+cw/2, y+ch/2 - 15, f"{input_nev}, tel: {input_tel}")
                p.setFont(M_FONT, 5.5)
                p.drawCentredString(x+cw/2, y+20, "* a kedvezmény telefonon leadott rendelésekre")
                p.drawCentredString(x+cw/2, y+14, "érvényesíthető területi képviselőnk által")

        p.save()
        st.download_button("📥 PDF LETÖLTÉSE (V5.6)", output.getvalue(), "interfood_v56.pdf")
