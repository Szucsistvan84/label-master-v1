import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v80(df_raw):
    temp_storage = {} 

    for idx, row in df_raw.iterrows():
        # Csak azokat a sorokat nézzük, ahol van ügyfélkód (P- vagy Z-)
        row_str = " ".join(str(val) for val in row.values)
        if not re.search(r'[PZ]-\d+', row_str):
            continue

        # Megpróbáljuk lekérni a következő sort az összegek miatt
        next_row = df_raw.iloc[idx + 1] if idx + 1 < len(df_raw) else None

        for i in range(0, len(row), 5):
            if i + 4 >= len(row): break
            
            raw_code_cell = str(row[i+1])
            name = str(row[i+2]).strip()
            tel_rend_cell = str(row[i+3])
            count_cell = str(row[i+4])
            
            if name == "nan" or len(name) < 3: continue

            # 1. PÉNZÜGYI ADAT (A 3. index alatti cellából)
            money = 0
            if next_row is not None and i+3 < len(next_row):
                money_str = str(next_row[i+3])
                # Kiszedjük a számokat (lehet benne mínusz jel is)
                money_match = re.search(r'(-?\d+[\s\d]*)', money_str)
                if money_match:
                    money = int(re.sub(r'\s+', '', money_match.group(1)))

            # 2. ADATOK KINYERÉSE (P/Z, Cím, Tel, Rendelés, DB)
            code_match = re.search(r'([PZ])-(\d+)', raw_code_cell)
            day_prefix = code_match.group(1) if code_match else "P"
            
            addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', raw_code_cell)
            addr = addr_m.group(1).strip() if addr_m else "Cím a PDF-ben..."

            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', tel_rend_cell)
            tel = tel_m.group(1) if tel_m else "NINCS"
            
            rend_list = re.findall(r'(\d+-[A-Z0-9]+)', tel_rend_cell)
            current_rend = ", ".join(rend_list)
            
            count = count_cell.split('.')[0] if '.' in count_cell else count_cell

            # 3. TÁROLÁS ÉS ÖSSZEVONÁS
            customer_key = (name, addr)
            if customer_key not in temp_storage:
                temp_storage[customer_key] = {
                    "név": name, "cím": addr, "tel": tel, 
                    "P": "", "Z": "", "db": 0, "pénz": 0
                }
            
            if day_prefix == "P":
                temp_storage[customer_key]["P"] = current_rend
            else:
                temp_storage[customer_key]["Z"] = current_rend

            # Összeadjuk a tételeket és a pénzt a két napról
            try:
                temp_storage[customer_key]["db"] += int(count) if count != "nan" else 0
            except: pass
            temp_storage[customer_key]["pénz"] += money

    # Lista építése
    final_list = []
    for data in temp_storage.values():
        label_type = "PÉNTEK"
        rend_info = data["P"]
        if data["P"] and data["Z"]:
            label_type = "PÉNTEK + SZOMBAT"
            rend_info = f"P: {data['P']} | SZ: {data['Z']}"
        elif data["Z"]:
            label_type = "SZOMBAT"
            rend_info = data["Z"]

        # Pénzügyi szöveg generálása
        money_text = ""
        if data["pénz"] > 0:
            money_text = f"BESZEDENDŐ: {data['pénz']} Ft"
        elif data["pénz"] < 0:
            money_text = f"VISSZAADNI: {abs(data['pénz'])} Ft"

        final_list.append({
            "Ügyintéző": data["név"], "Telefon": data["tel"], "Cím": data["cím"],
            "Rendelés": rend_info, "Típus": label_type, 
            "Összesen": f"{data['db']} tétel", "Pénz": money_text
        })
    return pd.DataFrame(final_list)

# --- PDF GENERÁLÁS V80 ---
def create_pdf_v80(df):
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
        
        # NÉV
        pdf.set_xy(x + 5, y + 4)
        pdf.set_font(f_main, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:35], 0, 1)
        
        # TÍPUS ÉS DARAB (Piros, ha P+SZ)
        pdf.set_xy(x + 5, y + 9)
        pdf.set_font(f_main, "B", 8)
        if "+" in row['Típus']: pdf.set_text_color(200, 0, 0)
        pdf.cell(60, 4, f"{row['Típus']} - {row['Összesen']}", 0, 1)
        pdf.set_text_color(0, 0, 0)

        # BESZEDENDŐ / VISSZAADANDÓ (Nagy és Vastag!)
        if row['Pénz']:
            pdf.set_xy(x + 5, y + 13)
            pdf.set_font(f_main, "B", 10)
            pdf.cell(60, 5, row['Pénz'], 0, 1)

        # TELEFON ÉS CÍM
        pdf.set_xy(x + 5, y + 18)
        pdf.set_font(f_main, "B", 8)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        
        pdf.set_xy(x + 5, y + 22)
        pdf.set_font(f_main, "", 8)
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        
        # RENDELÉS
        pdf.set_xy(x + 5, y + 32)
        pdf.set_font(f_main, "", 7)
        pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
        
    return pdf.output()

st.title("Interfood Etikett v80 - A Pénztáros")
f = st.file_uploader("Feltöltés", type="pdf")

if f:
    with st.spinner('Adatok és pénzügyek elemzése...'):
        with open("temp.pdf", "wb") as tp: tp.write(f.read())
        dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
        if dfs:
            raw_df = pd.concat(dfs, ignore_index=True)
            final_df = parse_v80(raw_df)
            st.dataframe(final_df)
            if not final_df.empty:
                pdf_out = create_pdf_v80(final_df)
                st.download_button("💾 PDF LETÖLTÉSE", bytes(pdf_out), "etikettek_v80.pdf")
        os.remove("temp.pdf")
