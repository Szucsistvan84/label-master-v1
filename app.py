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

st.set_page_config(page_title="Interfood Profi v5.4", layout="wide")
st.title("🚚 Interfood Etikett v5.4")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="+36201234567")

def extract_v54(pdf_file):
    reader = PdfReader(pdf_file)
    raw_data = []
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        # Egyben kezeljük az oldalt, hogy az oszlopok ne zavarjanak be
        blocks = re.split(r'(\d{1,3}\n[PZSC]-\d{6})', text)
        
        for i in range(1, len(blocks), 2):
            header = blocks[i]
            content = blocks[i+1] if i+1 < len(blocks) else ""
            full_block = header + content
            
            # Ügyfélkód és Nap
            id_match = re.search(r'([PZSC])-(\d{6})', header)
            if id_match:
                day, code = id_match.group(1), id_match.group(2)
                
                # Név keresése (Az Ügyintéző oszlopból, ami a cím után jön a PDF-ben)
                # Olyan szavakat keresünk, amik nagybetűvel kezdődnek és nem címek
                name_search = re.findall(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)?)', content)
                name = ""
                for n in name_search:
                    if "Debrecen" not in n and "Kft" not in n:
                        name = n
                        break
                
                # Cím
                cim_match = re.search(r'(\d{4}\s+Debrecen,.*)', full_block)
                cim = cim_match.group(1).split('\n')[0] if cim_match else ""
                
                # Telefon
                tel_match = re.search(r'(\d{2}/\d{7}|\d{10,11})', full_block)
                tel = tel_match.group(1) if tel_match else ""
                
                # Pénz
                money_match = re.search(r'(\d[\d\s]*\s?Ft)', full_block)
                money = money_match.group(1) if money_match else "0 Ft"

                # Rendelés kódok
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', full_block)
                
                raw_data.append({
                    'kod': code, 'nev': name, 'cim': cim, 
                    'codes': sorted(list(set(codes))), 
                    'day': day, 'tel': tel, 'penz': money
                })
    
    # Csoportosítás (Péntek + Szombat összevonása)
    final_customers = {}
    for item in raw_data:
        k = item['kod']
        if k not in final_customers:
            final_customers[k] = {
                'kod': k, 'nev': item['nev'], 'cim': item['cim'],
                'P': [], 'Z': [], 'tel': item['tel'], 'penz': item['penz'], 'napok': {item['day']}
            }
        
        if item['day'] == 'Z':
            final_customers[k]['Z'].extend(item['codes'])
            final_customers[k]['napok'].add('Z')
        else:
            final_customers[k]['P'].extend(item['codes'])
            final_customers[k]['napok'].add(item['day'])
            
    return list(final_customers.values())

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.4)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v54(uploaded_file)
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
                
                # FEJLÉC (P+Sz vagy Sz)
                if 'Z' in item['napok']:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    p.drawCentredString(x+cw/2, y+ch-9, "Péntek + Szombat!" if 'P' in item['napok'] or 'S' in item['napok'] else "Szombat")
                
                p.setFillColorRGB(0, 0, 0)
                # 1. SOR: NÉV (bal) | KÓD (jobb)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:25] if item['nev'] else "Ügyfél")
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # 2. SOR: CÍM
                p.setFont(M_FONT, 8.5)
                p.drawString(x+8, y+ch-36, item['cim'][:45])
                
                # TEL és PÉNZ
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-46, f"Tel: {item['tel']}" if item['tel'] else "")
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 11)
                    p.drawRightString(x+cw-10, y+ch-46, item['penz'])

                # RENDELÉS
                p.setFont(B_FONT, 9)
                total = len(item['P']) + len(item['Z'])
                p.drawString(x+8, y+30, f"Összesen: {total} tétel")
                
                p.setFont(B_FONT, 10)
                if item['P']: p.drawString(x+8, 20, f"P: {', '.join(sorted(list(set(item['P']))))}"[:40])
                if item['Z']: p.drawString(x+8, 10 if item['P'] else 20, f"Sz: {', '.join(sorted(list(set(item['Z']))))}"[:40])

                # LÁBLÉC (Saját)
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+6, x+cw-10, y+6)
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
        st.download_button("📥 PDF LETÖLTÉSE (V5.4)", output.getvalue(), "interfood_v54.pdf")
