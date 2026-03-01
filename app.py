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
        # Itt fontos, hogy a .ttf fájlok ott legyenek a script mellett!
        pdfmetrics.registerFont(TTFont('Roboto-Bold', 'Roboto-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('Roboto-Regular', 'Roboto-Regular.ttf'))
        return "Roboto-Regular", "Roboto-Bold"
    except: 
        return "Helvetica", "Helvetica-Bold"

M_FONT, B_FONT = get_fonts()

st.set_page_config(page_title="Interfood v8.1", layout="wide")
st.title("🚚 Interfood Etikett v8.1 - Stabilizált")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_v8(uploaded_file):
    reader = PdfReader(uploaded_file)
    customers = {}
    
    for page in reader.pages:
        text = page.extract_text()
        if not text: continue
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            # Kibővített kódkeresés (S, C, Z, P betűkre is)
            id_match = re.search(r'([PZSC])-(\d{6})', line)
            if id_match:
                day_type = id_match.group(1)
                cust_id = id_match.group(2)
                
                # SORSZÁM: Ha a sor elején van szám, az a sorszám
                sorszam = "?"
                s_match = re.match(r'^(\d{1,3})', line.strip())
                if s_match:
                    sorszam = s_match.group(1)
                elif i > 0:
                    s_match_prev = re.match(r'^(\d{1,3})$', lines[i-1].strip())
                    if s_match_prev:
                        sorszam = s_match_prev.group(1)

                if cust_id not in customers:
                    customers[cust_id] = {
                        'kod': cust_id, 
                        'sorszamok': {sorszam} if sorszam != "?" else set(),
                        'nev': "Ügyfél",
                        'cim': "", 
                        'P_rend': [], 'Z_rend': [], 'is_z': False
                    }
                else:
                    if sorszam != "?": customers[cust_id]['sorszamok'].add(sorszam)

                # NÉV ÉS CÍM: Ha a sorban benne van a kód, próbáljuk meg tisztítani
                clean_line = line.replace(id_match.group(0), "").strip()
                
                # Cím keresése (Irányítószám alapján)
                addr_match = re.search(r'(\d{4}\s+Debrecen[^\n,]+)', line)
                if addr_match: 
                    customers[cust_id]['cim'] = addr_match.group(1)
                    # Ami a cím előtt van, az lesz a név
                    potential_name = clean_line.split(addr_match.group(1))[0].strip()
                    if len(potential_name) > 2:
                        customers[cust_id]['nev'] = potential_name

                # ÉTELKÓDOK: A jelenlegi és a következő 2 sort nézzük
                for l in lines[i:i+3]:
                    codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', l)
                    if day_type in ['Z', 'S']:
                        customers[cust_id]['Z_rend'].extend(codes)
                    else:
                        customers[cust_id]['P_rend'].extend(codes)

    # Tisztítás a végén (halmazzá alakítás, hogy ne legyenek duplikátumok)
    for c in customers.values():
        c['P_rend'] = sorted(list(set(c['P_rend'])))
        c['Z_rend'] = sorted(list(set(c['Z_rend'])))

    return list(customers.values())

file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if file:
    data = process_v8(file)
    if data:
        st.success(f"Beolvasva: {len(data)} ügyfél") # Visszajelzés a felhasználónak
        
        out = io.BytesIO()
        c = canvas.Canvas(out, pagesize=A4)
        w, h = (A4[0]-20)/3, (A4[1]-40)/7
        
        for i in range(((len(data)-1)//21 + 1) * 21):
            if i > 0 and i % 21 == 0: c.showPage()
            col, row = (i % 21) % 3, 6 - ((i % 21) // 3)
            x, y = 10 + col * w, 20 + row * h
            
            # Keret színe
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.rect(x+2, y+2, w-4, h-4)

            if i < len(data):
                u = data[i]
                c.setFillColorRGB(0, 0, 0)
                
                # Sorszámok rendezve
                s_list = sorted(list(u['sorszamok']), key=lambda x: int(x) if x.isdigit() else 999)
                s_str = (" + ".join(s_list) + ".") if s_list else ""
                c.setFont(B_FONT, 10)
                c.drawString(x+8, y+h-15, s_str)

                # Név és Kód
                c.setFont(B_FONT, 11)
                # Név tisztítása a felesleges karakterektől
                d_name = u['nev'].replace('/', '').split('40')[0].strip()
                c.drawString(x+8, y+h-28, d_name[:22])
                c.drawRightString(x+w-10, y+h-28, u['kod'])
                
                # Cím
                c.setFont(M_FONT, 8.5)
                display_addr = u['cim'] if u['cim'] else "Debrecen (cím a PDF-ben)"
                c.drawString(x+8, y+h-40, display_addr[:38])
                
                # Rendelések
                c.setFont(B_FONT, 10)
                if u['P_rend']: c.drawString(x+8, y+22, f"P: {', '.join(u['P_rend'])}"[:35])
                if u['Z_rend']: c.drawString(x+8, y+10, f"Sz: {', '.join(u['Z_rend'])}"[:35])

                # Lábléc
                c.setFont(M_FONT, 7.5)
                c.drawString(x+8, y+4, f"{input_nev} | {input_tel}")
            else:
                # Üres helyekre reklám
                c.setFont(B_FONT, 11)
                c.drawCentredString(x+w/2, y+h/2 + 5, "15% KEDVEZMÉNY")
                c.setFont(M_FONT, 8)
                c.drawCentredString(x+w/2, y+h/2 - 10, "AZ ELSŐ RENDELÉSBŐL")
                c.drawCentredString(x+w/2, y+10, f"{input_nev} {input_tel}")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V8.1)", out.getvalue(), "interfood_v8_1.pdf")
