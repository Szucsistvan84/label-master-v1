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
VERZIO = "v203.48-MOD7"
st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

DAY_MAP = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}

def register_fonts():
    # Megpróbáljuk betölteni a fájl mellé csomagolt fontokat a magyar ékezetekhez
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n):
            pdfmetrics.registerFont(TTFont('DejaVu', f_n))
            pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
            return "DejaVu", "DejaVu-Bold"
    except:
        pass
    return "Helvetica", "Helvetica-Bold"

def custom_round(amount):
    return 5 * round(amount / 5)

# --- ADATFELDOLGOZÁS (PÉNZ + MEGJEGYZÉS + RENDELÉS) ---
def parse_interfood_pdf(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    money_pat = r'(-?\s?\d[\d\s]*)\s*Ft'
    phone_pat = r'(\d{2}/\d{6,7})'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            lines_dict = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines_dict:
                    if abs(y - ey) < 3:
                        lines_dict[ey].append(w)
                        break
                else:
                    lines_dict[y] = [w]
            
            sorted_y = sorted(lines_dict.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines_dict[y], key=lambda x: x['x0'])
                text_line = " ".join([w['text'] for w in line_words])
                
                # Ügyfélkód keresése (pl. S-430025)
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_line)
                
                if u_code_m:
                    prefix = u_code_m.group(0).split('-')[0]
                    uid = u_code_m.group(0).split('-')[-1]
                    
                    # Területi alapú kinyerés (koordináták alapján)
                    b_addr = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                    b_name = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                    
                    clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b_name).strip()
                    tel_m = re.search(phone_pat, text_line.replace(" ", ""))
                    
                    # Pénz és Megjegyzés keresése (az aktuális és a következő sorban)
                    money_val = 0
                    note = ""
                    
                    # Megjegyzés: ha van "/" a sorban, vagy a következő sor nem új ügyfél
                    if "/" in text_line:
                        note = text_line.split("/", 1)[1].strip()
                    
                    if i + 1 < len(sorted_y):
                        next_line_text = " ".join([w['text'] for w in sorted(lines_dict[sorted_y[i+1]], key=lambda x: x['x0'])])
                        if not re.search(r'([HKSCPZ]-[0-9]{5,7})', next_line_text):
                            if not note: note = next_line_text.strip()
                            # Pénz keresése a blokkban
                            money_m = re.search(money_pat, text_line + " " + next_line_text)
                            if money_m:
                                val_str = re.sub(r'[^-0-9]', '', money_m.group(0))
                                if val_str: money_val = int(val_str)

                    addr_m = re.search(r'(\d{4})', b_addr)
                    clean_addr = b_addr[addr_m.start():].strip() if addr_m else b_addr
                    
                    raw_orders = re.findall(order_pat, text_line)
                    v_o, sq = [], 0
                    for o in raw_orders:
                        try:
                            parts = o.split('-')
                            q = int(re.sub(r'\D', '', parts[0])[-1])
                            v_o.append(f"{q}-{parts[1]}")
                            sq += q
                        except: continue
                    
                    if v_o:
                        rows.append({
                            "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                            "Cím": clean_addr, "Telefon": tel_m.group(0) if tel_m else "", 
                            "Rendelés": ", ".join(v_o), "Összesen": sq, 
                            "Pénz_Int": custom_round(money_val), "Megjegyzés": note
                        })
    return rows

