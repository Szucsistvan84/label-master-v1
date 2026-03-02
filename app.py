import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_menetterv_v110(pdf_file):
    all_rows = []
    # A PDF megnyitása
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A táblázat kinyerése - a te menettervedhez ez a legjobb beállítás
            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines"
            })
            
            if not table: continue

            for row in table:
                # Az oszlopok ellenőrzése (0: Sor, 1: Ügyfél/Cím, 2: Ügyintéző, 3: Adatok)
                if not row or len(row) < 4: continue
                
                c1 = str(row[1]) if row[1] else ""
                # Ha a fejlécet látjuk, ugorjuk át
                if "Ügyfél" in c1 or "Sor" in str(row[0]): continue
                
                # Ügyfélkód keresése (P- vagy Z- és 6 szám)
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                if kod_m:
                    kod = kod_m.group(1)
                    # Cím: a kód utáni rész a cellában
                    cim = c1.split(kod)[-1].strip().replace('\n', ' ')
                    # Név: a 3. oszlop (Takács Ildikó, Tőkés István stb.)
                    nev = str(row[2]).strip().replace('\n', ' ')
                    
                    # 4. oszlop: Telefon, Pénz, Rendelés
                    c3 = str(row[3]) if row[3] else ""
                    tel_m = re.search(r'(\d{2}/\d{7})', c3)
                    tel = tel_m.group(1) if tel_m else "NINCS"
                    
                    penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                    penz = penz_m.group(1) if penz_m else "0 Ft"
                    
                    # Rendelés (minden, ami nem telefon és nem pénz)
                    rend_lines = [l.strip() for l in c3.split('\n') if l.strip() and "Ft" not in l and "/" not in l]
                    rend = ", ".join(rend_lines) if rend_lines else "Lásd PDF"
                    
                    all_rows.append({
                        "Kód": kod, "Ügyintéző": nev, "Cím": cim,
                        "Telefon": tel, "Pénz": penz, "Rendelés": rend
                    })
    return pd.DataFrame(all_rows)

def create_pdf_v110(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        # Latin-1 kódolás, hogy ne szálljon el speciális karaktereknél
        safe_name = str(row['Ügyintéző']).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(60, 5, safe_name[:25])
        
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+10)
        pdf.cell(60, 5, f"KOD: {row['Kód']} | {row['Pénz']}")
        
        pdf.set_font("Arial", "B", 9)
        pdf.set_xy(x+5, y+15)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}")
        
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+20)
        safe_addr = str(row['Cím']).encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(60, 4, safe_addr)
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

st.title("🚀 Interfood v110 - Fixált Telepítő")
uploaded = st.file_uploader("Menetterv PDF (4002.pdf)", type="pdf")

if uploaded:
    data = parse_menetterv_v110(uploaded)
    if not data.empty:
        st.success(f"Beolvasva: {len(data)} ügyfél")
        st.dataframe(data)
        
        pdf_bytes = create_pdf_v110(data)
        st.download_button("💾 PDF Letöltése", pdf_bytes, "etikettek.pdf", "application/pdf")
    else:
        st.error("Üres a táblázat! Biztos a 'menetterv 4002.pdf'-et töltötted fel?")
