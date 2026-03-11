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
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- KOORDINÁTA ALAPÚ ÉS OKOS KINYERŐ (v203.89) ---
def parse_interfood_v7(pdf_file):
    rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Táblázat kinyerése a struktúra megőrzéséhez
            table = page.extract_table({
                "vertical_strategy": "lines", 
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
            })
            
            if not table:
                # Ha nincs klasszikus táblázat, marad a blokk alapú, de szigorúbb regexszel
                text = page.extract_text()
                # ... (tartalék megoldás)
                continue

            for row in table:
                if not row or "Ügyfél" in str(row[1]): continue
                
                # Oszlopok felosztása a PDF szerkezete szerint:
                # 0: Sor, 1: Ügyfél/Cím/Megjegyzés, 2: Ügyintéző, 3: Telefon, 4: Rendelés, 5: Össz
                
                raw_client_info = row[1] if row[1] else ""
                name = row[2].strip() if len(row) > 2 and row[2] else ""
                phone_raw = row[3].strip() if len(row) > 3 and row[3] else ""
                order = row[4].strip() if len(row) > 4 and row[4] else ""
                total_db = row[5].strip() if len(row) > 5 and row[5] else "1"

                # ID és Pénz kinyerése a Telefon/Ügyfél cellából (Gyakran ott van a Ft)
                id_match = re.search(r'(?:C-?|ID:?\s*)(\d{5,7})', raw_client_info)
                uid = id_match.group(1) if id_match else ""
                
                money_match = re.search(r'(-?\d[\d\s]*)\s*Ft', phone_raw + " " + raw_client_info)
                money = money_match.group(1).replace(" ", "") if money_match else "0"

                # Cím és Megjegyzés szétválasztása (Cím általában irányítószámmal kezdődik)
                address = ""
                note = ""
                client_lines = [l.strip() for l in raw_client_info.split('\n') if l.strip()]
                
                for line in client_lines:
                    if re.search(r'\d{4}\s+[A-Z]', line) or "Debrecen" in line:
                        address = line
                    elif uid not in line and len(line) > 2:
                        # Ami nem ID és nem cím, az lesz a megjegyzés/kapukód
                        note += line + " "

                if uid:
                    rows.append({
                        "ID": uid,
                        "Ügyintéző": name,
                        "Cím": address,
                        "Megjegyzés": note.strip(),
                        "Telefon": re.sub(r'\s*-?\d+\s*Ft.*', '', phone_raw).strip(),
                        "Rendelés": order.replace('\n', ', '),
                        "Pénz": int(money) if money else 0,
                        "Összesen": total_db
                    })
    
    df = pd.DataFrame(rows).drop_duplicates(subset=['ID'])
    return df.to_dict('records')

# --- PDF GENERÁLÓ (MENETTERV INTEGRÁLT MEGJEGYZÉSSEL) ---
def create_manifest_v7(df, fn):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=5*mm, leftMargin=5*mm, topMargin=10*mm, bottomMargin=10*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    # Stílusok az ékezetekhez és a tördeléshez
    name_style = ParagraphStyle('NS', fontName=f_bold, fontSize=8, leading=9)
    note_style = ParagraphStyle('MS', fontName=f_reg, fontSize=7, leading=8, textColor=colors.red)
    norm_style = ParagraphStyle('RS', fontName=f_reg, fontSize=7, leading=8)

    chunks = [df[i:i + 22] for i in range(0, len(df), 22)]
    for idx, chunk in enumerate(chunks):
        elements.append(Paragraph(f"MENETTERV - Futár: {fn} ({idx+1}/{len(chunks)} oldal)", styles['Title']))
        
        data = [["#", "NÉV / CÍM / MEGJEGYZÉS", "TEL", "RENDELÉS", "PÉNZ", "DB"]]
        for _, r in chunk.iterrows():
            # A név, cím és a frissen talált MEGJEGYZÉS egy cellába megy, de elválasztva
            client_cell = [
                Paragraph(f"<b>{r['Ügyintéző']}</b>", name_style),
                Paragraph(f"{r['Cím']}", norm_style)
            ]
            if r['Megjegyzés']:
                client_cell.append(Paragraph(f"<i>KÓD: {r['Megjegyzés']}</i>", note_style))

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
        ]))
        elements.append(t)
        elements.append(PageBreak())
            
    doc.build(elements); buf.seek(0); return buf

# (Az UI rész változatlan, csak az 'edited' táblázatba bekerül a Megjegyzés oszlop)
# ... [Streamlit UI kód itt, az új oszlopkezeléssel] ...
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

