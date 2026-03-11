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

# --- FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        # Ha nincs meg a fájl, Helvetica-ra vált, de próbálkozik a DejaVu-val az ékezetek miatt
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- PROFI KOORDINÁTA ALAPÚ KINYERŐ (v7 - Megjegyzés kezeléssel) ---
def parse_interfood_v7(pdf_file):
    rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # A PDF-et táblázatként kezeljük, mert ez a legpontosabb a név/cím helyének megtartásához
            table = page.extract_table({
                "vertical_strategy": "lines", 
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            })
            
            if not table: continue

            for row in table:
                # Fejléc vagy üres sorok átugrása
                if not row or "Ügyfél" in str(row[1]) or len(row) < 5: continue
                
                # Nyers adatok az oszlopokból
                raw_client_info = row[1] if row[1] else ""
                raw_name = row[2].strip() if row[2] else ""
                raw_phone_and_money = row[3].strip() if row[3] else ""
                raw_order = row[4].strip() if row[4] else ""
                raw_total = row[5].strip() if len(row) > 5 and row[5] else "1"

                # 1. ID kinyerése
                id_match = re.search(r'(?:C-?|ID:?\s*)(\d{5,7})', raw_client_info)
                uid = id_match.group(1) if id_match else ""
                
                if not uid: continue # Ha nincs ID, nem valódi rendelési sor

                # 2. Pénz kinyerése (gyakran a telefon alatt/mellett van)
                money_match = re.search(r'(-?\d[\d\s]*)\s*Ft', raw_phone_and_money + " " + raw_client_info)
                money = money_match.group(1).replace(" ", "") if money_match else "0"

                # 3. Név, Cím és Megjegyzés szétválasztása
                # A név az Ügyintéző oszlopban van (raw_name)
                # Az Ügyfél oszlopban (raw_client_info) van a cím és a megjegyzések
                address = ""
                note = ""
                client_lines = [l.strip() for l in raw_client_info.split('\n') if l.strip()]
                
                for line in client_lines:
                    # Ha a sor irányítószámmal kezdődik, az a cím
                    if re.search(r'\d{4}\s+[A-Z]', line) or "Debrecen" in line:
                        address = line
                    elif uid not in line and raw_name not in line and len(line) > 2:
                        # Ami nem ID, nem név és nem cím, az a MEGJEGYZÉS (kapukód, porta, stb.)
                        note += line + " "

                # 4. Telefonszám tisztítása (pénz levágása róla)
                phone = re.sub(r'\s*-?\d+\s*Ft.*', '', raw_phone_and_money).strip()

                rows.append({
                    "ID": uid,
                    "Ügyintéző": raw_name if raw_name else "Név?",
                    "Cím": address if address else "Cím?",
                    "Megjegyzés": note.strip(),
                    "Telefon": phone,
                    "Rendelés": raw_order.replace('\n', ' '),
                    "Pénz": int(money) if money else 0,
                    "Összesen": raw_total
                })
    
    df = pd.DataFrame(rows).drop_duplicates(subset=['ID'], keep='first')
    return df.to_dict('records')

# --- PDF GENERÁLÓ (MENETTERV INTEGRÁLT MEGJEGYZÉSSEL) ---
def create_manifest_v7(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=5*mm, leftMargin=5*mm, topMargin=10*mm, bottomMargin=10*mm)
    elements = []
    
    name_style = ParagraphStyle('NS', fontName=f_bold, fontSize=8, leading=9)
    note_style = ParagraphStyle('MS', fontName=f_reg, fontSize=7, leading=8, textColor=colors.red)
    norm_style = ParagraphStyle('RS', fontName=f_reg, fontSize=7, leading=8)
    title_style = ParagraphStyle('TS', fontName=f_bold, fontSize=14, alignment=1, spaceAfter=10)

    chunks = [df[i:i + 22] for i in range(0, len(df), 22)]
    for idx, chunk in enumerate(chunks):
        elements.append(Paragraph(f"MENETTERV - Futár: {fn} ({idx+1}/{len(chunks)} oldal)", title_style))
        
        data = [["#", "NÉV / CÍM / MEGJEGYZÉS", "TEL", "RENDELÉS", "PÉNZ", "DB"]]
        for _, r in chunk.iterrows():
            client_cell = [
                Paragraph(f"<b>{r['Ügyintéző']}</b>", name_style),
                Paragraph(f"{r['Cím']}", norm_style)
            ]
            if r['Megjegyzés']:
                client_cell.append(Paragraph(f"<b>KÓD: {r['Megjegyzés']}</b>", note_style))

            data.append([
                f"#{int(r['Sorrend'])}",
                client_cell,
                r['Telefon'],
                Paragraph(str(r['Rendelés']), norm_style),
                f"{int(r['Pénz'])} Ft",
                r['Összesen']
            ])
            
        t = Table(data, colWidths=[10*mm, 75*mm, 25*mm, 55*mm, 20*mm, 10*mm])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (-1,0), f_bold),
        ]))
        elements.append(t)
        elements.append(PageBreak())
            
    doc.build(elements); buf.seek(0); return buf

