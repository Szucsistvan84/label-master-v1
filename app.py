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

st.set_page_config(page_title="Interfood v8.3", layout="wide")
st.title("🚚 Interfood Etikett v8.3 - Intelligens Újraszámozó")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_v8_3(uploaded_file):
    reader = PdfReader(uploaded_file)
    customers = {}
    ordered_ids = [] # A sorrend megtartásához
    
    # 1. Minden szöveg kinyerése egy nagy listába
    all_lines = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            all_lines.extend([l.strip() for l in text.split('\n') if l.strip()])

    # 2. Feldolgozás blokkokban
    current_cust_id = None
    
    for i, line in enumerate(all_lines):
        # Kód keresése (P-123456, Z-123456, stb.)
        id_match = re.search(r'([PZSC])-(\d{6})', line)
        
        if id_match:
            day_type = id_match.group(1)
            cust_id = id_match.group(2)
            
            if cust_id not in customers:
                current_cust_id = cust_id
                ordered_ids.append(cust_id)
                # Név kinyerése a kód mellől
                name_candidate = line.replace(id_match.group(0), "").strip()
                
                customers[cust_id] = {
                    'kod': cust_id,
                    'auto_sorszam': len(ordered_ids),
                    'nev': name_candidate if len(name_candidate) > 2 else "Ügyfél",
                    'cim': "Debrecen",
                    'rendelesek': set()
                }
            
            # Ha már megvan az ügyfél, adjuk hozzá a rendelést a környezetből
            # Megnézzük a sorban lévő ételkódokat
            codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
            if codes:
                customers[cust_id]['rendelesek'].update(codes)
        
        # Ha nincs új kód, de van egy aktív ügyfelünk, keressük a címet (Debrecen)
        elif current_cust_id:
            if "Debrecen" in line and customers[current_cust_id]['cim'] == "Debrecen":
                customers[current_cust_id]['cim'] = line
            # Ha ételkódot találunk a kód alatti sorokban
            codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', line)
            if codes:
                customers[current_cust_id]['rendelesek'].update(codes)

    # Lista összeállítása a sorrend alapján
    final_data = []
    for cid in ordered_ids:
        c = customers[cid]
        c['rend_lista'] = sorted(list(c['rendelesek']))
        c['total'] = len(c['rend_lista'])
        final_data.append(c)
        
    return final_data

file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if file:
    data = process_v8_3(file)
    if data:
        st.success(f"Sikeresen beolvasva {len(data)} címke.")
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
                
                # BAL FELSŐ: SAJÁT SORSZÁM (NAGYOBB)
                c.setFont(B_FONT, 14)
                c.drawString(x+8, y+h-18, f"{u['auto_sorszam']}.")
                
                # JOBB FELSŐ: ÖSSZESÍTŐ
                c.setFont(B_FONT, 10)
                c.drawRightString(x+w-10, y+h-15, f"Össz: {u['total']} db")

                # NÉV ÉS KÓD
                c.setFont(B_FONT, 10)
                name_display = u['nev'].split('/')[0].strip()[:25]
                c.drawString(x+8, y+h-32, name_display)
                c.setFont(M_FONT, 8)
                c.drawRightString(x+w-10, y+h-32, u['kod'])
                
                # CÍM
                c.setFont(M_FONT, 8)
                c.drawString(x+8, y+h-42, u['cim'][:40])
                
                # RENDELÉSEK (Kisebb betűvel a zsúfoltság ellen)
                rend_str = ", ".join(u['rend_lista'])
                f_size = 9 if len(rend_str) < 30 else 7.5
                c.setFont(B_FONT, f_size)
                
                # Sortörés kezelése, ha túl hosszú a rendelés
                if len(rend_str) > 40:
                    c.drawString(x+8, y+22, rend_str[:40])
                    c.drawString(x+8, y+12, rend_str[40:80])
                else:
                    c.drawString(x+8, y+18, rend_str)

                # LÁBLÉC
                c.setFont(M_FONT, 7)
                c.drawString(x+8, y+5, f"{input_nev} | {input_tel}")
            else:
                # Üres helyek kitöltése
                c.setFont(B_FONT, 10)
                c.drawCentredString(x+w/2, y+h/2, "ÜRES CÍMKE")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V8.3)", out.getvalue(), "interfood_v8_3.pdf")
