import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v81(df_raw):
    temp_storage = {} 

    for idx, row in df_raw.iterrows():
        # Csak azokat a sorokat nézzük, ahol van ügyfélkód
        row_str = " ".join(str(val) for val in row.values)
        if not re.search(r'[PZ]-\d+', row_str):
            continue

        next_row = df_raw.iloc[idx + 1] if idx + 1 < len(df_raw) else None

        # 5-ös blokkokban dolgozunk
        for i in range(0, len(row), 5):
            if i + 4 >= len(row): break
            
            raw_code_cell = str(row[i+1]) # Itt van a Kód ÉS a Cím
            name_cell = str(row[i+2]).strip() # Ügyintéző
            tel_rend_cell = str(row[i+3]) # Telefon + Rendelés
            count_cell = str(row[i+4]) # Tétel darabszám
            
            if name_cell == "nan" or len(name_cell) < 3: continue

            # 1. CÍM ÉS KÓD KINYERÉSE (1-es cella)
            # Irányítószám keresése: szóköz + 4 számjegy + szóköz
            addr = "Cím nem található"
            addr_match = re.search(r'\s(\d{4})\s+(.*)', raw_code_cell)
            if addr_match:
                addr = f"{addr_match.group(1)} {addr_match.group(2)}".strip()
            
            code_match = re.search(r'([PZ])-(\d+)', raw_code_cell)
            day_prefix = code_match.group(1) if code_match else "P"

            # 2. TELEFON ÉS RENDELÉS (3-as cella)
            # Telefonszám (06, +36, 20, 30, 70)
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', tel_rend_cell)
            tel = tel_m.group(1) if tel_m else "NINCS"
            
            # Rendelési kódok (pl. 1-DK)
            rend_list = re.findall(r'(\d+-[A-Z0-9]+)', tel_rend_cell)
            current_rend = ", ".join(rend_list)

            # 3. TÉTEL SZÁMLÁLÓ (4-es cella vagy manuális számolás)
            try:
                count_val = float(count_cell) if count_cell != 'nan' else 0
                if count_val == 0 and len(rend_list) > 0:
                    count_val = len(rend_list) # Ha a cella 0 de van kód, számoljuk a kódokat
                count_str = f"{int(count_val)} tétel"
            except:
                count_str = f"{len(rend_list)} tétel"

            # 4. PÉNZÜGY (Next row, 3-as index alatti)
            money = 0
            if next_row is not None and i+3 < len(next_row):
                money_match = re.search(r'(-?\d+[\s\d]*)', str(next_row[i+3]))
                if money_match:
                    money = int(re.sub(r'\s+', '', money_match.group(1)))

            # 5. TÁROLÁS
            customer_key = (name_cell, addr)
            if customer_key not in temp_storage:
                temp_storage[customer_key] = {
                    "név": name_cell, "cím": addr, "tel": tel, 
                    "P": "", "Z": "", "db": 0, "pénz": 0
                }
            
            if day_prefix == "P": temp_storage[customer_key]["P"] = current_rend
            else: temp_storage[customer_key]["Z"] = current_rend

            # Összeadás
            try:
                # Csak a számot adjuk hozzá
                db_num = int(re.search(r'\d+', count_str).group())
                temp_storage[customer_key]["db"] += db_num
            except: pass
            temp_storage[customer_key]["pénz"] += money

    # PDF formátumú lista
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

        money_text = ""
        if data["pénz"] > 0: money_text = f"BESZEDENDŐ: {data['pénz']} Ft"
        elif data["pénz"] < 0: money_text = f"VISSZAADNI: {abs(data['pénz'])} Ft"

        final_list.append({
            "Ügyintéző": data["név"], "Telefon": data["tel"], "Cím": data["cím"],
            "Rendelés": rend_info, "Típus": label_type, 
            "Összesen": f"{data['db']} tétel", "Pénz": money_text
        })
    return pd.DataFrame(final_list)

# --- PDF GENERÁLÁS (v81) ---
def create_pdf_v81(df):
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
        
        # Név
        pdf.set_xy(x + 5, y + 4)
        pdf.set_font(f_main, "B", 11)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:35], 0, 1)
        
        # Típus és tétel
        pdf.set_xy(x + 5, y + 9)
        pdf.set_font(f_main, "B", 9)
        if "+" in row['Típus']: pdf.set_text_color(200, 0, 0)
        pdf.cell(60, 4, f"{row['Típus']} - {row['Összesen']}", 0, 1)
        pdf.set_text_color(0, 0, 0)

        # Pénz
        if row['Pénz']:
            pdf.set_xy(x + 5, y + 13)
            pdf.set_font(f_main, "B", 10)
            pdf.cell(60, 5, row['Pénz'], 0, 1)

        # Telefon
        pdf.set_xy(x + 5, y + 18)
        pdf.set_font(f_main, "B", 9)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        
        # Cím (itt volt a gond, most fixáltuk)
        pdf.set_xy(x + 5, y + 22)
        pdf.set_font(f_main, "", 8)
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        
        # Rendelés
        pdf.set_xy(x + 5, y + 32)
        pdf.set_font(f_main, "", 7)
        pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
        
    return pdf.output()

# --- APP ---
st.title("Interfood v81 - Helyreállított Címek")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    with st.spinner('Adatok precíz rendezése...'):
        with open("temp.pdf", "wb") as tp: tp.write(f.read())
        dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
        if dfs:
            raw_df = pd.concat(dfs, ignore_index=True)
            final_df = parse_v81(raw_df)
            st.dataframe(final_df)
            if not final_df.empty:
                pdf_out = create_pdf_v81(final_df)
                st.download_button("💾 PDF LETÖLTÉSE", bytes(pdf_out), "etikettek_v81.pdf")
        os.remove("temp.pdf")
