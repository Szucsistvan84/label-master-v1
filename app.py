import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Betűtípusok - Roboto-Regular.ttf és Roboto-Bold.ttf kell a GitHubra!
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Etikett", layout="wide")
st.title("🚚 Interfood Menetterv Generátor")

st.sidebar.header("Beállítások")
f_nev = st.sidebar.text_input("Név:", value="", placeholder="Ebéd Elek")
f_tel = st.sidebar.text_input("Tel:", value="", placeholder="+36207654321")

def extract_flexible(pdf_file):
    reader = PdfReader(pdf_file)
    final_data = []
    
    # Aktuális ügyfél építése
    curr = {'id': '', 'nev': '', 'cim': '', 'rend': [], 'info': ''}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        
        # Tisztítjuk a szöveget, de megtartjuk a lényeget
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        for line in lines:
            # 1. SZŰRÉS: Fejlécek kidobása
            if any(x in line for x in ["Nyomtatta:", "Oldal", "Járatszám", "Menetterv", "Sor", "Ügyfél"]):
                continue
            
            # 2. ÚJ ÜGYFÉL KEZDETE: Sorszám VAGY P/Z kód
            id_match = re.match(r'^(\d+)$', line)
            kod_match = re.search(r'([PZ]-\d+)', line)
            
            if id_match or kod_match:
                # Mielőtt újat kezdünk, mentsük el a régit, ha van benne tartalom
                if curr['nev'] or curr['cim']:
                    final_data.append({
                        'id': curr['id'], 'nev': curr['nev'], 'cim': curr['cim'],
                        'rend': ", ".join(dict.fromkeys(curr['rend'])), 'info': curr['info']
                    })
                
                # Alaphelyzetbe állítás
                if id_match:
                    curr = {'id': id_match.group(1), 'nev': '', 'cim': '', 'rend': [], 'info': ''}
                else:
                    # Ha csak kódot találtunk, az ID marad a régi, de új ügyfél
                    name_part = line.split(kod_match.group(1))[-1].strip()
                    curr = {'id': curr['id'], 'nev': name_part, 'cim': '', 'rend': [], 'info': ''}
            
            # 3. ADATOK GYŰJTÉSE
            elif "Debrecen" in line:
                curr['cim'] = line
            elif re.search(r'\d-[A-Z0-9]', line):
                codes = re.findall(r'\d-[A-Z0-9]+', line)
                curr['rend'].extend(codes)
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs', 'porta']):
                curr['info'] += " " + line
            elif len(line) > 5 and not curr['cim']:
                # Ha se nem kód, se nem cím, akkor valószínűleg a név folytatása
                if not curr['nev']: curr['nev'] = line
                else: curr['nev'] += " " + line

    # Utolsó mentése
    if curr['nev'] or curr['cim']:
        final_data.append({'id': curr['id'], 'nev': curr['nev'], 'cim': curr['cim'], 
                           'rend': ", ".join(dict.fromkeys(curr['rend'])), 'info': curr['info']})
    
    return final_data

uploaded_file = st.file_uploader("Válaszd ki a PDF menettervet", type="pdf")

if uploaded_file:
    if f_nev and f_tel:
        results = extract_flexible(uploaded_file)
        if results:
            st.success(f"✅ Beolvasva: {len(results)} ügyfél.")
            
            output = io.BytesIO()
            c = canvas.Canvas(output, pagesize=A4)
            w, h = A4
            cw, ch = (w-20)/3, (h-40)/7
            
            for i, item in enumerate(results):
                if i > 0 and i % 21 == 0: c.showPage()
                col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
                x, y = 10 + col * cw, 20 + row * ch
                
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x+2, y+2, cw-4, ch-4)
                c.setFillColorRGB(0, 0, 0)
                
                # Név és Sorszám
                c.setFont(B_FONT, 10)
                name_display = f"{item['id']}. {item['nev']}" if item['id'] else item['nev']
                c.drawString(x+8, y+ch-18, name_display[:32])
                
                # Cím (Debrecen nélkül a helytakarékosság miatt)
                c.setFont(M_FONT, 8)
                t_cim = item['cim'].replace("4031 Debrecen, ", "").replace("4002 Debrecen, ", "").replace("4030 Debrecen, ", "")
                c.drawString(x+8, y+ch-28, t_cim[:40])
                
                # Infó pirossal
                if item['info']:
                    c.setFillColorRGB(0.8, 0, 0)
                    c.setFont(B_FONT, 7)
                    c.drawString(x+8, y+ch-38, f"INFÓ: {item['info'].strip()[:42]}")
                    c.setFillColorRGB(0, 0, 0)
                
                # Rendelés nagyban
                c.setFont(B_FONT, 14)
                c.drawString(x+8, y+35, item['rend'][:25])
                
                # Futár adatok alul
                c.setFont(M_FONT, 7)
                c.drawString(x+8, y+12, f"{f_nev} | {f_tel}")
                c.drawRightString(x+cw-10, y+12, "JÓ ÉTVÁGYAT!")

            c.save()
            st.download_button("📥 MATRICÁK LETÖLTÉSE", output.getvalue(), "interfood_matricak.pdf")
        else:
            st.error("A PDF-et sikerült beolvasni, de nem találtam benne felismerhető ügyféladatokat.")
    else:
        st.warning("⚠️ Kérlek, add meg a Nevedet és a Telefonszámodat a bal oldali sávban!")
