import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v90(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        row_values = [str(v).strip() for v in row.values if str(v) != 'nan']
        full_row_text = " ".join(row_values)
        if not re.search(r'[A-Z]-\s?\d{6}', full_row_text): continue
        
        next_row_text = ""
        if idx + 1 < len(df_raw):
            next_row_text = " ".join([str(val) for val in df_raw.iloc[idx + 1].values if str(val) != 'nan'])

        for i in range(0, len(row.values), 5):
            if i + 4 >= len(row.values): break
            
            # 1. ÜGYFÉLKÓD
            code_cell = str(row.values[i+1])
            code_match = re.search(r'([A-Z])-\s?(\d{6})', code_cell)
            if not code_match: continue
            day_prefix, cust_id = code_match.group(1), code_match.group(2)

            # 2. ÜGYINTÉZŐ NEVE (v89-es bevált logika)
            name = "Név nem található"
            # Itt most már bízunk a 2-es indexben, de ha rossz, pásztázunk
            candidates = [str(row.values[i+2]), str(row.values[i+1]), str(row.values[i+3])]
            for cand in candidates:
                c = cand.strip()
                if c != "nan" and len(c.split()) >= 2 and not re.search(r'\d{4}', c) and not re.search(r'[A-Z]-\d{6}', c):
                    name = c
                    break

            # 3. TELEFON ÉS RENDELÉS (SZEPARÁLÁS AZ ELSŐ SZÓKÖZNÉL)
            tel_rend_cell = str(row.values[i+3]).strip()
            if " " in tel_rend_cell:
                # Az első szóközig telefon, utána minden más a rendelés
                tel, raw_rend = tel_rend_cell.split(" ", 1)
            else:
                # Ha nincs benne szóköz, megnézzük, hogy telefon-e vagy rendelés
                if re.search(r'\d{2,}/', tel_rend_cell) or tel_rend_cell.startswith(('06', '+36', '20', '30', '70')):
                    tel, raw_rend = tel_rend_cell, ""
                else:
                    tel, raw_rend = "NINCS", tel_rend_cell

            # Tisztítsuk meg a rendelés részt a felesleges sallangtól
            rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', raw_rend)
            current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', raw_rend))
            total_db = sum(int(c) for c in rend_codes)

            # 4. CÍM
            addr = "Cím nem található"
            addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', code_cell)
            if addr_m: addr = addr_m.group(1).strip()

            # 5. PÉNZ
            money = 0
            money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', next_row_text)
            if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

            # TÁROLÁS
            customer_key = (name, addr)
            if customer_key not in temp_storage:
                temp_storage[customer_key] = {
                    "kód": cust_id, "név": name, "cím": addr, "tel": tel, 
                    "P": "", "Z": "", "db": 0, "pénz": 0, "orig_idx": len(order_list) + 1
                }
                order_list.append(customer_key)
            
            if day_prefix == "P": temp_storage[customer_key]["P"] = current_rend_str
            elif day_prefix == "Z": temp_storage[customer_key]["Z"] = current_rend_str
            else: temp_storage[customer_key]["P"] = current_rend_str 
            
            temp_storage[customer_key]["db"] += total_db
            temp_storage[customer_key]["pénz"] += money

    res = []
    for key in order_list:
        d = temp_storage[key]
        res.append({
            "Sorszám": d["orig_idx"], "Ügyfélkód": d["kód"], "Ügyintéző": d["név"],
            "Telefon": d["tel"], "Cím": d["cím"],
            "Rendelés": f"P: {d['P']} | SZ: {d['Z']}" if d['P'] and d['Z'] else (d['P'] or d['Z']),
            "Összesen": f"{d['db']} tétel",
            "Pénz": f"{d['pénz']} Ft" if d['pénz'] != 0 else ""
        })
    return pd.DataFrame(res)

# PDF generálás (DESIGN JAVÍTÁS: Telefonszám kiemelve)
def create_pdf_v90(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path = "DejaVuSans.ttf" 
    f_m = "DejaVu" if os.path.exists(font_path) else "Arial"
    if f_m == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=font_path); pdf.add_font("DejaVu", style="B", fname="DejaVuSans-Bold.ttf")

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        pdf.set_xy(x + 2, y + 2); pdf.set_font(f_m, "", 6); pdf.cell(50, 3, f"#{row['Sorszám']} | KÓD: {row['Ügyfélkód']}")
        
        # Név - Vastagabb és kicsit nagyobb
        pdf.set_xy(x + 5, y + 5); pdf.set_font(f_m, "B", 10); pdf.cell(60, 5, str(row['Ügyintéző'])[:30])
        
        # Pénz és Tételek
        pdf.set_xy(x + 5, y + 10); pdf.set_font(f_m, "B", 8); pdf.cell(60, 4, f"{row['Összesen']} {row['Pénz']}")
        
        # TELEFON - Mostantól tisztán, csak a szám!
        pdf.set_xy(x + 5, y + 15); pdf.set_font(f_m, "B", 10); pdf.set_text_color(0, 0, 150) # Kékes árnyalat a telefonnak
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_text_color(0, 0, 0)

        # Cím
        pdf.set_xy(x + 5, y + 20); pdf.set_font(f_m, "", 8); pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        
        # Rendelés kódok legalul
        pdf.set_xy(x + 5, y + 31); pdf.set_font(f_m, "", 7); pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v90 - Telefonszám Extrakció")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=True)
    if dfs:
        final_df = parse_v90(pd.concat(dfs, ignore_index=True))
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v90(final_df)), "etikettek_v90.pdf")
    os.remove("temp.pdf")
