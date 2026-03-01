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
    except: return "Helvetica", "Helvetica-Bold"

M_FONT, B_FONT = get_fonts()

st.set_page_config(page_title="Interfood v8.2", layout="wide")
st.title("🚚 Interfood Etikett v8.2 - Cím és Név Fixer")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_v8_2(uploaded_file):
    reader = PdfReader(uploaded_file)
    customers = {}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        for i, line in enumerate(lines):
            # Kód keresése: P-123456 vagy Z-123456
            id_match = re.search(r'([PZSC])-(\d{6})', line)
            if id_match:
                day_type = id_match.group(1)
                cust_id = id_match.group(2)
                
                if cust_id not in customers:
                    # NÉV: Általában a kód után van ugyanabban a sorban
                    name_part = line.split(id_match.group(0))[-1].strip()
                    # CÍM: Megnézzük a következő 1-2 sort irányítószámot keresve
                    address = ""
                    potential_name = name_part
                    
                    for j in range(i + 1, min(i + 4, len(lines))):
                        if re.search(r'\d{4}\s+Debrecen', lines[j]):
                            address = lines[j]
                            break
                    
                    customers[cust_id] = {
                        'kod': cust_id,
                        'sorszamok': set(),
                        'nev': potential_name if len(potential_name) > 2 else "Ismeretlen",
                        'cim': address if address else "Debrecen",
                        'P_rend': [], 'Z_rend': []
                    }

                # SORSZÁM KERESÉSE (környező sorokból, ha az elején van szám)
                s_match = re.match(r'^(\d{1,3})$', line) or (i > 0 and re.match(r'^(\d{1,3})$', lines[i-1]))
                if s_match:
                    customers[cust_id]['sorszamok'].add(s_match.group(1))

                # RENDELÉSEK KERESÉSE (kibővített környezetben)
                context = " ".join(lines[max(0, i-2) : i+5])
                codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', context)
                if day_type in ['Z', 'S']:
                    customers[cust_id]['Z_rend'].extend(codes)
                else:
                    customers[cust_id]['P_rend'].extend(codes)

    # Tisztítás
    for c in customers.values():
        c['P_rend'] = sorted(list(set(c['P_rend'])))
        c['Z_rend'] = sorted(list(set(c['Z_rend'])))
        # Összesítés kiszámítása
        c['total_items'] = len(c['P_rend']) + len(c['Z_rend'])

    return list(customers.values())

file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if file:
    data = process_v8_2(file)
    if data:
        out = io.BytesIO()
        c = canvas.Canvas(out, pagesize=A4)
        w, h = (A4[0]-20)/3, (A4[1]-40)/7
        
        for i in range(((len(data)-1)//21 + 1) * 21):
            if i > 0 and i % 21 == 0: c.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * w, 20 + row * h
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.rect(x+2, y+2, w-4, h-4)

            if i < len(data):
                u = data[i]
                c.setFillColorRGB(0, 0, 0)
                
                # SORSZÁM ÉS ÖSSZESÍTŐ
                c.setFont(B_FONT, 10)
                s_str = " + ".join(sorted(list(u['sorszamok'])))
                c.drawString(x+8, y+h-15, f"{s_str}. sorszám")
                
                # ÖSSZESEN TÉTEL (Kiemelve)
                c.setFillColorRGB(0.7, 0, 0) # Pirosas szín az összesítőnek
                c.drawRightString(x+w-10, y+h-15, f"Össz: {u['total_items']} db")
                c.setFillColorRGB(0, 0, 0)

                # NÉV ÉS KÓD
                c.setFont(B_FONT, 10.5)
                c.drawString(x+8, y+h-28, u['nev'][:22])
                c.setFont(M_FONT, 9)
                c.drawRightString(x+w-10, y+h-28, u['kod'])
                
                # CÍM
                c.setFont(M_FONT, 8)
                c.drawString(x+8, y+h-38, u['cim'][:40])
                
                # RENDELÉSEK (Kisebb betűvel, ha sok van)
                p_text = f"Péntek: {', '.join(u['P_rend'])}"
                z_text = f"Szombat: {', '.join(u['Z_rend'])}"
                
                # Betűméret skálázás a tartalom hosszától függően
                font_size = 8.5 if len(p_text + z_text) < 50 else 7.5
                c.setFont(B_FONT, font_size)
                
                if u['P_rend']:
                    c.drawString(x+8, y+24, p_text[:45])
                if u['Z_rend']:
                    c.drawString(x+8, y+13, z_text[:45])

                # LÁBLÉC
                c.setFont(M_FONT, 7)
                c.drawString(x+8, y+5, f"{input_nev} | {input_tel}")
            else:
                # Marketing rész az üres helyekre
                c.setFont(B_FONT, 12)
                c.drawCentredString(x+w/2, y+h-30, "15% KEDVEZMÉNY")
                c.setFont(M_FONT, 9)
                c.drawCentredString(x+w/2, y+15, f"{input_nev}")
                c.drawCentredString(x+w/2, y+6, f"{input_tel}")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V8.2)", out.getvalue(), "interfood_v8_2.pdf")
