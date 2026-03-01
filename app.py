import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def super_clean_v42(text, address_text):
    # 1. Munkahelyek és cégek - Kibővített lista
    blacklist = [
        "Richter Gedeon", "Richter", "Gedeon", "Zaza Süteményes", "Zaza", "Süteményes",
        "Gyógyszertár", "István úti csemege", "István csemege", "Csemege", "Harro Höfliger",
        "Pearl Enterprises", "DEKK", "Kenézy Gyula", "Főnix", "Fest-É-ker", "Medgyessy",
        "Általános Iskola", "Triton Services", "Javítsd Magad", "Matrackirály", "Ford Szalon",
        "ZsoZso Color", "Kormányhivatal", "Gázkészülék", "Csokimax", "Kérlek", "Köszönöm"
    ]
    
    # 2. Utcanév szűrés (Hogy ne legyen 'Házgyár István')
    addr_words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b', address_text)
    
    # 3. Tisztítás
    clean_text = text
    for item in blacklist:
        clean_text = re.sub(r'\b' + re.escape(item) + r'\b', '', clean_text, flags=re.IGNORECASE)
    
    # 4. Név kinyerése (Nagybetűs szavak)
    words = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]+\b', clean_text)
    
    final_parts = []
    for w in words:
        if (w not in ["Debrecen", "Sorszám", "Összesen"] and 
            w not in addr_words and 
            w.upper() not in ["KCS", "DKM", "PORTÁN", "HUNGARY", "KFT", "ZRT", "HIV"]):
            
            if w not in final_parts:
                # Duplikáció szűrés (Juhász vs Juhász-Takács)
                is_sub = False
                for idx, existing in enumerate(final_parts):
                    if w in existing: is_sub = True; break
                    if existing in w: final_parts[idx] = w; is_sub = True; break
                if not is_sub:
                    final_parts.append(w)
    
    return " ".join(final_parts[:3])

def create_labels_pdf(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    
    # Etikett beállítások (3 oszlop, 7 sor)
    label_w, label_h = 70, 42.4
    margin_x, margin_y = 0, 0
    
    for i, row in df.iterrows():
        col = i % 3
        line = (i // 3) % 7
        
        if i > 0 and i % 21 == 0:
            pdf.add_page()
        
        x = col * label_w
        y = line * label_h
        
        pdf.set_xy(x + 5, y + 10)
        pdf.set_font("Arial", "B", 11) # Itt használhatod a saját fontodat, ha feltöltöd!
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1, 'L')
        
        pdf.set_x(x + 5)
        pdf.set_font("Arial", "", 9)
        pdf.cell(60, 5, str(row['Cím']), 0, 1, 'L')
        
        pdf.set_x(x + 5)
        pdf.set_font("Arial", "I", 8)
        pdf.multi_cell(60, 4, f"Rendelés: {row['Rendelés']}", 0, 'L')
        
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- Streamlit UI ---
st.title("Interfood v42 - A Végleges Megoldás")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    # Adatkinyerés (a v41/v42 logikával)
    all_data = []
    with pdfplumber.open(f) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = [{'num': w['text'], 'top': w['top']} for w in words if w['x0'] < 40 and re.match(r'^\d+$', w['text'])]
            for i in range(len(markers)):
                top, bottom = markers[i]['top'], (markers[i+1]['top'] if i+1 < len(markers) else page.height)
                block = " ".join([w['text'] for w in words if top - 2 <= w['top'] < bottom - 2])
                cim = (re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block).group(1) if re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', block) else "")
                name = super_clean_v42(block, cim)
                all_data.append({"Sorszám": markers[i]['num'], "Ügyintéző": name, "Cím": cim, "Rendelés": ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', block))})
    
    df = pd.DataFrame(all_data)
    st.dataframe(df)
    
    # Export lehetőségek
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("CSV letöltése", df.to_csv(index=False).encode('utf-8-sig'), "lista.csv")
    with col2:
        pdf_data = create_labels_pdf(df)
        st.download_button("ETIKETT PDF letöltése", pdf_data, "etikettek.pdf")
