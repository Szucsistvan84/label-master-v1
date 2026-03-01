import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

# --- 1. AZ "ADAT-MÁGNES" TISZTÍTÓ (v77) ---
def clean_tabula_row(df_raw):
    cleaned_data = []
    
    # Végigmegyünk a nyers táblázat minden során
    for index, row in df_raw.iterrows():
        row_str = " ".join(str(val) for val in row.values if str(val) != 'nan')
        
        # Keressük az ügyfél-kódot (P- vagy Z-), ez az új ügyfél kezdete
        if re.search(r'[PZ]-\d+', row_str):
            # NÉV kinyerése (P-kód utáni rész, de a cím előtt)
            name_match = re.search(r'[PZ]-\d+\s+(.*?)(?=\d{4}\s+|$)', row_str)
            name = name_match.group(1).strip() if name_match else ""
            
            # CÍM kinyerése (Irányítószámtól kezdve)
            addr_match = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', row_str)
            addr = addr_match.group(1).strip() if addr_m else "Cím a sorban..."
            
            # TELEFON (06 vagy +36 vagy 20/30/70)
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', row_str)
            tel = tel_m.group(1) if tel_m else "NINCS"
            
            # RENDELÉS (Tipikus Interfood kódok: szám-betűk)
            rend_list = re.findall(r'(\d+-[A-Z0-9]+)', row_str)
            rend = ", ".join(rend_list) if rend_list else ""

            # Ha a név túl rövid vagy szemét, nézzük meg a szomszédos oszlopokat (Tabula hiba javítása)
            if len(name) < 3:
                # Ilyenkor gyakran a következő oszlopban van a név
                for val in row.values:
                    if isinstance(val, str) and len(val) > 3 and not re.search(r'\d{4}', val):
                        name = val
                        break

            if len(name) > 2 and "ÖSSZESÍTŐ" not in row_str:
                cleaned_data.append({"Ügyintéző": name, "Telefon": tel, "Cím": addr, "Rendelés": rend})
    
    return pd.DataFrame(cleaned_data)

# --- 2. A MÁR BIZONYÍTOTT FIX RÁCSOS PDF GENERÁTOR ---
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
        pdf.cell(60, 5, str(row['Ügyintéző'])[:40], 0, 1)
        
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

# --- 3. STREAMLIT APP ---
st.title("Interfood Etikett v77 - A Megoldás")

f = st.file_uploader("Eredeti PDF feltöltése", type="pdf")

if f:
    with st.spinner('Adatok kinyerése és rendezése...'):
        try:
            # Tabula beolvasás
            with open("temp.pdf", "wb") as tp: tp.write(f.read())
            dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=True)
            
            if dfs:
                raw_df = pd.concat(dfs, ignore_index=True)
                # Itt történik a varázslat: rendberakjuk a szétesett sorokat
                final_df = clean_tabula_row(raw_df)
                final_df = final_df.drop_duplicates(subset=['Ügyintéző', 'Cím'])
                
                st.success(f"Siker! {len(final_df)} ügyfél rendszerezve.")
                st.dataframe(final_df)
                
                if not final_df.empty:
                    pdf_out = create_pdf_v77(final_df)
                    st.download_button("💾 ETIKETTEK LETÖLTÉSE (PDF)", bytes(pdf_out), "etikettek_v77.pdf")
            
            os.remove("temp.pdf")
        except Exception as e:
            st.error(f"Hiba: {e}")
