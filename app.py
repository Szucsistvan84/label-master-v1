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

st.set_page_config(page_title="Interfood Etikett & Marketing", layout="wide")
st.title("🚚 Interfood Menetterv + Marketing Generátor")

# Sidebar: Kötelező adatok
st.sidebar.header("Futár azonosítása")
f_nev = st.sidebar.text_input("Saját Név:", value="", placeholder="Pl: Kovács János")
f_tel = st.sidebar.text_input("Saját Tel:", value="", placeholder="Pl: +36201234567")

def extract_data(pdf_file):
    reader = PdfReader(pdf_file)
    data = []
    curr = {'id': '', 'nev': '', 'cim': '', 'rend': [], 'info': '', 'napok': set()}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        for line in lines:
            if any(x in line for x in ["Nyomtatta", "Oldal", "Járatszám", "Menetterv"]): continue
            
            # P- vagy Z- kód azonosítása
            kod_match = re.search(r'([PZ])-\d+', line)
            if kod_match:
                if curr['nev'] or curr['cim']:
                    data.append(curr.copy())
                
                nap = kod_match.group(1)
                id_m = re.match(r'^(\d+)', line)
                name_p = line.split(kod_match.group(0))[-1].strip()
                curr = {'id': id_m.group(1) if id_m else '', 'nev': name_p, 'cim': '', 'rend': [], 'info': '', 'napok': {nap}}
            
            elif "Debrecen" in line:
                curr['cim'] = line
            elif re.search(r'\d-[A-Z0-9]', line):
                curr['rend'].extend(re.findall(r'\d-[A-Z0-9]+', line))
                if "P-" in line: curr['napok'].add('P')
                if "Z-" in line: curr['napok'].add('Z')
            elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs', 'porta']):
                curr['info'] = (curr['info'] + " " + line).strip()
            elif len(line) > 5 and not curr['cim'] and not curr['nev']:
                curr['nev'] = line

    if curr['nev'] or curr['cim']: data.append(curr)
    return data

uploaded_file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if uploaded_file:
    if not f_nev.strip() or not f_tel.strip():
        st.error("❌ Kérlek, add meg a Nevedet és a Telefonszámodat a bal oldalon a folytatáshoz!")
        st.stop()
    
    results = extract_data(uploaded_file)
    if results:
        st.success(f"✅ {len(results)} ügyfél beolvasva. Az ív többi része marketing címke lesz.")
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        w, h = A4
        cw, ch = (w-20)/3, (h-40)/7

        total_slots = ((len(results) - 1) // 21 + 1) * 21
        
        for i in range(total_slots):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            # Keret
            p.setStrokeColorRGB(0, 0, 0)
            p.setLineWidth(0.3)
            p.rect(x+2, y+2, cw-4, ch-4)

            # --- FEJLÉC ---
            p.setFillColorRGB(0, 0, 0)
            p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
            p.setFillColorRGB(1, 1, 1)
            p.setFont(B_FONT, 9)

            if i < len(results):
                # ÜGYFÉL CÍMKE
                item = results[i]
                napok = item['napok']
                h_text = "Péntek + Szombat!" if 'P' in napok and 'Z' in napok else ("Péntek" if 'P' in napok else "Szombat")
                p.drawCentredString(x+cw/2, y+ch-9, h_text)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 9)
                p.drawString(x+8, y+ch-25, f"{item['id']}. {item['nev']}"[:32])
                p.setFont(M_FONT, 8)
                c_clean = item['cim'].replace("Debrecen", "").strip(", 4031 4002 4030 ")
                p.drawString(x+8, y+ch-35, c_clean[:42])
                
                if item['info']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    prefix = "KCS: " if any(k in item['info'].lower() for k in ["kcs", "kulcs", "kapu"]) else "INFÓ: "
                    p.drawString(x+8, y+ch-45, f"{prefix}{item['info']}"[:45])
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 12)
                r_codes = ", ".join(list(dict.fromkeys(item['rend'])))
                p.drawString(x+8, y+22, f"Rend: {r_codes[:25]}")
            else:
                # MARKETING CÍMKE (Étlapra)
                p.drawCentredString(x+cw/2, y+ch-9, "INTERFOOD ÉTLAP")
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 11)
                p.drawCentredString(x+cw/2, y+ch-30, "RENDELJEN TŐLEM!")
                p.setFont(M_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch-45, "Házias ízek, pontos szállítás.")
                p.setFont(B_FONT, 8)
                p.drawCentredString(x+cw/2, y+25, "Keresse a futár telefonszámát:")

            # --- LÁBLÉC (FUTÁR ADATOK) ---
            p.setFont(M_FONT, 7)
            p.setFillColorRGB(0, 0, 0)
            p.line(x+10, y+15, x+cw-10, y+15)
            p.drawString(x+8, y+8, f"{f_nev} | {f_tel}")
            p.drawRightString(x+cw-10, y+8, "JÓ ÉTVÁGYAT!")

        p.save()
        st.download_button("📥 PDF LETÖLTÉSE", output.getvalue(), "interfood_profi_marketing.pdf")
