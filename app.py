import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# 1. Betűtípusok (Roboto az ékezetekhez)
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v4.2", layout="wide")
st.title("🚚 Interfood Intelligens Etikett - v4.2")

# Sidebar
st.sidebar.header("Futár azonosítása")
input_nev = st.sidebar.text_input("Saját Név:", value="", placeholder="Pl: Kovács János")
input_tel = st.sidebar.text_input("Saját Tel:", value="", placeholder="Pl: +36201234567")

def extract_smart_data(pdf_file):
    reader = PdfReader(pdf_file)
    customers = {} 
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        last_id = None
        for line in lines:
            # H, K, S, C, P, Z felismerés
            match = re.search(r'([HKSCPZ])-(\d+)', line)
            
            if match:
                nap, szam = match.group(1), match.group(2)
                last_id = szam
                if last_id not in customers:
                    name_p = line.split(match.group(0))[-1].strip()
                    customers[last_id] = {'nev': name_p, 'cim': '', 'rend': [], 'kk': '', 'napok': {nap}}
                else:
                    customers[last_id]['napok'].add(nap)
                    name_p = line.split(match.group(0))[-1].strip()
                    if len(name_p) > len(customers[last_id]['nev']):
                        customers[last_id]['nev'] = name_p

            elif last_id:
                # Cím keresése (Irányítószám + Város marad!)
                if re.match(r'^\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', line, re.IGNORECASE):
                    customers[last_id]['cim'] = line
                # Csak a kapukódos megjegyzések megtartása
                elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs']):
                    # Csak akkor adjuk hozzá, ha még nincs benne (duplikáció szűrés)
                    if line not in customers[last_id]['kk']:
                        customers[last_id]['kk'] = (customers[last_id]['kk'] + " " + line).strip()
                # Ételkódok (1-A, 11-D2 stb.)
                elif re.search(r'\d-[A-Z0-9]', line):
                    codes = re.findall(r'\d-[A-Z0-9]+', line)
                    customers[last_id]['rend'].extend(codes)
    
    return [c for c in customers.values() if len(c['nev']) > 2]

uploaded_file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if uploaded_file:
    if not input_nev.strip() or not input_tel.strip():
        st.error("❌ Kérlek, add meg az adataidat a bal oldali sávban!")
        st.stop()
    
    results = extract_smart_data(uploaded_file)
    
    if results:
        st.success(f"✅ {len(results)} ügyfél feldolgozva (P/Z egyesítve).")
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        w, h = A4
        cw, ch = (w-20)/3, (h-40)/7

        for i in range(((len(results)-1)//21+1)*21):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            p.setStrokeColorRGB(0, 0, 0)
            p.setLineWidth(0.3)
            p.rect(x+2, y+2, cw-4, ch-4)
            p.setFillColorRGB(0, 0, 0)
            p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
            p.setFillColorRGB(1, 1, 1)
            p.setFont(B_FONT, 9)

            if i < len(results):
                item = results[i]
                n = item['napok']
                header = "Péntek + Szombat!" if ('P' in n and 'Z' in n) else \
                         ("Péntek" if 'P' in n else ("Szombat" if 'Z' in n else "INTERFOOD"))
                p.drawCentredString(x+cw/2, y+ch-9, header)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 9.5)
                p.drawString(x+8, y+ch-25, item['nev'][:30])
                p.setFont(M_FONT, 7.5)
                # Itt nem vágjuk le a várost, marad a teljes cím
                p.drawString(x+8, y+ch-35, item['cim'][:42])
                
                if item['kk']:
                    p.setFillColorRGB(0.8, 0, 0) # Piros a fontos belépési kódnak
                    p.setFont(B_FONT, 7.5)
                    p.drawString(x+8, y+ch-44, f"KÓD: {item['kk']}"[:45])
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 12)
                ételkódok = ", ".join(sorted(list(set(item['rend']))))
                p.drawString(x+8, y+20, f"Rend: {ételkódok if ételkódok else '---'}")
            else:
                # MARKETING MÓD (Változatlanul, ahogy kérted)
                p.drawCentredString(x+cw/2, y+ch-9, "INTERFOOD ÉTLAP")
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 11)
                p.drawCentredString(x+cw/2, y+ch-30, "RENDELJEN TŐLEM!")
                p.setFont(M_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch-45, "Házias ízek, pontos szállítás.")
                p.setFont(B_FONT, 8)
                p.drawCentredString(x+cw/2, y+25, "Keresse a futár telefonszámát:")

            # LÁBLÉC
            p.setFont(M_FONT, 7)
            p.setFillColorRGB(0, 0, 0)
            p.line(x+10, y+15, x+cw-10, y+15)
            p.drawString(x+8, y+8, f"{input_nev} | {input_tel}")
            p.drawRightString(x+cw-10, y+8, "JÓ ÉTVÁGYAT!")

        p.save()
        st.download_button("📥 PDF GENERÁLÁSA", output.getvalue(), "interfood_profi_v4.2.pdf")
