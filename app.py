import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF

def parse_final_v109(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A menetterv táblázatos szerkezetének kinyerése
            table = page.extract_table()
            if not table: continue
            for row in table:
                # Oszlopok: 0: Sor, 1: Kód+Cím, 2: Ügyintéző, 3: Telefon/Rendelés
                c1 = str(row[1]) if row[1] else ""
                if "Ügyfél" in c1 or "Sor" in str(row[0]): continue
                
                kod_m = re.search(r'([PZ]-\d{6})', c1)
                if kod_m:
                    kod = kod_m.group(1)
                    # Szétválasztjuk a kódot és a címet
                    cim = c1.split(kod)[-1].strip().replace('\n', ' ')
                    nev = str(row[2]).strip().replace('\n', ' ')
                    
                    # Adatok a 3. oszlopból (Telefon, Pénz, Rendelés)
                    c3 = str(row[3]) if row[3] else ""
                    tel_m = re.search(r'(\d{2}/\d{7})', c3)
                    tel = tel_m.group(1) if tel_m else "NINCS"
                    
                    penz_m = re.search(r'(\d+[\s\d]*Ft)', c3)
                    penz = penz_m.group(1) if penz_m else "0 Ft"
                    
                    # Rendelés (a cella utolsó sorai)
                    rend_lines = [l.strip() for l in c3.split('\n') if l.strip() and "Ft" not in l and "/" not in l]
                    rend = ", ".join(rend_lines) if rend_lines else "Lásd PDF"
                    
                    all_rows.append({
                        "Kód": kod, "Ügyintéző": nev, "Cím": cim,
                        "Telefon": tel, "Pénz": penz, "Rendelés": rend
                    })
    return pd.DataFrame(all_rows)

def create_pdf_v109(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        # Név
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(x+5, y+5)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:25].encode('latin-1', 'replace').decode('latin-1'))
        
        # Kód és Pénz
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+10)
        pdf.cell(60, 5, f"KOD: {row['Kód']} | {row['Pénz']}")
        
        # Telefon
        pdf.set_font("Arial", "B", 9)
        pdf.set_xy(x+5, y+15)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}")
        
        # Cím
        pdf.set_font("Arial", "", 8)
        pdf.set_xy(x+5, y+20)
        pdf.multi_cell(60, 4, str(row['Cím']).encode('latin-1', 'replace').decode('latin-1'))
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

st.title("🚀 Interfood v109 - Menetterv Feldolgozó")
st.info("Töltsd fel a '2026-02-27 menetterv 4002.pdf' fájlt!")

uploaded = st.file_uploader("PDF feltöltése", type="pdf")

if uploaded:
    with st.spinner("Adatok beolvasása..."):
        data = parse_final_v109(uploaded)
    
    if not data.empty:
        st.success(f"Találva: {len(data)} ügyfél")
        st.dataframe(data) # Itt ellenőrizd az első sorban Tőkés Istvánt!
        
        pdf_bytes = create_pdf_v109(data)
        st.download_button(
            label="💾 KÉSZ ETIKETTEK LETÖLTÉSE",
            data=pdf_bytes,
            file_name="interfood_etikettek.pdf",
            mime="application/pdf"
        )
    else:
        st.error("Nem sikerült adatot kinyerni. Ellenőrizd a PDF-et!")
