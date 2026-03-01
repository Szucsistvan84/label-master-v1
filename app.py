import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v99(pdf_path):
    all_customers = []
    # Oldalanként olvassuk be, hogy ne csússzanak össze a hasábok
    total_pages = tabula.read_pdf(pdf_path, pages='all', stream=True, guess=False)
    
    for df_page in total_pages:
        matrix = df_page.values.tolist()
        page_text_list = []
        for row in matrix:
            page_text_list.extend([str(c).strip() for c in row if str(c) != 'nan' and str(c) != ''])
        
        full_page_str = " | ".join(page_text_list)
        
        # Keressük meg az összes ügyfélkódot az oldalon
        codes = re.findall(r'([PZ])\s?-\s?(\d{6})', full_page_str)
        
        for prefix, cid in codes:
            # Megkeressük a kódot tartalmazó cellát és a környezetét a listában
            idx = -1
            for i, val in enumerate(page_text_list):
                if cid in val and (prefix + "-" in val or prefix + " -" in val):
                    idx = i
                    break
            
            if idx == -1: continue

            # NÉV KERESÉSE: Megnézzük az összes cellát az oldalon, 
            # ami NEM tartalmaz kódot, de 2-3 szóból áll és Nagybetűs
            name = "Név hiányzik"
            # Először nézzük meg a kód ELŐTTI 3 cellát (legvalószínűbb)
            for i in range(max(0, idx-5), idx+5):
                cand = page_text_list[i]
                clean = re.sub(r'[PZ]\s?-\s?\d{6}', '', cand).strip()
                clean = re.sub(r'^\d+\s+', '', clean).strip()
                if len(clean.split()) >= 2 and not re.search(r'\d{2,}', clean):
                    if not any(x in clean for i, x in enumerate(["Debrecen", "utca", "út", "tér", "tétel", "Ft"])):
                        name = clean
                        break

            # TELEFON: Bárhol az oldalon, ami a kód közelében van
            tel = "NINCS"
            search_area = " ".join(page_text_list[max(0, idx-10):min(len(page_text_list), idx+20)])
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', search_area)
            if tel_m: tel = tel_m.group(1)

            # CÍM: Irányítószám alapján
            addr = "Cím hiányzik"
            addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^|]+)', search_area)
            if addr_m: addr = addr_m.group(1).strip()

            # PÉNZ:
            money = 0
            money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', search_area)
            if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

            # RENDELÉS:
            rends = re.findall(r'(\d+-[A-Z0-9]+)', search_area)

            all_customers.append({
                "id": cid, "prefix": prefix, "name": name, "tel": tel, 
                "addr": addr, "money": money, "rend": rends
            })

    # Összesítés és duplikátum szűrés
    final_dict = {}
    for item in all_customers:
        key = (item["name"], item["addr"])
        if key not in final_dict:
            final_dict[key] = {"id": item["id"], "név": item["name"], "cím": item["addr"], 
                               "tel": item["tel"], "P": [], "Z": [], "pénz": 0}
        if item["prefix"] == "Z": final_dict[key]["Z"].extend(item["rend"])
        else: final_dict[key]["P"].extend(item["rend"])
        final_dict[key]["pénz"] += item["money"]

    return pd.DataFrame([{
        "Sorszám": i+1, "Ügyfélkód": d["id"], "Ügyintéző": d["név"],
        "Telefon": d["tel"], "Cím": d["cím"],
        "Rendelés": f"P: {', '.join(set(d['P']))} | SZ: {', '.join(set(d['Z']))}".strip(" |"),
        "Összesen": f"{len(d['P'])+len(d['Z'])} tétel",
        "Pénz": f"{d['pénz']} Ft" if d['pénz'] > 0 else ""
    } for i, d in enumerate(final_dict.values())])

# PDF generáló változatlan
def create_pdf_v99(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    f_p, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    f_m = "DejaVu" if os.path.exists(f_p) else "Arial"
    if f_m == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=f_p); pdf.add_font("DejaVu", style="B", fname=f_b)
    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        x, y = (i % 3) * 70, ((i // 3) % 7) * 42.4
        pdf.set_xy(x+2, y+2); pdf.set_font(f_m, "", 6); pdf.cell(50, 3, f"#{row['Sorszám']} | KÓD: {row['Ügyfélkód']}")
        pdf.set_xy(x+5, y+5); pdf.set_font(f_m, "B", 10); pdf.cell(60, 5, str(row['Ügyintéző'])[:30])
        pdf.set_xy(x+5, y+10); pdf.set_font(f_m, "B", 8); pdf.cell(60, 4, f"{row['Összesen']} {row['Pénz']}")
        pdf.set_xy(x+5, y+15); pdf.set_font(f_m, "B", 10); pdf.set_text_color(0, 0, 150)
        pdf.cell(60, 5, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_text_color(0,0,0); pdf.set_xy(x+5, y+20); pdf.set_font(f_m, "", 8)
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        pdf.set_xy(x+5, y+31); pdf.set_font(f_m, "", 7); pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v99 - A Detektív")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    final_df = parse_v99("temp.pdf")
    st.write(f"Ügyfelek: {len(final_df)}")
    st.dataframe(final_df)
    if not final_df.empty:
        st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v99(final_df)), "etikettek_v99.pdf")
    os.remove("temp.pdf")
