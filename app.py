import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def extract_name_v96(cells, row_str):
    """Mélyelemzéssel megkeresi a nevet a sorban."""
    # 1. Próbálkozás: Perjel utáni rész (leggyakoribb a cégesnél)
    slash_match = re.search(r'/\s*([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű.\-\s]{3,})', row_str)
    if slash_match:
        cand = slash_match.group(1).strip()
        if not re.search(r'\d{4}', cand): # Ne legyen benne irányítószám
            return cand

    # 2. Próbálkozás: Olyan cella, ami legalább két szóból áll, Nagybetűs, és nincs benne szám
    for c in cells:
        c = c.strip()
        if len(c.split()) >= 2 and re.match(r'^[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ\-\s]+$', c):
            if "Debrecen" not in c and "utca" not in c and "út" not in c:
                return c

    # 3. Próbálkozás: Ha a cím cellájában van benne a név a végén (pl. "... 4030 Debrecen, Kiss Géza")
    addr_name_match = re.search(r'\d{4}\s+Debrecen,?\s+.*?\s+([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)', row_str)
    if addr_name_match:
        return addr_name_match.group(1).strip()

    return "Név hiányzik"

def parse_v96(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        cells = [str(c).strip() for c in row.values if str(c) != 'nan' and str(c) != '']
        row_str = " ".join(cells)
        
        code_match = re.search(r'([A-Z])-\s?(\d{6})', row_str)
        if not code_match: continue
        
        day_prefix, cust_id = code_match.group(1), code_match.group(2)
        
        # Név keresése az új logikával
        name = extract_name_v96(cells, row_str)
        
        # Telefon, Cím, Rendelés marad a bevált v94/v95 logikán
        tel, addr, raw_rend = "NINCS", "Cím hiányzik", ""
        for c in cells:
            if re.search(r'(\d{2}/[\d\s-]{7,})', c) or c.startswith(('+36', '06')):
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', c)
                if tel_m: tel = tel_m.group(1); raw_rend += " " + c.replace(tel, "").strip()
            elif re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', c):
                addr = c
            if re.search(r'\d+-[A-Z0-9]+', c):
                raw_rend += " " + c

        # Pénz (keressük az aktuális és a következő sorban is)
        money = 0
        search_money = row_str
        if idx + 1 < len(df_raw):
            search_money += " " + " ".join([str(v) for v in df_raw.iloc[idx+1].values if str(v) != 'nan'])
        money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', search_money)
        if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

        rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', raw_rend)
        current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', raw_rend))
        total_db = sum(int(c) for c in rend_codes)

        customer_key = (name, addr)
        if customer_key not in temp_storage:
            temp_storage[customer_key] = {
                "kód": cust_id, "név": name, "cím": addr, "tel": tel, 
                "P": "", "Z": "", "db": 0, "pénz": 0, "orig_idx": len(order_list) + 1
            }
            order_list.append(customer_key)
        
        if day_prefix == "Z": temp_storage[customer_key]["Z"] = current_rend_str
        else: temp_storage[customer_key]["P"] = current_rend_str 
        temp_storage[customer_key]["db"] += total_db
        temp_storage[customer_key]["pénz"] += money

    return pd.DataFrame([{
        "Sorszám": d["orig_idx"], "Ügyfélkód": d["kód"], "Ügyintéző": d["név"],
        "Telefon": d["tel"], "Cím": d["cím"],
        "Rendelés": f"P: {d['P']} | SZ: {d['Z']}" if d['P'] and d['Z'] else (d['P'] or d['Z']),
        "Összesen": f"{d['db']} tétel", "Pénz": f"{d['pénz']} Ft" if d['pénz'] != 0 else ""
    } for key, d in temp_storage.items()])

# PDF generálás (Sorszám fontossága miatt marad a design)
def create_pdf_v96(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    f_m = "DejaVu" if os.path.exists(font_path) else "Arial"
    if f_m == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=font_path); pdf.add_font("DejaVu", style="B", fname=font_bold)

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        pdf.set_xy(x + 2, y + 2); pdf.set_font(f_m, "", 6); pdf.cell(50, 3, f"#{row['Sorszám']} | KÓD: {row['Ügyfélkód']}")
        pdf.set_xy(x + 5, y + 5); pdf.set_font(f_m, "B", 10); pdf.cell(60, 5, str(row['Ügyintéző'])[:30])
        pdf.set_xy(x + 5, y + 10); pdf.set_font(f_m, "B", 8); pdf.cell(60, 4, f"{row['Összesen']} {row['Pénz']}")
        pdf.set_xy(x + 5, y + 15); pdf.set_font(f_m, "B", 10); pdf.set_text_color(0, 0, 150)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(x + 5, y + 20); pdf.set_font(f_m, "", 8); pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        pdf.set_xy(x + 5, y + 31); pdf.set_font(f_m, "", 7); pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v96 - Névbányász")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
    if dfs:
        final_df = parse_v96(pd.concat(dfs, ignore_index=True))
        st.write(f"Ügyfelek: {len(final_df)}")
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v96(final_df)), "etikettek_v96.pdf")
    os.remove("temp.pdf")
