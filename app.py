import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Betűtípusok betöltése
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Etikett", layout="wide")
st.title("🚚 Interfood Menetterv Generátor v2.1")

st.sidebar.header("Beállítások")
f_nev = st.sidebar.text_input("Név:", value="", placeholder="Ebéd Elek")
f_tel = st.sidebar.text_input("Tel:", value="", placeholder="+36207654321")

def extract_precise(pdf_file):
    reader = PdfReader(pdf_file)
    final_data = []
    curr = {'id': '', 'nev': '', 'cim': '', 'rend': [], 'info': ''}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        for line in lines:
            # 1. Nagyon szigorú szűrés a szemét adatok ellen
            if any(x in line for x in ["Nyomtatta:", "Oldal", "Járatszám", "Menetterv", "Ügyfél", "Telefon"]):
                continue
            if re.search(r'\d{4}\.\s?\d{2}\.\s?\d{2}', line): # Dátum (pl 2026. 02. 26.) kiszűrése
                continue

            id_match = re.match(r'^(\d+)$', line)
            kod_match = re.search(r'([PZ]-\d+)', line)
            
            if id_match or kod_match:
                if (curr['nev'] or curr['id']) and curr['cim']:
                    final_data.append({
                        'id': curr['id'], 'nev': curr['nev'], 'cim': curr['cim'],
                        'rend': ", ".join(dict.fromkeys(curr['rend'])), 'info': curr['info']
                    })
                
                if id_match:
                    curr = {'id': id_match.group(1), 'nev': '', 'cim': '', 'rend': [], 'info': ''}
                else:
                    name_p = line.split(kod_match.group(1))[-1].strip()
                    curr = {'id': curr['id'], 'nev': name_p, 'cim': '', 'rend': [], 'info': ''}
            
            elif "Debrecen" in line:
                curr['cim'] = line
            elif re.search(r'\d-[A-Z0-9]', line):
                codes = re.findall(r'\d-[A-Z0-9]+', line)
                curr['rend'].extend(codes)
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs', 'porta']):
                curr['info'] = (curr['info'] + " " + line).strip()
            elif len(line) > 3 and not curr['cim']:
                if not curr['nev']: curr['nev'] = line
                else: curr['nev'] = (curr['nev'] + " " + line).strip()

    if curr['cim']:
        final_data.append({'id': curr['id'], 'nev': curr['nev'], 'cim': curr['cim'], 
                           'rend': ", ".join(dict.fromkeys(curr['rend'])), 'info': curr['info']})
    return final_data

uploaded_file = st.file_uploader("PDF feltöltése", type="pdf")

if uploaded_file and f_nev and f_tel:
    results = extract_precise(uploaded_file)
    if results:
        st.success(f"✅ {len(results)} matrica készen áll.")
        output = io.BytesIO()
        c = canvas.Canvas(output, pagesize=A4)
        w, h = A4
        cw, ch = (w-20)/3, (h-40)/7 # 3 oszlop, 7 sor
        
        for i, item in enumerate(results):
            if i > 0 and i % 21 == 0: c.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            # Halvány keret a vágáshoz
            c.setStrokeColorRGB(0.85, 0.85, 0.85)
            c.rect(x+2, y+2, cw-4, ch-4)
            c.setFillColorRGB(0, 0, 0)
            
            # 1. Sorszám és Név (Kisebb font, hogy ne lógjon ki)
            c.setFont(B_FONT, 8.5)
            nev_szoveg = f"{item['id']}. {item['nev']}" if item['id'] else item['nev']
            c.drawString(x+8, y+ch-15, nev_szoveg[:38])
            
            # 2. Cím (Még kisebb, Debrecen nélkül)
            c.setFont(M_FONT, 8)
            t_cim = item['cim'].replace("4031 Debrecen, ", "").replace("4002 Debrecen, ", "").replace("4030 Debrecen, ", "").replace("4025 Debrecen, ", "").replace("4026 Debrecen, ", "")
            c.drawString(x+8, y+ch-26, t_cim[:42])
            
            # 3. INFO (Ha van) - Pirossal, feltűnően
            if item['info']:
                c.setFillColorRGB(0.8, 0, 0)
                c.setFont(B_FONT, 7)
                # "INFO: " előtag csak ha nem üres
                info_szoveg = item['info'] if "INFO" in item['info'].upper() else f"INFÓ: {item['info']}"
                c.drawString(x+8, y+ch-36, info_szoveg[:45])
                c.setFillColorRGB(0, 0, 0)
            
            # 4. RENDELÉS (A matrica közepe, nagy betűvel)
            c.setFont(B_FONT, 16)
            c.drawCentredString(x+cw/2, y+32, item['rend'][:20])
            
            # 5. Futár adatok és Jó étvágyat (Alulra kicsiben)
            c.setFont(M_FONT, 6.5)
            c.setStrokeColorRGB(0.7, 0.7, 0.7)
            c.line(x+10, y+18, x+cw-10, y+18) # Elválasztó vonal
            c.drawString(x+8, y+10, f"{f_nev} | {f_tel}")
            c.drawRightString(x+cw-8, y+10, "JÓ ÉTVÁGYAT!")

        c.save()
        st.download_button("📥 MATRICÁK LETÖLTÉSE", output.getvalue(), "interfood_javitott.pdf")
