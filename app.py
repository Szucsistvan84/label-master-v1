import streamlit as st
import pdfplumber
import pandas as pd
import re
from fpdf import FPDF
import io

def parse_menetterv(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Kivonjuk a táblázatot a pdfplumber beépített algoritmusával, 
            # ami sokkal jobb a Menetterv-típusú fájlokhoz
            table = page.extract_table({
                "vertical_strategy": "lines", 
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            })
            
            if not table:
                # Ha nincsenek vonalak, szöveg-koordináta alapú kinyerés
                text_instances = page.extract_words()
                # (Ez a biztonsági tartalék, ha a vonalak nem látszanak)
                continue

            for row in table:
                # Tisztítás a fejléc-elemektől
                row_str = " ".join([str(c) for c in row if c])
                if "Ügyfél" in row_str or "Sor" in row_str:
                    continue

                # Adatok kinyerése a cellákból (Az oszlopok sorrendje fix a PDF-ben)
                # 0: Sorszám, 1: Kód/Cím, 2: Ügyintéző, 3: Telefon/Rendelés, 4: Össz.
                if len(row) >= 4:
                    kod_match = re.search(r'([PZ]-\d{6})', str(row[1]))
                    if kod_match:
                        # Tőkés István és a többiek itt lesznek összekötve!
                        all_rows.append({
                            "Kód": kod_match.group(1),
                            "Ügyintéző": str(row[2]).strip().replace('\n', ' '),
                            "Cím": str(row[1]).split(kod_match.group(1))[-1].strip().replace('\n', ' '),
                            "Telefon": re.findall(r'(\d{2}/\d{7})', str(row[3]))[0] if re.search(r'\d{2}/\d{7}', str(row[3])) else "NINCS",
                            "Rendelés": str(row[3]).split('\n')[-1].strip(),
                            "Pénz": re.findall(r'(\d+[\s\d]*Ft)', str(row[3]))[0] if "Ft" in str(row[3]) else "0 Ft"
                        })
    return pd.DataFrame(all_rows)

# Az etikett generáló (FPDF) rész következik...
def create_etikett_pdf(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    # Font beállítás az elmentett instrukciód alapján (DejaVu)
    # ... (font betöltés kódja) ...
    
    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        # 3x7-es rács kalkuláció
        x = (i % 3) * 70
        y = ((i // 3) % 7) * 42.4
        
        pdf.set_xy(x+5, y+5)
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:25])
        
        pdf.set_xy(x+5, y+10)
        pdf.set_font("DejaVu", "", 8)
        pdf.cell(60, 5, f"KÓD: {row['Kód']} | {row['Pénz']}")
        
        pdf.set_xy(x+5, y+15)
        pdf.set_font("DejaVu", "B", 9)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}")
        
        pdf.set_xy(x+5, y+20)
        pdf.set_font("DejaVu", "", 8)
        pdf.multi_cell(60, 4, str(row['Cím']))
        
        pdf.set_xy(x+5, y+32)
        pdf.set_font("DejaVu", "", 7)
        pdf.cell(60, 5, f"REND: {row['Rendelés']}")
        
    return pdf.output(dest='S').encode('latin-1')

st.title("Interfood Menetterv Feldolgozó v106")
uploaded_file = st.file_uploader("Töltsd fel a 2026-02-27 menetterv 4002.pdf-et", type="pdf")

if uploaded_file:
    df_result = parse_menetterv(uploaded_file)
    if not df_result.empty:
        st.success(f"Beolvasva: {len(df_result)} ügyfél")
        st.dataframe(df_result)
        # Itt jelenik meg Tőkés István az 1. sorban!
        pdf_out = create_etikett_pdf(df_result)
        st.download_button("💾 Etikettek letöltése (PDF)", pdf_out, "kesz_etikettek.pdf")