# --- ETIKETT GENERÁLÓ ---
def create_labels_v7(df, fn, ft):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm
    mx, my = 5*mm, 5*mm

    for i, r in df.iterrows():
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        p.setFont(f_bold, 8)
        p.drawString(x + mx, y + lh - my, f"#{int(r['Sorrend'])}")
        p.drawRightString(x + lw - mx, y + lh - my, f"ID: {r['ID']}")
        
        p.setFont(f_bold, 9)
        p.drawString(x + mx, y + lh - my - 5*mm, str(r['Ügyintéző'])[:30])
        p.setFont(f_reg, 8)
        p.drawString(x + mx, y + lh - my - 9*mm, str(r['Cím'])[:40])
        
        if r['Megjegyzés']:
            p.setFont(f_bold, 7)
            p.drawString(x + mx, y + lh - my - 13*mm, f"KÓD: {str(r['Megjegyzés'])[:35]}")
        
        p.setFont(f_reg, 7)
        p.drawString(x + mx, y + 12*mm, str(r['Rendelés'])[:45])
        
        p.setFont(f_bold, 10)
        p.drawString(x + mx, y + my, f"FIZET: {int(r['Pénz'])} Ft")
        p.drawRightString(x + lw - mx, y + my, f"{r['Összesen']} db")
        
    p.save(); buf.seek(0); return buf

# --- UI ---
st.set_page_config(page_title="Interfood Label Master v7", layout="wide")

if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("Beállítások")
    futar_neve = st.text_input("Futár neve", "Szűcs István")
    futar_tel = st.text_input("Futár telefon", "+36 20 886 8971")
    feltoltott_fajlok = st.file_uploader("Válaszd ki a PDF menetterveket", accept_multiple_files=True, type=['pdf'])

if feltoltott_fajlok and st.button("🚀 ADATOK BEOLVASÁSA"):
    osszes_adat = []
    for f in feltoltott_fajlok:
        osszes_adat.extend(parse_interfood_v7(f))
    
    if osszes_adat:
        df = pd.DataFrame(osszes_adat)
        df['Sorrend'] = range(1, len(df) + 1)
        st.session_state.mdf = df
        st.rerun()

if st.session_state.mdf is not None:
    st.subheader("Beolvasott adatok ellenőrzése")
    # Megjelenítjük a Megjegyzés oszlopot is
    szerkesztett_df = st.data_editor(
        st.session_state.mdf, 
        use_container_width=True, 
        hide_index=True, 
        num_rows="dynamic",
        column_order=["Sorrend", "ID", "Ügyintéző", "Cím", "Megjegyzés", "Telefon", "Rendelés", "Pénz", "Összesen"]
    )
    
    if st.button("💾 Módosítások mentése"):
        st.session_state.mdf = szerkesztett_df
        st.success("Adatok frissítve!")

    st.divider()
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("📥 ETIKETTEK (3x7)", create_labels_v7(szerkesztett_df, futar_neve, futar_tel), "etikettek.pdf", "application/pdf", use_container_width=True)
    with c2:
        st.download_button("📋 MENETTERV (Kódokkal)", create_manifest_v7(szerkesztett_df, futar_neve), "menetterv_uj.pdf", "application/pdf", use_container_width=True)
    with d3:
        csv_data = szerkesztett_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📂 EXPORT (CSV)", csv_data, "adatok.csv", "text/csv", use_container_width=True)
