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

st.set_page_config(page_title="Interfood Profi v4.6", layout="wide")
st.title("🚚 Interfood Etikett & Kedvezményes Marketing")

# Sidebar
st.sidebar.header("Futár azonosítása")
input_nev = st.sidebar.text_input("Saját Név:", value="", placeholder="Pl: Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", value="", placeholder="Pl: +36201234567")

def extract_all_info(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {} 
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        last_id = None
        for line in lines:
            # Nap és kód (H, K, S, C, P, Z)
            match = re.search(r'([HKSCPZ])-(\d+)', line)
            if match:
                nap, szid = match.group(1), match.group(2)
                last_id = szid
                if last_id not in customers:
                    name_p = line.split(match.group(0))[-1].strip()
                    customers[last_id] = {'nev': name_p, 'cim': '', 'rend': [], 'kk': '', 'napok': {nap}}
                else:
                    customers[last_id]['napok'].add(nap)
            
            elif last_id:
                # Cím (Irányítószám + Település)
                if re.match(r'^\d{4}\s+', line):
                    customers[last_id]['cim'] = line
                # Ételkódok (pl. 1-A, 11-B2) - Megerősített keresés
                if re.search(r'\b\d{1,2}-[A-Z0-9]{1,3}\b', line):
                    found = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,3}\b', line)
                    customers[last_id]['rend'].extend(found)
                # Kapukód
                elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'kcs', 'kulcs']):
                    if line not in customers[last_id]['kk']:
                        customers[last_id]['kk'] = (customers[last_id]['kk'] + " " + line).strip()
    
    return [c for c in customers.values() if len(c['nev']) > 1]

uploaded_file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if uploaded_file:
    if not input_nev.strip() or not input_tel.strip():
        st.error("❌ Kérlek, add meg a neved és telefonszámod a bal oldalon!")
        st.stop()
    
    results = extract_all_info(uploaded_file)
    if results:
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        cw, ch = (A4[0]-20)/3, (A4[1]-40)/7

        for i in range(((len(results)-1)//21+1)*21):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            p.setStrokeColorRGB(0, 0, 0)
            p.rect(x+2, y+2, cw-4, ch-4)

            if i < len(results):
                # --- ÜGYFÉL CÍMKE ---
                p.setFillColorRGB(0, 0, 0)
                p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                p.setFillColorRGB(1, 1, 1)
                p.setFont(B_FONT, 9)
                
                item = results[i]
                n = item['napok']
                header = "Péntek + Szombat!" if ('P' in n and 'Z' in n) else ("Péntek" if 'P' in n else ("Szombat" if 'Z' in n else "INTERFOOD"))
                p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:32]) # NÉV külön sor
                p.setFont(M_FONT, 8.5)
                p.drawString(x+8, y+ch-38, item['cim'][:42]) # CÍM külön sor
                
                if item['kk']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    p.drawString(x+8, y+ch-48, f"KÓD: {item['kk']}"[:45])
                
                p.setFillColorRGB(0, 0, 0)
                unique_rend = sorted(list(set(item['rend'])))
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+28, f"Összesen: {len(unique_rend)} tétel")
                p.setFont(B_FONT, 12)
                p.drawString(x+8, y+16, f"Rend: {', '.join(unique_rend)}")
            else:
                # --- MARKETING CÍMKE (PONTOSAN A KÉRT SZÖVEGGEL) ---
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 13)
                p.drawCentredString(x+cw/2, y+ch-25, "15% kedvezmény* 3 hétig")
                p.setFont(B_FONT, 11)
                p.drawCentredString(x+cw/2, y+ch-40, "Új Ügyfeleink részére!")
                
                p.setFont(M_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch/2 - 5, "Rendelés leadás:")
                p.setFont(B_FONT, 10)
                p.drawCentredString(x+cw/2, y+ch/2 - 18, f"{input_nev}, tel: {input_tel}")
                
                # Apróbetűs rész
                p.setFont(M_FONT, 5.5)
                p.drawCentredString(x+cw/2, y+22, "* a kedvezmény telefonon leadott rendelésekre")
                p.drawCentredString(x+cw/2, y+16, "érvényesíthető területi képviselőnk által")

            # LÁBLÉC (JÓ ÉTVÁGYAT)
            p.setFont(M_FONT, 7.5)
            p.setFillColorRGB(0, 0, 0)
            p.line(x+10, y+13, x+cw-10, y+13)
            p.drawString(x+8, y+5, f"{input_nev} | {input_tel}")
            p.drawRightString(x+cw-10, y+5, "JÓ ÉTVÁGYAT!")

        p.save()
        st.download_button("📥 KÉSZ PDF LETÖLTÉSE", output.getvalue(), "interfood_profi_marketing.pdf")
