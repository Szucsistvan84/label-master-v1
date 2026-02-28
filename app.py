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

st.set_page_config(page_title="Interfood Profi v5.9", layout="wide")
st.title("🚚 Interfood Etikett v5.9")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="+36208868971")

def extract_v59(pdf_file):
    reader = PdfReader(pdf_file)
    customers = []
    
    # Ételkód minta: szigorúan szám-betű/szám (pl: 1-L1K, 12-A1)
    # Kizárjuk a magányos számokat, hogy ne legyen "38 tétel" hiba
    food_code_pattern = r'\b\d{1,2}-[A-Z0-9]{1,4}\b'
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        
        # Ügyfélblokkok vágása (Sorszám + Kód azonosító)
        blocks = re.split(r'\n(?=\d{1,3}\n[PZSC]-)', text)
        
        for block in blocks:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if not lines: continue
            
            id_match = re.search(r'([PZSC])-(\d{6})', block)
            if not id_match: continue
            
            day, code = id_match.group(1), id_match.group(2)
            
            # Név: Az "Ügyintéző" oszlopból, ami a telefonszám sorában vagy felette van
            name = ""
            for line in lines:
                if re.match(r'^[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s[A-ZÁÉÍÓÖŐÚÜŰ]', line):
                    if not any(x in line for x in ["Debrecen", "Kft", "Interfood", "Sor", "Ügyfél"]):
                        name = line.split("  ")[0].strip() # Csak a sor eleji név
                        break
            
            # Cím
            cim_match = re.search(r'(\d{4}\s+Debrecen,.*)', block)
            cim = "Debrecen, " + cim_match.group(1).split("Debrecen,")[1].split("\n")[0].strip() if cim_match else ""
            
            # Pénz
            money_match = re.search(r'(\d[\d\s]*\s?Ft)', block)
            money = money_match.group(1) if money_match else "0 Ft"
            
            # RENDELÉSEK SZŰRÉSE
            # Csak azokat a kódokat gyűjtjük, amik a blokkban vannak, 
            # de NEM a sor eleji sorszámok vagy az összesen darabszámok
            raw_codes = re.findall(food_code_pattern, block)
            clean_codes = sorted(list(set(raw_codes)))
            
            customers.append({
                'kod': code, 'nev': name if name else "Ügyfél", 'cim': cim, 
                'rend': clean_codes, 'day': day, 'penz': money
            })

    # Péntek + Szombat összevonás
    merged = {}
    for c in customers:
        k = c['kod']
        if k not in merged:
            merged[k] = c
            merged[k]['P_rend'] = c['rend'] if c['day'] != 'Z' else []
            merged[k]['Z_rend'] = c['rend'] if c['day'] == 'Z' else []
            merged[k]['napok'] = {c['day']}
        else:
            merged[k]['napok'].add(c['day'])
            if c['day'] == 'Z': merged[k]['Z_rend'].extend(c['rend'])
            else: merged[k]['P_rend'].extend(c['rend'])
            
    return list(merged.values())

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.9)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v59(uploaded_file)
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
                
                # Fejléc (Z)
                if 'Z' in item['napok']:
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 9)
                    p.drawCentredString(x+cw/2, y+ch-9, "Péntek + Szombat!" if 'P' in item['napok'] else "Szombat")
                
                p.setFillColorRGB(0, 0, 0)
                # NÉV és KÓD
                p.setFont(B_FONT, 10.5)
                p.drawString(x+8, y+ch-25, item['nev'][:24])
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # CÍM
                p.setFont(M_FONT, 9)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                # PÉNZ
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 12)
                    p.drawRightString(x+cw-10, y+ch-48, item['penz'])

                # RENDELÉSEK (SZIGORÚ LISTA)
                p_list = sorted(list(set(item['P_rend'])))
                z_list = sorted(list(set(item['Z_rend'])))
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+32, f"Összesen: {len(p_list)+len(z_list)} tétel")
                
                p.setFont(B_FONT, 11)
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
                p.setFont(M_FONT, 9.5)
                p.drawCentredString(x+cw/2, y+ch/2 - 5, "Rendelés leadás:")
                p.setFont(B_FONT, 11)
                p.drawCentredString(x+cw/2, y+ch/2 - 18, f"{input_nev}, tel: {input_tel}")

        p.save()
        st.download_button("📥 PDF LETÖLTÉSE (V5.9)", output.getvalue(), "interfood_v59.pdf")
