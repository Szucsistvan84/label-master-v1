import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. AZ ADAT-MÁGNES JAVÍTVA (v77.1) ---
def clean_tabula_row(df_raw):
    cleaned_data = []
    
    for index, row in df_raw.iterrows():
        # Sor összefűzése szöveggé a kereséshez
        row_str = " ".join(str(val) for val in row.values if str(val) != 'nan')
        
        # Ügyfél kezdete: P- vagy Z- kód
        if re.search(r'[PZ]-\d+', row_str):
            # 1. TELEFON (06, +36, 20, 30, 70)
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', row_str)
            tel = tel_m.group(1) if tel_m else "NINCS"
            
            # 2. CÍM (Irányítószám + Város + Utca)
            addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-z-]+\b.*)', row_str)
            addr = addr_m.group(1).strip() if addr_m else "Cím a sorban..."
            
            # 3. NÉV (A technikai kód és a cím közötti rész)
            name = ""
            name_match = re.search(r'[PZ]-\d+\s+(.*?)(?=\d{4}\s+|$)', row_str)
            if name_match:
                name = name_match.group(1).strip()
            
            # Ha a név üres maradt, nézzük meg a táblázat oszlopait külön
            if len(name) < 3:
                for val in row.values:
                    v_str = str(val)
                    if len(v_str) > 3 and not re.search(r'\d{4}', v_str) and "nan" not in v_str.lower():
                        name = v_str
                        break

            # 4. RENDELÉS (Szám-Betű kódok)
            rend_list = re.findall(r'(\d+-[A-Z0-9]+)', row_str)
            rend = ", ".join(rend_list) if rend_list else ""

            # Csak ha van értékelhető név
            if len(name) > 2 and "ÖSSZESÍTŐ" not in row_str:
                cleaned_data.append({
                    "Ügyintéző": name[:40], 
                    "Telefon": tel, 
                    "Cím": addr, 
                    "Rendelés": rend
                })
    
    return pd.DataFrame(cleaned_data)

# --- 2. GENERÁTOR ---
def create_pdf_v77(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path = "DejaVuSans.ttf" 
    f_main = "DejaVu" if os.path.exists(font_path) else "Arial"
    if f_main == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=font_path)
        pdf.add_font("DejaVu", style="B", fname="DejaVuSans-Bold.ttf")

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        pdf.set_xy(x + 5, y + 5)
        pdf.set_font(f_main, "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző']), 0, 1)
        
        pdf.set_xy(x + 5, y + 12)
        pdf.set_font(f_main, "B", 9)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        
        pdf.set_xy(x + 5, y + 18)
        pdf.set_font(f_main, "", 8)
        pdf.multi_cell(60, 4, str(row['Cím']), 0, 'L')
        
        pdf.set_xy(x + 5, y + 30)
        pdf.set_font(f_main, "", 7)
        pdf.cell(60, 4, f"REND: {row['Rendelés']}"[:45], 0, 1)
        
    return pdf.output()

# --- 3. APP ---
st.title("Interfood Etikett v77.1")

f = st.file_uploader("Eredeti PDF feltöltése", type="pdf")

if f:
    with st.spinner('Feldolgozás folyamatban...'):
        try:
            # Ideiglenes fájl a Tabulának
            with open("temp.pdf", "wb") as tp:
                tp.write(f.getvalue())
            
            # Tabula beolvasás
            dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=True)
            
            if dfs:
                raw_df = pd.concat(dfs, ignore_index=True)
                final_df = clean_tabula_row(raw_df)
                final_df = final_df.drop_duplicates(subset=['Ügyintéző', 'Cím'])
                
                st.write(f"Talált ügyfelek: {len(final_df)}")
                st.dataframe(final_df)
                
                if not final_df.empty:
                    pdf_out = create_pdf_v77(final_df)
                    st.download_button("💾 PDF LETÖLTÉSE", bytes(pdf_out), "etikettek_v77.pdf")
            
            os.remove("temp.pdf")
        except Exception as e:
            st.error(f"Hiba történt: {e}")
