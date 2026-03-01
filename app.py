import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def clean_extracted_name(name_cand):
    """Megtisztítja a nevet a zavaró PDF elemektől."""
    if not name_cand: return "Név hiányzik"
    # Fejlécek és szemetek szűrése
    garbage = ["Sor", "Ügyfél", "Ügyintéző", "Címe", "Rendelés", "tétel", "Ft", "TEL:", "KÓD:"]
    for g in garbage:
        if g in name_cand: return "Név hiányzik"
    
    # Tisztítás
    name_cand = re.sub(r'[PZ]\s?-\s?\d{6}', '', name_cand)
    name_cand = re.sub(r'^\d+\s+', '', name_cand)
    name_cand = name_cand.strip(" |-/")
    
    if len(name_cand.split()) >= 2 and not re.search(r'\d{3,}', name_cand):
        return name_cand
    return "Név hiányzik"

def parse_v101(pdf_path):
    all_customers = []
    # Kétféle módszerrel is megpróbáljuk beolvasni az oldalt
    try:
        dfs = tabula.read_pdf(pdf_path, pages='all', stream=True, guess=True)
    except:
        return pd.DataFrame()

    for df_page in dfs:
        matrix = df_page.values.tolist()
        # Minden cellát egyetlen nagy listába fűzünk az oldalon
        page_items = []
        for row in matrix:
            for cell in row:
                val = str(cell).strip()
                if val != 'nan' and val != '':
                    page_items.append(val)

        # Keressük a horgonyokat (ügyfélkódokat)
        for i, item in enumerate(page_items):
            code_m = re.search(r'([PZ])\s?-\s?(\d{6})', item)
            if code_m:
                prefix, cid = code_m.group(1), code_m.group(2)
                
                # NÉV KERESÉSE (Különös tekintettel a környező 10 cellára)
                name = "Név hiányzik"
                # Megnézzük a kód előtt és után lévő cellákat
                potential_range = page_items[max(0, i-6):min(len(page_items), i+6)]
                for cand in potential_range:
                    cleaned = clean_extracted_name(cand)
                    if cleaned != "Név hiányzik":
                        name = cleaned
                        break
                
                # Ha a kód cellájában benne van a név is (pl. "Nagy Ákos P-123456")
                if name == "Név hiányzik":
                    name = clean_extracted_name(item)

                # ADATOK (Telefon, Cím, Pénz, Rendelés)
                # Kiterjesztett keresési tartomány a csúszások miatt
                context_window = " ".join(page_items[max(0, i-10):min(len(page_items), i+30)])
                
                tel = "NINCS"
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', context_window)
                if tel_m: tel = tel_m.group(1)

                addr = "Cím hiányzik"
                addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^|]+)', context_window)
                if addr_m: addr = addr_m.group(1).strip()

                money = 0
                money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', context_window)
                if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

                rends = re.findall(r'(\d+-[A-Z0-9]+)', context_window)

                all_customers.append({
                    "id": cid, "prefix": prefix, "name": name, "tel": tel, 
                    "addr": addr, "money": money, "rend": rends
                })

    # Összesítés (Név + Cím alapján csoportosítva)
    final_dict = {}
    for item in all_customers:
        key = (item["name"], item["addr"])
        if key not in final_dict:
            final_dict[key] = {"id": item["id"], "név": item["name"], "cím": item["addr"], 
                               "tel": item["tel"], "P": [], "Z": [], "pénz": 0}
        if item["prefix"] == "Z": final_dict[key]["Z"].extend(item["rend"])
        else: final_dict[key]["P"].extend(item["rend"])
        final_dict[key]["pénz"] += item["money"]

    # Eredmény táblázat
    res = []
    for i, d in enumerate(final_dict.values()):
        res.append({
            "Sorszám": i+1, "Ügyfélkód": d["id"], "Ügyintéző": d["név"],
            "Telefon": d["tel"], "Cím": d["cím"],
            "Rendelés": f"P: {', '.join(set(d['P']))} | SZ: {', '.join(set(d['Z']))}".strip(" |"),
            "Összesen": f"{len(d['P'])+len(d['Z'])} tétel",
            "Pénz": f"{d['pénz']} Ft" if d['pénz'] > 0 else ""
        })
    return pd.DataFrame(res)

# PDF generáló (Design marad)
def create_pdf_v101(df):
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

st.title("Interfood v101 - Mélyelemző")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    final_df = parse_v101("temp.pdf")
    if not final_df.empty:
        st.write(f"Talált ügyfelek: {len(final_df)}")
        st.dataframe(final_df)
        st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v101(final_df)), "etikettek_v101.pdf")
    else:
        st.error("Nem sikerült adatot kinyerni. Ellenőrizd a PDF formátumát!")
    os.remove("temp.pdf")
