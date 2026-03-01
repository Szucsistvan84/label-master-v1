import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v94(df_raw):
    temp_storage = {} 
    order_list = [] 

    # Tisztítjuk az egész táblázatot a teljesen üres oszlopoktól/soroktól az elején
    df_raw = df_raw.dropna(how='all').reset_index(drop=True)

    for idx, row in df_raw.iterrows():
        # A sort egyetlen szövegként kezeljük a kereséshez
        row_values = [str(c).strip() for c in row.values if str(c) != 'nan']
        if not row_values: continue
        row_str = " ".join(row_values)
        
        # Ügyfélkód keresése
        code_match = re.search(r'([A-Z])-\s?(\d{6})', row_str)
        if not code_match: continue
        
        day_prefix, cust_id = code_match.group(1), code_match.group(2)
        
        # Adatok alaphelyzetbe állítása minden találatnál
        name, tel, addr, raw_rend = "Név hiányzik", "NINCS", "Cím hiányzik", ""

        # Végigmegyünk a sor celláin és "szüretelünk"
        for c in row_values:
            # Telefonszám (regex: 06 vagy +36 vagy 20/30/70 és perjel)
            if re.search(r'(\d{2}/[\d\s-]{7,})', c) or c.startswith(('+36', '06')):
                tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', c)
                if tel_m:
                    tel = tel_m.group(1)
                    raw_rend += " " + c.replace(tel, "").strip()
            # Cím (irányítószám alapján)
            elif re.search(r'\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ]', c):
                addr = c
            # Név (ha még nincs meg, legalább 2 szó és nincs benne szám)
            elif name == "Név hiányzik" and len(c.split()) >= 2 and not re.search(r'\d', c):
                name = c
            # Rendelés kódok
            if re.search(r'\d+-[A-Z0-9]+', c):
                raw_rend += " " + c

        # Pénz keresése (vagy ebben a sorban, vagy a következőben)
        money = 0
        search_text_for_money = row_str
        if idx + 1 < len(df_raw):
            next_row_str = " ".join([str(v) for v in df_raw.iloc[idx+1].values if str(v) != 'nan'])
            search_text_for_money += " " + next_row_str
            
        money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', search_text_for_money)
        if money_m:
            money = int(re.sub(r'\s+', '', money_m.group(1)))

        # Összegzés
        rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', raw_rend)
        current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', raw_rend))
        total_db = sum(int(c) for c in rend_codes)

        # Tárolás (Név + Cím kulccsal az összevonáshoz)
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

# PDF generáló függvény (v93 alapján)
def create_pdf_v94(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path, font_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    f_m = "DejaVu" if os.path.exists(font_path) else "Arial"
    if f_m == "DejaVu":
        pdf.add_font("DejaVu", style="", fname=font_path)
        pdf.add_font("DejaVu", style="B", fname=font_bold)

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

st.title("Interfood v94 - Stabilizált Motor")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    try:
        # Stream=True és guess=False a stabilitásért
        dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
        if dfs:
            final_df = parse_v94(pd.concat(dfs, ignore_index=True))
            st.write(f"Sikeresen feldolgozva: {len(final_df)} ügyfél")
            st.dataframe(final_df)
            if not final_df.empty:
                st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v94(final_df)), "etikettek_v94.pdf")
    except Exception as e:
        st.error(f"Hiba történt a feldolgozás során: {e}")
    finally:
        if os.path.exists("temp.pdf"): os.remove("temp.pdf")
