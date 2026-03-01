import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. AZ INTELLIGENS NÉV-VALIDÁTOR (v59) ---
def intelligent_name_cleaner_v59(text, address_text):
    # Általános intézményi/helyszín szavak (nem csak konkrét cégnevek)
    inst_markers = [
        "Kft", "Zrt", "Bt", "Kht", "Egyéni", "Vállalkozó", "Bolt", "Üzlet", "Patika", "Gyógyszertár",
        "Iskola", "Óvoda", "Hivatal", "Kormány", "Campus", "Klinika", "Kórház", "Rendelő", "Porta",
        "Services", "International", "Hungary", "Color", "Fest", "Gáz", "Készülék", "Minit", "Pláza",
        "Expert", "Group", "Center", "Trade", "Technic", "LGM", "DKM", "VDK", "Fsz", "Ipark"
    ]
    
    # 1. Alaptisztítás: cím és felesleges karakterek eltávolítása
    clean_text = text.replace(address_text, "")
    clean_text = re.sub(r'\d{2}/\d{3}-?\d{4}', '', clean_text) # Telefon ki
    
    # 2. Szavak kinyerése (Nagybetűs szavak)
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    # 3. Szűrés: kidobjuk a nyilvánvalóan nem név-szavakat
    name_parts = []
    for w in words:
        is_inst = any(marker.lower() in w.lower() for marker in inst_markers)
        # Tiltólista a beküldött hibák alapján
        trash = ["Pearl", "Enterprises", "Zaza", "Süteményes", "Lapostetős", "HARAPÓS", "Ford", "Gyula", "Hamar"]
        
        if (not is_inst and 
            w.upper() not in [t.upper() for t in trash] and
            w not in ["Debrecen", "Sorszám", "Összesítés", "Összesen"] and
            len(w) > 2):
            name_parts.append(w)
            
    # 4. Magyar név logika: Általában 2-3 tagú. 
    # Ha több maradt, próbáljuk megkeresni az értelmes nevet.
    if len(name_parts) > 3:
        # Ha az első szó gyanús, és a második-harmadik inkább névnek tűnik (pl. "Services Rátkai János")
        # akkor eltoljuk a kezdőpontot.
        return " ".join(name_parts[-3:]).strip()
    
    return " ".join(name_parts).strip() if name_parts else "Ismeretlen"

# --- 2. PDF GENERÁLÁS (3x7 Etikett) ---
def create_pdf_v59(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_reg, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    if os.path.exists(font_reg):
        pdf.add_font("DejaVu", style="", fname=font_reg)
        pdf.add_font("DejaVu", style="B", fname=font_bold)
        f_name = "DejaVu"
    else: return None

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        pdf.set_font(f_name, "B", 9)
        pdf.set_x(x + 5)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_font(f_name, "", 8)
        pdf.set_x(x + 5)
        pdf.cell(60, 4, str(row['Cím']), 0, 1)
        pdf.set_font(f_name, "", 7)
        pdf.set_x(x + 5)
        pdf.multi_cell(60, 3.5, f"REND: {row['Rendelés']}", 0)
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v59 - Országos Verzió")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    extracted = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top'], 'x1': w['x1']} for w in words if w['x0'] < 45 and re.match(r'^\d+$', w['text'])]
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                # Sorszámtól jobbra, a sorszám vonalában keresünk
                block_words = [w for w in words if (top - 2 <= w['top'] < bottom - 2) and (w['x0'] >= markers[i]['x1'] - 5)]
                block_text = " ".join([w['text'] for w in block_words]).split("Összesítés")[0]
                
                cim = (re.search(r'(\d{4}\s+.*?\d+[\s/]*[A-Z-]*\.?)', block_text).group(1) if re.search(r'(\d{4}\s+.*?\d+[\s/]*[A-Z-]*\.?)', block_text) else "")
                tel = (re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text).group(1) if re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', block_text) else "NINCS")
                
                # Név kinyerése az intelligens tisztítóval
                name = intelligent_name_cleaner_v59(block_text, cim)
                rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', block_text)))))
                
                extracted.append({"Sorszám": markers[i]['num'], "Ügyintéző": name, "Telefon": tel, "Cím": cim, "Rendelés": rend})

    df = pd.DataFrame(extracted)
    st.dataframe(df)
    pdf_bytes = create_pdf_v59(df)
    if pdf_bytes:
        st.download_button("💾 PDF LETÖLTÉSE (v59)", bytes(pdf_bytes), "interfood_v59.pdf", "application/pdf")
