import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. PRECIZÍS NÉV- ÉS CÍMTISZTÍTÓ (v60) ---
def clean_data_v60(block_text):
    # 1. Cím kinyerése (Irányítószám + Város + Utca + Házszám)
    # Ez a regex felismeri a magyar címformátumot
    cim_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b,?\s+.*?(\d+[\s/]*[A-Z-]*\.?))', block_text)
    cim = cim_m.group(1).strip() if cim_m else ""
    
    # 2. Név kinyerése: A blokk legelső sora, de levágjuk belőle a sorszámot
    # Az Interfoodnál a név az első sorban van.
    lines = [line.strip() for line in block_text.split('\n') if line.strip()]
    raw_name = lines[0] if lines else ""
    
    # Eltávolítjuk a sorszámot az elejéről (pl. "24 ")
    name = re.sub(r'^\d+\s+', '', raw_name)
    
    # 3. Név finomhangolása (Tiltólista a végére)
    # Ha a névben benne van a cím egy darabja, vagy tiltott szó, levágjuk.
    trash = ["Portán", "Kft", "Zrt", "Nem", "Ifjúsági", "Összesítés", "Hiv", "VDK", "DKM", "CICA", "Services"]
    
    # Ha a név tartalmazza a cégneveket, amiket korábban írtál, azokat is kivehetjük
    for t in ["Csokimax", "Harro Höfliger", "Pearl Enterprises", "Globiz", "Ford"]:
        name = name.replace(t, "").strip()
        
    for word in trash:
        name = re.sub(r'\s' + word + r'$', '', name, flags=re.IGNORECASE).strip()
    
    # 4. Telefon
    tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text)
    tel = tel_m.group(1) if tel_m else "NINCS"
    
    # 5. Rendelés
    rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text)))))
    
    return name, cim, tel, rend

# --- 2. PDF GENERÁLÁS (A kért 3x7 elrendezés) ---
def create_pdf_v60(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_reg, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    if os.path.exists(font_reg):
        pdf.add_font("DejaVu", style="", fname=font_reg); pdf.add_font("DejaVu", style="B", fname=font_bold)
        f_name = "DejaVu"
    else: return None

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1) # NÉV
        
        pdf.set_font(f_name, "B", 9)
        pdf.set_x(x + 5)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1) # TEL
        
        pdf.set_font(f_name, "", 8)
        pdf.set_x(x + 5)
        pdf.multi_cell(60, 4, str(row['Cím']), 0) # CÍM (Multi-cell ha hosszú)
        
        pdf.set_font(f_name, "", 7)
        pdf.set_x(x + 5)
        pdf.cell(60, 4, f"REND: {row['Rendelés']}", 0, 1) # REND
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v60")
f = st.file_uploader("Feltöltés", type="pdf")

if f:
    data = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            # Itt a titok: sorszámok alapján vágjuk szét a szöveget, NEM koordináta alapján
            text = page.extract_text()
            # Keresünk minden olyan részt, ami számmal kezdődik és van alatta szöveg
            # Az Interfood PDF-ben minden blokk egy sorszámmal kezdődik
            blocks = re.split(r'\n(?=\d+\s+[A-ZÁÉÍÓÖŐÚÜŰ])', text)
            
            for b in blocks:
                if not b.strip(): continue
                name, cim, tel, rend = clean_data_v60(b)
                if name and cim: # Csak ha van értékelhető adat
                    data.append({"Ügyintéző": name, "Telefon": tel, "Cím": cim, "Rendelés": rend})

    df = pd.DataFrame(data)
    st.dataframe(df)
    pdf_out = create_pdf_v60(df)
    if pdf_out:
        st.download_button("💾 PDF LETÖLTÉSE (v60)", bytes(pdf_out), "etikettek_v60.pdf", "application/pdf")
