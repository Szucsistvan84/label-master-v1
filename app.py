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

st.set_page_config(page_title="Interfood Profi v5.3", layout="wide")
st.title("🚚 Interfood Etikett v5.3")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="+36201234567")

def extract_v53(pdf_file):
    reader = PdfReader(pdf_file)
    customers = []
    
    # PDF oldalak feldolgozása
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        
        # Tisztított sorok
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 0]
        
        current_cust = None
        
        for i, line in enumerate(lines):
            # 1. Ügyfélkód keresése (pl. P-428867)
            id_match = re.search(r'([HKSCPZ])-(\d{6})', line)
            if id_match:
                day, code = id_match.group(1), id_match.group(2)
                
                # Új ügyfél objektum
                current_cust = {
                    'kod': code, 'nev': '', 'cim': '', 
                    'P_rend': [], 'Z_rend': [], 
                    'tel': '', 'penz': '', 'kk': '', 'napok': {day}
                }
                customers.append(current_cust)
                
                # Név keresése a környező sorokban (az "Ügyintéző" oszlop miatt)
                # Megnézzük a következő 3 sort, hátha ott van a név
                for j in range(1, 4):
                    if i + j < len(lines):
                        candidate = lines[i+j]
                        # Ha a sorban van telefonszám, az valószínűleg a név utáni adat
                        t_match = re.search(r'(\d{2}/\d{7}|\d{10,11})', candidate)
                        if t_match and not current_cust['tel']:
                            current_cust['tel'] = t_match.group(1)
                        
                        # Ha a sorban van irányítószám, az a cím
                        if re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', candidate):
                            current_cust['cim'] = candidate
                        
                        # Ha nem cím, nem telefon és nem kód, akkor ez lesz a név (pl. Tőkés István)
                        if len(candidate) > 3 and not re.search(r'\d{4}', candidate) and \
                           not re.search(r'\d{2}/', candidate) and \
                           not any(x in candidate.lower() for x in ['rendelés', 'össz', 'kód']):
                            if not current_cust['nev']:
                                current_cust['nev'] = candidate

            # 2. Adatok gyűjtése a meglévő ügyfélhez
            if current_cust:
                # Pénz keresése
                m_match = re.search(r'(\d[\d\s]*\s?Ft)', line)
                if m_match: current_cust['penz'] = m_match.group(1)
                
                # Ételkódok (v5.1 logika alapján)
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
                if codes:
                    # Nap szerinti szétválogatás
                    if 'Z-' in line or ('Z' in current_cust['napok'] and 'P-' not in line):
                        current_cust['Z_rend'].extend(codes)
                    else:
                        current_cust['P_rend'].extend(codes)
                
                # Kapukód
                if any(x in line.lower() for x in ['kcs', 'kulcs', 'kapu']):
                    current_cust['kk'] = line

    return [c for c in customers if c['kod']]

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.3)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v53(uploaded_file)
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
                
                # Fejléc (Szombat esetén)
                if item['Z_rend'] or 'Z' in item['napok']:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    p.drawCentredString(x+cw/2, y+ch-9, "Péntek + Szombat!" if item['P_rend'] else "Szombat")
                
                p.setFillColorRGB(0, 0, 0)
                # 1. Sor: NÉV (bal) | KÓD (jobb)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:25] if item['nev'] else "Ügyfél")
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # 2. Sor: CÍM
                p.setFont(M_FONT, 9)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                # Tel és Pénz
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-46, f"Tel: {item['tel']}" if item['tel'] else "")
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 11)
                    p.drawRightString(x+cw-10, y+ch-46, item['penz'])

                # Rendelés
                p.setFont(B_FONT, 10)
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                
                p.drawString(x+8, y+30, f"Összesen: {len(p_list)+len(z_list)} tétel")
                
                if p_list: p.drawString(x+8, 20, f"P: {', '.join(p_list)}"[:40])
                if z_list: p.drawString(x+8, 10 if p_list else 20, f"Sz: {', '.join(z_list)}"[:40])

                # Lábléc
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+6, x+cw-10, y+6)
                p.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
                p.drawRightString(x+cw-10, y+4, "JÓ ÉTVÁGYAT!")
            else:
                # MARKETING (BETONOZVA)
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
        st.download_button("📥 PDF LETÖLTÉSE (V5.3)", output.getvalue(), "interfood_v53.pdf")
