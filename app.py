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

st.set_page_config(page_title="Interfood Etikett Profi", layout="wide")
st.title("🚚 Interfood Menetterv Generátor v3.3")

# --- SIDEBAR: KÖTELEZŐ ADATOK ---
st.sidebar.header("Futár azonosítása")
st.sidebar.info("A folytatáshoz kérlek, add meg a saját adataidat. Ezek nélkül nem generálható PDF.")

f_nev = st.sidebar.text_input("Saját Név:", value="", placeholder="Pl: Kovács János")
f_tel = st.sidebar.text_input("Saját Tel:", value="", placeholder="Pl: +36201234567")

def extract_data(pdf_file):
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

            kod_m = re.search(r'([PZ]-\d+)', line)
            if kod_m:
                if curr['nev'] or curr['cim']:
                    data.append(curr.copy())
                id_m = re.match(r'^(\d+)', line)
                curr = {'id': id_m.group(1) if id_m else '', 'nev': line.split(kod_m.group(1))[-1].strip(), 'cim': '', 'rend': [], 'info': ''}
            elif "Debrecen" in line:
                curr['cim'] = line
            elif re.search(r'\d-[A-Z0-9]', line):
                curr['rend'].extend(re.findall(r'\d-[A-Z0-9]+', line))
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs', 'porta']):
                curr['info'] = (curr['info'] + " " + line).strip()
            elif len(line) > 5 and not curr['cim']:
                curr['nev'] = (curr['nev'] + " " + line).strip()

    if curr['nev'] or curr['cim']: data.append(curr)
    return data

# --- FŐ LOGIKA ---
uploaded_file = st.file_uploader("Válaszd ki a PDF menettervet", type="pdf")

if uploaded_file:
    # BIZTONSÁGI ELLENŐRZÉS: Csak akkor lépünk tovább, ha NINCSENEK üresen az adatok
    if not f_nev.strip() or not f_tel.strip():
        st.error("❌ HIBA: Kérlek, add meg a Nevedet és a Telefonszámodat a bal oldali sávban!")
        st.stop() # Itt megáll a kód futása, nem generál semmit
    
    # Ha minden adat megvan, mehet a munka
    results = extract_data(uploaded_file)
    
    if results:
        st.success(f"✅ Beolvasva: {len(results)} ügyfél. A teljes ív (21 db) kitöltésre kerül.")
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        w, h = A4
        cw, ch = (w-20)/3, (h-40)/7

        # Mindig az utolsó megkezdett oldalt is teleírjuk üres matricákkal
        total_slots = ((len(results) - 1) // 21 + 1) * 21
        
        for i in range(total_slots):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            # Alap keret és fejléc
            p.setStrokeColorRGB(0, 0, 0)
            p.setLineWidth(0.3)
            p.rect(x+2, y+2, cw-4, ch-4)
            p.setFillColorRGB(0, 0, 0)
            p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
            p.setFillColorRGB(1, 1, 1)
            p.setFont(B_FONT, 9)
            p.drawCentredString(x+cw/2, y+ch-9, "Péntek + Szombat!")

            # Adatok csak akkor, ha van beolvasott ügyfél az adott sorszámon
            if i < len(results):
                item = results[i]
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, f"{item['id']}. {item['nev']}"[:28])
                p.setFont(B_FONT, 8)
                c_clean = item['cim'].replace("Debrecen", "").replace("4031", "").replace("4002", "").strip(", ")
                p.drawString(x+8, y+ch-35, c_clean[:40])
                if item['info']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    prefix = "KCS: " if any(k in item['info'].lower() for k in ["kcs", "kulcs", "kapu"]) else "INFÓ: "
                    p.drawString(x+8, y+ch-45, f"{prefix}{item['info']}"[:45])
                    p.setFillColorRGB(0, 0, 0)
                rend_list = list(dict.fromkeys(item['rend']))
                p.setFont(M_FONT, 7)
                p.drawString(x+8, y+28, f"Összesen: {len(rend_list)} tétel")
                p.setFont(B_FONT, 11)
                p.drawString(x+8, y+18, f"P: {', '.join(rend_list)[:25]}")
            
            # --- FUTÁR ADATAI (MINDIG VALÓDI ADAT KERÜL IDE) ---
            p.setFont(M_FONT, 6.5)
            p.setFillColorRGB(0, 0, 0)
            p.line(x+10, y+15, x+cw-10, y+15)
            p.drawString(x+8, y+8, f"{f_nev} | {f_tel}")
            p.drawRightString(x+cw-10, y+8, "JÓ ÉTVÁGYAT!")

        p.save()
        st.download_button("📥 MATRICÁK LETÖLTÉSE", output.getvalue(), "interfood_matricak.pdf")
