import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- Konfiguráció és Betűtípusok ---
st.set_page_config(page_title="Interfood Etikett v8.5", layout="wide")

def get_fonts():
    try:
        # Alapértelmezett Helvetica, ha nincs betöltve egyedi font
        return "Helvetica", "Helvetica-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

M_FONT, B_FONT = get_fonts()

# --- Felület ---
st.title("🚚 Interfood Etikett Generátor v8.5")
st.markdown("Adatkinyerés táblázatos PDF struktúrából (pdfplumber).")

with st.sidebar:
    st.header("Futár adatai")
    futar_nev = st.text_input("Saját Név:", value="Ebéd Elek")
    futar_tel = st.text_input("Saját Tel:", value="+3620/7654321")
    st.divider()
    uploaded_file = st.file_uploader("Válaszd ki a Menetterv PDF-et", type="pdf")

# --- Adatfeldolgozó Logika ---
def extract_interfood_data(pdf_file):
    extracted_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            })
            
            if not table: continue
            
            for row in table:
                # row[0]: Sorszám (pl. 1, 2, 3...)
                sorszam_raw = str(row[0]).strip() if row[0] else ""
                
                # Csak a számmal kezdődő sorokat dolgozzuk fel (Sorszám oszlop)
                if not re.match(r'^\d+$', sorszam_raw.split('\n')[0]):
                    continue
                
                content_col = row[1] if row[1] else ""
                order_col = row[3] if row[3] else ""
                
                # Ügyfélkód kinyerése (P-123456)
                kod_match = re.search(r'([PZSC]-\d{6})', content_col)
                kod = kod_match.group(1) if kod_match else ""
                
                # Cím: 40xx Debrecen...
                addr_match = re.search(r'(\d{4}\s+Debrecen,.*)', content_col, re.DOTALL)
                cim = addr_match.group(1).replace('\n', ' ').strip() if addr_match else "Cím nem található"
                
                # Név: A cella első sora a kód után
                nev_parts = content_col.replace(kod, "").strip().split('\n')
                nev = nev_parts[0].strip() if nev_parts else "Ismeretlen"
                
                # Telefon és Rendelések a 4. oszlopból (Index 3)
                tel_match = re.search(r'(\d{2}/\d{3,}-?\d{3,})', order_col)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]{1,4})', order_col)
                
                # Megjegyzés kinyerése (pl. Kapukód)
                megj = ""
                if "kapukód" in content_col.lower():
                    m = re.search(r'(kapukód:?\s*[^\n]+)', content_col, re.IGNORECASE)
                    megj = m.group(1) if m else ""

                extracted_data.append({
                    'sorszam': sorszam_raw.split('\n')[0],
                    'nev': nev[:25],
                    'cim': cim,
                    'tel': tel_match.group(1) if tel_match else "",
                    'rendelesek': rendelesek,
                    'kod': kod,
                    'megjegyzes': megj
                })
    return extracted_data

# --- PDF Generálás (3x7-es etikett) ---
def create_label_pdf(data, f_nev, f_tel):
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=A4)
    width, height = A4
    
    cols, rows = 3, 7
    label_w = (width - 20) / cols
    label_h = (height - 40) / rows
    
    for i in range(len(data)):
        if i > 0 and i % (cols * rows) == 0:
            c.showPage()
            
        idx = i % (cols * rows)
        col = idx % cols
        row = rows - 1 - (idx // cols)
        
        x, y = 10 + col * label_w, 20 + row * label_h
        
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(x + 2, y + 2, label_w - 4, label_h - 4)
        
        u = data[i]
        c.setFillColorRGB(0, 0, 0)
        
        # Adatok felírása
        c.setFont(B_FONT, 10)
        c.drawString(x + 8, y + label_h - 15, f"{u['sorszam']}.")
        c.drawRightString(x + label_w - 10, y + label_h - 15, f"{len(u['rendelesek'])} db")
        
        c.setFont(B_FONT, 11)
        c.drawString(x + 8, y + label_h - 28, u['nev'])
        
        c.setFont(M_FONT, 9)
        c.drawString(x + 8, y + label_h - 40, f"Tel: {u['tel']}")
        
        c.setFont(M_FONT, 8)
        c_text = u['cim']
        if len(c_text) > 38:
            c.drawString(x + 8, y + label_h - 52, c_text[:38])
            c.drawString(x + 8, y + label_h - 62, c_text[38:76])
        else:
            c.drawString(x + 8, y + label_h - 52, c_text)
            
        rend_str = ", ".join(u['rendelesek'])
        c.setFont(B_FONT, 8)
        c.drawString(x + 8, y + 25, f"Kód: {rend_str[:40]}")
        
        if u['megjegyzes']:
            c.setFont(M_FONT, 7)
            c.drawString(x + 8, y + 16, u['megjegyzes'][:45])

        c.setFont(M_FONT, 7)
        c.drawString(x + 8, y + 6, f"Futár: {f_nev} | {f_tel}")

    c.save()
    return output.getvalue()

# --- Fő folyamat ---
if uploaded_file:
    with st.spinner("Processing..."):
        try:
            data = extract_interfood_data(uploaded_file)
            if data:
                st.success(f"Beolvasva: {len(data)} ügyfél.")
                
                # Itt volt a hiba: most már a 'pd' (pandas) definiálva van!
                with st.expander("Előnézet (első 10 sor)"):
                    st.table(pd.DataFrame(data).head(10))
                
                pdf_bytes = create_label_pdf(data, futar_nev, futar_tel)
                st.download_button("📥 PDF Letöltése", pdf_bytes, "interfood_v85.pdf", "application/pdf")
            else:
                st.warning("Nem sikerült adatokat kinyerni. Ellenőrizd a PDF-et!")
        except Exception as e:
            st.error(f"Hiba történt: {e}")
