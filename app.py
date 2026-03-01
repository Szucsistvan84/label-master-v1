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

st.set_page_config(page_title="Interfood v7.3", layout="wide")
st.title("🚚 Interfood Etikett v7.3 - Sorszám Fix")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_v73(uploaded_file):
    reader = PdfReader(uploaded_file)
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"
    
    # Kinyerjük az összes sort a PDF-ből
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    
    customers = {}
    current_cust = None
    
    # Keressük a sorszámot és az ügyfélkódot
    # A PDF-ben gyakran így néz ki: "1", utána a következő sorban "P-428867"
    for i in range(len(lines)):
        line = lines[i]
        # Ügyfélkód felismerése
        id_match = re.search(r'([PZSC])-(\d{6})', line)
        
        if id_match:
            day_type = id_match.group(1)
            cust_id = id_match.group(2)
            
            # Megpróbáljuk visszakeresni a sorszámot (az előző 1-2 sorban lehet)
            sorszam = "?"
            for j in range(1, 3):
                if i-j >= 0 and lines[i-j].isdigit() and len(lines[i-j]) < 4:
                    sorszam = lines[i-j]
                    break
            
            if cust_id not in customers:
                # NÉV: A kód utáni részben keressük, vagy az alatta lévő sorban
                raw_name = line.split(id_match.group(0))[-1].strip()
                if not raw_name or "Debrecen" in raw_name:
                    if i+1 < len(lines): raw_name = lines[i+1]
                
                # Tisztítás: csak az első 2-3 szót hagyjuk meg (Név)
                clean_name = " ".join([w for w in raw_name.split() if w[0].isupper() and "Debrecen" not in w][:3])
                
                # CÍM: 40-nel kezdődő irányítószám keresése a közelben
                cim = ""
                for k in range(i, min(i+5, len(lines))):
                    if "40" in lines[k] and "Debrecen" in lines[k]:
                        cim = lines[k]
                        break

                customers[cust_id] = {
                    'kod': cust_id, 'sorszamok': {sorszam} if sorszam != "?" else set(),
                    'nev': clean_name if clean_name else "Ügyfél",
                    'cim': cim, 'P_rend': [], 'Z_rend': [], 'is_z': False
                }
            else:
                if sorszam != "?": customers[cust_id]['sorszamok'].add(sorszam)
            
            # ÉTELKÓDOK gyűjtése a következő sorokból a következő ügyfélig
            for k in range(i, min(i+10, len(lines))):
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', lines[k])
                if day_type == 'Z':
                    customers[cust_id]['Z_rend'].extend(codes)
                    customers[cust_id]['is_z'] = True
                else:
                    customers[cust_id]['P_rend'].extend(codes)

    return list(customers.values())

file = st.file_uploader("Feltöltés", type="pdf")

if file:
    data = process_v73(file)
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
                # 1. sor: Sorszám(ok) - Sorba rendezve
                c.setFont(B_FONT, 9)
                s_list = sorted(list(u['sorszamok']), key=lambda x: int(x) if x.isdigit() else 999)
                s_str = (" + ".join(s_list) + ".") if s_list else ""
                c.drawString(x+8, y+h-15, s_str)

                # 2. sor: Név és Ügyfélkód
                c.setFont(B_FONT, 11)
                c.drawString(x+8, y+h-28, u['nev'][:22])
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
                # Marketing (Üres helyekre)
                c.setFont(B_FONT, 12)
                c.drawCentredString(x+w/2, y+h-30, "15% KEDVEZMÉNY")
                c.setFont(M_FONT, 8.5)
                c.drawCentredString(x+w/2, y+h-45, "Új ügyfeleknek 3 hétig!")
                c.setFont(B_FONT, 10)
                c.drawCentredString(x+w/2, y+15, f"{input_nev}")
                c.drawCentredString(x+w/2, y+5, f"{input_tel}")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V7.3)", out.getvalue(), "interfood_v73.pdf")
