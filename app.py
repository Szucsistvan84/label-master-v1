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

st.set_page_config(page_title="Interfood v203.0 - Teljes Adatvisszaállítás", layout="wide")

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- 2. INTELLIGENS BLOKK-ALAPÚ PARSER ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9]*)'
    phone_pat = r'(\d{2}/\d{6,9})'
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            # Csoportosítjuk a szavakat sorokba (y koordináta alapján)
            lines_dict = {}
            for w in words:
                y = round(w['top'], 0)
                lines_dict.setdefault(y, []).append(w)
            
            sorted_y = sorted(lines_dict.keys())
            
            for y in sorted_y:
                line_text = " ".join([w['text'] for w in sorted(lines_dict[y], key=lambda x: x['x0'])])
                u_code_m = re.search(r'([HKSCPZ])-([0-9]{5,7})', line_text)
                
                if u_code_m:
                    prefix = u_code_m.group(1)
                    uid = u_code_m.group(2)
                    
                    # Keressük az adatokat a kód környezetében (ugyanazon a lapon)
                    # Név: Általában a kódtól jobbra van (x > 300)
                    name_parts = [w['text'] for w in words if abs(w['top'] - y) < 5 and w['x0'] > 300 and w['x0'] < 450]
                    # Cím: Általában a kód alatt vagy mellett van (x < 300)
                    addr_parts = [w['text'] for w in words if (abs(w['top'] - y) < 25) and w['x0'] < 300 and "Debrecen" in w['text']]
                    if not addr_parts: # Ha nem találja a várost, nézze a környező sorokat
                        addr_parts = [w['text'] for w in words if abs(w['top'] - (y+10)) < 10 and w['x0'] < 300]

                    # Pénz és Telefon keresése a blokkban
                    context_text = " ".join([w['text'] for w in words if abs(w['top'] - y) < 30])
                    
                    money_m = re.search(money_pat, context_text)
                    money_val = int(re.sub(r'[^\d-]', '', money_m.group(1))) if money_m else 0
                    
                    tel_m = re.search(phone_pat, context_text.replace(" ", ""))
                    
                    orders = re.findall(order_pat, context_text)
                    valid_o = []
                    sq = 0
                    for o in set(orders):
                        q = int(o.split('-')[0][-1])
                        valid_o.append(o)
                        sq += q
                    
                    if sq > 0:
                        rows.append({
                            "Prefix": prefix, "ID": uid,
                            "Ügyintéző": " ".join(name_parts).strip(),
                            "Cím": " ".join(addr_parts).strip(),
                            "Telefon": tel_m.group(0) if tel_m else "",
                            "Rendelés": ", ".join(valid_o),
                            "sq": sq, "Penz_Int": money_val
                        })
    return rows

def merge_weekend_data(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
        
        order_str = ""
        if p_items: order_str += f"P: {', '.join(set(', '.join(p_items).split(', ')))}"
        if z_items:
            if order_str: order_str += " | "
            order_str += f"SZ: {', '.join(set(', '.join(z_items).split(', ')))}"
            base['Prefix'] = 'Z'
            
        base['Rendelés'] = order_str
        base['Összesen'] = group['sq'].sum()
        base['Penz_Final'] = group['Penz_Int'].sum()
        merged.append(base)
    return merged

# --- 4. PDF GENERÁTOR ---
def create_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2, (h - 7*lh)/2
    
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
        
        kassza = r['Penz_Final']
        if kassza != 0:
            p.setFont(f_bold, 11)
            txt = f"{kassza} Ft" if kassza > 0 else f"Visszaad: {abs(kassza)} Ft"
            p.drawRightString(x+lw-5*mm, y+31.5*mm, txt)
        
        p.setFont(f_bold, 9.5)
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

# --- UI ---
st.title("Interfood Címke Master v203")
with st.sidebar:
    fn = st.text_input("Futár", "Szűcs István")
    ft = st.text_input("Telefon", "+36208868971")

up_files = st.file_uploader("Menettervek", accept_multiple_files=True)

if up_files:
    if st.button("BEOLVASÁS"):
        all_data = []
        for f in up_files:
            all_data.extend(parse_interfood_pro(f))
        
        merged = merge_weekend_data(all_data)
        st.session_state.mdf = pd.DataFrame(merged)
        st.session_state.mdf.insert(0, "Sorrend", range(1, len(st.session_state.mdf) + 1))

if "mdf" in st.session_state:
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    if st.button("PDF GENERÁLÁSA"):
        pdf = create_pdf(edited_df, fn, ft)
        st.download_button("📥 Letöltés", pdf, "interfood_v203.pdf")
