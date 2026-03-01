import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- Konfiguráció ---
st.set_page_config(page_title="Interfood Etikett v8.7", layout="wide")

with st.sidebar:
    st.header("Futár adatai")
    futar_nev = st.text_input("Saját Név:", value="Ebéd Elek")
    futar_tel = st.text_input("Saját Tel:", value="+3620/7654321")
    st.divider()
    uploaded_file = st.file_uploader("Válaszd ki a Menetterv PDF-et", type="pdf")

def extract_v8_7(pdf_file):
    extracted_data = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            # Keressük az ügyfél blokkokat (Sorszám + Kód kombinációja)
            # Példa: "10 P-410511"
            lines = text.split('\n')
            
            current_cust = None
            
            for line in lines:
                line = line.strip()
                
                # 1. ÚJ ÜGYFÉL INDÍTÁSA: Ha a sor elején sorszám van (1-101)
                # Az Interfood PDF-ben a sorszám után gyakran ott a kód: "10 P-465258"
                sorszam_match = re.match(r'^(\d{1,3})\s+([PZSC]-\d{6})?\s*(.*)', line)
                
                if sorszam_match:
                    if current_cust: extracted_data.append(current_cust)
                    
                    s_num = sorszam_match.group(1)
                    kod = sorszam_match.group(2) if sorszam_match.group(2) else ""
                    maradek = sorszam_match.group(3).strip()
                    
                    current_cust = {
                        'sorszam': s_num,
                        'kod': kod,
                        'nev': maradek if maradek else "Feldolgozás...",
                        'cim': "",
                        'tel': "",
                        'rendelesek': [],
                        'megjegyzes': ""
                    }
                    continue
                
                if not current_cust: continue
                
                # 2. TELEFON KERESÉS
                tel_match = re.search(r'(\d{2}/\d{3,}-?\d{3,})', line)
                if tel_match:
                    current_cust['tel'] = tel_match.group(1)
                
                # 3. RENDELÉS KERESÉS (pl. 1-L1K)
                rend_matches = re.findall(r'(\d+-[A-Z0-9]{1,4})', line)
                if rend_matches:
                    current_cust['rendelesek'].extend(rend_matches)
                
                # 4. CÍM KERESÉS (40xx Debrecen)
                if "Debrecen" in line:
                    current_cust['cim'] = line
                elif not current_cust['cim'] and re.match(r'^\d{4}\s+', line):
                    current_cust['cim'] = line
                
                # 5. NÉV FINOMÍTÁS (Ha az első sorban nem volt meg)
                if current_cust['nev'] == "Feldolgozás..." and len(line) > 3 and not any(x in line for x in ["Debrecen", "30/", "20/", "70/"]):
                    current_cust['nev'] = line

                # 6. MEGJEGYZÉS (pl. kapukód)
                if any(x in line.lower() for x in ["kapu", "kcs", "porta", "kulcs"]):
                    current_cust['megjegyzes'] = line

    if current_cust: extracted_data.append(current_cust)
    return extracted_data

# --- PDF Generálás (3x7-es) ---
def create_label_pdf(data, f_nev, f_tel):
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    cols, rows = 3, 7
    label_w, label_h = (width - 20) / cols, (height - 40) / rows
    
    for i in range(len(data)):
        if i > 0 and i % 21 == 0: c.showPage()
        idx = i % 21
        col, row = idx % 3, 6 - (idx // 3)
        x, y = 10 + col * label_w, 20 + row * label_h
        
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(x + 2, y + 2, label_w - 4, label_h - 4)
        
        u = data[i]
        c.setFillColorRGB(0, 0, 0)
        
        # Sorszám és Darab
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 8, y + label_h - 15, f"{u['sorszam']}.")
        c.drawRightString(x + label_w - 10, y + label_h - 15, f"{len(u['rendelesek'])} db")
        
        # Név
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 8, y + label_h - 28, u['nev'][:25])
        
        # Telefon és Cím
        c.setFont("Helvetica", 8)
        c.drawString(x + 8, y + label_h - 40, f"Tel: {u['tel']}")
        c.drawString(x + 8, y + label_h - 50, u['cim'][:38])
        
        # Rendelések
        rend_str = ", ".join(u['rendelesek'])
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 8, y + 20, f"Kódok: {rend_str[:40]}")
        
        # Futár (Lábléc)
        c.setFont("Helvetica", 7)
        c.drawString(x + 8, y + 8, f"{f_nev} | {f_tel}")
    
    c.save()
    return output.getvalue()

# --- Fő folyamat ---
if uploaded_file:
    data = extract_v8_7(uploaded_file)
    if data:
        st.success(f"Beolvasva: {len(data)} ügyfél")
        st.table(pd.DataFrame(data).head(10)) # Itt látni fogod az eredményt!
        
        pdf_bytes = create_label_pdf(data, futar_nev, futar_tel)
        st.download_button("📥 PDF Letöltése", pdf_bytes, "etikett_v87.pdf")
