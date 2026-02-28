import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Betűtípusok beállítása
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v5.5", layout="wide")
st.title("🚚 Interfood Etikett v5.5")

input_nev = st.sidebar.text_input("Saját Név:", placeholder="Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", placeholder="+36201234567")

def extract_v55(pdf_file):
    reader = PdfReader(pdf_file)
    customers = []
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        
        # A PDF-et sorokra bontjuk, de figyelünk a táblázatos szerkezetre
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            # 1. Horgony: Ügyfélkód keresése (P-428867 formátum)
            id_match = re.search(r'([PZSC])-(\d{6})', line)
            if id_match:
                day, code = id_match.group(1), id_match.group(2)
                
                # Keressük az adatokat a környező sorokban
                # A táblázatban a Név az "Ügyintéző" oszlopban van (általában ugyanaz a sor vagy +1)
                name = ""
                cim = ""
                tel = ""
                penz = "0 Ft"
                rendelesek = []
                
                # Keresési ablak az adatokhoz
                search_window = lines[max(0, i-1):min(len(lines), i+5)]
                full_context = " ".join(search_window)
                
                # Név: A kód utáni rész, vagy a következő sor eleje, ami nem cím
                # A feltöltött PDF alapján a "Tőkés István" típusú neveket keressük
                names = re.findall(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)?)', full_context)
                for n in names:
                    if "Debrecen" not in n and "Kft" not in n and "Interfood" not in n:
                        name = n
                        break
                
                # Cím: 4 számjegy + Debrecen
                cim_m = re.search(r'(\d{4}\s+Debrecen,.*)', full_context)
                if cim_m: cim = cim_m.group(1).split(',')[0] + "," + cim_m.group(1).split(',')[1].split(' ')[1] if ',' in cim_m.group(1) else cim_m.group(1)

                # Telefon: 06... vagy 20/...
                tel_m = re.search(r'(\d{2}/\d{7}|\d{10,11})', full_context)
                if tel_m: tel = tel_m.group(1)

                # Pénz: Ft-tal a végén
                money_m = re.search(r'(\d[\d\s]*\s?Ft)', full_context)
                if money_m: penz = money_m.group(1)

                # Ételkódok: csak a szám-betűk (pl. 1-L1K)
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', full_context)
                rendelesek = sorted(list(set(codes)))

                customers.append({
                    'kod': code, 'nev': name, 'cim': cim, 
                    'rend': rendelesek, 'day': day, 'tel': tel, 'penz': penz
                })
    
    # Duplikátumok szűrése és napok összevonása
    merged = {}
    for c in customers:
        k = c['kod']
        if k not in merged:
            merged[k] = c
            merged[k]['napok'] = {c['day']}
            merged[k]['P_rend'] = c['rend'] if c['day'] != 'Z' else []
            merged[k]['Z_rend'] = c['rend'] if c['day'] == 'Z' else []
        else:
            merged[k]['napok'].add(c['day'])
            if c['day'] == 'Z': merged[k]['Z_rend'].extend(c['rend'])
            else: merged[k]['P_rend'].extend(c['rend'])
            
    return list(merged.values())

uploaded_file = st.file_uploader("Menetterv feltöltése (v5.5)", type="pdf")

if uploaded_file and input_nev and input_tel:
    data = extract_v55(uploaded_file)
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
                # NÉV és KÓD (Szigorúan bal-jobb)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:25] if item['nev'] else "Ügyfél")
                p.drawRightString(x+cw-10, y+ch-25, item['kod'])
                
                # CÍM (Külön sorban)
                p.setFont(M_FONT, 9)
                p.drawString(x+8, y+ch-36, item['cim'][:42])
                
                # TEL és PÉNZ
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-46, f"Tel: {item['tel']}" if item['tel'] else "")
                if item['penz'] and item['penz'] != "0 Ft":
                    p.setFont(B_FONT, 11)
                    p.drawRightString(x+cw-10, y+ch-46, item['penz'])

                # RENDELÉS
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
        st.download_button("📥 PDF LETÖLTÉSE (V5.5)", output.getvalue(), "interfood_v55.pdf")
