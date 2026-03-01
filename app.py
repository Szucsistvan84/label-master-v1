import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v98(df_raw):
    matrix = df_raw.values.tolist()
    rows = len(matrix)
    cols = len(matrix[0])
    
    found_customers = []

    for r in range(rows):
        for c in range(cols):
            cell_val = str(matrix[r][c]).strip()
            
            # ÜGYFÉLKÓD KERESÉSE (P-123456 vagy Z-123456)
            code_match = re.search(r'([PZ])\s?-\s?(\d{6})', cell_val)
            if code_match:
                prefix = code_match.group(1)
                cid = code_match.group(2)
                
                # --- NÉV KERESÉSE (Közvetlen környezetben: felette, mellette, benne) ---
                name = "Név hiányzik"
                search_candidates = []
                
                # 1. Megnézzük ugyanazt a cellát (hátha benne van a név is)
                search_candidates.append(cell_val)
                # 2. Megnézzük a felette lévő cellát (nagyon gyakori!)
                if r > 0: search_candidates.append(str(matrix[r-1][c]))
                # 3. Megnézzük a balra lévő cellát
                if c > 0: search_candidates.append(str(matrix[r][c-1]))
                # 4. Megnézzük a jobbra lévő cellát
                if c < cols - 1: search_candidates.append(str(matrix[r][c+1]))

                for cand in search_candidates:
                    cand = cand.strip()
                    if cand == "nan" or cand == "": continue
                    # Tisztítás: ha benne van a kód, vágjuk le
                    clean_cand = re.sub(r'[PZ]\s?-\s?\d{6}', '', cand).strip()
                    clean_cand = re.sub(r'^\d+\s+', '', clean_cand).strip() # Sorszám le
                    
                    # Ha maradt értelmes név (2 szó, nincs benne 'tétel' vagy 'Ft')
                    if len(clean_cand.split()) >= 2 and not re.search(r'\d{3,}', clean_cand):
                        if "tétel" not in clean_cand.lower() and "beszedendő" not in clean_cand.lower():
                            name = clean_cand
                            break

                # --- TELEFON, CÍM, RENDELÉS, PÉNZ ---
                # Itt egy kicsit tágabb kört nézünk, mert ezek el tudnak csúszni (ahogy írtad)
                context = []
                for ri in range(max(0, r-2), min(rows, r+6)):
                    for ci in range(max(0, c-2), min(cols, c+15)):
                        val = str(matrix[ri][ci]).strip()
                        if val != "nan" and val != "": context.append(val)
                
                full_context = " | ".join(context)
                
                tel = "NINCS"
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', full_context)
                if tel_m: tel = tel_m.group(1)
                
                addr = "Cím hiányzik"
                addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^|]+)', full_context)
                if addr_m: addr = addr_m.group(1).strip()
                
                money = 0
                money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', full_context)
                if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))
                
                rend_list = re.findall(r'(\d+-[A-Z0-9]+)', full_context)
                
                found_customers.append({
                    "cid": cid, "prefix": prefix, "name": name, "tel": tel, 
                    "addr": addr, "money": money, "rend": rend_list
                })

    # Összesítés (Péntek + Szombat összevonás)
    final_dict = {}
    for item in found_customers:
        key = (item["name"], item["addr"])
        if key not in final_dict:
            final_dict[key] = {"id": item["cid"], "név": item["name"], "cím": item["addr"], 
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

# PDF generáló marad
def create_pdf_v98(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    f_path, f_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    f_m = "DejaVu" if os.path.exists(f_path) else "Arial"
    if f_m == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=f_path); pdf.add_font("DejaVu", style="B", fname=f_bold)
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

st.title("Interfood v98 - Precíziós Horgony")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
    if dfs:
        final_df = parse_v98(pd.concat(dfs, ignore_index=True))
        st.write(f"Ügyfelek: {len(final_df)}")
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v98(final_df)), "etikettek_v98.pdf")
    os.remove("temp.pdf")
