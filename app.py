import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Betűtípus beállítása
font_path, font_bold_path = "Roboto-Regular.ttf", "Roboto-Bold.ttf"
if os.path.exists(font_path) and os.path.exists(font_bold_path):
    pdfmetrics.registerFont(TTFont('Roboto', font_path))
    pdfmetrics.registerFont(TTFont('Roboto-Bold', font_bold_path))
    M_FONT, B_FONT = "Roboto", "Roboto-Bold"
else:
    M_FONT, B_FONT = "Helvetica", "Helvetica-Bold"

st.set_page_config(page_title="Interfood Profi v6.0", layout="wide")
st.title("🚚 Interfood Etikett v6.0 - Stabil Verzió")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def extract_v60(pdf_file):
    reader = PdfReader(pdf_file)
    raw_text = ""
    for page in reader.pages:
        raw_text += page.extract_text() + "\n---PAGE---\n"
    
    # Ügyfelek azonosítása a P-123456 formátum alapján
    customer_chunks = re.split(r'(\n\d{1,3}\n[PZSC]-\d{6})', raw_text)
    
    data_list = []
    for i in range(1, len(customer_chunks), 2):
        header = customer_chunks[i]
        body = customer_chunks[i+1] if i+1 < len(customer_chunks) else ""
        full_block = header + body
        
        # Kód és Nap kinyerése
        id_match = re.search(r'([PZSC])-(\d{6})', header)
        if not id_match: continue
        day_type, cust_code = id_match.group(1), id_match.group(2)
        
        # NÉV: A blokk elején keressük (Tőkés István, Hajós-Szabó Anett stb.)
        # Olyan szavakat keresünk, amik nagybetűvel kezdődnek és legalább kettő van belőlük
        name = "Ügyfél"
        name_candidates = re.findall(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:\s[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)?)', full_block)
        for cand in name_candidates:
            if not any(x in cand for x in ["Debrecen", "Kft", "Interfood", "Házgyár", "Határ"]):
                name = cand
                break
        
        # CÍM: Debrecen + utca
        cim = ""
        cim_m = re.search(r'(\d{4}\s+Debrecen,.*)', full_block)
        if cim_m:
            cim = cim_m.group(1).split('\n')[0].strip()

        # ÉTELKÓDOK: Szigorú 1-A12 vagy 10-K formátum
        food_codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', body)
        
        data_list.append({
            'kod': cust_code, 'nev': name, 'cim': cim, 
            'rend': sorted(list(set(food_codes))), 'day': day_type
        })

    # Összevonás (Péntek + Szombat)
    merged = {}
    for item in data_list:
        k = item['kod']
        if k not in merged:
            merged[k] = item
            merged[k]['P_rend'] = item['rend'] if item['day'] != 'Z' else []
            merged[k]['Z_rend'] = item['rend'] if item['day'] == 'Z' else []
            merged[k]['is_z'] = (item['day'] == 'Z')
        else:
            if item['day'] == 'Z':
                merged[k]['Z_rend'].extend(item['rend'])
                merged[k]['is_z'] = True
            else:
                merged[k]['P_rend'].extend(item['rend'])
    
    return list(merged.values())

uploaded_file = st.file_uploader("Menetterv feltöltése", type="pdf")

if uploaded_file:
    customers = extract_v60(uploaded_file)
    if customers:
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        cw, ch = (A4[0]-20)/3, (A4[1]-40)/7

        for i in range(((len(customers)-1)//21+1)*21):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            p.setStrokeColorRGB(0, 0, 0)
            p.setLineWidth(0.5)
            p.rect(x+2, y+2, cw-4, ch-4)

            if i < len(customers):
                c = customers[i]
                # FEJLÉC
                if c.get('is_z'):
                    p.setFillColorRGB(0, 0, 0)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 8)
                    p.drawCentredString(x+cw/2, y+ch-9, "PÉNTEK + SZOMBAT" if c['P_rend'] else "SZOMBAT")
                
                p.setFillColorRGB(0, 0, 0)
                # NÉV (Bal) - KÓD (Jobb)
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, c['nev'][:22])
                p.drawRightString(x+cw-8, y+ch-25, c['kod'])
                
                # CÍM
                p.setFont(M_FONT, 8.5)
                p.drawString(x+8, y+ch-36, c['cim'][:38])
                
                # RENDELÉSEK
                p.setFont(B_FONT, 10)
                if c['P_rend']:
                    p.drawString(x+8, y+22, f"P: {', '.join(c['P_rend'])}"[:35])
                if c['Z_rend']:
                    p.drawString(x+8, y+10, f"Sz: {', '.join(c['Z_rend'])}"[:35])
                
                # FIX LÁBLÉC
                p.setFont(M_FONT, 7)
                p.line(x+10, y+6, x+cw-10, y+6)
                p.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
            else:
                # FIX MARKETING CÍMKE (Ez nem tűnhet el!)
                p.setFillColorRGB(0, 0, 0)
                p.setFont(B_FONT, 12)
                p.drawCentredString(x+cw/2, y+ch-25, "15% KEDVEZMÉNY")
                p.setFont(M_FONT, 8)
                p.drawCentredString(x+cw/2, y+ch-38, "Új ügyfeleknek 3 hétig!")
                p.setFont(B_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch/2-5, "RENDELÉS LEADÁS:")
                p.drawCentredString(x+cw/2, y+ch/2-18, f"{input_nev}")
                p.drawCentredString(x+cw/2, y+ch/2-28, f"{input_tel}")

        p.save()
        st.download_button("📥 PDF LETÖLTÉSE (V6.0)", output.getvalue(), "interfood_v6.pdf")
