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

st.set_page_config(page_title="Interfood Etikett", layout="wide")
st.title("🚚 Interfood Menetterv Generátor v2.3")

# Sidebar
st.sidebar.header("Beállítások")
f_nev = st.sidebar.text_input("Név:", value="", placeholder="Ebéd Elek")
f_tel = st.sidebar.text_input("Tel:", value="", placeholder="+36207654321")

def extract_data(pdf_file):
    reader = PdfReader(pdf_file)
    data = []
    
    # Kezdő állapot
    curr = {'id': '?', 'nev': '', 'cim': '', 'rend': [], 'info': ''}
    
    for page in reader.pages:
        lines = page.extract_text().split('\n')
        
        for line in lines:
            line = line.strip()
            if len(line) < 2 or "Nyomtatta" in line or "Oldal" in line: continue
            
            # Új blokk kezdődik, ha látunk egy ügyfélkódot (P- vagy Z-)
            kod_match = re.search(r'([PZ]-\d+)', line)
            
            if kod_match:
                # Ha már van valami az előzőben, mentsük el
                if curr['nev'] or curr['cim']:
                    data.append(curr.copy())
                
                # Sorszám kinyerése a sor elejéről, ha van
                id_m = re.match(r'^(\d+)', line)
                new_id = id_m.group(1) if id_m else curr['id']
                
                # Név kinyerése a kód utáni részből
                name_part = line.split(kod_match.group(1))[-1].strip()
                
                curr = {'id': new_id, 'nev': name_part, 'cim': '', 'rend': [], 'info': ''}
            
            elif "Debrecen" in line:
                curr['cim'] = line
            elif re.search(r'\d-[A-Z0-9]', line):
                curr['rend'].extend(re.findall(r'\d-[A-Z0-9]+', line))
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs', 'porta']):
                curr['info'] = (curr['info'] + " " + line).strip()
            elif len(line) > 5 and not curr['cim']:
                # Ez valószínűleg a név folytatása
                curr['nev'] = (curr['nev'] + " " + line).strip()

    if curr['nev'] or curr['cim']: data.append(curr)
    return data

uploaded_file = st.file_uploader("Töltsd fel a PDF-et", type="pdf")

# Ha van fájl, de nincs név/tel, akkor is mutassunk valamit
if uploaded_file:
    with st.spinner('Feldolgozás...'):
        results = extract_data(uploaded_file)
    
    if not results:
        st.error("Sajnos egyetlen ügyfelet sem sikerült kiolvasni. Próbáljuk meg másképp?")
    else:
        st.success(f"Találtam {len(results)} ügyfelet!")
        
        if not f_nev or not f_tel:
            st.warning("⚠️ A letöltéshez add meg a neved és számod a bal oldalon!")
        else:
            # PDF GENERÁLÁS
            output = io.BytesIO()
            p = canvas.Canvas(output, pagesize=A4)
            w, h = A4
            cw, ch = (w-20)/3, (h-40)/7
            
            for i, item in enumerate(results):
                if i > 0 and i % 21 == 0: p.showPage()
                col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
                x, y = 10 + col * cw, 20 + row * ch
                
                p.setStrokeColorRGB(0.8, 0.8, 0.8)
                p.rect(x+2, y+2, cw-4, ch-4)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 8.5)
                p.drawString(x+8, y+ch-15, f"{item['id']}. {item['nev']}"[:38])
                
                p.setFont(M_FONT, 8)
                c_clean = item['cim']
                for d in ["4031", "4002", "4030", "4025", "4026", "Debrecen", ","]: 
                    c_clean = c_clean.replace(d, "")
                p.drawString(x+8, y+ch-26, c_clean.strip()[:42])
                
                if item['info']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7)
                    p.drawString(x+8, y+ch-36, f"INFÓ: {item['info']}"[:45])
                    p.setFillColorRGB(0, 0, 0)
                
                p.setFont(B_FONT, 15)
                r_text = ", ".join(dict.fromkeys(item['rend']))
                p.drawCentredString(x+cw/2, y+32, r_text[:22])
                
                p.setFont(M_FONT, 6.5)
                p.line(x+10, y+18, x+cw-10, y+18)
                p.drawString(x+8, y+10, f"{f_nev} | {f_tel}")
                p.drawRightString(x+cw-8, y+10, "JÓ ÉTVÁGYAT!")

            p.save()
            st.download_button("📥 MATRICÁK LETÖLTÉSE", output.getvalue(), "etikett.pdf")
