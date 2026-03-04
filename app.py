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

st.set_page_config(page_title="Interfood v196.0 - Full Ékezet Support", layout="wide")

# --- 1. BETŰTÍPUSOK REGISZTRÁLÁSA (A GitHub mappádból) ---
def register_fonts():
    # A GitHubra feltöltött fájljaid nevei (kis/nagybetű érzékeny!)
    font_normal = "DejaVuSans.ttf"
    font_bold = "DejaVuSans-Bold.ttf"
    
    try:
        if os.path.exists(font_normal):
            pdfmetrics.registerFont(TTFont('DejaVu', font_normal))
        else:
            st.error(f"Hiányzik a fájl: {font_normal}")
            
        if os.path.exists(font_bold):
            pdfmetrics.registerFont(TTFont('DejaVu-Bold', font_bold))
        else:
            st.error(f"Hiányzik a fájl: {font_bold}")
            
        return "DejaVu", "DejaVu-Bold"
    except Exception as e:
        st.error(f"Betűtípus hiba: {e}")
        return "Helvetica", "Helvetica-Bold" # Tartalék, ha elszállna

# --- 2. PDF FELDOLGOZÓ (P/Z prefix + Telefon + Czinege-fix) ---
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
                prefix = f_code.split('-')[0]
                uid = f_code.split('-')[-1]
                
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
                    q = int(parts[0])
                    if q >= 10: q = int(str(q)[-1])
                    valid_o.append(f"{q}-{parts[1]}")
                    sq += q
                
                if sq > 0:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name,
                        "Cím": clean_addr, "Telefon": final_tel, 
                        "Rendelés": ", ".join(valid_o), "Összesen": sq
                    })
    return rows

# --- 3. PDF GENERÁTOR (3x7 ív) ---
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
        
        p.setLineWidth(1.5 if r['Prefix'] == 'Z' else 0.2)
        p.rect(x+2*mm, y+2*mm, lw-4*mm, lh-4*mm)
        
        p.setFont(f_bold, 10)
        p.drawString(x+5*mm, y+35*mm, f"#{r['Sorrend']}  {r['ID']}")
        p.drawRightString(x+lw-5*mm, y+35*mm, "SZOMBAT" if r['Prefix'] == 'Z' else "PÉNTEK")
        
        p.setFont(f_bold, 10)
        p.drawString(x+5*mm, y+28*mm, str(r['Ügyintéző'])[:24])
        p.setFont(f_reg, 8)
        p.drawRightString(x+lw-5*mm, y+28*mm, str(r['Telefon']))
        
        p.setFont(f_reg, 8)
        p.drawString(x+5*mm, y+23*mm, str(r['Cím'])[:45])
        
        p.setFont(f_bold, 8)
        p.drawString(x+5*mm, y+15*mm, f"{str(r['Rendelés'])[:38]}")
        p.drawRightString(x+lw-5*mm, y+15*mm, f"Össz: {r['Összesen']} db")
        
        p.setFont(f_reg, 7)
        p.drawCentredString(x+lw/2, y+6*mm, f"Futár: {fn} ({ft}) | Jó étvágyat! :)")
        
    p.save()
    buf.seek(0)
    return buf

# --- 4. STREAMLIT UI ---
with st.sidebar.form("futar_form"):
    st.write("🚚 Szállítási adatok")
    n = st.text_input("Futár neve", value=st.session_state.get('n', ""))
    t = st.text_input("Telefonszáma", value=st.session_state.get('t', ""))
    if st.form_submit_button("ADATOK MENTÉSE"):
        st.session_state.n, st.session_state.t = n, t
        st.rerun()

if not st.session_state.get('n'):
    st.title("Interfood Címke Master")
    st.warning("👈 Kérlek, add meg a futár adatait bal oldalt a kezdéshez!")
    st.stop()

st.title(f"🏷️ Etikett Generátor - Üdv, {st.session_state.n}!")
files = st.file_uploader("PDF menettervek feltöltése", accept_multiple_files=True)

if files:
    st.subheader("Járatok sorrendje")
    fo = st.data_editor([{"Sorszám": i+1, "Fájlnév": f.name} for i, f in enumerate(files)], hide_index=True)
    
    if st.button("BEOLVASÁS ÉS FELDOLGOZÁS"):
        sorted_names = pd.DataFrame(fo).sort_values("Sorszám")["Fájlnév"].tolist()
        res = []
        for sn in sorted_names:
            fobj = next(f for f in files if f.name == sn)
            res.extend(parse_interfood_pro(fobj))
        
        df = pd.DataFrame(res)
        df.insert(0, "Sorrend", [str(i+1) for i in range(len(df))])
        st.session_state.mdf = df
        st.rerun()

if st.session_state.get('mdf') is not None:
    st.divider()
    st.subheader("Címek végleges sorrendje")
    edf = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True, key="main_editor")
    
    if not edf.equals(st.session_state.mdf):
        def sf(x):
            try: return float(str(x).replace(',','.'))
            except: return 999.0
        edf['sk'] = edf['Sorrend'].apply(sf)
        new = edf.sort_values('sk').drop(columns=['sk'])
        new['Sorrend'] = [str(i+1) for i in range(len(new))]
        st.session_state.mdf = new
        st.rerun()
    
    st.divider()
    pdf_out = create_pdf(st.session_state.mdf, st.session_state.n, st.session_state.t)
    st.download_button("📥 3x7-es PDF Etikett Letöltése", pdf_out, "interfood_etikett.pdf", "application/pdf", use_container_width=True)
