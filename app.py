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
from reportlab.platypus import Paragraph, Table, TableStyle, SimpleDocTemplate
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# --- FONT REGISZTRÁCIÓ ---
def register_fonts():
    try:
        # Próbáld meg betölteni a betűtípust, ha elérhető a szerveren
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# --- KINYERŐ (v10 - String alapú pénzkezelés) ---
def parse_interfood_v10(pdf_file):
    rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            table = page.extract_table({
                "vertical_strategy": "lines", 
                "horizontal_strategy": "lines"
            })
            if not table: continue

            for row in table:
                if not row or len(row) < 6 or "Sor" in str(row[0]): continue
                
                # Nyers adatok
                raw_client = str(row[1]) if row[1] else ""
                raw_address = str(row[2]) if row[2] else ""
                raw_name = str(row[3]) if row[3] else ""
                raw_phone_money = str(row[4]) if row[4] else ""
                raw_order = str(row[5]) if row[5] else ""
                raw_count = str(row[6]) if len(row) > 6 and row[6] else "1"

                # ID és Megjegyzés
                id_match = re.search(r'C-?(\d{5,7})', raw_client)
                uid = id_match.group(1) if id_match else ""
                note = raw_client.replace(f"C-{uid}", "").replace(f"C{uid}", "").strip()
                note = note.replace("\n", " ")

                # Pénz kinyerése szövegként (nem alakítjuk számmá!)
                money_match = re.search(r'(-?\d[\d\s]*)\s*Ft', raw_phone_money)
                money_str = money_match.group(1).replace(" ", "") if money_match else "0"
                
                # Telefon tisztítása
                phone = re.sub(r'-?\d[\d\s]*\s*Ft.*', '', raw_phone_money).strip().replace("\n", "")

                if uid or raw_name:
                    rows.append({
                        "ID": uid,
                        "Ügyintéző": raw_name.strip().replace("\n", " "),
                        "Cím": raw_address.strip().replace("\n", " "),
                        "Megjegyzés": note,
                        "Telefon": phone,
                        "Rendelés": raw_order.strip().replace("\n", " "),
                        "Pénz": money_str, # Itt már szöveg (string) marad!
                        "Összesen": raw_count.strip()
                    })
    return rows

# --- PDF GENERÁLÓK ---
def create_manifest_v10(df, futar_nev, futar_tel):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=5*mm, leftMargin=5*mm, topMargin=10*mm, bottomMargin=10*mm)
    elements = []
    
    styles = getSampleStyleSheet()
    header_style = ParagraphStyle('HS', fontName=f_bold, fontSize=12, spaceAfter=10)
    elements.append(Paragraph(f"Menetterv - Futár: {futar_nev} ({futar_tel})", header_style))

    name_style = ParagraphStyle('NS', fontName=f_bold, fontSize=8)
    note_style = ParagraphStyle('MS', fontName=f_reg, fontSize=7, textColor=colors.red)
    norm_style = ParagraphStyle('RS', fontName=f_reg, fontSize=7)

    data = [["#", "NÉV / CÍM / MEGJEGYZÉS", "TEL", "RENDELÉS", "PÉNZ", "DB"]]
    for i, r in df.iterrows():
        client_info = [
            Paragraph(f"<b>{r['Ügyintéző']}</b>", name_style),
            Paragraph(f"{r['Cím']}", norm_style)
        ]
        if r['Megjegyzés']:
            client_info.append(Paragraph(f"MEGJ: {r['Megjegyzés']}", note_style))

        data.append([
            f"#{r['Sorrend']}",
            client_info,
            r['Telefon'],
            Paragraph(r['Rendelés'], norm_style),
            f"{r['Pénz']} Ft",
            r['Összesen']
        ])
            
    t = Table(data, colWidths=[10*mm, 75*mm, 25*mm, 55*mm, 20*mm, 10*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'TOP')]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    return buf

def create_labels_v10(df, futar_nev, futar_tel):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
    
    for i, r in df.iterrows():
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        p.setFont(f_bold, 8)
        p.drawString(x+5*mm, y+lh-8*mm, f"#{r['Sorrend']}  ID: {r['ID']}")
        p.setFont(f_bold, 10)
        p.drawString(x+5*mm, y+lh-13*mm, str(r['Ügyintéző'])[:28])
        p.setFont(f_reg, 8)
        p.drawString(x+5*mm, y+lh-17*mm, str(r['Cím'])[:35])
        
        if r['Megjegyzés'] and len(str(r['Megjegyzés'])) > 2:
            p.setFont(f_bold, 7)
            p.setFillColor(colors.red)
            p.drawString(x+5*mm, y+lh-21*mm, f"!! {str(r['Megjegyzés'])[:40]}")
            p.setFillColor(colors.black)

        p.setFont(f_reg, 7)
        p.drawString(x+5*mm, y+12*mm, str(r['Rendelés'])[:45])
        p.setFont(f_bold, 10)
        p.drawString(x+5*mm, y+5*mm, f"FIZET: {r['Pénz']} Ft")
        
        p.setFont(f_reg, 6)
        p.drawRightString(x+lw-5*mm, y+10*mm, f"{futar_nev}")
        p.drawRightString(x+lw-5*mm, y+7*mm, f"{futar_tel}")
        p.setFont(f_bold, 10)
        p.drawRightString(x+lw-5*mm, y+2*mm, f"{r['Összesen']} db")
        
    p.save()
    buf.seek(0)
    return buf

# --- STREAMLIT UI ---
st.set_page_config(page_title="Interfood v10", layout="wide")

st.title("Interfood Menetterv Feldolgozó v10")

with st.sidebar:
    st.header("Beállítások")
    futar_nev = st.text_input("Futár neve", "Szűcs István")
    futar_tel = st.text_input("Futár telefonszáma", "+36 20 886 8971")
    uploaded_files = st.file_uploader("Válaszd ki a PDF-eket", accept_multiple_files=True, type=['pdf'])

if uploaded_files:
    if st.button("🚀 Fájlok feldolgozása"):
        all_data = []
        for f in uploaded_files:
            try:
                data = parse_interfood_v10(f)
                all_data.extend(data)
            except Exception as e:
                st.error(f"Hiba a(z) {f.name} feldolgozása közben: {e}")
        
        if all_data:
            df = pd.DataFrame(all_data)
            df['Sorrend'] = range(1, len(df) + 1)
            st.session_state.v10_df = df

if 'v10_df' in st.session_state:
    df = st.data_editor(st.session_state.v10_df, use_container_width=True, hide_index=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("📥 Etikettek (PDF)", create_labels_v10(df, futar_nev, futar_tel), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 Menetterv (PDF)", create_manifest_v10(df, futar_nev, futar_tel), "menetterv.pdf", use_container_width=True)
    with c3:
        st.download_button("📂 CSV Export", df.to_csv(index=False).encode('utf-8-sig'), "export.csv", use_container_width=True)
