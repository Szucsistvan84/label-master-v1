import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v88(df_raw):
    temp_storage = {} 
    order_list = [] 

    for idx, row in df_raw.iterrows():
        # Ellenőrizzük, hogy van-e a sorban ügyfélkód (H, K, S, C, P, Z + 6 számjegy)
        row_str = " ".join([str(v) for v in row.values if str(v) != 'nan'])
        if not re.search(r'[A-Z]-\d{6}', row_str): continue
        
        # Pénzügyi adat az alatta lévő sorból
        next_row_text = ""
        if idx + 1 < len(df_raw):
            next_row_text = " ".join([str(val) for val in df_raw.iloc[idx + 1].values if str(val) != 'nan'])

        # 5-ös blokkokban dolgozunk (a hasábok miatt)
        for i in range(0, len(row.values), 5):
            if i + 4 >= len(row.values): break
            
            # 1. ÜGYFÉLKÓD (atombiztos 6 jegyű, az 1-es indexű oszlopban)
            code_cell = str(row.values[i+1])
            code_match = re.search(r'([A-Z])-\s?(\d{6})', code_cell)
            if not code_match: continue
            day_prefix, cust_id = code_match.group(1), code_match.group(2)

            # 2. ÜGYINTÉZŐ NEVE (Szigorúan a 2-es index, ahogy kérted!)
            # Ez a cella tartalmazza a "színtiszta nevet"
            name = str(row.values[i+2]).strip()
            
            # Ha nan vagy üres, akkor ne hagyjuk teljesen üresen
            if name == "nan" or not name:
                name = "Név hiányzik a 2-es oszlopból"

            # 3. CÍM (Az 1-es cellából az irányítószámtól kezdődően)
            addr = "Cím nem található"
            addr_m = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', code_cell)
            if addr_m: addr = addr_m.group(1).strip()

            # 4. TELEFON ÉS RENDELÉS (A 3-as indexből)
            tel_rend_cell = str(row.values[i+3])
            tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', tel_rend_cell)
            tel = tel_m.group(1) if tel_m else "NINCS"
            
            rend_codes = re.findall(r'(\d+)-[A-Z0-9]+', tel_rend_cell)
            current_rend_str = ", ".join(re.findall(r'(\d+-[A-Z0-9]+)', tel_rend_cell))
            total_db = sum(int(c) for c in rend_codes)

            # 5. PÉNZ (Az alatta lévő sorból keresünk Ft-ot)
            money = 0
            money_m = re.search(r'(-?\d+[\s\d]*)\s*Ft', next_row_text)
            if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

            # --- TÁROLÁS ÉS ÖSSZEVONÁS (Név + Cím alapján) ---
            customer_key = (name, addr)
            if customer_key not in temp_storage:
                temp_storage[customer_key] = {
                    "kód": cust_id, "név": name, "cím": addr, "tel": tel, 
                    "P": "", "Z": "", "db": 0, "pénz": 0, 
                    "orig_idx": len(order_list) + 1
                }
                order_list.append(customer_key)
            
            if day_prefix == "P": temp_storage[customer_key]["P"] = current_rend_str
            elif day_prefix == "Z": temp_storage[customer_key]["Z"] = current_rend_str
            else: temp_storage[customer_key]["P"] = current_rend_str 
            
            temp_storage[customer_key]["db"] += total_db
            temp_storage[customer_key]["pénz"] += money

    # Eredmény lista összeállítása
    res = []
    for key in order_list:
        d = temp_storage[key]
        res.append({
            "Sorszám": d["orig_idx"],
            "Ügyfélkód": d["kód"],
            "Ügyintéző": d["név"],
            "Telefon": d["tel"], 
            "Cím": d["cím"],
            "Rendelés": f"P: {d['P']} | SZ: {d['Z']}" if d['P'] and d['Z'] else (d['P'] or d['Z']),
            "Összesen": f"{d['db']} tétel",
            "Pénz": f"BESZEDENDŐ: {d['pénz']} Ft" if d['pénz'] > 0 else (f"VISSZAADNI: {abs(d['pénz'])} Ft" if d['pénz'] < 0 else "")
        })
    return pd.DataFrame(res)

# PDF generálás (v85-ös stabil design sorszámmal)
def create_pdf_v88(df):
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
        pdf.set_font(f_m, "", 6)
        pdf.cell(50, 3, f"#{row['Sorszám']} | KÓD: {row['Ügyfélkód']}", 0, 0)

        pdf.set_xy(x + 5, y + 5)
        pdf.set_font(f_m, "B", 10)
        pdf.cell(60, 5, str(row['Ügyintéző'])[:30], 0, 1)
        
        pdf.set_xy(x + 5, y + 10)
        pdf.set_font(f_m, "B", 8)
        pdf.cell(60, 4, f"{row['Összesen']} {row['Pénz']}", 0, 1)

        pdf.set_xy(x + 5, y + 15)
        pdf.set_font(f_m, "B", 9)
        pdf.cell(60, 4, f"TEL: {row['Telefon']}", 0, 1)
        pdf.set_xy(x + 5, y + 20)
        pdf.set_font(f_m, "", 8)
        pdf.multi_cell(60, 3.5, str(row['Cím']), 0, 'L')
        pdf.set_xy(x + 5, y + 31)
        pdf.set_font(f_m, "", 7)
        pdf.multi_cell(60, 3, f"REND: {row['Rendelés']}", 0, 'L')
    return pdf.output()

st.title("Interfood v88 - Fix Indexű Névkereső")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    # A Tabula beállításait kicsit lazítjuk, hogy ne maradjon le semmi
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=True)
    if dfs:
        raw_df = pd.concat(dfs, ignore_index=True)
        final_df = parse_v88(raw_df)
        
        st.write(f"Feldolgozott sorok száma: {len(raw_df)}")
        st.write(f"Talált ügyfelek száma: {len(final_df)}")
        
        if final_df.empty:
            st.warning("Nem találtam ügyfeleket. Így néz ki az adat eleje a PDF-ben:")
            st.dataframe(raw_df.head(10))
        else:
            st.dataframe(final_df)
            pdf_out = create_pdf_v88(final_df)
            st.download_button("💾 PDF LETÖLTÉSE", bytes(pdf_out), "etikettek_v88.pdf")
    os.remove("temp.pdf")
