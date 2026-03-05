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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

st.set_page_config(page_title="Interfood Logisztika v203.11", layout="wide")

# --- Betűk regisztrálása ---
def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- PDF PARSER v203.11 ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
    price_pat = r'(\d[\d\s\.]*)\s*Ft'
    
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
                
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                prefix = u_code_m.group(0).split('-')[0]
                uid = u_code_m.group(0).split('-')[-1]
                
                # Kapukód / Megjegyzés kinyerése
                extra_info = ""
                gate_m = re.search(r'(kcs\s*[:\-]\s*\d+)', text_ws, re.IGNORECASE)
                if gate_m: extra_info = gate_m.group(0)
                elif "porta" in text_ws.lower(): extra_info = "PORTA"
                
                # Oszlopok koordinátái (koordináták a vizsgált PDF-ek alapján)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355]) # Cím
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490]) # Név/Ügyintéző
                
                tel_m = re.search(phone_pat, text_ws.replace(" ", ""))
                final_tel = tel_m.group(0) if tel_m else ""
                
                # ÁR KERESÉSE (A teljes sorban, javított regex)
                price_m = re.search(price_pat, text_ws)
                if price_m:
                    p_val = re.sub(r'\D', '', price_m.group(1))
                    final_price = f"{int(p_val):,} Ft".replace(",", " ") if p_val else "0 Ft"
                else:
                    final_price = "0 Ft"
                
                addr_m = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_m.start():].strip() if addr_m else b3
                if extra_info: clean_addr += f" ({extra_info})"
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                raw_orders = re.findall(order_pat, text_ws)
                valid_o, sq = [], 0
                for o in raw_orders:
                    parts = o.split('-')
                    if len(parts) < 2: continue
                    q_val = int(re.sub(r'\D', '', parts[0])[-1])
                    valid_o.append(f"{q_val}-{parts[1]}")
                    sq += q_val
                
                if valid_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": clean_addr, "Telefon": final_tel, 
                        "Rendelés": ", ".join(valid_o), "Összesen": sq, "Ár": final_price
                    })
    return rows

def merge_data_flexible(raw_rows):
    if not raw_rows: return []
    df = pd.DataFrame(raw_rows)
    merged = []
    for uid, group in df.groupby("ID", sort=False):
        # Péntek-Szombat összevonás (P és Z prefixek)
        if any(p in ['P', 'Z'] for p in group['Prefix']):
            base = group.iloc[0].copy().to_dict()
            p_items = group[group['Prefix'] == 'P']['Rendelés'].tolist()
            z_items = group[group['Prefix'] == 'Z']['Rendelés'].tolist()
            order_str = ""
            if p_items: order_str += f"P: {', '.join(p_items)}"
            if z_items:
                if order_str: order_str += " | "
                order_str += f"SZ: {', '.join(z_items)}"
                base['Prefix'] = 'Z'
            base['Rendelés'] = order_str
            # Árak összeadása összevonáskor
            try:
                total_p = sum([int(re.sub(r'\D', '', str(x))) for x in group['Ár']])
                base['Ár'] = f"{total_p:,} Ft".replace(",", " ")
            except: base['Ár'] = group.iloc[0]['Ár']
            base['Összesen'] = group['Összesen'].sum()
            merged.append(base)
        else:
            for _, row in group.iterrows(): merged.append(row.to_dict())
    return merged

# --- ETIKETT GENERÁLÁS ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    # KYOCERA FIX: Margók eltolása a nyomtatható tartományba
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2 + 1*mm, (h - 7*lh)/2 
    
    styles = getSampleStyleSheet()
    order_style = ParagraphStyle('OrderStyle', fontName=f_bold, fontSize=7.5, leading=8.5)
    
    total_labels = len(df)
    total_slots = math.ceil(total_labels / 21) * 21
    
    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        
        if i < total_labels:
            r = df.iloc[i]
            # Keret: vastagabb ha fizetős (Z)
            p.setLineWidth(1.2 if str(r.get('Prefix','')) == 'Z' else 0.2)
            p.rect(x+4*mm, y+3*mm, lw-8*mm, lh-6*mm) # 4mm biztonsági margó
            
            p.setFont(f_bold, 10); p.drawString(x+7*mm, y+36*mm, f"#{int(float(r['Sorrend']))}")
            p.setFont(f_reg, 8); p.drawRightString(x+lw-8*mm, y+36*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x+7*mm, y+31*mm, str(r['Ügyintéző'])[:25])
            p.setFont(f_reg, 7.5); p.drawRightString(x+lw-8*mm, y+31*mm, str(r['Telefon']))
            p.setFont(f_reg, 7); p.drawString(x+7*mm, y+27*mm, str(r['Cím'])[:45])
            
            # RENDELÉS AUTOMATIKUS SORTÖRÉSSEL
            para = Paragraph(str(r['Rendelés']), order_style)
            para.wrapOn(p, lw-14*mm, 12*mm)
            para.drawOn(p, x+7*mm, y+16*mm)
            
            # PÉNZÜGY ÉS INFÓ
            p.setFont(f_bold, 8.5); p.drawRightString(x+lw-8*mm, y+10.5*mm, f"Fizetendő: {r.get('Ár', '0 Ft')}")
            p.setFont(f_reg, 7); p.drawRightString(x+lw-8*mm, y+7*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6); p.drawCentredString(x+lw/2, y+4.5*mm, f"Futár: {fn} ({ft})")
        else:
            # MARKETING (KERET NÉLKÜL)
            m_lines = ["15% kedvezmény* 3 hétig", "Új Ügyfeleink részére!", "Rendelés leadás:", f"{fn}, tel: {ft}", "* a kedvezmény telefonon leadott rendelésekre", "érvényesíthető területi képviselőnk által"]
            p.setFont(f_bold, 9.5); p.drawCentredString(x+lw/2, y+34*mm, m_lines[0])
            p.setFont(f_reg, 9); p.drawCentredString(x+lw/2, y+29*mm, m_lines[1])
            p.setFont(f_bold, 8); p.drawCentredString(x+lw/2, y+23*mm, m_lines[2])
            p.setFont(f_reg, 8.5); p.drawCentredString(x+lw/2, y+18*mm, m_lines[3])
            p.setFont(f_reg, 6.5); p.drawCentredString(x+lw/2, y+10*mm, m_lines[4]); p.drawCentredString(x+lw/2, y+7*mm, m_lines[5])
    p.save(); buf.seek(0)
    return buf

