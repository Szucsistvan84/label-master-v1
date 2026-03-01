import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v85(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        row_values = [str(val).strip() for val in row.values if str(val) != 'nan']
        full_row_text = " ".join(row_values)
        
        # Keressük az ügyfélkódot (Nap-jelzés + 6 számjegy)
        if not re.search(r'[A-Z]-\d{6}', full_row_text): continue
        
        next_row_text = ""
        if idx + 1 < len(df_raw):
            next_row_text = " ".join([str(val) for val in df_raw.iloc[idx + 1].values if str(val) != 'nan'])

        for i in range(0, len(row.values), 5):
            if i + 3 >= len(row.values): break
            chunk = " ".join([str(row.values[i+j]) for j in range(5) if i+j < len(row.values)])
            
            # 1. ÜGYFÉLKÓD ÉS NAP (H, K, S, C, P, Z kezelése)
            code_match = re.search(r'([A-Z])-\s?(\d{6})', chunk)
            if not code_match: continue
            day_prefix = code_match.group(1)
            cust_id = code_match.group(2)

            # 2. CÍM (Irányítószámtól)
            addr = "Cím nem található"
            addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][^0-9]+[^,]+,?\s*[^0-9\s]*)', chunk)
            if addr_m: addr = addr_m.group(1).strip()

            # 3. NÉV (Kód és irányítószám között, vagy a 2. oszlopból)
            name = "Név hiba"
            name_m = re.search(r'[A-Z]-\s?\d{6}\s+(.*?)\s+\d{4}', chunk)
            if name_m:
                name = name_m.group(1).replace('/', '').strip()
            
            if len(name) < 3 or name == "Név hiba":
                cand = str(row.values[i+2]).strip()
                if len(cand) > 3 and not re.search(r'\d{2}/\d{7}', cand):
                    name = cand

            # 4. TELEFON
            tel = "NINCS"
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', chunk)
            if tel_m: tel = tel_m.group(1)

            # 5. RENDELÉS ÉS MENNYISÉG (Kötőjel előtti számok összege)
            rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', chunk)
            current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', chunk))
            total_db = sum(int(c) for c in rend_codes)

            # 6. PÉNZ
            money = 0
            money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', next_row_text)
            if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

            # --- TÁROLÁS ---
            customer_key = (name, addr)
            if customer_key not in temp_storage:
                temp_storage[customer_key] = {
                    "kód": cust_id, "név": name, "cím": addr, "tel": tel, 
                    "P": "", "Z": "", "db": 0, "pénz": 0, 
                    "orig_idx": len(order_list) + 1
                }
                order_list.append(customer_key)
            
            if day_prefix == "P": temp_storage[customer_key]["P"] = current_rend_str
            elif day_prefix == "Z": temp_storage[customer_key]["Z"] = current_rend_str
            else: temp_storage[customer_key]["P"] = current_rend_str # Egyéb napok kezelése
            
            temp_storage[customer_key]["db"] += total_db
            temp_storage[customer_key]["pénz"] += money

    # Lista építése
    res = []
    for key in order_list:
        d = temp_storage[key]
        res.append({
            "Sorszám": d["orig_idx"],
            "Ügyfélkód": d["kód"],
            "Ügyintéző": d["név"], "Telefon": d["tel"], "Cím": d["cím"],
            "Rendelés": f"P: {d['P']} | SZ: {d['Z']}" if d['P'] and d['Z'] else (d['P'] or d['Z']),
            "Összesen": f"{d['db']} tétel",
            "Pénz": f"BESZEDENDŐ: {d['pénz']} Ft" if d['pénz'] > 0 else (f"VISSZAADNI: {abs(d['pénz'])} Ft" if d['pénz'] < 0 else "")
        })
    return pd.DataFrame(res)

def create_pdf_v85(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path = "DejaVuSans.ttf" 
    f_m = "DejaVu" if os.path.exists(font_path) else "Arial"
    if f_m == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=font_path)
        pdf.add_font("DejaVu", style="B", fname="DejaVuSans-Bold.ttf")

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        
        # Sorszám és Kód
        pdf.set_xy(x + 2, y + 2)
        pdf.set_font(f_m, "", 6)
        pdf.cell(50, 3, f"#{row['Sorszám']} | KÓD: {row['Ügyfélkód']}", 0, 0)

        # Név
        pdf.set_xy(x + 5, y + 5)
        pdf.set_font(f_m, "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:30], 0, 1)
        
        # Tétel és Pénz
        pdf.set_xy(x + 5, y + 10)
        pdf.set_font(f_m, "B", 8)
        pdf.cell(60, 4, f"{row['Összesen']} {row['Pénz']}", 0, 1)

        # Tel / Cím / Rendelés
        pdf.set_xy(x + 5, y + 15)
        pdf.set_font(f_m, "B", 9)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_xy(x + 5, y + 20)
        pdf.set_font(f_m, "", 8)
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        pdf.set_xy(x + 5, y + 31)
        pdf.set_font(f_m, "", 7)
        pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v85 - Ügyfélkód és Precíz Sorszám")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
    if dfs:
        final_df = parse_v85(pd.concat(dfs, ignore_index=True))
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v85(final_df)), "etikettek_v85.pdf")
    os.remove("temp.pdf")
