import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v83(df_raw):
    temp_storage = {} 

    for idx, row in df_raw.iterrows():
        # Sor összefűzése egyetlen nagy szöveggé a könnyebb kereséshez
        row_values = [str(val).strip() for val in row.values if str(val) != 'nan']
        full_row_text = " ".join(row_values)
        
        # Csak azokat a sorokat nézzük, ahol van P- vagy Z- kód
        if not re.search(r'[PZ]-\d+', full_row_text): continue
        
        # Alatt lévő sor a pénz miatt
        next_row_text = ""
        if idx + 1 < len(df_raw):
            next_row_text = " ".join([str(val) for val in df_raw.iloc[idx + 1].values if str(val) != 'nan'])

        # Blokkokra bontás (5-ös egységek, ahogy korábban megbeszéltük)
        for i in range(0, len(row.values), 5):
            if i + 3 >= len(row.values): break
            
            # Az adott ügyfélhez tartozó összes szövegmorzsa
            chunk = " ".join([str(row.values[i+j]) for j in range(5) if i+j < len(row.values)])
            
            # 1. KÓD ÉS NAP
            code_match = re.search(r'([PZ])-(\d+)', chunk)
            if not code_match: continue
            day_prefix = code_match.group(1)
            cust_id = code_match.group(2)

            # 2. CÍM (4 jegyű irányítószámtól)
            addr = "Cím nem található"
            addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ][^0-9]+[^,]+,?\s*[^0-9\s]*)', chunk)
            if addr_m:
                addr = addr_m.group(1).strip()

            # 3. NÉV (Az ügyfélkód és az irányítószám közötti rész)
            # Ez a legkritikusabb rész, itt rontottuk el korábban
            name = "Ismeretlen Ügyfél"
            name_m = re.search(r'[PZ]-\d+\s+(.*?)\s+\d{4}', chunk)
            if name_m:
                name = name_m.group(1).replace('/', '').strip()
            elif len(row.values) > i+2: # Tartalék megoldás: a 2. indexű oszlop
                name = str(row.values[i+2]).strip()

            # 4. TELEFON
            tel = "NINCS"
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', chunk)
            if tel_m: tel = tel_m.group(1)

            # 5. RENDELÉS ÉS MENNYISÉG (1-L1K típusú kódok összege)
            rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', chunk)
            current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', chunk))
            total_db = sum(int(c) for c in rend_codes)

            # 6. PÉNZ (A következő sorból, ha van benne Ft vagy szám)
            money = 0
            money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', next_row_text)
            if money_m:
                money = int(re.sub(r'\s+', '', money_m.group(1)))

            # --- TÁROLÁS ---
            customer_key = (name, addr)
            if customer_key not in temp_storage:
                temp_storage[customer_key] = {"név": name, "cím": addr, "tel": tel, "P": "", "Z": "", "db": 0, "pénz": 0}
            
            if day_prefix == "P": temp_storage[customer_key]["P"] = current_rend_str
            else: temp_storage[customer_key]["Z"] = current_rend_str
            
            temp_storage[customer_key]["db"] += total_db
            temp_storage[customer_key]["pénz"] += money

    # DataFrame építése
    res = []
    for d in temp_storage.values():
        t = "PÉNTEK"
        r = d["P"]
        if d["P"] and d["Z"]:
            t, r = "PÉNTEK + SZOMBAT", f"P: {d['P']} | SZ: {d['Z']}"
        elif d["Z"]:
            t, r = "SZOMBAT", d["Z"]
            
        res.append({
            "Ügyintéző": d["név"], "Telefon": d["tel"], "Cím": d["cím"],
            "Rendelés": r, "Típus": t, "Összesen": f"{d['db']} tétel",
            "Pénz": f"BESZEDENDŐ: {d['pénz']} Ft" if d['pénz'] > 0 else (f"VISSZAADNI: {abs(d['pénz'])} Ft" if d['pénz'] < 0 else "")
        })
    return pd.DataFrame(res)

# PDF generálás (marad a bevált v82-es design)
def create_pdf_v83(df):
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
        pdf.set_xy(x + 5, y + 4)
        pdf.set_font(f_m, "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:30], 0, 1)
        pdf.set_xy(x + 5, y + 9)
        pdf.set_font(f_m, "B", 8)
        if "+" in row['Típus']: pdf.set_text_color(200, 0, 0)
        pdf.cell(60, 4, f"{row['Típus']} - {row['Összesen']}", 0, 1)
        pdf.set_text_color(0, 0, 0)
        if row['Pénz']:
            pdf.set_xy(x + 5, y + 13)
            pdf.set_font(f_m, "B", 10)
            pdf.cell(60, 5, row['Pénz'], 0, 1)
        pdf.set_xy(x + 5, y + 18)
        pdf.set_font(f_m, "B", 9)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_xy(x + 5, y + 22)
        pdf.set_font(f_m, "", 8)
        pdf.multi_cell(60, 3.3, str(row['Cím']), 0, 'L')
        pdf.set_xy(x + 5, y + 32)
        pdf.set_font(f_m, "", 7)
        pdf.multi_cell(60, 2.8, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v83 - Név Helyreállító")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
    if dfs:
        final_df = parse_v83(pd.concat(dfs, ignore_index=True))
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v83(final_df)), "etikettek_v83.pdf")
    os.remove("temp.pdf")
