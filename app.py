import streamlit as st
import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

VERZIO = "v203.68-CLEAN-DATA"
WEIGHTS_FILE = "client_weights.csv"
NAP_MAP = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}

st.set_page_config(page_title=f"Interfood Logisztika {VERZIO}", layout="wide")

def parse_interfood_pro(pdf_file):
    rows = []
    # ID: Nap prefix + pontosan 6 számjegy
    u_code_pat = r'([HKSCPZ])-(\d{6})'
    # Irányítószám: Space + 4 számjegy + Space
    zip_pat = r'\s(\d{4})\s'
    # Pénz: számok, amiket " Ft" követ
    money_pat = r'(-?\d[\d\s]*)\s*Ft'
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            # Sorokra bontjuk, de figyelünk az összefüggésekre
            lines = text.split('\n')
            for i, line in enumerate(lines):
                u_match = re.search(u_code_pat, line)
                if u_match:
                    nap_prefix = u_match.group(1)
                    uid = u_match.group(2)
                    
                    # Környezet (2 sor fel, 2 le) a pontos adatokhoz
                    context = " ".join(lines[max(0, i-2):i+3])
                    
                    # NÉV TISZTÍTÁSA
                    # Az ügyintéző általában az ID után vagy a sor végén van
                    raw_name = line.split(u_match.group(0))[-1].strip()
                    # Levágjuk a telefonszám foszlányokat (20, 30, 70) és a felesleges szavakat
                    clean_name = re.sub(r'\s*(20|30|70|#|Sor|Ügyfél).*$', '', raw_name).strip()
                    # Ha túl rövid vagy szemetes, keressünk mást a környezetben
                    if len(clean_name) < 3:
                         clean_name = "Név ellenőrizendő"

                    # CÍM KERESÉSE (Szigorúan: " 4000 ")
                    addr_match = re.search(r'\s(\d{4})\s+([A-ZÁÉÍÓÖŐÚÜŰ][^,]+[^,]{5,})', context)
                    clean_addr = addr_match.group(0).strip() if addr_match else "Cím nem található"
                    # Szemételtávolítás a címből
                    clean_addr = re.sub(r'(Sor|Ügyfél|Ügyintéző|Telefon|Rendelése|Össz).*$', '', clean_addr).strip()

                    # TELEFON
                    phone_m = re.search(r'(\d{2}/\d{6,7})', context.replace(" ", ""))
                    
                    # PÉNZ (Csak az Ft előtti tiszta szám)
                    money = 0
                    m_match = re.search(money_pat, context)
                    if m_match:
                        try:
                            money = int(re.sub(r'[^\d\-]', '', m_match.group(1)))
                        except: pass

                    rows.append({
                        "ID": uid, "Ügyintéző": clean_name, "Telefon": phone_m.group(0) if phone_m else "",
                        "Cím": clean_addr, "Rendelés": list(set(re.findall(order_pat, context))),
                        "Pénz": money, "Nap": NAP_MAP.get(nap_prefix, "Sze"), "Original_Order": i
                    })
    return rows

def create_label_pdf(df, f_name, f_phone):
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    label_w, label_h = 70.0 * mm, 42.428 * mm
    m = 5*mm # 5mm BIZTONSÁGI MARGÓ

    for i in range(len(df)):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = float(col * label_w), float(row_i * label_h)
        r = df.iloc[i]
        
        p.setFont("Helvetica", 7)
        p.drawString(x + m, y + label_h - m, f"#{r['Sorrend']}")
        p.drawRightString(x + label_w - m, y + label_h - m, f"ID: {r['ID']}")
        
        p.setFont("Helvetica-Bold", 9)
        p.drawString(x + m, y + label_h - m - 5*mm, str(r['Ügyintéző'])[:25])
        p.setFont("Helvetica", 8)
        p.drawRightString(x + label_w - m, y + label_h - m - 5*mm, str(r['Telefon']))
        
        p.setFont("Helvetica", 8)
        p.drawString(x + m, y + label_h - m - 10*mm, str(r['Cím'])[:40])
        
        p.setFont("Helvetica-Bold", 8.5)
        p.drawString(x + m, y + m + 10*mm, f"{r['Nap']}: {', '.join(r['Rendelés'])}"[:60])
        
        p.setFont("Helvetica-Bold", 10)
        p.drawRightString(x + label_w - m, y + m + 4*mm, f"{r['Össz db']} db")
        if int(r['Pénz']) > 0:
            p.drawString(x + m, y + m + 4*mm, f"FIZET: {r['Pénz']} Ft")
            
        p.setFont("Helvetica", 6)
        p.drawCentredString(x + label_w/2, y + m - 2*mm, f"Futár: {f_name} | {f_phone}")
        
    p.save(); buf.seek(0); return buf

# --- UI ---
st.title(f"Interfood Logisztika {VERZIO}")
c1, c2 = st.columns(2)
with c1: f_nev = st.text_input("Futár neve", "Szűcs István")
with c2: f_tel = st.text_input("Telefonszám", "+36 20 886 8971")

files = st.file_uploader("Menetterv PDF feltöltése", accept_multiple_files=True)

if files and st.button("📊 ADATOK TISZTÍTÁSA ÉS BETÖLTÉSE"):
    all_data = []
    for f in files: all_data.extend(parse_interfood_pro(f))
    
    if all_data:
        df = pd.DataFrame(all_data).drop_duplicates(subset=['ID', 'Nap'])
        df = df.groupby('ID').agg({
            'Ügyintéző': 'first', 'Telefon': 'first', 'Cím': 'first',
            'Rendelés': lambda x: [i for s in x for i in s],
            'Pénz': 'sum', 'Nap': lambda x: "+".join(sorted(list(set(x)))),
            'Original_Order': 'min'
        }).reset_index()
        
        df['Össz db'] = df['Rendelés'].apply(len)
        
        # Súlyozás betöltése
        if os.path.exists(WEIGHTS_FILE):
            weights = pd.read_csv(WEIGHTS_FILE, dtype={'ID': str}).set_index('ID')['Weight'].to_dict()
            df['Weight'] = df['ID'].map(weights).fillna(df['Original_Order'] + 2000).astype(int)
        else:
            df['Weight'] = df['Original_Order']
            
        df = df.sort_values(by='Weight').reset_index(drop=True)
        df['Sorrend'] = range(1, len(df) + 1)
        
        st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Rendelés', 'Pénz', 'Nap', 'Össz db']]

if 'mdf' in st.session_state:
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True)
    
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("💾 SORREND MENTÉSE"):
            edited[['ID', 'Sorrend']].rename(columns={'Sorrend': 'Weight'}).to_csv(WEIGHTS_FILE, index=False)
            st.success("Sorrend rögzítve!")
    with col_b:
        if st.button("📥 ETIKETTEK (5mm margóval)"):
            pdf = create_label_pdf(edited, f_nev, f_tel)
            st.download_button("PDF Mentése", pdf, "etikettek.pdf")
    with col_c:
        csv = edited.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📝 TISZTA EXPORT", csv, "menetterv_tiszta.csv")
