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

st.set_page_config(page_title="Interfood v198.7", layout="wide")

def register_fonts():
    f_n, f_b = "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"
    try:
        if os.path.exists(f_n): pdfmetrics.registerFont(TTFont('DejaVu', f_n))
        if os.path.exists(f_b): pdfmetrics.registerFont(TTFont('DejaVu-Bold', f_b))
        return "DejaVu", "DejaVu-Bold"
    except: return "Helvetica", "Helvetica-Bold"

# --- PDF PARSER (v198 STABIL) ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
    phone_pat = r'(\d{2}/\d{6,7})'
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
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                f_code = u_code_m.group(0)
                prefix, uid = f_code.split('-')[0], f_code.split('-')[-1]
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
                    rows.append({"Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, "Cím": clean_addr, "Telefon": final_tel, "Rendelés": ", ".join(valid_o), "Összesen": sq})
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
        if p_items: order_str += f"P: {', '.join(p_items)}"
        if z_items:
            if order_str: order_str += " | "
            order_str += f"SZ: {', '.join(z_items)}"
            base['Prefix'] = 'Z'
        base['Rendelés'] = order_str
        base['Összesen'] = group['Összesen'].sum()
        merged.append(base)
    return merged

# --- ETIKETT GENERÁTOR JAVÍTOTT MARKETINGGEL ÉS KISEBB BETŰVEL ---
def create_label_pdf(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    lw, lh = 70*mm, 42.4*mm
    mx, my = (w - 3*lw)/2, (h - 7*lh)/2
    
    # Marketing szöveg szóról szóra (Excel alapján)
    m_lines = [
        "Jövő heti étlapunkat",
        "már keresse a futárnál!",
        f"Futár: {fn}",
        f"Tel: {ft}",
        "Várjuk megrendelését a",
        "következő héten is!",
        "Jó étvágyat!"
    ]

    total_labels = len(df)
    total_slots = math.ceil(total_labels / 21) * 21

    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = mx + col*lw, my + row_i*lh
        p.setLineWidth(0.2)
        p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
        
        if i < total_labels:
            r = df.iloc[i]
            p.setLineWidth(1.2 if r['Prefix'] == 'Z' else 0.2)
            p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
            p.setFont(f_bold, 10)
            p.drawString(x+5*mm, y+36*mm, f"#{r['Sorrend']}")
            p.drawRightString(x+lw-5*mm, y+36*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9.5)
            p.drawString(x+5*mm, y+30*mm, str(r['Ügyintéző'])[:24])
            p.setFont(f_reg, 8)
            p.drawRightString(x+lw-5*mm, y+30*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5)
            p.drawString(x+5*mm, y+25.5*mm, str(r['Cím'])[:50])
            
            # RENDELÉS KISEBB BETŰVEL (7 pt)
            p.setFont(f_bold, 7)
            r_text = str(r['Rendelés'])
            if " | " in r_text:
                p_part, z_part = r_text.split(" | ")
                p.drawString(x+5*mm, y+19.5*mm, p_part[:55])
                p.drawString(x+5*mm, y+15.5*mm, z_part[:55])
            else:
                p.drawString(x+5*mm, y+17.5*mm, r_text[:55])
            
            p.setFont(f_bold, 8)
            p.drawRightString(x+lw-5*mm, y+11*mm, f"Össz: {r['Összesen']} db")
            p.setFont(f_reg, 6)
            p.drawCentredString(x+lw/2, y+5*mm, f"Futár: {fn} ({ft}) | Jó étvágyat! :)")
        else:
            p.setFont(f_bold, 9)
            p.drawCentredString(x+lw/2, y+32*mm, "TÁJÉKOZTATÁS")
            p.setFont(f_reg, 8)
            for j, line in enumerate(m_lines):
                p.drawCentredString(x+lw/2, y+25*mm-(j*4.2*mm), line)

    p.save()
    buf.seek(0)
    return buf

# --- KOMPAKT TÁBLÁZATOS MENETTERV OLDALSZÁMMAL ÉS ARRÉBB TOLT OSZLOPOKKAL ---
def create_compact_itinerary(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    
    total_items = len(df)
    items_per_page = 32
    total_pages = math.ceil(total_items / items_per_page)

    for page_num in range(1, total_pages + 1):
        p.setFont(f_bold, 12)
        p.drawString(15*mm, h-15*mm, f"MENETTERV - {fn}")
        p.setFont(f_reg, 8)
        p.drawRightString(w-15*mm, h-15*mm, f"Összesen: {total_items} cím")
        
        y = h - 25*mm
        # FEJLÉC - Új pozíciókkal
        p.setFont(f_bold, 7)
        p.drawString(15*mm, y, "SOR")
        p.drawString(25*mm, y, "NÉV / CÍM")
        p.drawString(85*mm, y, "TELEFON") # Arrébb tolva balra (eredeti 110 volt)
        p.drawString(110*mm, y, "RENDELÉS") # Arrébb tolva balra (eredeti 140 volt)
        p.drawRightString(w-15*mm, y, "DB")
        y -= 3*mm
        p.line(15*mm, y, w-15*mm, y)
        y -= 5*mm

        start_idx = (page_num - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        
        page_df = df.iloc[start_idx:end_idx]

        for _, r in page_df.iterrows():
            p.setFont(f_bold, 8)
            p.drawString(15*mm, y, f"#{r['Sorrend']}")
            p.drawString(25*mm, y, str(r['Ügyintéző'])[:32])
            p.setFont(f_reg, 7)
            p.drawString(85*mm, y, str(r['Telefon']))
            p.setFont(f_bold, 6.5) # Kicsit kisebb rendelés a listán is a több helyért
            p.drawString(110*mm, y, str(r['Rendelés'])[:85])
            p.drawRightString(w-15*mm, y, str(r['Összesen']))
            
            y -= 3.8*mm
            p.setFont(f_reg, 7)
            p.drawString(25*mm, y, str(r['Cím'])[:65])
            y -= 2*mm
            p.setStrokeColor(colors.lightgrey)
            p.line(15*mm, y, w-15*mm, y)
            p.setStrokeColor(colors.black)
            y -= 4*mm
        
        # OLDALSZÁMOZÁS
        p.setFont(f_reg, 7)
        p.drawCentredString(w/2, 10*mm, f"- {page_num}. oldal / {total_pages} -")
        
        if page_num < total_pages:
            p.showPage()
        
    p.save()
    buf.seek(0)
    return buf

# --- UI ---
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

st.title("🏷️ Logisztikai Központ v198.7")
up_files = st.file_uploader("Menetterv PDF-ek", accept_multiple_files=True)

if up_files:
    file_order_data = [{"Sorszám": i+1, "Fájl": f.name} for i, f in enumerate(up_files)]
    st.write("📂 Fájlok sorrendje (húzd vagy írd át):")
    fo_df = st.data_editor(file_order_data, hide_index=True)
    
    if st.button("BEOLVASÁS"):
        sorted_names = pd.DataFrame(fo_df).sort_values("Sorszám")["Fájl"].tolist()
        raw = []
        for name in sorted_names:
            fobj = next(f for f in up_files if f.name == name)
            raw.extend(parse_interfood_pro(fobj))
        merged = merge_weekend_data(raw)
        mdf = pd.DataFrame(merged)
        mdf.insert(0, "Sorrend", [str(i+1) for i in range(len(mdf))])
        st.session_state.mdf = mdf
        st.rerun()

if st.session_state.get('mdf') is not None:
    st.divider()
    edf = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True)
    
    if not edf.equals(st.session_state.mdf):
        def sf(x):
            try: return float(str(x).replace(',','.'))
            except: return 999.0
        edf['sk'] = edf['Sorrend'].apply(sf)
        new = edf.sort_values('sk').drop(columns=['sk'])
        new['Sorrend'] = [str(i+1) for i in range(len(new))]
        st.session_state.mdf = new
        st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 ETIKETTEK LETÖLTÉSE"):
            pdf = create_label_pdf(st.session_state.mdf, st.session_state.n, st.session_state.t)
            pages = math.ceil(len(st.session_state.mdf) / 21)
            st.success(f"Kész! Helyezz be {pages} db etikettlapot CÍMKÉVEL LEFELÉ!")
            st.download_button("Fájl mentése", pdf, "interfood_etikett.pdf")
    with c2:
        if st.button("📋 TÁBLÁZATOS MENETTERV"):
            pdf = create_compact_itinerary(st.session_state.mdf, st.session_state.n)
            st.download_button("Menetterv mentése", pdf, "kiszallitasi_lista.pdf")
