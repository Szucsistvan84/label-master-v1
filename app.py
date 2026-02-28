import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# 1. Betűtípusok beállítása
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi Generátor", layout="wide")
st.title("🚚 Interfood Intelligens Etikett v3.9")

# Futár adatok a marketinghez és lábléchez
st.sidebar.header("Futár azonosítása")
f_nev = st.sidebar.text_input("Saját Név:", value="")
f_tel = st.sidebar.text_input("Saját Tel:", value="")

def extract_and_merge_all_days(pdf_file):
    reader = PdfReader(pdf_file)
    # Az ügyfeleket a tiszta számkódjuk alapján tároljuk el
    customers = {} 
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 1]
        
        last_id = None
        for line in lines:
            # Keresünk bármilyen nap-kódot: H-, K-, S-, C-, P-, Z- utáni számokat
            kod_match = re.search(r'([HKSCPZ])-(\d+)', line)
            
            if kod_match:
                nap_betu = kod_match.group(1)
                ugyfel_szam = kod_match.group(2)
                last_id = ugyfel_szam
                
                if last_id not in customers:
                    customers[last_id] = {
                        'nev': line.split(kod_match.group(0))[-1].strip(),
                        'cim': '',
                        'rend': [],
                        'info': '',
                        'napok': {nap_betu}
                    }
                else:
                    customers[last_id]['napok'].add(nap_betu)
                    # Ha a név még rövid vagy üres, frissítjük
                    new_name = line.split(kod_match.group(0))[-1].strip()
                    if len(new_name) > len(customers[last_id]['nev']):
                        customers[last_id]['nev'] = new_name

            elif last_id:
                # Adatgyűjtés az aktuális ügyfélhez
                if "Debrecen" in line:
                    customers[last_id]['cim'] = line
                elif re.search(r'\d-[A-Z0-9]', line):
                    # Ételkódok gyűjtése (pl. 1-A2)
                    codes = re.findall(r'\d-[A-Z0-9]+', line)
                    customers[last_id]['rend'].extend(codes)
                elif any(x in line.lower() for x in ['kód', 'kk', 'kapu', 'itthon', 'kcs', 'kulcs', 'porta']):
                    # Info gyűjtése
                    if line not in customers[last_id]['info']:
                        customers[last_id]['info'] = (customers[last_id]['info'] + " " + line).strip()

    # Tisztítás: csak azokat adjuk vissza, amiknek van nevük vagy címük
    valid_customers = [c for c in customers.values() if c['nev'] or c['cim']]
    return valid_customers

uploaded_file = st.file_uploader("Töltsd fel a Menetterv PDF-et", type="pdf")

if uploaded_file:
    if not f_nev.strip() or not f_tel.strip():
        st.error("❌ Kérlek, add meg a Nevedet és a Telefonszámodat a bal oldalon!")
        st.stop()
    
    data = extract_and_merge_all_days(uploaded_file)
    
    if data:
        st.success(f"✅ {len(data)} ügyfelet azonosítottam és vontam össze.")
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        w, h = A4
        cw, ch = (w-20)/3, (h-40)/7

        # 21-esével töltjük az oldalakat
        total_slots = ((len(data) - 1) // 21 + 1) * 21
        
        for i in range(total_slots):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            p.setStrokeColorRGB(0, 0, 0)
            p.setLineWidth(0.3)
            p.rect(x+2, y+2, cw-4, ch-4)

            # FEJLÉC
            p.setFillColorRGB(0, 0, 0)
            p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
            p.setFillColorRGB(1, 1, 1)
            p.setFont(B_FONT, 9)

            if i < len(data):
                # --- ÜGYFÉL MÓD ---
                item = data[i]
                n = item['napok']
                # Fejléc logika a napok alapján
                if 'P' in n and 'Z' in n: h_txt = "Péntek + Szombat!"
                elif 'P' in n: h_txt = "Péntek"
                elif 'Z' in n: h_txt = "Szombat"
                elif 'H' in n: h_txt = "Hétfő"
                elif 'K' in n: h_txt = "Kedd"
                elif 'S' in n: h_txt = "Szerda"
                elif 'C' in n: h_txt = "Csütörtök"
                else: h_txt = "INTERFOOD"
                
                p.drawCentredString(x+cw/2, y+ch-9, h_txt)
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 9.5)
                p.drawString(x+8, y+ch-25, item['nev'][:30])
                
                p.setFont(M_FONT, 8)
                c_clean = item['cim'].replace("Debrecen", "").strip(", 4031 4002 4030 ")
                p.drawString(x+8, y+ch-35, c_clean[:40])
                
                if item['info']:
                    p.setFillColorRGB(0.8, 0, 0)
                    p.setFont(B_FONT, 7.5)
                    prefix = "KCS: " if any(k in item['info'].lower() for k in ["kcs", "kulcs"]) else "INFÓ: "
                    p.drawString(x+8, y+ch-44, f"{prefix}{item['info']}"[:45])
                
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 12)
                # Egyedi ételkódok listázása
                rendelesek = ", ".join(sorted(list(set(item['rend']))))
                p.drawString(x+8, y+22, f"Rend: {rendelesek if rendelesek else '---'}")
            else:
                # --- MARKETING MÓD (A beküldött minta alapján) ---
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
            p.drawString(x+8, y+8, f"{f_nev} | {f_tel}")
            p.drawRightString(x+cw-10, y+8, "JÓ ÉTVÁGYAT!")

        p.save()
        st.download_button("📥 PDF GENERÁLÁSA", output.getvalue(), "interfood_etikett_final.pdf")
