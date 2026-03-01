import streamlit as st
import tabula
import pandas as pd
import re
from fpdf import FPDF
import os

def get_total_items(rend_str):
    """Kiszámolja a darabszámot: a kötőjel előtti számokat adja össze."""
    if not rend_str or rend_str == "nan": return 0
    # Megkeresi az összes "szám-kód" formátumot (pl. 2-F4K)
    counts = re.findall(r'(\d+)-[A-Z0-9]+', rend_str)
    return sum(int(c) for c in counts)

def parse_v82(df_raw):
    temp_storage = {} 

    for idx, row in df_raw.iterrows():
        row_list = [str(val).strip() for val in row.values]
        row_str = " ".join(row_list)
        
        if not re.search(r'[PZ]-\d+', row_str): continue
        next_row = df_raw.iloc[idx + 1] if idx + 1 < len(df_raw) else None

        for i in range(0, len(row_list), 5):
            if i + 4 >= len(row_list): break
            
            # --- ADATOK BEGYŰJTÉSE ---
            raw_code_cell = row_list[i+1]
            col2 = row_list[i+2] # Ez nálad most a telefon
            col3 = row_list[i+3] # Ez a vegyes cella
            
            # --- OSZLOPHELYREÁLLÍTÁS ---
            # Ha a 2-es oszlopban telefonszám van, tegyük a helyére
            tel = "NINCS"
            name = "Ismeretlen"
            
            # Telefonszám keresése a 2-es és 3-as oszlopban is
            all_nearby_text = f"{col2} {col3}"
            tel_match = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', all_nearby_text)
            if tel_match:
                tel = tel_match.group(1)
            
            # NÉV: A CSV-d alapján a név gyakran a 2. vagy 3. oszlopban van, 
            # de ha a 2-esben telefon van, akkor a név valószínűleg a 3-as eleje vagy a 2-es vége.
            # A legbiztosabb: ami nem telefon és nem rendelési kód, az a név.
            name_candidate = col2 if not re.search(r'(\d{2}/\d{7})', col2) else col3.split(' ')[0]
            name = name_candidate if len(name_candidate) > 2 else "Név hiba"

            # --- CÍM (Irányítószám alapján) ---
            addr = "Cím nem található"
            addr_match = re.search(r'(\d{4}\s+[A-ZÁÉÍÓÖŐÚÜŰ].*)', raw_code_cell)
            if addr_match:
                addr = addr_match.group(1).strip()

            # --- RENDELÉS ÉS MENNYISÉG ---
            rend_list = re.findall(r'(\d+-[A-Z0-9]+)', col3)
            current_rend = ", ".join(rend_list)
            current_count = get_total_items(current_rend)

            # --- P / Z KÓD ---
            code_m = re.search(r'([PZ])-(\d+)', raw_code_cell)
            day_prefix = code_m.group(1) if code_m else "P"

            # --- PÉNZÜGY (Next row) ---
            money = 0
            if next_row is not None and i+3 < len(next_row):
                m_match = re.search(r'(-?\d+[\s\d]*)', str(next_row[i+3]))
                if m_match:
                    money = int(re.sub(r'\s+', '', m_match.group(1)))

            # --- TÁROLÁS ---
            customer_key = (name, addr)
            if customer_key not in temp_storage:
                temp_storage[customer_key] = {"név": name, "cím": addr, "tel": tel, "P": "", "Z": "", "db": 0, "pénz": 0}
            
            if day_prefix == "P": temp_storage[customer_key]["P"] = current_rend
            else: temp_storage[customer_key]["Z"] = current_rend
            
            temp_storage[customer_key]["db"] += current_count
            temp_storage[customer_key]["pénz"] += money

    # Formázás
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

# --- PDF GENERÁLÁS (Fixált koordináták) ---
def create_pdf_v82(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    font_path, f_bold = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    has_font = os.path.exists(font_path)
    f_m = "DejaVu" if has_font else "Arial"
    if has_font:
        pdf.add_font("DejaVu", style="", fname=font_path)
        pdf.add_font("DejaVu", style="B", fname=f_bold)

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

st.title("Interfood v82 - Mennyiség és Adatjavítás")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    with open("temp.pdf", "wb") as tp: tp.write(f.read())
    dfs = tabula.read_pdf("temp.pdf", pages='all', stream=True, guess=False)
    if dfs:
        final_df = parse_v82(pd.concat(dfs, ignore_index=True))
        st.dataframe(final_df)
        if not final_df.empty:
            st.download_button("💾 PDF LETÖLTÉSE", bytes(create_pdf_v82(final_df)), "etikettek_v82.pdf")
    os.remove("temp.pdf")
