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

st.set_page_config(page_title="Interfood v201.0 - Fixált Adatok", layout="wide")

# --- 1. FONT REGISZTRÁCIÓ ---
def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- 2. PDF PARSER (Javított pénz és cikkszám logikával) ---
def parse_interfood_pro(pdf_file):
    rows = []
    # Cikkszám minta: mennyiség - kód (pl. 1-DK)
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,9})'
    # Pénz: számok, esetleg szóközökkel elválasztva, amit 'Ft' követ
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
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
                
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                # 1. Pénz keresése (mielőtt szétvágjuk a sort)
                money_m = re.search(money_pat, text_ws)
                money_val = 0
                if money_m:
                    try:
                        clean_money = re.sub(r'[^\d-]', '', money_m.group(1))
                        money_val = int(clean_money)
                    except: pass

                # 2. Cikkszámok keresése
                # Fontos: Csak azokat keressük, amik tényleg cikkszámok (szám-betű)
                orders = re.findall(order_pat, text_ws)
                valid_o = []
                sq = 0
                for o in orders:
                    # Megelőzzük a darabszám "hozzáragadását"
                    # Ha a kód végén túl sok szám van, levágjuk
                    valid_o.append(o)
                    q_part = o.split('-')[0]
                    sq += int(q_part[-1]) if len(q_part) > 1 else int(q_part)

                # 3. Alapadatok szétválasztása
                f_code = u_code_m.group(0)
                prefix = f_code.split('-')[0]
                uid = f_code.split('-')[-1]
                
                # Név és Cím (koordináta alapú sávokból)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                final_tel = tel_m.group(0) if tel_m else ""
                
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                if valid_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": final_tel, 
                        "Rendelés": ", ".join(valid_o), "Összesen": sq,
                        "Penz_Int": money_val
                    })
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

# --- 4. PDF GENERÁTOR (Fixált pozíciók) ---
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
        
        # Pénz kiírása (Ha nem 0)
        kassza = r['Penz_Final']
        if kassza != 0:
            p.setFont(f_bold, 11)
            prefix_p = "Visszaad: " if kassza < 0 else ""
            p.drawRightString(x+lw-5*mm, y+31.5*mm, f"{prefix_p}{abs(kassza)} Ft")
        
        # Név (Balra) és Telefon (Jobbra zárva - Fix helyre!)
        p.setFont(f_bold, 9.5)
        p.drawString(x+5*mm, y+30*mm, str(r['Ügyintéző'])[:22])
        p.setFont(f_reg, 8)
        # Fixált jobb margó a telefonnak, hogy ne csússzon a név alá
        p.drawRightString(x+lw-5*mm, y+27*mm, str(r['Telefon']))
        
        # Cím
        p.setFont(f_reg, 7.5)
        p.drawString(x+5*mm, y+23*mm, str(r['Cím'])[:50])
        
        # Rendelés - Itt már a tiszta cikkszámok vannak
        p.setFont(f_bold, 8)
        r_text = str(r['Rendelés'])
        if " | " in r_text:
            p_part, z_part = r_text.split(" | ")
            p.drawString(x+5*mm, y+18*mm, p_part[:42])
            p.drawString(x+5*mm, y+14*mm, z_part[:42])
        else:
            p.drawString(x+5*mm, y+16*mm, r_text[:42])
            
        # Összesen
        p.setFont(f_bold, 8)
        p.drawRightString(x+lw-5*mm, y+10*mm, f"Össz: {r['Összesen']} db")
        
        # Futár
        p.setFont(f_reg, 6)
        p.drawCentredString(x+lw/2, y+5*mm, f"Futár: {fn} ({ft}) | Jó étvágyat! :)")
        
    p.save()
    buf.seek(0)
    return buf

# --- UI (Változatlan marad, csak a hívásokat frissítettük) ---
with st.sidebar.form("setup"):
    st.write("🚚 Szállítási adatok")
    fn = st.text_input("Futár neve", value=st.session_state.get('n', "Szűcs István"))
    ft = st.text_input("Telefonszáma", value=st.session_state.get('t', "+36208868971"))
    if st.form_submit_button("MENTÉS"):
        st.session_state.n, st.session_state.t = fn, ft
        st.rerun()

if not st.session_state.get('n'):
    st.title("Interfood Címke Master")
    st.warning("👈 Add meg a futár adatait!")
    st.stop()

st.title(f"🏷️ Interfood Etikett v201")
up_files = st.file_uploader("Menetterv PDF-ek", accept_multiple_files=True)

if up_files:
    fo = st.data_editor([{"Sorszám": i+1, "Fájl": f.name} for i, f in enumerate(up_files)], hide_index=True)
    if st.button("FELDOLGOZÁS"):
        sorted_f = pd.DataFrame(fo).sort_values("Sorszám")["Fájl"].tolist()
        raw = []
        for s in sorted_f:
            fobj = next(f for f in up_files if f.name == s)
            raw.extend(parse_interfood_pro(fobj))
        merged = merge_weekend_data(raw)
        mdf = pd.DataFrame(merged)
        mdf['Pénz'] = mdf['Penz_Final'].apply(lambda x: f"{x} Ft")
        mdf.insert(0, "Sorrend", [str(i+1) for i in range(len(mdf))])
        st.session_state.mdf = mdf
        st.rerun()

if st.session_state.get('mdf') is not None:
    edf = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    if st.button("PDF Letöltése"):
        pdf = create_pdf(edf, st.session_state.n, st.session_state.t)
        st.download_button("📥 Kattints a letöltéshez", pdf, "interfood_v201.pdf", "application/pdf")
