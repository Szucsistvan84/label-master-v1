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

st.set_page_config(page_title="Interfood Etikett", layout="wide")
st.title("🚚 Interfood Menetterv Generátor v2.2")

# Sidebar
st.sidebar.header("Beállítások")
f_nev = st.sidebar.text_input("Név:", value="", placeholder="Ebéd Elek")
f_tel = st.sidebar.text_input("Tel:", value="", placeholder="+36207654321")

# Adatkinyerő funkció
def get_data(pdf_file):
    reader = PdfReader(pdf_file)
    data = []
    curr = {'id': '', 'nev': '', 'cim': '', 'rend': [], 'info': ''}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        for line in lines:
            if any(x in line for x in ["Nyomtatta", "Oldal", "Járatszám", "Menetterv", "Ügyfél"]): continue
            if re.search(r'\d{4}\.\s?\d{2}\.\s?\d{2}', line): continue

            id_m = re.match(r'^(\d+)$', line)
            kod_m = re.search(r'([PZ]-\d+)', line)
            
            if id_m or kod_m:
                if curr['cim']: # Csak ha van már címünk, akkor mentjük az előzőt
                    data.append(curr.copy())
                
                if id_m:
                    curr = {'id': id_m.group(1), 'nev': '', 'cim': '', 'rend': [], 'info': ''}
                else:
                    n_p = line.split(kod_m.group(1))[-1].strip()
                    curr = {'id': curr['id'], 'nev': n_p, 'cim': '', 'rend': [], 'info': ''}
            
            elif "Debrecen" in line:
                curr['cim'] = line
            elif re.search(r'\d-[A-Z0-9]', line):
                curr['rend'].extend(re.findall(r'\d-[A-Z0-9]+', line))
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs']):
                curr['info'] = (curr['info'] + " " + line).strip()
            elif len(line) > 3 and not curr['cim']:
                curr['nev'] = (curr['nev'] + " " + line).strip()

    if curr['cim']: data.append(curr)
    return data

# FŐ FOLYAMAT
uploaded_file = st.file_uploader("Töltsd fel a PDF-et", type="pdf")

if uploaded_file:
    if not f_nev or not f_tel:
        st.warning("⬅️ Kérlek, töltsd ki a nevedet és a telefonszámodat a bal oldalon!")
    else:
        # Itt indul a feldolgozás
        with st.spinner('Adatok feldolgozása...'):
            results = get_data(uploaded_file)
            
        if results:
            st.success(f"✅ Sikerült! {len(results)} ügyfelet találtam.")
            
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
                
                # Név
                p.setFont(B_FONT, 8.5)
                p.drawString(x+8, y+ch-15, f"{item['id']}. {item['nev']}"[:38])
                
                # Cím (Tisztítva)
                p.setFont(M_FONT, 8)
                c_clean = item['cim']
                for d in ["4031", "4002", "4030", "4025", "4026", "Debrecen", ","]: 
                    c_clean = c_clean.replace(d, "")
                p.drawString(x+8, y+ch-26, c_clean.strip()[:42])
                
                # Info
                if item['info']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7)
                    p.drawString(x+8, y+ch-36, f"INFÓ: {item['info']}"[:45])
                    p.setFillColorRGB(0, 0, 0)
                
                # Ételkód
                p.setFont(B_FONT, 15)
                p.drawCentredString(x+cw/2, y+35, ", ".join(dict.fromkeys(item['rend']))[:22])
                
                # Futár infó
                p.setFont(M_FONT, 6.5)
                p.line(x+10, y+18, x+cw-10, y+18)
                p.drawString(x+8, y+10, f"{f_nev} | {f_tel}")
                p.drawRightString(x+cw-8, y+10, "JÓ ÉTVÁGYAT!")

            p.save()
            st.download_button("📥 MATRICÁK LETÖLTÉSE (PDF)", output.getvalue(), "interfood_kesz.pdf")
        else:
            st.error("❌ A fájlt beolvastam, de nem találtam benne etikett adatokat. Biztos jó PDF-et töltöttél fel?")
