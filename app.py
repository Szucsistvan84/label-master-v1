import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v87(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        # Sor ellenőrzése (ügyfélkód jelenléte)
        row_list = [str(v).strip() for v in row.values]
        full_text = " ".join(row_list)
        if not re.search(r'[A-Z]-\d{6}', full_text): continue
        
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

            # 2. ÜGYINTÉZŐ NEVE (Intelligens index-kereső)
            # Elsődlegesen a 2-es indexet nézzük, de ha ott nem név van, keresünk tovább
            potential_name = ""
            candidates = [str(row.values[i+2]), str(row.values[i+1]), str(row.values[i+3])]
            
            for cand in candidates:
                cand = cand.strip()
                # Szűrés: nem nan, nem csak szám, nem ügyfélkód, nem irányítószám
                if cand != "nan" and not re.match(r'^\d+$', cand) and not re.search(r'[A-Z]-\d{6}', cand) and not re.search(r'\d{4}', cand):
                    # Ha van benne "/", akkor csak a nevet kérjük (gyakran: Cégnév / Név)
                    if "/" in cand:
                        potential_name = cand.split("/")[-1].strip()
                    else:
                        potential_name = cand
                    if len(potential_name) > 2: break

            name = potential_name if potential_name else "Név nem azonosítható"

            # 3. CÍM (1-es cella irányítószámtól)
            addr = "Cím hiányzik"
            addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', code_cell)
            if addr_m: addr = addr_m.group(1).strip()

            # 4. TELEFON ÉS RENDELÉS (3-as index)
            tel_rend_cell = str(row.values[i+3])
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', tel_rend_cell)
            tel = tel_m.group(1) if tel_m else "NINCS"
            
            rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', tel_rend_cell)
            current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', tel_rend_cell))
            total_db = sum(int(c) for c in rend_codes)

            # 5. PÉNZ (Alatta lévő sor)
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

# A PDF generátor maradt a régi (v86)
def create_pdf_v87(df):
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
        pdf.set_xy(x + 2, y + 2)
        pdf.set_font(f_m, "", 6); pdf.cell(50, 3, f"#{row['Sorszám']} | KÓD: {row['Ügyfélkód']}")
        pdf.set_xy(x + 5, y + 5)
        pdf.set_font(f_m, "B", 10); pdf.cell(60, 5, str(row['Ügyintéző'])[:30])
        pdf.set_xy(x + 5, y + 10)
        pdf.set_font(f_m, "B", 8); pdf.cell(60, 4, f"{row['Összesen']} {row['Pénz']}")
        pdf.set_xy(x + 5, y + 15)
        pdf.set_font(f_m, "B", 9); pdf.cell(60, 4, f"TEL: {row['Telefon']}")
        pdf.set_xy(x + 5, y + 20)
        pdf.set_font(f_m, "", 8); pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        pdf.set_xy(x + 5, y + 31)
        pdf.set_font(f_m, "", 7); pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v87 - Rugalmas Névkereső")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
    if dfs:
        final_df = parse_v87(pd.concat(dfs, ignore_index=True))
        st.write(f"Talált ügyfelek száma: {len(final_df)}")
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v87(final_df)), "etikettek_v87.pdf")
    os.remove("temp.pdf")