# --- MENETTERV GENERÁLÁS ---
def create_manifest_pdf(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    rows_per_page = 22
    total_p = math.ceil(len(df)/rows_per_page)
    for p_idx in range(total_p):
        p.setFont(f_bold, 12); p.drawString(15*mm, h-15*mm, f"MENETTERV - {fn}")
        y_table_top = h - 25*mm
        data = [["SOR", "NÉV / CÍM", "TELEFON / ÁR", "RENDELÉS", "DB"]]
        subset = df.iloc[p_idx*rows_per_page : (p_idx+1)*rows_per_page]
        for _, r in subset.iterrows():
            name_addr = f"{r['Ügyintéző']}\n{r['Cím']}"
            tel_price = f"{r['Telefon']}\n{r['Ár']}"
            data.append([f"#{int(float(r['Sorrend']))}", name_addr, tel_price, r['Rendelés'], r['Összesen']])
        t = Table(data, colWidths=[12*mm, 60*mm, 33*mm, 65*mm, 10*mm])
        t.setStyle(TableStyle([('FONTNAME', (0,0), (-1,0), f_bold), ('FONTSIZE', (0,0), (-1,0), 8), ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke), ('FONTNAME', (0,1), (-1,-1), f_reg), ('FONTSIZE', (0,1), (-1,-1), 7.5), ('GRID', (0,0), (-1,-1), 0.1, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        tw, th = t.wrap(w - 30*mm, h - 50*mm)
        t.drawOn(p, 15*mm, y_table_top - th)
        p.line(15*mm, 20*mm, w-15*mm, 20*mm)
        p.setFont(f_reg, 8); p.drawCentredString(w/2, 12*mm, f"{p_idx+1} / {total_p} oldal")
        if p_idx < total_p - 1: p.showPage()
    p.save(); buf.seek(0)
    return buf

# --- UI ---
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("🚚 Beállítások")
    fn = st.text_input("Futár neve", "Szűcs István")
    ft = st.text_input("Telefonszáma", "+36208868971")

st.title("🏷️ Interfood Logisztika v203.11")
up_files = st.file_uploader("PDF feltöltése", accept_multiple_files=True)

if up_files:
    f_order_data = [{"Sorrend": float(i+1), "Fájl": f.name} for i, f in enumerate(up_files)]
    f_order = st.data_editor(f_order_data, hide_index=True)
    if st.button("FELDOLGOZÁS"):
        raw = []
        for name in pd.DataFrame(f_order).sort_values("Sorrend")["Fájl"]:
            fobj = next(f for f in up_files if f.name == name)
            raw.extend(parse_interfood_pro(fobj))
        mdf = pd.DataFrame(merge_data_flexible(raw))
        mdf.insert(0, "Sorrend", range(1, len(mdf)+1))
        st.session_state.mdf = mdf.astype({"Sorrend": float})
        st.rerun()

if st.session_state.mdf is not None:
    st.subheader("📋 Ellenőrzés és Sorrendezés")
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    col_a, col_b = st.columns([1, 4])
    with col_a:
        if st.button("🔄 LISTA FRISSÍTÉSE"):
            new_df = edited_df.sort_values("Sorrend").copy()
            new_df["Sorrend"] = range(1, len(new_df) + 1)
            st.session_state.mdf = new_df.astype({"Sorrend": float})
            st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            final_df = edited_df.sort_values("Sorrend")
            pdf = create_label_pdf(final_df, fn, ft)
            st.download_button("Mentés (etikett)", pdf, "etikettek.pdf")
    with c2:
        if st.button("📋 MENETTERV LETÖLTÉSE"):
            final_df = edited_df.sort_values("Sorrend")
            pdf = create_manifest_pdf(final_df, fn)
            st.download_button("Mentés (menetterv)", pdf, "menetterv.pdf")
