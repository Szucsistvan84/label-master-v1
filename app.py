import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Alapértelmezett betűtípus kezelése
def get_fonts():
    try:
        pdfmetrics.registerFont(TTFont('Roboto-Bold', 'Roboto-Bold.ttf'))
        return "Roboto-Bold"
    except:
        return "Helvetica-Bold"

B_FONT = get_fonts()

st.set_page_config(page_title="Interfood v7.0", layout="wide")
st.title("🚚 Interfood Etikett v7.0")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_pdf_v7(uploaded_file):
    try:
        reader = PdfReader(uploaded_file)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
        
        # Ügyfélkódok kigyűjtése (P-XXXXXX vagy Z-XXXXXX)
        pattern = r'([PZSC])-(\d{6})'
        matches = list(re.finditer(pattern, full_text))
        
        if not matches:
            st.error("Nem találtam ügyfélkódokat a PDF-ben! Biztos jó fájlt töltöttél fel?")
            return []

        st.success(f"Találtam {len(matches)} tételt. Feldolgozás...")
        
        results = {}
        for i, match in enumerate(matches):
            day_type = match.group(1)
            code = match.group(2)
            
            # Szövegblokk az aktuális és a következő kód között
            start = match.start()
            end = matches[i+1].start() if i+1 < len(matches) else len(full_text)
            block = full_text[start:end]
            
            if code not in results:
                # Név keresése: a kód utáni első pár szó, ami nem irányítószám
                name_part = block.split(code)[-1].split('\n')[0].strip()
                if "40" in name_part: name_part = name_part.split("40")[0].strip()
                
                # Cím keresése
                cim = ""
                cim_match = re.search(r'(40\d{2}\s+Debrecen[^\n]+)', block)
                if cim_match: cim = cim_match.group(1)

                results[code] = {
                    'kod': code, 'nev': name_part if name_part else "Ügyfél",
                    'cim': cim, 'P_rend': [], 'Z_rend': [], 'is_z': False
                }
            
            # Ételkódok (pl. 1-DK)
            food_codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', block)
            if day_type == 'Z':
                results[code]['Z_rend'].extend(food_codes)
                results[code]['is_z'] = True
            else:
                results[code]['P_rend'].extend(food_codes)

        return list(results.values())
    except Exception as e:
        st.error(f"Hiba történt: {e}")
        return []

file = st.file_uploader("Válaszd ki a menetterv PDF-et", type="pdf")

if file:
    data = process_pdf_v7(file)
    if data:
        out = io.BytesIO()
        c = canvas.Canvas(out, pagesize=A4)
        w, h = (A4[0]-20)/3, (A4[1]-40)/7

        # 21 hely van egy lapon, töltsük fel marketinggel a maradékot
        total_slots = ((len(data)-1)//21 + 1) * 21
        
        for i in range(total_slots):
            if i > 0 and i % 21 == 0: c.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * w, 20 + row * h
            
            c.setStrokeColorRGB(0.7, 0.7, 0.7)
            c.rect(x+2, y+2, w-4, h-4)
            c.setFillColorRGB(0, 0, 0)

            if i < len(data):
                u = data[i]
                # Szombat jelzés
                if u['is_z']:
                    c.setFillColorRGB(0, 0, 0)
                    c.rect(x+2, y+h-12, w-4, 10, fill=1)
                    c.setFillColorRGB(1, 1, 1)
                    c.setFont(B_FONT, 8)
                    c.drawCentredString(x+w/2, y+h-9, "PÉNTEK + SZOMBAT" if u['P_rend'] else "SZOMBAT")
                
                c.setFillColorRGB(0, 0, 0)
                c.setFont(B_FONT, 10)
                c.drawString(x+8, y+h-25, u['nev'][:22])
                c.drawRightString(x+w-10, y+h-25, u['kod'])
                
                c.setFont(B_FONT, 8)
                c.drawString(x+8, y+h-35, u['cim'][:35])
                
                # Ételek
                c.setFont(B_FONT, 10)
                if u['P_rend']: c.drawString(x+8, y+20, f"P: {', '.join(set(u['P_rend']))}"[:35])
                if u['Z_rend']: c.drawString(x+8, y+10, f"Sz: {', '.join(set(u['Z_rend']))}"[:35])
            else:
                # MARKETING
                c.setFont(B_FONT, 12)
                c.drawCentredString(x+w/2, y+h-25, "15% KEDVEZMÉNY")
                c.setFont(B_FONT, 8)
                c.drawCentredString(x+w/2, y+h-40, "Új ügyfeleknek 3 hétig!")
                c.drawCentredString(x+w/2, y+25, "Rendelés leadás:")
                c.setFont(B_FONT, 10)
                c.drawCentredString(x+w/2, y+10, f"{input_nev} {input_tel}")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V7.0)", out.getvalue(), "interfood_v7.pdf")
