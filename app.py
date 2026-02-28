import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# 1. Betűtípusok betöltése
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v4.4", layout="wide")
st.title("🚚 Interfood Etikett & Marketing - Hivatalos Verzió")

# Sidebar adatok
st.sidebar.header("Futár azonosítása")
input_nev = st.sidebar.text_input("Saját Név:", value="", placeholder="Pl: Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", value="", placeholder="Pl: +36201234567")

def extract_all_data(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {} 
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        current_id = None
        for line in lines:
            # Nap és ügyfélkód keresése (H, K, S, C, P, Z)
            match = re.search(r'([HKSCPZ])-(\d+)', line)
            
            if match:
                nap, id_szam = match.group(1), match.group(2)
                current_id = id_szam
                if current_id not in customers:
                    # Név kinyerése a kód utáni részből
                    name_p = line.split(match.group(0))[-1].strip()
                    customers[current_id] = {'nev': name_p, 'cim': '', 'rend': [], 'kk': '', 'napok': {nap}}
                else:
                    customers[current_id]['napok'].add(nap)
            
            elif current_id:
                # Cím keresése (4 számjegy + Város)
                if re.match(r'^\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line, re.IGNORECASE):
                    customers[current_id]['cim'] = line
                # Kapukód és info (KK, kód, kulcs)
                elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs']):
                    if line not in customers[current_id]['kk']:
                        customers[current_id]['kk'] = (customers[current_id]['kk'] + " " + line).strip()
                # Ételkódok vadászata (Pl: 1-A, 12-Z2)
                elif re.search(r'\d-[A-Z0-9]+', line):
                    found = re.findall(r'\d-[A-Z0-9]+', line)
                    customers[current_id]['rend'].extend(found)

    return [c for c in customers.values() if len(c['nev']) > 2]

uploaded_file = st.file_uploader("Menetterv feltöltése", type="pdf")

if uploaded_file:
    if not input_nev.strip() or not input_tel.strip():
        st.error("❌ Add meg a Neved és a Számod a bal oldali sávban!")
        st.stop()
    
    data = extract_all_data(uploaded_file)
    if data:
        st.success(f"✅ {len(data)} ügyfél egyesítve. Generálás...")
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        cw, ch = (A4[0]-20)/3, (A4[1]-40)/7

        for i in range(((len(data)-1)//21+1)*21):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            p.setStrokeColorRGB(0, 0, 0)
            p.rect(x+2, y+2, cw-4, ch-4)
            p.setFillColorRGB(0, 0, 0)
            p.rect(x+2, y+ch-12, cw-4, 10, fill=1) # Fekete fejléc
            p.setFillColorRGB(1, 1, 1)
            p.setFont(B_FONT, 9)

            if i < len(data):
                # --- ÜGYFÉL CÍMKE ---
                item = data[i]
                n = item['napok']
                header = "Péntek + Szombat!" if ('P' in n and 'Z' in n) else \
                         ("Péntek" if 'P' in n else ("Szombat" if 'Z' in n else "INTERFOOD"))
                p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, item['nev'][:30])
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-35, item['cim'][:42])
                
                if item['kk']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    p.drawString(x+8, y+ch-45, f"KÓD: {item['kk']}"[:45])
                
                # RENDELÉSI ÖSSZESÍTŐ ÉS ÉTELKÓDOK
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                unique_rend = sorted(list(set(item['rend'])))
                p.drawString(x+8, y+28, f"Összesen: {len(unique_rend)} tétel")
                p.setFont(B_FONT, 12)
                p.drawString(x+8, y+16, f"Rend: {', '.join(unique_rend)[:22]}")
            else:
                # --- MARKETING CÍMKE (PONTOSAN A MINTA SZERINT) ---
                p.drawCentredString(x+cw/2, y+ch-9, "INTERFOOD ÉTLAP")
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 16)
                p.drawCentredString(x+cw/2, y+ch/2 + 8, "RENDELJEN")
                p.drawCentredString(x+cw/2, y+ch/2 - 12, "TŐLEM!")

            # LÁBLÉC (MINDIG OTT VAN)
            p.setFont(M_FONT, 7.5)
            p.setFillColorRGB(0, 0, 0)
            p.line(x+10, y+14, x+cw-10, y+14)
            p.drawString(x+8, y+6, f"{input_nev} | {input_tel}")
            p.drawRightString(x+cw-10, y+6, "JÓ ÉTVÁGYAT!")

        p.save()
        st.download_button("📥 PDF LETÖLTÉSE", output.getvalue(), "interfood_final_labels.pdf")
