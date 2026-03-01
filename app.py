import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. PROFI NÉVTISZTÍTÓ (v61) ---
def clean_name_v61(text):
    # Olyan szavak, amik biztosan nem egy emberi név részei (Országos lista)
    company_markers = [
        "Kft", "Zrt", "Bt", "Kht", "Nonprofit", "Alapítvány", "Iskola", "Óvoda", 
        "Kormányhivatal", "Hivatal", "Campus", "Klinika", "Kórház", "Gyógyszertár", 
        "Services", "International", "Hungary", "Expert", "Mister", "Minit", "Pláza",
        "Ford", "Szalon", "Autó", "Gázkészülék", "Fodrászat", "Csemege", "Bolt"
    ]
    
    # Eltávolítjuk a sorszámot és a felesleges szóközöket
    name = re.sub(r'^\d+\s+', '', text).strip()
    
    # Ha a névben benne van bármelyik céges marker, levágjuk a kifejezést
    for marker in company_markers:
        # Ha a sor elején van: "Services Rátkai János" -> "Rátkai János"
        name = re.sub(r'^' + marker + r'\s+', '', name, flags=re.IGNORECASE)
        # Ha a sor végén van: "Sápi Réka Kormányhivatal" -> "Sápi Réka"
        name = re.sub(r'\s+' + marker + r'.*$', '', name, flags=re.IGNORECASE)

    # Egyedi fixek az általad küldött hibákra
    trash = ["Pearl Enterprises", "Zaza Süteményes", "Fest-É-ker", "ZsoZso Color", "LGM", "HARAPÓS", "Csokimax"]
    for t in trash:
        name = name.replace(t, "")
        
    # Utolsó simítás: ha maradtak felesleges nagybetűs maradványok a végén (pl. Nem, Ifjúsági)
    name = re.sub(r'\s(Nem|Ifjúsági|Összesítés|Portán|Kérlek)$', '', name).strip()
    
    return name

# --- 2. PDF GENERÁLÁS (A szabványos 3x7 etikett) ---
def create_pdf_v61(df):
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
        
        # NÉV
        pdf.set_xy(x + 5, y + 8)
        pdf.set_font(f_name, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
        # TELEFON
        pdf.set_font(f_name, "B", 9)
        pdf.set_x(x + 5)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        
        # CÍM
        pdf.set_font(f_name, "", 8)
        pdf.set_x(x + 5)
        pdf.multi_cell(60, 4, str(row['Cím']), 0)
        
        # RENDELÉS
        pdf.set_font(f_name, "", 7)
        pdf.set_x(x + 5)
        pdf.cell(60, 4, f"REND: {row['Rendelés']}", 0, 1)
    return pdf.output()

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett Mester v61")
f = st.file_uploader("Válaszd ki az eredeti Interfood PDF-et", type="pdf")

if f:
    results = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Sorszámok keresése (a bal szélen)
            markers = [w for w in words if w['x0'] < 45 and re.match(r'^\d+$', w['text'])]
            
            for i, m in enumerate(markers):
                top = m['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                # BLOKK SZÖVEGE (Zónákra bontva)
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                
                # 1. NÉV (A sorszám sorában van)
                name_line_words = [w for w in block_words if abs(w['top'] - top) < 3 and w['x0'] > m['x1']]
                raw_name = " ".join([w['text'] for w in name_line_words])
                clean_name = clean_name_v61(raw_name)
                
                # 2. CÍM (Irányítószámot keresünk a blokkban)
                full_text = " ".join([w['text'] for w in block_words])
                cim_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b,?\s+.*?(\d+[\s/]*[A-Z-]*\.?))', full_text)
                cim = cim_m.group(1).strip() if cim_m else ""
                
                # 3. TELEFON
                tel_m = re.search(r'((?:\+36|06|20/|30/|70/)[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', full_text)
                tel = tel_m.group(1) if tel_m else "NINCS"
                
                # 4. RENDELÉS
                rend = ", ".join(sorted(list(set(re.findall(r'(\d+-[A-Z0-9]+)', full_text)))))
                
                if clean_name or cim:
                    results.append({
                        "Ügyintéző": clean_name if clean_name else "Ismeretlen",
                        "Telefon": tel,
                        "Cím": cim,
                        "Rendelés": rend
                    })

    df = pd.DataFrame(results)
    st.dataframe(df)
    
    if not df.empty:
        pdf_bytes = create_pdf_v61(df)
        st.download_button("💾 PDF LETÖLTÉSE (v61)", bytes(pdf_bytes), "etikettek_v61.pdf", "application/pdf")
