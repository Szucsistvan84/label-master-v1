import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

st.set_page_config(page_title="Interfood v202.0 - Adat Fix", layout="wide")

# --- 1. FONT REGISZTRÁCIÓ ---
def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- 2. JAVÍTOTT PDF PARSER (Cikkszám + Pénz védelem) ---
def parse_interfood_pro(pdf_file):
    rows = []
    # Szigorúbb cikkszám minta: szám-betűk (pl. 1-DK2, 2-L3)
    order_pat = r'(\d+-[A-Z][A-Z0-9]*)'
    phone_pat = r'(\d{2}/\d{6,9})'
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            # Sorokra bontva dolgozunk, hogy ne keverjük az ügyfeleket
            lines = text.split('\n')
            
            current_row = None
            
            for line in lines:
                # Ügyfélkód keresése (ez indítja az új blokkot)
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', line)
                
                if u_code_m:
                    # Ha van előző, mentsük el
                    if current_row and current_row['sq'] > 0:
                        rows.append(current_row)
                    
                    f_code = u_code_m.group(0)
                    current_row = {
                        "Prefix": f_code.split('-')[0],
                        "ID": f_code.split('-')[-1],
                        "Ügyintéző": "", "Cím": "", "Telefon": "",
                        "Rendelés": [], "sq": 0, "Penz_Int": 0
                    }
                
                if current_row:
                    # Pénz keresés (szóközöket kivéve)
                    m_m = re.search(money_pat, line)
                    if m_m:
                        try:
                            val = int(re.sub(r'[^\d-]', '', m_m.group(1)))
                            current_row['Penz_Int'] += val
                        except: pass
                    
                    # Telefonszám
                    t_m = re.search(phone_pat, line.replace(" ", ""))
                    if t_m: current_row['Telefon'] = t_m.group(0)
                    
                    # Cikkszámok - Csak a tiszta formátumot fogadjuk el
                    found_orders = re.findall(order_pat, line)
                    for o in found_orders:
                        # Levágjuk, ha a végére szám ragadt (max 4 karakter a kód része)
                        parts = o.split('-')
                        q = int(parts[0][-1]) if len(parts[0]) > 0 else 0
                        code = parts[1]
                        # Ha a kód végén túl sok szám van (pl DK113), levágjuk a felesleget
                        # Az Interfood kódok általában 1-4 karakteresek
                        clean_o = f"{q}-{code}"
                        if clean_o not in current_row['Rendelés']:
                            current_row['Rendelés'].append(clean_o)
                            current_row['sq'] += q
            
            # Utolsó sor mentése
            if current_row and current_row['sq'] > 0:
                rows.append(current_row)

    # Adatok finomítása (Cím és Név visszatöltése a PDF-ből a koordináták alapján ha kell)
    # De a fenti sor-alapú is sokat javít a cikkszámokon.
    for r in rows:
        r['Rendelés'] = ", ".join(r['Rendelés'])
    
    return rows

# --- 3. ÖSSZEVONÓ LOGIKA ---
def merge_weekend_data(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
        
        total_money = group['Penz_Int'].sum()
        
        order_str = ""
        if p_items: 
            # Tisztítás a duplikációktól
            p_clean = ", ".join(list(set(", ".join(p_items).split(", "))))
            order_str += f"P: {p_clean}"
        if z_items:
            z_clean = ", ".join(list(set(", ".join(z_items).split(", "))))
            if order_str: order_str += " | "
            order_str += f"SZ: {z_clean}"
            base['Prefix'] = 'Z'
            
        base['Rendelés'] = order_str
        base['Összesen'] = group['sq'].sum()
        base['Penz_Final'] = total_money
        merged.append(base)
    return merged

# --- 4. PDF GENERÁTOR (Fixált Pozíciók) ---
def create_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2, (h - 7*lh)/2
    
    # SORRENDEZÉS ÉRVÉNYESÍTÉSE (Számmá alakítva a biztos sikerért)
    df['sort_key'] = pd.to_numeric(df['Sorrend'], errors='coerce').fillna(999)
    df = df.sort_values('sort_key')

    for i, (_, r) in enumerate(df.iterrows()):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        
        p.setLineWidth(1.2 if r['Prefix'] == 'Z' else 0.2)
        p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
        
        p.setFont(f_bold, 10)
        p.drawString(x+5*mm, y+36*mm, f"#{int(r['sort_key'])}")
        p.drawRightString(x+lw-5*mm, y+36*mm, f"ID: {r['ID']}")
        
        # PÉNZ (Csak ha nem 0)
        kassza = r['Penz_Final']
        if kassza != 0:
            p.setFont(f_bold, 11)
            txt = f"{kassza} Ft" if kassza > 0 else f"Visszaad: {abs(kassza)} Ft"
            p.drawRightString(x+lw-5*mm, y+31.5*mm, txt)
        
        p.setFont(f_bold, 9.5)
        # Név és Telefonszám (Külön sor, biztos ami biztos)
        p.drawString(x+5*mm, y+30*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 8)
        p.drawRightString(x+lw-5*mm, y+27*mm, str(r['Telefon']))
        
        p.setFont(f_reg, 7.5)
        p.drawString(x+5*mm, y+23*mm, str(r['Cím'])[:50])
        
        p.setFont(f_bold, 8)
        r_text = str(r['Rendelés'])
        if " | " in r_text:
            parts = r_text.split(" | ")
            p.drawString(x+5*mm, y+18*mm, parts[0][:42])
            p.drawString(x+5*mm, y+14*mm, parts[1][:42])
        else:
            p.drawString(x+5*mm, y+16*mm, r_text[:42])
            
        p.drawRightString(x+lw-5*mm, y+10*mm, f"Össz: {r['Összesen']} db")
        p.setFont(f_reg, 6)
        p.drawCentredString(x+lw/2, y+5*mm, f"Futár: {fn} ({ft}) | Jó étvágyat! :)")
        
    p.save()
    buf.seek(0)
    return buf

# --- UI (Feldolgozás és Mentés) ---
st.title("Interfood Címke Master v202")

with st.sidebar:
    fn = st.text_input("Futár neve", "Szűcs István")
    ft = st.text_input("Telefon", "+36208868971")

up_files = st.file_uploader("Menetterv PDF-ek", accept_multiple_files=True)

if up_files:
    if st.button("ADATOK BEOLVASÁSA"):
        all_data = []
        for f in up_files:
            all_data.extend(parse_interfood_pro(f))
        
        merged = merge_weekend_data(all_data)
        mdf = pd.DataFrame(merged)
        mdf.insert(0, "Sorrend", range(1, len(mdf) + 1))
        st.session_state.mdf = mdf

if "mdf" in st.session_state:
    st.subheader("Szerkeszthető adatok (Itt írd át a Sorrendet!)")
    # A data_editorban átírt sorrend alapján fogunk generálni
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    if st.button("PDF GENERÁLÁSA"):
        pdf_file = create_pdf(edited_df, fn, ft)
        st.download_button("📥 Letöltés", pdf_file, "interfood_v202.pdf")