def merge_data(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p = []
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            if not day_group.empty:
                items = day_group['Rendelés'].tolist()
                o_p.append(f"{DAY_MAP[pfix]}: {', '.join(items)}")
        
        base['Rendelés'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        total_money = group['Pénz_Int'].sum()
        base['Pénz'] = f"{total_money} Ft" if total_money != 0 else ""
        
        all_notes = group['Megjegyzés'].unique()
        base['Megjegyzés'] = " ".join([n for n in all_notes if n and len(n) > 2])
        merged.append(base)
    return merged

# --- PDF GENERÁLÁS (ETIKETT - 60x32,43mm) ---
def create_label_pdf(df, filename):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    
    # Paraméterek: 3 oszlop, 7 sor = 21 etikett / oldal
    lw, lh = 60*mm, 32.43*mm
    inner_m = 5*mm # 5mm-es belső margó minden oldalon
    
    for i in range(len(df)):
        idx_on_page = i % 21
        if idx_on_page == 0 and i > 0:
            p.showPage()
            
        col = idx_on_page % 3
        row = 6 - (idx_on_page // 3)
        
        x = col * lw
        y = row * lh
        
        # Keret (halvány szürke a vágáshoz)
        p.setStrokeColor(colors.lightgrey)
        p.setLineWidth(0.1*mm)
        p.rect(x, y, lw, lh)
        
        # Tartalom rajzolása a cellán belül
        r = df.iloc[i]
        p.setFillColor(colors.black)
        
        # Sorrend és ID (a felső 5mm-es sávban)
        p.setFont(f_bold, 8)
        p.drawString(x + inner_m, y + lh - 7*mm, f"#{int(r['Sorrend'])}")
        p.setFont(f_reg, 6)
        p.drawRightString(x + lw - inner_m, y + lh - 7*mm, f"ID: {r['ID']}")
        
        # Név és Cím
        p.setFont(f_bold, 9)
        p.drawString(x + inner_m, y + lh - 12*mm, str(r['Ügyintéző'])[:25])
        p.setFont(f_reg, 7)
        p.drawString(x + inner_m, y + lh - 16*mm, str(r['Cím'])[:40])
        
        # Rendelés (többsoros Paragraph)
        order_s = ParagraphStyle('LStyle', fontName=f_reg, fontSize=7, leading=8)
        para = Paragraph(str(r['Rendelés']), order_s)
        para.wrap(lw - 2*inner_m, 10*mm)
        para.drawOn(p, x + inner_m, y + 10*mm)
        
        # Alsó sor: Pénz és darabszám
        if r['Pénz']:
            p.setFont(f_bold, 9)
            p.drawString(x + inner_m, y + inner_m, f"FIZET: {r['Pénz']}")
        
        p.setFont(f_bold, 8)
        p.drawRightString(x + lw - inner_m, y + inner_m, f"{r['Összesen']} db")
        
    p.save()
    buf.seek(0)
    return buf

# --- PDF GENERÁLÁS (MENETTERV) ---
def create_manifest_pdf(df, filename):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    name_s = ParagraphStyle('NameS', fontName=f_bold, fontSize=10, leading=11)
    cell_s = ParagraphStyle('CellS', fontName=f_reg, fontSize=8, leading=9)

    rows_per_page = 25 
    total_pages = math.ceil(len(df)/rows_per_page)

    for p_idx in range(total_pages):
        p.setFont(f_bold, 11)
        p.drawString(15*mm, h-12*mm, f"MENETTERV - {filename} ({p_idx+1}/{total_pages} oldal)")
        
        data = [["SOR", "ÜGYFÉL / CÍM / MEGJEGYZÉS", "OK", "TELEFON", "RENDELÉS", "DB", "PÉNZ"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        
        for _, r in subset.iterrows():
            # Piros dőlt megjegyzés a cím alatt
            m_text = f"<br/><font color='red' size=7><i>{r['Megjegyzés']}</i></font>" if r['Megjegyzés'] else ""
            info = Paragraph(f"{r['Ügyintéző']}<br/><font size=7 color='#444444'>{r['Cím']}</font>{m_text}", name_s)
            
            data.append([
                f"#{int(r['Sorrend'])}", info, "[ ]", r['Telefon'], 
                Paragraph(r['Rendelés'], cell_s), r['Összesen'], r['Pénz']
            ])
        
        # Táblázat szélességek beállítása az A4-hez
        t = Table(data, colWidths=[10*mm, 70*mm, 8*mm, 25*mm, 47*mm, 8*mm, 22*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('GRID', (0,0), (-1,-1), 0.2, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (2,0), (2,-1), 'CENTER'),
            ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
        ]))
        
        tw, th = t.wrap(w-20*mm, h-35*mm)
        t.drawOn(p, 10*mm, (h-16*mm)-th)
        p.showPage()
    
    p.save()
    buf.seek(0)
    return buf

# --- STREAMLIT UI ---
def main():
    st.title(f"🚚 Interfood Logisztikai Segéd {VERZIO}")
    up_files = st.file_uploader("Válaszd ki a menetterv PDF-eket", type="pdf", accept_multiple_files=True)

    if up_files:
        all_raw = []
        for f in up_files:
            all_raw.extend(parse_interfood_pdf(f))
        
        if all_raw:
            merged_data = merge_data(all_raw)
            final_df = pd.DataFrame(merged_data)
            final_df['Sorrend'] = range(1, len(final_df) + 1)
            
            st.success(f"Beolvasva: {len(final_df)} egyedi ügyfél.")
            st.dataframe(final_df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Pénz', 'Megjegyzés']])
            
            fname = up_files[0].name.replace(".pdf", "")
            
            col1, col2 = st.columns(2)
            with col1:
                l_pdf = create_label_pdf(final_df, fname)
                st.download_button("Etikettek letöltése (60x32mm)", l_pdf, f"etikett_{fname}.pdf")
            with col2:
                m_pdf = create_manifest_pdf(final_df, fname)
                st.download_button("Menetterv letöltése (Megjegyzésekkel)", m_pdf, f"menetterv_{fname}.pdf")

if __name__ == "__main__":
    main()
