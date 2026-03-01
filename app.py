import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v97(df_raw):
    # 1. Alakítsuk az egész táblázatot egy nagy szöveges mátrixszá, ahol minden cella tiszta
    matrix = df_raw.values.tolist()
    rows = len(matrix)
    cols = len(matrix[0])
    
    customers = []
    
    # Végigszaladunk az összes létező cellán (függetlenül attól, hol van)
    for r in range(rows):
        for c in range(cols):
            cell_val = str(matrix[r][c]).strip()
            if cell_val == "nan" or cell_val == "": continue
            
            # KERESSÜK A HORGONYT (Ügyfélkód: pl. P-123456 vagy "89 P-446205")
            code_match = re.search(r'([PZ])\s?-\s?(\d{6})', cell_val)
            if code_match:
                day_prefix = code_match.group(1)
                cust_id = code_match.group(2)
                
                # Találtunk egy ügyfelet! Most gyűjtsük össze a környezetéből az adatokat.
                # Megnézzük a horgony celláját és a környező cellákat (5 soron és 10 oszlopon belül)
                search_area = []
                for ri in range(max(0, r-1), min(rows, r+4)):
                    for ci in range(max(0, c-2), min(cols, c+15)): # Bőven nézzünk jobbra (F, K, P, V oszlopok miatt)
                        val = str(matrix[ri][ci]).strip()
                        if val != "nan" and val != "":
                            search_area.append(val)
                
                full_text = " | ".join(search_area)
                
                # ADATOK KINYERÉSE A KÖRNYEZETBŐL
                # 1. Telefonszám
                tel = "NINCS"
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', full_text)
                if tel_m: tel = tel_m.group(1)
                
                # 2. Ügyintéző név (Azt mondtad, külön cellában van - keressük a legvalószínűbbet)
                name = "Név hiányzik"
                for item in search_area:
                    # Olyan szöveg, ami 2-3 szóból áll, nagybetűs, nincs benne kód, se "tétel", se "Ft"
                    if len(item.split()) >= 2 and not re.search(r'\d', item) and "tétel" not in item.lower():
                        if not any(x in item for x in ["Debrecen", "utca", "út", "tér", "Interfood"]):
                            name = item
                            break
                
                # 3. Cím (Irányítószám alapján)
                addr = "Cím hiányzik"
                addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^|]+)', full_text)
                if addr_m: addr = addr_m.group(1).strip()
                
                # 4. Pénz (Ft-ot keresünk)
                money = 0
                money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', full_text)
                if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))
                
                # 5. Rendelés kódok (pl. 1-L3K)
                rend_list = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                current_rend_str = ", ".join(rend_list)
                total_db = sum(int(re.search(r'(\d+)', x).group(1)) for x in rend_list if re.search(r'(\d+)', x))

                customers.append({
                    "id": cust_id, "prefix": day_prefix, "name": name, 
                    "tel": tel, "addr": addr, "money": money, 
                    "rend": current_rend_str, "db": total_db
                })

    # Duplikációk szűrése és összevonás (ha ugyanaz a név és cím)
    final_data = {}
    for c in customers:
        key = (c["name"], c["addr"])
        if key not in final_data:
            final_data[key] = {
                "kód": c["id"], "név": c["name"], "cím": c["addr"], "tel": c["tel"],
                "P": "", "SZ": "", "db": 0, "pénz": 0
            }
        if c["prefix"] == "Z": final_data[key]["SZ"] = c["rend"]
        else: final_data[key]["P"] = c["rend"]
        final_data[key]["db"] += c["db"]
        final_data[key]["pénz"] += c["money"]

    return pd.DataFrame([{
        "Sorszám": i+1, "Ügyfélkód": d["kód"], "Ügyintéző": d["név"],
        "Telefon": d["tel"], "Cím": d["cím"],
        "Rendelés": f"P: {d['P']} | SZ: {d['SZ']}" if d['P'] and d['SZ'] else (d['P'] or d['SZ']),
        "Összesen": f"{d['db']} tétel", "Pénz": f"{d['pénz']} Ft" if d['pénz'] != 0 else ""
    } for i, d in enumerate(final_data.values())])

# A PDF generáló (v96 design) maradhat
def create_pdf_v97(df):
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

st.title("Interfood v97 - A Hasáb-törő")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    # Megpróbáljuk a lehető legnyersebb módon kinyerni az adatokat
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False, lattice=False)
    if dfs:
        final_df = parse_v97(pd.concat(dfs, ignore_index=True))
        st.write(f"Talált ügyfelek: {len(final_df)}")
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v97(final_df)), "etikettek_v97.pdf")
    os.remove("temp.pdf")
