import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

st.set_page_config(page_title="Interfood v193.0", layout="wide")

# --- 1. PDF FELDOLGOZÓ MOTOR ---
def parse_interfood_pro(pdf_file):
    rows = []
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'
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
                text = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text)
                if not u_code_m: continue
                
                # Cím és Név koordináták alapján
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 480])
                
                # Adat tisztítás
                f_code = u_code_m.group(0)
                prefix = f_code.split('-')[0]
                uid = f_code.split('-')[-1]
                
                addr_match = re.search(r'(\d{4})', b3)
                clean_addr = b3[addr_match.start():].strip() if addr_match else b3
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                # Rendelés + Czinege-fix
                orders = re.findall(order_pat, text.replace(" ", ""))
                valid_o = []
                sq = 0
                for o in orders:
                    q = int(o.split('-')[0])
                    if q >= 10: q = int(str(q)[-1])
                    valid_o.append(f"{q}-{o.split('-')[1]}")
                    sq += q
                
                if sq > 0:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name,
                        "Cím": clean_addr, "Rendelés": ", ".join(valid_o),
                        "Összesen": sq, "Telefon": "nincs" # Telefon kereső elhagyva a stabilitásért
                    })
    return rows

# --- 2. PDF GENERÁTOR (3x7) ---
def create_pdf(df, fn, ft):
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
        p.setFont("Helvetica-Bold", 10)
        p.drawString(x+5*mm, y+35*mm, f"#{r['Sorrend']}  {r['ID']}")
        p.drawRightString(x+lw-5*mm, y+35*mm, "SZOMBAT" if r['Prefix'] == 'Z' else "PÉNTEK")
        p.setFont("Helvetica-Bold", 9)
        p.drawString(x+5*mm, y+28*mm, str(r['Ügyintéző'])[:25])
        p.setFont("Helvetica", 8)
        p.drawString(x+5*mm, y+23*mm, str(r['Cím'])[:45])
        p.setFont("Helvetica-Bold", 8)
        p.drawString(x+5*mm, y+15*mm, f"{r['Rendelés'][:35]}")
        p.drawRightString(x+lw-5*mm, y+15*mm, f"Össz: {r['Összesen']} db")
        p.setFont("Helvetica-Oblique", 7)
        p.drawCentredString(x+lw/2, y+6*mm, f"Futár: {fn} ({ft}) | Jó étvágyat! :)")
    p.save()
    buf.seek(0)
    return buf

# --- 3. UI ÉS LOGIKA ---
with st.sidebar.form("f"):
    st.write("🚚 Futár adatok")
    n = st.text_input("Név", value=st.session_state.get('n', ""))
    t = st.text_input("Tel", value=st.session_state.get('t', ""))
    if st.form_submit_button("MENTÉS"):
        st.session_state.n, st.session_state.t = n, t
        st.rerun()

if not st.session_state.get('n'):
    st.warning("👈 Add meg a futár adatait!")
    st.stop()

files = st.file_uploader("PDF-ek", accept_multiple_files=True)
if files:
    fo = st.data_editor([{"Sorszám": i+1, "Név": f.name} for i, f in enumerate(files)])
    if st.button("BEOLVASÁS"):
        sorted_names = pd.DataFrame(fo).sort_values("Sorszám")["Név"].tolist()
        res = []
        for sn in sorted_names:
            fobj = next(f for f in files if f.name == sn)
            res.extend(parse_interfood_pro(fobj))
        df = pd.DataFrame(res)
        df.insert(0, "Sorrend", [str(i+1) for i in range(len(df))])
        st.session_state.mdf = df
        st.rerun()

if st.session_state.get('mdf') is not None:
    edf = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True, key="ed")
    if not edf.equals(st.session_state.mdf):
        def sf(x):
            try: return float(str(x).replace(',','.'))
            except: return 999.0
        edf['sk'] = edf['Sorrend'].apply(sf)
        new = edf.sort_values('sk').drop(columns=['sk'])
        new['Sorrend'] = [str(i+1) for i in range(len(new))]
        st.session_state.mdf = new
        st.rerun()
    
    pdf = create_pdf(st.session_state.mdf, st.session_state.n, st.session_state.t)
    st.download_button("📥 PDF Letöltése", pdf, "etikett.pdf", "application/pdf")
