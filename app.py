import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Table, TableStyle, SimpleDocTemplate, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- FONT REGISZTRÁCIÓ (Ű és Ő betűkhöz) ---
def register_fonts():
    try:
        # Ha a fájl mellett van a .ttf, ezt használja
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- OKOSABB ADATKINYERÉS ---
def parse_interfood_v6(pdf_file):
    rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            # Ügyfélblokkok keresése (C- kód vagy sima kód alapján)
            # A minta keresi a kódokat, és megpróbálja a környező sorokat beazonosítani
            blocks = re.split(r'(?=#\d+|ID:\s*\d+|C-\d+)', text)
            
            for block in blocks:
                lines = [l.strip() for l in block.split('\n') if l.strip()]
                if not lines: continue
                
                # ID kinyerése
                id_match = re.search(r'(\d{5,7})', block)
                if not id_match: continue
                uid = id_match.group(1)
                
                # Név, Cím, Telefon, Pénz alaphelyzet
                name, address, phone, money, order = "", "", "", 0, ""
                
                # Logika: A sorok tartalmának elemzése
                for i, line in enumerate(lines):
                    # Telefonszám
                    if re.search(r'\d{2}/\d{6,7}', line):
                        phone = re.search(r'\d{2}/\d{6,7}', line).group(0)
                    # Pénz (FIZET: XXX Ft vagy sima XXX Ft)
                    if 'Ft' in line:
                        m_val = re.sub(r'[^\d-]', '', line.split('Ft')[0])
                        if m_val: money = int(m_val)
                    # Rendelés (Csü:, Hét: stb)
                    if any(nap in line for nap in ['Hét:', 'Ked:', 'Sze:', 'Csü:', 'Pén:']):
                        order = line
                
                # Név és cím tipp (gyakran az ID előtti/utáni első értelmes sorok)
                # Ez a rész a PDF konkrét kinézetétől függ, de a legtöbb Interfood PDF-nél:
                potential_names = [l for l in lines if len(l) > 3 and not any(x in l for x in ['ID:', 'Ft', 'db', '/'])]
                if potential_names:
                    name = potential_names[0]
                    if len(potential_names) > 1:
                        address = potential_names[1]

                rows.append({
                    "ID": uid,
                    "Ügyintéző": name if name else "Név?",
                    "Cím": address if address else "Cím?",
                    "Telefon": phone,
                    "Rendelés": order,
                    "Pénz": money,
                    "Összesen": 1
                })
    
    # Duplikátum szűrés ID alapján
    df = pd.DataFrame(rows).drop_duplicates(subset=['ID'], keep='first')
    return df.to_dict('records')

# --- PDF GENERÁLÓK ---
def create_labels_v6(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm
    mx, my = 5*mm, 5*mm # 5mm margó fixálva

    for i, r in df.iterrows():
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        # Felső sáv (Sorrend és ID)
        p.setFont(f_bold, 8)
        p.drawString(x + mx, y + lh - my, f"#{int(r['Sorrend'])}")
        p.drawRightString(x + lw - mx, y + lh - my, f"ID: {r['ID']}")
        
        # Név és Cím (Safe zone-ban)
        p.setFont(f_bold, 9)
        p.drawString(x + mx, y + lh - my - 6*mm, str(r['Ügyintéző'])[:35])
        p.setFont(f_reg, 8)
        p.drawString(x + mx, y + lh - my - 10*mm, str(r['Cím'])[:45])
        
        # Rendelés
        p.setFont(f_reg, 7)
        p.drawString(x + mx, y + 15*mm, str(r['Rendelés'])[:50])
        
        # Alsó rész (Pénz és db)
        p.setFont(f_bold, 10)
        p.drawString(x + mx, y + my + 2*mm, f"FIZET: {int(r['Pénz'])} Ft")
        p.drawRightString(x + lw - mx, y + my + 2*mm, f"{r['Összesen']} db")
        
        p.setFont(f_reg, 6)
        p.drawCentredString(x + lw/2, y + 2*mm, f"{fn} | {ft}")
        
    p.save(); buf.seek(0); return buf

def create_manifest_v6(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    # Margók beállítása a levágás ellen
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=15*mm, bottomMargin=20*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    # Egyedi stílus az Ű és Ő betűkhöz
    custom_style = ParagraphStyle('Custom', fontName=f_reg, fontSize=8, leading=10)
    title_style = ParagraphStyle('T', fontName=f_bold, fontSize=14, alignment=1, spaceAfter=10)
    
    chunks = [df[i:i + 25] for i in range(0, len(df), 25)]
    for idx, chunk in enumerate(chunks):
        elements.append(Paragraph(f"MENETTERV - Futár: {fn}", title_style))
        
        data = [["#", "ÜGYINTÉZŐ / CÍM", "TELEFON", "RENDELÉS", "PÉNZ", "DB"]]
        for _, r in chunk.iterrows():
            data.append([
                f"#{int(r['Sorrend'])}",
                Paragraph(f"<b>{r['Ügyintéző']}</b><br/>{r['Cím']}", custom_style),
                r['Telefon'],
                Paragraph(str(r['Rendelés']), custom_style),
                f"{int(r['Pénz'])} Ft",
                r['Összesen']
            ])
            
        t = Table(data, colWidths=[12*mm, 55*mm, 25*mm, 60*mm, 20*mm, 10*mm])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('FONTNAME', (0,0), (-1,0), f_bold),
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph(f"Oldal: {idx+1} / {len(chunks)}", custom_style))
        elements.append(PageBreak())
            
    doc.build(elements); buf.seek(0); return buf

# --- UI ---
st.set_page_config(layout="wide")

if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("Beállítások")
    futar = st.text_input("Futár", "Szűcs István")
    tel = st.text_input("Telefon", "+36 20 886 8971")
    files = st.file_uploader("PDF feltöltése", accept_multiple_files=True)

if files and st.button("🚀 ADATOK BEOLVASÁSA"):
    all_rows = []
    for f in files:
        all_rows.extend(parse_interfood_v6(f))
    if all_rows:
        df = pd.DataFrame(all_rows)
        df['Sorrend'] = range(1, len(df) + 1)
        st.session_state.mdf = df[['Sorrend', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Rendelés', 'Pénz', 'Összesen']]
        st.rerun()

if st.session_state.mdf is not None:
    st.subheader("Szerkeszthető adatok")
    # Teljes szélességű táblázat
    edited = st.data_editor(st.session_state.mdf, use_container_width=True, hide_index=True, num_rows="dynamic")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Mentés és PDF generálás"):
            st.session_state.mdf = edited
            st.success("Adatok rögzítve.")
    
    st.divider()
    
    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button("📥 ETIKETTEK (A4, 3x7)", create_labels_v6(edited, futar, tel), "etikettek_3x7.pdf", "application/pdf", use_container_width=True)
    with d2:
        st.download_button("📋 MENETTERV (Ű betű fix)", create_manifest_v6(edited, futar), "menetterv.pdf", "application/pdf", use_container_width=True)
    with d3:
        csv = edited.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📂 ADATOK (CSV)", csv, "export.csv", "text/csv", use_container_width=True)
