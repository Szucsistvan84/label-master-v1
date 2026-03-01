import streamlit as st
import pdfplumber
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
        # Ha van saját TTF fájlod, itt töltheted be
        pdfmetrics.registerFont(TTFont('Roboto-Bold', 'Roboto-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('Roboto-Regular', 'Roboto-Regular.ttf'))
        return "Roboto-Regular", "Roboto-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

M_FONT, B_FONT = get_fonts()

# --- Felület ---
st.title("🚚 Interfood Etikett Generátor v8.5")
st.markdown("A rendszer **pdfplumber** technológiával olvassa a táblázatokat a pontosabb kinyerés érdekében.")

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
            # Táblázat kinyerése rácsvonalak alapján
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            })
            
            if not table: continue
            
            for row in table:
                # row[0]: Sorszám, row[1]: Ügyfél/Cím, row[2]: Ügyintéző, row[3]: Telefon/Rendelés
                sorszam_raw = str(row[0]).strip() if row[0] else ""
                
                # Csak a számmal kezdődő sorokat dolgozzuk fel
                if not re.match(r'^\d+$', sorszam_raw):
                    continue
                
                content_col = row[1] if row[1] else ""
                order_col = row[3] if row[3] else ""
                
                # Adat kinyerés RegEx-el a cellán belül
                kod_match = re.search(r'([PZSC]-\d{6})', content_col)
                kod = kod_match.group(1) if kod_match else ""
                
                # Cím: Irányítószámtól a végéig (vagy következő sorig)
                addr_match = re.search(r'(\d{4}\s+Debrecen,.*)', content_col, re.DOTALL)
                cim = addr_match.group(1).replace('\n', ' ').strip() if addr_match else "Cím nem található"
                
                # Név: A kód utáni első sor
                nev_lines = content_col.replace(kod, "").strip().split('\n')
                nev = nev_lines[0].strip() if nev_lines else "Ismeretlen"
                
                # Telefon és Rendelések a 3. oszlopból
                tel_match = re.search(r'(\d{2}/\d{3,}-?\d{3,})', order_col)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]{1,4})', order_col)
                
                # Megjegyzés keresése (pl. kapukód)
                megj = ""
                if "kapukód" in content_col.lower():
                    m = re.search(r'(kapukód:?\s*[^\n]+)', content_col, re.IGNORECASE)
                    megj = m.group(1) if m else ""

                extracted_data.append({
                    'sorszam': sorszam_raw,
                    'nev': nev[:30],
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
    
    # Margók és méretek
    cols = 3
    rows = 7
    label_w = (width - 20) / cols
    label_h = (height - 40) / rows
    
    for i in range(len(data)):
        if i > 0 and i % (cols * rows) == 0:
            c.showPage()
            
        idx = i % (cols * rows)
        col = idx % cols
        row = rows - 1 - (idx // cols)
        
        x = 10 + col * label_w
        y = 20 + row * label_h
        
        # Keret rajzolása
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(x + 2, y + 2, label_w - 4, label_h - 4)
        
        u = data[i]
        c.setFillColorRGB(0, 0, 0)
        
        # 1. Sor: Sorszám és Darabszám
        c.setFont(B_FONT, 10)
        c.drawString(x + 8, y + label_h - 15, f"{u['sorszam']}.")
        c.drawRightString(x + label_w - 10, y + label_h - 15, f"{len(u['rendelesek'])} db")
        
        # 2. Sor: Név
        c.setFont(B_FONT, 11)
        c.drawString(x + 8, y + label_h - 28, u['nev'])
        
        # 3. Sor: Telefon
        c.setFont(M_FONT, 9)
        c.drawString(x + 8, y + label_h - 40, f"Tel: {u['tel']}")
        
        # 4. Sor: Cím (tördelve, ha hosszú)
        c.setFont(M_FONT, 8)
        c_text = u['cim']
        if len(c_text) > 40:
            c.drawString(x + 8, y + label_h - 52, c_text[:40])
            c.drawString(x + 8, y + label_h - 62, c_text[40:80])
        else:
            c.drawString(x + 8, y + label_h - 52, c_text)
            
        # 5. Rendelések kódjai
        rend_str = ", ".join(u['rendelesek'])
        c.setFont(B_FONT, 8)
        c.drawString(x + 8, y + 25, f"Kódok: {rend_str[:45]}")
        
        # Megjegyzés (ha van)
        if u['megjegyzes']:
            c.setFont(M_FONT, 7)
            c.setFillColorRGB(0.8, 0, 0) # Pirosas szín a figyelemfelhíváshoz
            c.drawString(x + 8, y + 15, u['megjegyzes'][:45])
            c.setFillColorRGB(0, 0, 0)

        # Lábléc: Futár adatai
        c.setFont(M_FONT, 7)
        c.drawString(x + 8, y + 6, f"Futár: {f_nev} | {f_tel}")

    c.save()
    return output.getvalue()

# --- Fő folyamat ---
if uploaded_file:
    with st.spinner("Adatok beolvasása folyamatban..."):
        try:
            data = extract_interfood_data(uploaded_file)
            if data:
                st.success(f"Sikeresen beolvasva: {len(data)} ügyfél.")
                
                # Táblázatos előnézet (opcionális, ellenőrzéshez)
                with st.expander("Beolvasott adatok ellenőrzése"):
                    st.table(pd.DataFrame(data).head(10))
                
                # PDF generálás gomb
                pdf_bytes = create_label_pdf(data, futar_nev, futar_tel)
                st.download_button(
                    label="📥 Etikett PDF letöltése",
                    data=pdf_bytes,
                    file_name="interfood_etikett_v85.pdf",
                    mime="application/pdf"
                )
            else:
                st.error("Nem találtam feldolgozható adatokat a PDF-ben. Ellenőrizd a fájl formátumát!")
        except Exception as e:
            st.error(f"Hiba történt: {e}")
