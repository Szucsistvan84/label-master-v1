import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def clean_name_v95(text):
    """Kiszűri a nevet a zavaros cellákból is."""
    if not text or text == "nan": return None
    
    # 1. Ha van benne perjel, a perjel utáni rész a név (pl. Cég Kft / Kovács János)
    if "/" in text:
        text = text.split("/")[-1]
    
    # 2. Távolítsuk el az irányítószámokat és házszámokat (4+ számjegy vagy számok a végén)
    text = re.sub(r'\d{4,}', '', text) # Irányítószám ki
    text = re.sub(r'\d+$', '', text)    # Sor végi számok ki
    
    # 3. Alapvető takarítás
    text = text.strip(",. ")
    
    # Ha maradt benne betű és legalább 3 karakter, akkor ez lesz a név
    if len(text) > 3 and re.search(r'[a-zA-ZÁÉÍÓÖŐÚÜŰ]', text):
        return text
    return None

def parse_v95(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        cells = [str(c).strip() for c in row.values if str(c) != 'nan']
        row_str = " ".join(cells)
        
        code_match = re.search(r'([A-Z])-\s?(\d{6})', row_str)
        if not code_match: continue
        
        day_prefix, cust_id = code_match.group(1), code_match.group(2)
        
        # Alapadatok
        name, tel, addr, raw_rend = "Név hiányzik", "NINCS", "Cím hiányzik", ""

        # --- NÉV KERESÉSE (Prioritás: 2-es index, majd a többi) ---
        # Megpróbáljuk a fix helyet először
        if len(row.values) > 2:
            potential_name = clean_name_v95(str(row.values[2]))
            if potential_name: name = potential_name

        # Ha nem lett meg, végignézzük a cellákat
        if name == "Név hiányzik":
            for c in cells:
                if "tétel" in c or "Ft" in c or "-" in c: continue # Ezek nem nevek
                res = clean_name_v95(c)
                if res:
                    name = res
                    break

        # --- TELEFON, CÍM, RENDELÉS ---
        for c in cells:
            if re.search(r'(\d{2}/[\d\s-]{7,})', c) or c.startswith(('+36', '06')):
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', c)
                if tel_m:
                    tel = tel_m.group(1)
                    raw_rend += " " + c.replace(tel, "").strip()
            elif re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', c):
                addr = c
            if re.search(r'\d+-[A-Z0-9]+', c):
                raw_rend += " " + c

        # PÉNZ KERESÉSE
        money = 0
        search_money = row_str
        if idx + 1 < len(df_raw):
            search_money += " " + " ".join([str(v) for v in df_raw.iloc[idx+1].values if str(v) != 'nan'])
        money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', search_money)
        if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

        # ÖSSZEGZÉS ÉS TÁROLÁS
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

# PDF generáló (v94-es design)
def create_pdf_v95(df):
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

st.title("Interfood v95 - Névkereső Javítás")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
    if dfs:
        final_df = parse_v95(pd.concat(dfs, ignore_index=True))
        st.write(f"Ügyfelek: {len(final_df)}")
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v95(final_df)), "etikettek_v95.pdf")
    os.remove("temp.pdf")
