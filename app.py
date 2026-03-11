import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
import math
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# --- ALAPBEÁLLÍTÁSOK ---
VERZIO = "v203.48-MOD11-LASER"
st.set_page_config(page_title=f"Interfood Master {VERZIO}", layout="wide")

def register_fonts():
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

def custom_round(amount):
    return 5 * round(amount / 5)

# --- ADATFELDOLGOZÁS (A STABIL MOD3 LOGIKA) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    money_pat = r'(-?\s?\d[\d\s]*)\s*Ft'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines_dict = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines_dict:
                    if abs(y - ey) < 3:
                        lines_dict[ey].append(w); break
                else: lines_dict[y] = [w]
            
            sorted_y = sorted(lines_dict.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines_dict[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                
                if u_code_m:
                    prefix, uid = u_code_m.group(0).split('-')[0], u_code_m.group(0).split('-')[-1]
                    # Koordináta alapú oszlop meghatározás (MOD3 szerint)
                    b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                    b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                    tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                    money_m = re.search(money_pat, text_ws)
                    
                    if not money_m and i + 1 < len(sorted_y):
                        next_text = " ".join([w['text'] for w in sorted(lines_dict[sorted_y[i+1]], key=lambda x: x['x0'])])
                        if not re.search(r'([HKSCPZ]-[0-9]{5,7})', next_text):
                            money_m = re.search(money_pat, next_text)

                    raw_money = 0
                    if money_m:
                        val_str = re.sub(r'[^-0-9]', '', money_m.group(0))
                        if val_str: raw_money = int(val_str)
                    
                    rounded_money = custom_round(raw_money)
                    addr_m = re.search(r'(\d{4})', b3)
                    clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                    raw_orders = re.findall(order_pat, text_ws)
                    v_o, sq = [], 0
                    for o in raw_orders:
                        try:
                            q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                            v_o.append(f"{q}-{o.split('-')[1]} street"); sq += q
                        except: continue
                    
                    if v_o:
                        rows.append({
                            "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                            "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                            "Rendelés": ", ".join(v_o), "Összesen": sq, "Pénz_Int": rounded_money
                        })
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    day_map = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            if not day_group.empty:
                items = day_group['Rendelés'].tolist()
                o_p.append(f"{day_map[pfix]}: {', '.join(items)}")
        base['Rendelés'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        total_m = group['Pénz_Int'].sum()
        base['Pénz'] = f"{total_m} Ft" if total_m != 0 else ""
        merged.append(base)
    return merged

# --- ETIKETT GENERÁLÁS (60x32,43mm rács, 5mm belső margó) ---
def create_label_pdf(df, driver_name, driver_phone):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    # Paraméterek a kérésed szerint
    lw, lh = 60*mm, 32.43*mm
    inner_m = 5*mm  # 5mm margó a cellán belül minden oldalon
    
    # 3 oszlop, 7 sor = 21 etikett / lap
    for i in range(math.ceil(len(df)/21)*21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col = idx % 3
        row_i = 6 - (idx // 3) # Alulról felfelé építkezik a koordináta rendszer
        
        # X és Y pozíció (0 margó az oldalon, a cellák kitöltik)
        x = col * lw
        y = row_i * lh
        
        # Cella keret (fekete, vékony - lézerbarát)
        p.setStrokeColor(colors.black)
        p.setLineWidth(0.1*mm)
        p.rect(x, y, lw, lh)
        
        if i < len(df):
            r = df.iloc[i]
            
            # --- Tartalom elhelyezése a belső 5mm-es margón belül ---
            
            # Felső sor: Sorszám és ID
            p.setFont(f_bold, 9)
            p.drawString(x + inner_m, y + lh - inner_m - 3*mm, f"#{i+1}")
            
            p.setFont(f_reg, 7)
            p.drawRightString(x + lw - inner_m, y + lh - inner_m - 3*mm, f"ID: {r['ID']}")
            
            # Név (Kicsit lejjebb)
            p.setFont(f_bold, 8.5)
            p.drawString(x + inner_m, y + lh - inner_m - 8*mm, str(r['Ügyintéző'])[:28])
            
            # Cím (Kisebb betűvel, hogy beférjen)
            p.setFont(f_reg, 7)
            p.drawString(x + inner_m, y + lh - inner_m - 12*mm, str(r['Cím'])[:40])
            
            # Rendelés (Paragraph-hal a tördelés miatt)
            order_s = ParagraphStyle('OrderLaser', fontName=f_reg, fontSize=6.5, leading=7, textColor=colors.black)
            para = Paragraph(f"{r['Rendelés']} | {r['Telefon']}", order_s)
            # A magasságot úgy lőjük be, hogy a Fizetendő felett álljon meg
            para.wrap(lw - 2*inner_m, 10*mm)
            para.drawOn(p, x + inner_m, y + inner_m + 6*mm)
            
            # Alsó sor: Fizetendő és Össz db
            if r['Pénz']:
                p.setFont(f_bold, 9)
                p.drawString(x + inner_m, y + inner_m, f"FIZET: {r['Pénz']}")
            
            p.setFont(f_bold, 8)
            p.drawRightString(x + lw - inner_m, y + inner_m, f"{r['Összesen']} db")
            
    p.save()
    buf.seek(0)
    return buf

# --- UI ---
def main():
    st.title(f"🚚 Interfood Laser Master {VERZIO}")
    
    with st.sidebar:
        fn_in = st.text_input("Futár neve", "Szűcs István")
        ft_in = st.text_input("Telefonszáma", "+3620/886-89-71")
        st.info("Fekete-fehér lézer optimalizált mód (60x32.43mm)")

    up_files = st.file_uploader("Menetterv PDF feltöltése", accept_multiple_files=True)
    
    if up_files and st.button("📊 FELDOLGOZÁS"):
        raw = []
        for f in up_files: 
            raw.extend(parse_interfood_pro(f))
        
        if raw:
            mdf = pd.DataFrame(merge_data_flexible(raw))
            # Sorrendezés (MOD3 logika szerint)
            mdf['Sorrend'] = range(1, len(mdf) + 1)
            
            st.session_state.mdf = mdf
            st.success(f"{len(mdf)} ügyfél betöltve.")
            st.dataframe(mdf[['ID', 'Ügyintéző', 'Cím', 'Pénz']])

            pdf_labels = create_label_pdf(mdf, fn_in, ft_in)
            st.download_button(
                "📥 ETIKETTEK LETÖLTÉSE (PDF)", 
                pdf_labels, 
                f"etikettek_{fn_in}.pdf", 
                "application/pdf"
            )

if __name__ == "__main__":
    main()
