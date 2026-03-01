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

st.set_page_config(page_title="Interfood v8.4", layout="wide")
st.title("🚚 Interfood Etikett v8.4 - Ügyintéző adatokkal")

input_nev = st.sidebar.text_input("Saját Név:", value="Szűcs István")
input_tel = st.sidebar.text_input("Saját Tel:", value="+36208868971")

def process_v8_4(uploaded_file):
    reader = PdfReader(uploaded_file)
    customers = []
    
    all_text = ""
    for page in reader.pages:
        all_text += page.extract_text() + "\n---PAGE---\n"
    
    # Keressük az ügyfél blokkokat. A kód (P-123456) a fix pontunk.
    # Spliteljük a szöveget a kódok mentén, de tartsuk meg a kódokat.
    raw_blocks = re.split(r'([PZSC]-\d{6})', all_text)
    
    # Az első elem a fejléc, azt eldobjuk
    for i in range(1, len(raw_blocks), 2):
        full_code = raw_blocks[i]      # pl. P-428867
        block_content = raw_blocks[i+1] # A kód utáni szöveg a következő kódig
        
        cust_id = full_code.split('-')[1]
        
        # ÜGYFÉL TELEFON (pl. 30/6707456 vagy 0630...)
        tel_match = re.search(r'(\d{2}/\d{3,}-?\d{3,})', block_content)
        u_tel = tel_match.group(1) if tel_match else ""
        
        # CÍM (Irányítószámtól Debrecenig)
        addr_match = re.search(r'(\d{4}\s+Debrecen,[^,\n]+)', block_content)
        u_cim = addr_match.group(1).strip() if addr_match else "Debrecen"
        
        # ÜGYINTÉZŐ NEVE
        # A PDF-ben az ügyintéző neve az ügyfél neve/címe után, de a telefon előtt van.
        # Megpróbáljuk kiszedni a blokk elejéről, ami nem a cím.
        clean_content = block_content.replace(u_cim, "").replace(u_tel, "").strip()
        lines = [l.strip() for l in clean_content.split('\n') if len(l.strip()) > 2]
        u_nev = lines[0] if lines else "Ügyfél"

        # RENDELÉSEK
        codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', block_content)
        
        customers.append({
            'kod': cust_id,
            'sorszam': len(customers) + 1,
            'nev': u_nev[:25],
            'tel': u_tel,
            'cim': u_cim,
            'rendelesek': sorted(list(set(codes)))
        })
        
    return customers

file = st.file_uploader("Menetterv PDF feltöltése", type="pdf")

if file:
    data = process_v8_4(file)
    if data:
        st.success(f"Beolvasva: {len(data)} ügyfél")
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
                
                # SORSZÁM (Kisebb, ahogy kérted)
                c.setFont(B_FONT, 10)
                c.drawString(x+8, y+h-15, f"{u['sorszam']}.")
                
                # ÖSSZESÍTŐ
                c.drawRightString(x+w-10, y+h-15, f"Össz: {len(u['rendelesek'])} db")

                # ÜGYINTÉZŐ NEVE + KÓD
                c.setFont(B_FONT, 11)
                c.drawString(x+8, y+h-28, u['nev'])
                c.setFont(M_FONT, 8)
                c.drawRightString(x+w-10, y+h-28, u['kod'])
                
                # ÜGYFÉL TELEFONJA (Új elem!)
                if u['tel']:
                    c.setFont(B_FONT, 9)
                    c.drawString(x+8, y+h-38, f"Tel: {u['tel']}")
                
                # CÍM (Új sorban, elkülönítve)
                c.setFont(M_FONT, 8)
                y_addr = y+h-48 if u['tel'] else y+h-38
                c.drawString(x+8, y_addr, u['cim'][:38])
                
                # RENDELÉSEK
                rend_str = ", ".join(u['rendelesek'])
                f_size = 9 if len(rend_str) < 30 else 7.5
                c.setFont(B_FONT, f_size)
                
                if len(rend_str) > 40:
                    c.drawString(x+8, y+22, rend_str[:40])
                    c.drawString(x+8, y+12, rend_str[40:80])
                else:
                    c.drawString(x+8, y+18, rend_str)

                # LÁBLÉC (Saját adatok)
                c.setFont(M_FONT, 7)
                c.drawString(x+8, y+5, f"{input_nev} | {input_tel}")
            else:
                c.setFont(M_FONT, 8)
                c.drawCentredString(x+w/2, y+h/2, "---")

        c.save()
        st.download_button("📥 PDF LETÖLTÉSE (V8.4)", out.getvalue(), "interfood_v8_4.pdf")
