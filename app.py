import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

st.set_page_config(page_title="Interfood v186.0 - PDF Generátor", layout="wide")

# --- KÖTELEZŐ MEZŐK ---
st.sidebar.title("🚚 Szállítási adatok")
futar_nev = st.sidebar.text_input("Futár neve (KÖTELEZŐ)")
futar_tel = st.sidebar.text_input("Futár telefonszáma (KÖTELEZŐ)")

# --- PDF GENERÁLÁS (3x7 ív: 70x42.4mm) ---
def create_label_pdf(df, f_nev, f_tel):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # 3x7 beállítások
    cols = 3
    rows = 7
    label_w = 70 * mm
    label_h = 42.4 * mm
    margin_x = (width - (cols * label_w)) / 2
    margin_y = (height - (rows * label_h)) / 2

    for i, (_, row) in enumerate(df.iterrows()):
        idx_in_page = i % (cols * rows)
        if idx_in_page == 0 and i > 0:
            p.showPage()
        
        col = idx_in_page % cols
        row_idx = rows - 1 - (idx_in_page // cols)
        
        x = margin_x + col * label_w
        y = margin_y + row_idx * label_h

        # Keret (csak szombatnál vastagabb)
        p.setLineWidth(0.2)
        if str(row.get('Prefix', '')).upper() == 'Z':
            p.setLineWidth(1.5)
        p.rect(x + 2*mm, y + 2*mm, label_w - 4*mm, label_h - 4*mm)
        p.setLineWidth(0.2)

        # 1. sor: #Sorszám és ID + NAP
        p.setFont("Helvetica-Bold", 10)
        p.drawString(x + 5*mm, y + 35*mm, f"#{row['Sorszám']}  ID: {row['ID']}")
        nap_szoveg = "SZOMBAT" if str(row.get('Prefix', '')).upper() == 'Z' else "PÉNTEK"
        p.drawRightString(x + label_w - 5*mm, y + 35*mm, nap_szoveg)

        # 2. sor: Név és Telefon
        p.setFont("Helvetica-Bold", 9)
        p.drawString(x + 5*mm, y + 30*mm, str(row['Ügyintéző'])[:25])
        p.setFont("Helvetica", 8)
        p.drawRightString(x + label_w - 5*mm, y + 30*mm, str(row['Telefon']))

        # 3. sor: Cím
        p.setFont("Helvetica", 8)
        p.drawString(x + 5*mm, y + 25*mm, str(row['Cím'])[:45])

        # 4. sor: Rendelés
        p.setFont("Helvetica-Bold", 8)
        p.drawString(x + 5*mm, y + 18*mm, f"Rendelés: {str(row['Rendelés'])[:40]}")
        p.drawRightString(x + label_w - 5*mm, y + 18*mm, f"Össz: {row['Összesen']} db")

        # Alja: Futár és üzenet
        p.setFont("Helvetica-Oblique", 7)
        info_line = f"Futár: {f_nev} ({f_tel}) | Jó étvágyat! :)"
        p.drawCentredString(x + label_w/2, y + 6*mm, info_line)

    p.save()
    buffer.seek(0)
    return buffer

# --- ADATKINYERÉS ---
def parse_pdf(file):
    # Itt a korábbi v180+ parser fut, ami kinyeri a Prefixet is!
    # Fontos: a visszakapott DataFrame-ben KELL lennie 'Prefix' oszlopnak
    pass 

if not futar_nev or not futar_tel:
    st.warning("⚠️ Add meg a futár adatait a folytatáshoz!")
else:
    # PDF feltöltés és táblázat szerkesztés helye...
    # (A korábbi kódod ide jön, ügyelve, hogy a 'Prefix' oszlop ne tűnjön el)
    
    if 'working_df' in st.session_state:
        df = st.session_state.working_df
        
        # JAVÍTÁS: Ellenőrizzük, hogy megvan-e minden oszlop
        required_cols = ['Sorszám', 'ID', 'Ügyintéző', 'Cím', 'Telefon', 'Rendelés', 'Összesen', 'Prefix']
        for col in required_cols:
            if col not in df.columns:
                df[col] = "" # Üres oszlop létrehozása, ha hiányozna

        st.subheader("📍 Címke adatok ellenőrzése")
        edited_df = st.data_editor(df, use_container_width=True, hide_index=True)

        if st.button("📥 3x7-es PDF Etikett Letöltése"):
            pdf_out = create_label_pdf(edited_df, futar_nev, futar_tel)
            st.download_button(
                label="Klikk a letöltéshez",
                data=pdf_out,
                file_name="interfood_etikett_3x7.pdf",
                mime="application/pdf"
            )
