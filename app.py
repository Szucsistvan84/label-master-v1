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



st.set_page_config(page_title="Interfood v8.0", layout="wide")

st.title("🚚 Interfood Etikett v8.0 - Táblázatkezelő")



input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")

input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")



def process_v8(uploaded_file):

    reader = PdfReader(uploaded_file)

    customers = {}

    

    for page in reader.pages:

        text = page.extract_text()

        # A táblázat sorait általában az új sor karakterek mentén kapjuk meg

        lines = text.split('\n')

        

        for i, line in enumerate(lines):

            # Keressük az ügyfélkódot (P-123456 vagy Z-123456)

            id_match = re.search(r'([PZSC])-(\d{6})', line)

            if id_match:

                day_type = id_match.group(1)

                cust_id = id_match.group(2)

                

                # 1. SORSZÁM KERESÉSE: A sor elején vagy az előző sorban

                # Megnézzük a sor elejét, hátha ott a sorszám

                sorszam = "?"

                s_match = re.match(r'^(\d{1,3})', line.strip())

                if s_match:

                    sorszam = s_match.group(1)

                elif i > 0: # Ha nincs ott, megnézzük az előző sort

                    s_match_prev = re.match(r'^(\d{1,3})$', lines[i-1].strip())

                    if s_match_prev:

                        sorszam = s_match_prev.group(1)



                # 2. NÉV ÉS CÍM KERESÉSE (Szigorúbban)

                # A név általában az "Ügyintéző" oszlopban van, vagy a kód mellett

                name = "Ügyfél"

                address = ""

                

                # Próbáljuk kinyerni a nevet a sorból (kiszűrve a kódokat)

                parts = line.split(id_match.group(0))

                potential_name = parts[-1].strip() if len(parts) > 1 else ""

                

                # Ha a sorban van irányítószám, az a cím

                if "40" in line and "Debrecen" in line:

                    addr_match = re.search(r'(40\d{2}\s+Debrecen[^\n,]+)', line)

                    if addr_match: address = addr_match.group(1)



                if cust_id not in customers:

                    customers[cust_id] = {

                        'kod': cust_id, 'sorszamok': {sorszam} if sorszam != "?" else set(),

                        'nev': potential_name if len(potential_name) > 3 else "Ügyfél",

                        'cim': address, 'P_rend': [], 'Z_rend': [], 'is_z': False

                    }

                else:

                    if sorszam != "?": customers[cust_id]['sorszamok'].add(sorszam)



                # 3. ÉTELKÓDOK KERESÉSE (A sorban vagy az alatta lévőben)

                look_range = lines[i:i+3] # Megnézzük ezt a sort és a következő kettőt

                for l in look_range:

                    codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', l)

                    if day_type == 'Z':

                        customers[cust_id]['Z_rend'].extend(codes)

                        customers[cust_id]['is_z'] = True

                    else:

                        customers[cust_id]['P_rend'].extend(codes)



    return list(customers.values())



file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")



if file:

    data = process_v8(file)

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

                # Sorszám

                s_list = sorted(list(u['sorszamok']), key=lambda x: int(x) if x.isdigit() else 999)

                s_str = (" + ".join(s_list) + ".") if s_list else ""

                c.setFont(B_FONT, 10)

                c.drawString(x+8, y+h-15, s_str)



                # Név és Kód

                c.setFont(B_FONT, 11)

                display_name = u['nev'].split('/')[0].split('40')[0].strip()

                c.drawString(x+8, y+h-28, display_name[:20])

                c.drawRightString(x+w-10, y+h-28, u['kod'])

                

                # Cím (Ha üres, próbálunk menteni valamit)

                c.setFont(M_FONT, 8.5)

                c.drawString(x+8, y+h-40, u['cim'][:38] if u['cim'] else "Debrecen (cím a PDF-ben)")

                

                # Rendelések

                c.setFont(B_FONT, 10)

                p_set = sorted(list(set(u['P_rend'])))

                z_set = sorted(list(set(u['Z_rend'])))

                if p_set: c.drawString(x+8, y+22, f"P: {', '.join(p_set)}"[:35])

                if z_set: c.drawString(x+8, y+10, f"Sz: {', '.join(z_set)}"[:35])



                # Lábléc

                c.setFont(M_FONT, 7.5)

                c.drawString(x+8, y+4, f"{input_nev} | {input_tel}")

            else:

                # Marketing

                c.setFont(B_FONT, 12)

                c.drawCentredString(x+w/2, y+h-30, "15% KEDVEZMÉNY")

                c.setFont(M_FONT, 9)

                c.drawCentredString(x+w/2, y+15, f"{input_nev}")

                c.drawCentredString(x+w/2, y+6, f"{input_tel}")



        c.save()

        st.download_button("📥 PDF LETÖLTÉSE (V8.0)", out.getvalue(), "interfood_v8.pdf")
