import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v92(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        row_str = " ".join([str(v) for v in row.values if str(v) != 'nan'])
        # Csak azokat a sorokat nézzük, ahol van ügyfélkód
        if not re.search(r'[A-Z]-\s?\d{6}', row_str): continue
        
        next_row_text = ""
        if idx + 1 < len(df_raw):
            next_row_text = " ".join([str(val) for val in df_raw.iloc[idx + 1].values if str(val) != 'nan'])

        # 5-ös blokkok kezelése (hasábos elrendezés miatt)
        for i in range(0, len(row.values), 5):
            if i + 4 >= len(row.values): break
            
            # 1. ÜGYFÉLKÓD (Mindig az 1-es index környékén)
            code_cell = str(row.values[i+1])
            code_match = re.search(r'([A-Z])-\s?(\d{6})', code_cell)
            if not code_match: continue
            day_prefix, cust_id = code_match.group(1), code_match.group(2)

            # 2. ÜGYINTÉZŐ NEVE (Visszahozzuk a v89-es logikát)
            name = "Név nem található"
            for offset in [2, 1, 3]: # Megnézzük a szomszédos cellákat is
                cand = str(row.values[i+offset]).strip()
                # Ha nem nan, nem csak szám, nem kód és van benne legalább 4 karakter
                if cand != "nan" and not re.match(r'^\d+$', cand) and not re.search(r'[A-Z]-\d{6}', cand) and len(cand) > 3:
                    if "/" in cand and not re.search(r'\d{2}/', cand): # Ha cégnév/név, de nem telefon
                        name = cand.split("/")[-1].strip()
                    else:
                        name = cand
                    break

            # 3. TELEFON ÉS RENDELÉS (A 3-as vagy 4-es cellából)
            tel = "NINCS"
            raw_rend = ""
            # Megnézzük a 3-as és 4-es indexet is telefonszámért
            target_cells = [str(row.values[i+3]), str(row.values[i+4])]
            
            for cell in target_cells:
                cell = cell.strip()
                if cell == "nan": continue
                
                # Ha van benne telefonszám minta (perjel és számok)
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', cell)
                if tel_m:
                    tel = tel_m.group(1)
                    # A maradék a rendelés
                    raw_rend += " " + cell.replace(tel, "").strip()
                else:
                    raw_rend += " " + cell

            rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', raw_rend)
            current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', raw_rend))
            total_db = sum(int(c) for c in rend_codes)

            # 4. CÍM (Az 1-es cellából az irányítószámtól)
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

# PDF generálás (A v90-ben dicsért kék telefonos design)
def create_pdf_v92(df):
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
        pdf.set_xy(x + 5, y + 5); pdf.set_font(f_m, "B", 10); pdf.cell(60, 5, str(row['Ügyintéző'])[:30])
        pdf.set_xy(x + 5, y + 10); pdf.set_font(f_m, "B", 8); pdf.cell(60, 4, f"{row['Összesen']} {row['Pénz']}")
        
        # TELEFON - Kiemelve
        pdf.set_xy(x + 5, y + 15); pdf.set_font(f_m, "B", 10); pdf.set_text_color(0, 0, 150)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_text_color(0, 0, 0)

        pdf.set_xy(x + 5, y + 20); pdf.set_font(f_m, "", 8); pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        pdf.set_xy(x + 5, y + 31); pdf.set_font(f_m, "", 7); pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v92 - Rekonstrukciós Verzió")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=True)
    if dfs:
        final_df = parse_v92(pd.concat(dfs, ignore_index=True))
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v92(final_df)), "etikettek_v92.pdf")
    os.remove("temp.pdf")
