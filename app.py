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

st.set_page_config(page_title="Interfood v200.0 - Intelligens Kassza", layout="wide")

# --- 1. FONT REGISZTRÁCIÓ ---
def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- 2. PDF PARSER (Pénzösszeg előjeles kezeléssel) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    # Pénz kereső: figyeli a mínusz jelet is!
    money_pat = r'(-?\d+[\s\d]*)\s*Ft'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                found = False
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w)
                        found = True
                        break
                if not found: lines[y] = [w]
            
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                text_ns = "".join([w['text'] for w in line_words])
                
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                # Pénz kinyerése és számmá alakítása
                money_m = re.search(money_pat, text_ws)
                if money_m:
                    # Kiszedjük a szóközöket a szám közül, de a mínusz jelet megtartjuk
                    val_str = money_m.group(1).replace(" ", "")
                    money_val = int(val_str)
                else:
                    money_val = 0
                
                f_code = u_code_m.group(0)
                prefix = f_code.split('-')[0]
                uid = f_code.split('-')[-1]
                
                # Cím és Név sávok
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                tel_m = re.search(phone_pat, text_ns)
                final_tel = tel_m.group(0) if tel_m else ""
                
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                orders = re.findall(order_pat, text_ns)
                valid_o, sq = [], 0
                for o in orders:
                    parts = o.split('-')
                    if len(parts) < 2: continue
                    q = int(parts[0]); q = int(str(q)[-1]) if q >= 10 else q
                    valid_o.append(f"{q}-{parts[1]}")
                    sq += q
                
                if sq > 0:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": final_tel, 
                        "Rendelés": ", ".join(valid_o), "Összesen": sq,
                        "Penz_Int": money_val # Itt tároljuk a tiszta számot
                    })
    return rows

# --- 3. ÖSSZEVONÓ LOGIKA (Matematikai szumma) ---
def merge_weekend_data(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
        z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
        
        # Pénzügyi szumma
        total_money = group['Penz_Int'].sum()
        
        order_str = ""
        if p_items: order_str += f"P: {', '.join(p_items)}"
        if z_items:
            if order_str: order_str += " | "
            order_str += f"SZ: {', '.join(z_items)}"
            base['Prefix'] = 'Z'
            
        base['Rendelés'] = order_str
        base['Összesen'] = group['Összesen'].sum()
        base['Penz_Final'] = total_money
        merged.append(base)
    return merged

# --- 4. PDF GENERÁTOR (Feltételes Pénz Megjelenítés) ---
def create_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2, (h - 7*lh)/2
    
    for i, (_, r) in enumerate(df.iterrows()):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        
        p.setLineWidth(1.2 if r['Prefix'] == 'Z' else 0.2)
        p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
        
        # Sorszám és ID
        p.setFont(f_bold, 10)
        p.drawString(x+5*mm, y+36*mm, f"#{r['Sorrend']}")
        p.drawRightString(x+lw-5*mm, y+36*mm, f"ID: {r['ID']}")
        
        # PÉNZÜGYI LOGIKA AZ ETIKETTEN
        kassza = r['Penz_Final']
        if kassza > 0:
            p.setFont(f_bold, 11)
            p.drawRightString(x+lw-5*mm, y+31.5*mm, f"{kassza} Ft")
        elif kassza < 0:
            p.setFont(f_bold, 10)
            p.drawRightString(x+lw-5*mm, y+31.5*mm, f"Visszaad: {kassza} Ft")
        # Ha 0, akkor nem írunk semmit.
        
        # Név és Telefon
        p.setFont(f_bold, 9.5)
        p.drawString(x+5*mm, y+30*mm, str(r['Ügyintéző'])[:24])
        p.setFont(f_reg, 8)
        p.drawRightString(x+lw-42*mm, y+30*mm, str(r['Telefon']))
        
        # Cím (Kisebb)
        p.setFont(f_reg, 7.5)
        p.drawString(x+5*mm, y+25.5*mm, str(r['Cím'])[:50])
        
        # Rendelés
        p.setFont(f_bold, 8)
        r_text = str(r['Rendelés'])
        if " | " in r_text:
            p_part, z_part = r_text.split(" | ")
            p.drawString(x+5*mm, y+19.5*mm, p_part[:42])
            p.drawString(x+5*mm, y+15.5*mm, z_part[:42])
        else:
            p.drawString(x+5*mm, y+17.5*mm, r_text[:42])
            
        # Összesen db
        p.setFont(f_bold, 8)
        p.drawRightString(x+lw-5*mm, y+11*mm, f"Össz: {r['Összesen']} db")
        
        # Futár (Kisebb)
        p.setFont(f_reg, 6)
        p.drawCentredString(x+lw/2, y+5*mm, f"Futár: {fn} ({ft}) | Jó étvágyat! :)")
        
    p.save()
    buf.seek(0)
    return buf

# --- UI (Feldolgozó rész frissítve) ---
# ... [Fájl feltöltő rész változatlan] ...
if up_files:
    # ...
    if st.button("BEOLVASÁS ÉS ÖSSZEVONÁS"):
        # ... parse hívás ...
        merged = merge_weekend_data(raw)
        mdf = pd.DataFrame(merged)
        # Megjelenítéshez átnevezzük a pénzt, hogy látható legyen a táblázatban is
        mdf['Fizetendő'] = mdf['Penz_Final'].apply(lambda x: f"{x} Ft" if x != 0 else "0 Ft")
        mdf.insert(0, "Sorrend", [str(i+1) for i in range(len(mdf))])
        st.session_state.mdf = mdf
        st.rerun()
