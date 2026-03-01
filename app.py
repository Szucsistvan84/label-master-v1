import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

def get_fonts():
    try:
        pdfmetrics.registerFont(TTFont('Roboto-Bold', 'Roboto-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('Roboto-Regular', 'Roboto-Regular.ttf'))
        return "Roboto-Regular", "Roboto-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

M_FONT, B_FONT = get_fonts()

st.set_page_config(page_title="Interfood v7.1", layout="wide")
st.title("🚚 Interfood Etikett v7.1 - Sorszámozva")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_pdf_v71(uploaded_file):
    try:
        reader = PdfReader(uploaded_file)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
        
        # Ügyfélblokkok azonosítása (Sorszám + Kód páros keresése)
        # Minta: "1\n P-428867"
        pattern = r'(\d{1,3})\n([PZSC])-(\d{6})'
        matches = list(re.finditer(pattern, full_text))
        
        if not matches:
            st.error("Nem találtam megfelelő sorszám-kód párost!")
            return []

        results = {}
        for i, match in enumerate(matches):
            sor_szam = match.group(1)
            day_type = match.group(2)
            code = match.group(3)
            
            start = match.start()
            end = matches[i+1].start() if i+1 < len(matches) else len(full_text)
            block = full_text[start:end]
            
            if code not in results:
                # Név kinyerése
                name_part = block.split(code)[-1].split('\n')[0].strip()
                if "40" in name_part: name_part = name_part.split("40")[0].strip()
                
                # Cím kinyerése
                cim = ""
                cim_match = re.search(r'(40\d{2}\s+Debrecen[^\n]+)', block)
                if cim_match: cim = cim_match.group(1)

                results[code] = {
                    'kod': code, 'sorszamok': [sor_szam], 'nev': name_part if name_part else "Ügyfél",
                    'cim': cim, 'P_rend': [], 'Z_rend': [], 'is_z': False
                }
            else:
                # Ha már létezik a kód, csak a sorszámot adjuk hozzá (pl. Péntek mellé a Szombatét)
                if sor_szam not in results[code]['sorszamok']:
                    results[code]['sorszamok'].append(sor_szam)
            
            # Ételkódok
            food_codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', block)
            if day_type == 'Z':
                results[code]['Z_rend'].extend(food_codes)
                results[code]['is_z'] = True
            else:
                results[code]['P_rend'].extend(food_codes)

        return list(results.values())
    except Exception as e:
        st.error(f"Hiba: {e}")
        return []

file = st.file_uploader("Feltöltés", type="pdf")

if file:
    data = process_pdf_v71(file)
    if data:
        out = io.BytesIO()
        c = canvas.Canvas(out, pagesize=A4)
        w, h = (A4[0]-20)/3, (A4[1]-40)/7
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
                # Sorszám(ok) megjelenítése
                sorszam_str = " + ".join(u['sorszamok']) + "."
                c.setFont(B_FONT, 9)
                c.drawString(x+8, y+h-15, sorszam_str)

                # Név és Kód
                c.setFont(B_FONT, 10.5)
                c.drawString(x+8, y+h-27, u['nev'][:22])
                c.drawRightString(x+w-10, y+h-27, u['kod'])
                
                # Cím
                c.setFont(M_FONT, 8.5)
                c.drawString(x+8, y+h-38, u['cim'][:38])
                
                # Ételek és Napok
                c.setFont(B_FONT, 10)
                p_set = sorted(list(set(u['P_rend'])))
                z_set = sorted(list(set(u['Z_rend'])))
                if p_set: c.drawString(x+8, y+22, f"P: {', '.join(p_set)}"[:35])
                if z_set: c.drawString(x+8, y+10, f"Sz: {', '.join(z_set)}"[:35])

                # Fix marketing lábléc a tétel alatt
                c.setFont(M_FONT, 7)
                c.line(x+10, y+6, x+w-10, y+6)
                c.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
            else:
                # MARKETING CÍMKE
                c.setFont(B_FONT, 12)
                c.drawCentredString(x+w/2, y+h-30, "15% KEDVEZMÉNY")
                c.setFont(M_FONT, 8)
                c.drawCentredString(x+w/2, y+h-45, "Új ügyfeleknek 3 hétig!")
                c.drawCentredString(x+w/2, y+25, "Rendelés leadás:")
                c.setFont(B_FONT, 10)
                c.drawCentredString(x+w/2, y+12, f"{input_nev}")
                c.drawCentredString(x+w/2, y+4, f"{input_tel}")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V7.1)", out.getvalue(), "interfood_sorszamozott.pdf")
