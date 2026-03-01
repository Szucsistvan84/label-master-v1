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

st.set_page_config(page_title="Interfood v7.2", layout="wide")
st.title("🚚 Interfood Etikett v7.2 - Precíz Adatok")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_v72(uploaded_file):
    reader = PdfReader(uploaded_file)
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"
    
    # Blokkokra bontás az ügyfélkódok alapján (P-XXXXXX vagy Z-XXXXXX)
    blocks = re.split(r'\n(?=\d{1,3}\n[PZSC]-)', full_text)
    
    customers = {}
    
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3: continue
        
        # Sorszám és Kód kinyerése
        # A blokk elején: sorszám (1-3 számjegy), majd kód (P/Z-6 számjegy)
        sorszam_match = re.search(r'^(\d{1,3})', block)
        kod_match = re.search(r'([PZSC])-(\d{6})', block)
        
        if not kod_match: continue
        
        sorszam = sorszam_match.group(1) if sorszam_match else "?"
        day_type = kod_match.group(1)
        cust_id = kod_match.group(2)
        
        if cust_id not in customers:
            # NÉV KERESÉSE: A blokkban keressük a nevet (pl. Tőkés István)
            # Kizárjuk a Debrecent és a cégneveket a tiszta névhez
            name = "Ügyfél"
            # A név általában a kód után vagy az "Ügyintéző" oszlopban van (ami a blokk közepe felé található)
            potential_names = re.findall(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)?)', block)
            for n in potential_names:
                if not any(x in n for x in ["Debrecen", "Interfood", "Kft", "Házgyár", "Határ", "porta"]):
                    name = n
                    break
            
            # CÍM KERESÉSE
            cim = ""
            cim_m = re.search(r'(40\d{2}\s+Debrecen[^\n,]+(?:,[^\n]+)?)', block)
            if cim_m: cim = cim_m.group(1).strip()

            customers[cust_id] = {
                'kod': cust_id, 'sorszamok': [sorszam], 'nev': name,
                'cim': cim, 'P_rend': [], 'Z_rend': [], 'is_z': False
            }
        else:
            if sorszam not in customers[cust_id]['sorszamok']:
                customers[cust_id]['sorszamok'].append(sorszam)
        
        # ÉTELKÓDOK
        food_codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', block)
        if day_type == 'Z':
            customers[cust_id]['Z_rend'].extend(food_codes)
            customers[cust_id]['is_z'] = True
        else:
            customers[cust_id]['P_rend'].extend(food_codes)

    return list(customers.values())

file = st.file_uploader("Feltöltés", type="pdf")

if file:
    data = process_v72(file)
    if data:
        out = io.BytesIO()
        c = canvas.Canvas(out, pagesize=A4)
        w, h = (A4[0]-20)/3, (A4[1]-40)/7
        
        for i in range(((len(data)-1)//21 + 1) * 21):
            if i > 0 and i % 21 == 0: c.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * w, 20 + row * h
            c.setStrokeColorRGB(0.7, 0.7, 0.7)
            c.rect(x+2, y+2, w-4, h-4)

            if i < len(data):
                u = data[i]
                c.setFillColorRGB(0, 0, 0)
                # 1. sor: Sorszám(ok)
                c.setFont(B_FONT, 9)
                s_str = " + ".join(sorted(u['sorszamok'], key=int)) + "."
                c.drawString(x+8, y+h-15, s_str)

                # 2. sor: Név és Ügyfélkód
                c.setFont(B_FONT, 11)
                c.drawString(x+8, y+h-28, u['nev'][:20])
                c.drawRightString(x+w-10, y+h-28, u['kod'])
                
                # 3. sor: Cím
                c.setFont(M_FONT, 8.5)
                c.drawString(x+8, y+h-40, u['cim'][:38])
                
                # Ételek
                c.setFont(B_FONT, 10)
                p_set = sorted(list(set(u['P_rend'])))
                z_set = sorted(list(set(u['Z_rend'])))
                if p_set: c.drawString(x+8, y+22, f"P: {', '.join(p_set)}"[:35])
                if z_set: c.drawString(x+8, y+10, f"Sz: {', '.join(z_set)}"[:35])

                # Fix lábléc
                c.setFont(M_FONT, 7.5)
                c.line(x+10, y+6, x+w-10, y+6)
                c.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
            else:
                # Marketing
                c.setFillColorRGB(0, 0, 0)
                c.setFont(B_FONT, 12)
                c.drawCentredString(x+w/2, y+h-30, "15% KEDVEZMÉNY")
                c.setFont(M_FONT, 8.5)
                c.drawCentredString(x+w/2, y+h-45, "Új ügyfeleknek 3 hétig!")
                c.setFont(B_FONT, 10)
                c.drawCentredString(x+w/2, y+15, f"{input_nev}")
                c.drawCentredString(x+w/2, y+5, f"{input_tel}")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V7.2)", out.getvalue(), "interfood_v72.pdf")
