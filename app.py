import os
import streamlit as st
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import re

# Betűtípus regisztrálása
def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('Roboto', 'Roboto-Regular.ttf'))
        pdfmetrics.registerFont(TTFont('Roboto-Bold', 'Roboto-Bold.ttf'))
        return "Roboto", "Roboto-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

M_FONT, B_FONT = register_fonts()

st.set_page_config(page_title="Interfood Profi v6.1", layout="wide")
st.title("🚚 Interfood Etikett v6.1")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def extract_v61(pdf_file):
    try:
        reader = PdfReader(pdf_file)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
        
        # Keressük az ügyfélkódokat (P- vagy Z- után 6 számjegy)
        # Ez a legbiztosabb pont a PDF-ben
        matches = list(re.finditer(r'([PZSC])-(\d{6})', full_text))
        st.write(f"🔍 Debug: {len(matches)} ügyfélkódot találtam a PDF-ben.")
        
        customers = {}
        for i, match in enumerate(matches):
            day_type = match.group(1)
            cust_code = match.group(2)
            
            # Kikeressük a két kód közötti szövegrészletet (ez egy ügyfél adata)
            start = match.start()
            end = matches[i+1].start() if i+1 < len(matches) else len(full_text)
            block = full_text[start:end]
            
            if cust_code not in customers:
                # NÉV KERESÉSE (A kód utáni első értelmes szöveg, ami nem cím)
                name = "Ismeretlen Ügyfél"
                lines = [l.strip() for l in block.split('\n') if len(l.strip()) > 2]
                for line in lines:
                    if not any(x in line for x in ["Debrecen", "Ft", "Tel:", "P-", "Z-", "403"]):
                        name = line.split('/')[1].strip() if '/' in line else line
                        break
                
                # CÍM KERESÉSE (40-nel kezdődő irányítószám)
                cim = ""
                cim_match = re.search(r'(40\d{2}\s+Debrecen,.*)', block)
                if cim_match:
                    cim = cim_match.group(1).split('\n')[0]

                customers[cust_code] = {
                    'kod': cust_code, 'nev': name, 'cim': cim,
                    'P_rend': [], 'Z_rend': [], 'is_z': False
                }
            
            # RENDELÉSEK (1-A1 formátum)
            codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', block)
            if day_type == 'Z':
                customers[cust_code]['Z_rend'].extend(codes)
                customers[cust_code]['is_z'] = True
            else:
                customers[cust_code]['P_rend'].extend(codes)

        return list(customers.values())
    except Exception as e:
        st.error(f"❌ Hiba a PDF feldolgozása közben: {e}")
        return []

uploaded_file = st.file_uploader("Töltsd fel a Menettervet!", type="pdf")

if uploaded_file:
    data = extract_v61(uploaded_file)
    
    if not data:
        st.warning("⚠️ Nem sikerült adatokat kinyerni. Ellenőrizd a PDF formátumát!")
    else:
        output = io.BytesIO()
        p = canvas.Canvas(output, pagesize=A4)
        cw, ch = (A4[0]-20)/3, (A4[1]-40)/7

        # 21 etikett helye (7 sor x 3 oszlop)
        total_slots = ((len(data)-1)//21 + 1) * 21
        
        for i in range(total_slots):
            if i > 0 and i % 21 == 0: p.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * cw, 20 + row * ch
            
            # Keret rajzolása
            p.setStrokeColorRGB(0.8, 0.8, 0.8) # Világosszürke keret
            p.rect(x+2, y+2, cw-4, ch-4)
            p.setFillColorRGB(0, 0, 0)

            if i < len(data):
                item = data[i]
                # FEJLÉC
                if item['is_z']:
                    p.setFillColorRGB(0.1, 0.1, 0.1)
                    p.rect(x+2, y+ch-12, cw-4, 10, fill=1)
                    p.setFillColorRGB(1, 1, 1)
                    p.setFont(B_FONT, 8)
                    p.drawCentredString(x+cw/2, y+ch-9, "SZOMBATI RENDELÉS IS!")
                
                p.setFillColorRGB(0, 0, 0)
                # NÉV és KÓD
                p.setFont(B_FONT, 10)
                p.drawString(x+8, y+ch-25, str(item['nev'])[:22])
                p.drawRightString(x+cw-10, y+ch-25, str(item['kod']))
                
                # CÍM
                p.setFont(M_FONT, 8)
                p.drawString(x+8, y+ch-35, str(item['cim'])[:40])
                
                # RENDELÉS
                p.setFont(B_FONT, 10)
                p_text = f"P: {', '.join(set(item['P_rend']))}" if item['P_rend'] else ""
                z_text = f"Sz: {', '.join(set(item['Z_rend']))}" if item['Z_rend'] else ""
                if p_text: p.drawString(x+8, y+20, p_text[:35])
                if z_text: p.drawString(x+8, y+10, z_text[:35])
            else:
                # FIX MARKETING (Ha nincs több ügyfél)
                p.setFont(B_FONT, 12)
                p.drawCentredString(x+cw/2, y+ch-25, "ÚJ ÜGYFÉL AKCIÓ")
                p.setFont(M_FONT, 9)
                p.drawCentredString(x+cw/2, y+ch/2, "15% kedvezmény!")
                p.setFont(B_FONT, 10)
                p.drawCentredString(x+cw/2, y+15, f"{input_nev}")
                p.drawCentredString(x+cw/2, y+5, f"{input_tel}")

        p.save()
        st.success(f"✅ Elkészült {len(data)} ügyfél etikettje!")
        st.download_button("📥 PDF LETÖLTÉSE", output.getvalue(), "interfood_etikett.pdf")
