import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Betűtípusok betöltése
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v5.8", layout="wide")
st.title("🚚 Interfood Etikett v5.8")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="+36208868971")

def extract_v58(pdf_file):
    reader = PdfReader(pdf_file)
    customers = []
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        
        # Sorszám + Kód alapú blokkolás (pl. "1\n P-428867")
        # Ez a legstabilabb pont a menettervben
        blocks = re.split(r'\n(?=\d{1,3}\n[PZSC]-)', text)
        
        for block in blocks:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if not lines: continue
            
            # Ügyfélkód keresése
            id_match = re.search(r'([PZSC])-(\d{6})', block)
            if not id_match: continue
            
            day, code = id_match.group(1), id_match.group(2)
            
            # ADATOK KINYERÉSE A BLOKKBÓL
            # Név: Az "Ügyintéző" oszlop tartalma (általában a 3. vagy 4. sor a blokkban)
            name = ""
            for line in lines:
                if re.match(r'^[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s[A-ZÁÉÍÓÖŐÚÜŰ]', line):
                    if "Debrecen" not in line and "Interfood" not in line and "Kft" not in line:
                        name = line
                        break
            
            # Cím: 4 számjegy + Város
            cim_match = re.search(r'(\d{4}\s+Debrecen,.*)', block)
            cim = cim_match.group(1).split(',')[0] + "," + cim_match.group(1).split(',')[1].split(' ')[1] if cim_match and ',' in cim_match.group(1) else (cim_match.group(1) if cim_match else "")
            
            # Pénz
            money_match = re.search(r'(\d[\d\s]*\s?Ft)', block)
            money = money_match.group(1) if money_match else "0 Ft"
            
            # Rendelés (Csak az adott blokkban lévő ételkódok!)
            codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', block)
            
            customers.append({
                'kod': code, 'nev': name if name else "Ügyfél", 'cim': cim, 
                'rend': sorted(list(set(codes))), 'day': day, 'penz': money
            })

    # Összevonás (P+Sz napok)
    final = {}
    for c in customers:
        k = c['kod']
        if k not in final:
            final[k] = c
            final[k]['P_rend'] = c['rend'] if c['day'] != 'Z' else []
            final[k]['Z_rend'] = c['rend'] if c['day'] == 'Z' else []
            final[k]['napok'] = {c['day']}
        else:
            final[k]['napok'].add(c['day'])
            if c['day'] == 'Z': final[k]['Z_rend'].extend(c['rend'])
            else: final[k]['P_rend'].extend(c['rend'])
            
    return list(final.values())

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.8)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v58(uploaded_file)
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
                # Fejléc (Szombat jelzés)
                if 'Z' in item['napok']:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    p.drawCentredString(x+cw/2, y+ch-9, "Péntek + Szombat!" if 'P' in item['napok'] else "Szombat")
                
                p.setFillColorRGB(0, 0, 0)
                # 1. sor: NÉV és KÓD
                p.setFont(B_FONT, 10.5)
                p.drawString(x+8, y+ch-25, item['nev'][:25])
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # 2. sor: CÍM
                p.setFont(M_FONT, 9)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                # PÉNZ (Kiemelve)
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 12)
                    p.drawRightString(x+cw-10, y+ch-48, item['penz'])

                # RENDELÉS
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+32, f"Összesen: {len(p_list)+len(z_list)} tétel")
                
                p.setFont(B_FONT, 10)
                if p_list: p.drawString(x+8, 22, f"P: {', '.join(p_list)}"[:40])
                if z_list: p.drawString(x+8, 12 if p_list else 22, f"Sz: {', '.join(z_list)}"[:40])

                # Lábléc
                p.setFont(M_FONT, 7.5)
                p.line(x+10, y+6, x+cw-10, y+6)
                p.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
                p.drawRightString(x+cw-10, y+4, "JÓ ÉTVÁGYAT!")
            else:
                # MARKETING
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 13)
                p.drawCentredString(x+cw/2, y+ch-25, "15% kedvezmény* 3 hétig")
                p.setFont(M_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch/2 - 2, "Rendelés leadás:")
                p.setFont(B_FONT, 10.5)
                p.drawCentredString(x+cw/2, y+ch/2 - 15, f"{input_nev}, tel: {input_tel}")

        p.save()
        st.download_button("📥 PDF LETÖLTÉSE (V5.8)", output.getvalue(), "interfood_v58.pdf")
