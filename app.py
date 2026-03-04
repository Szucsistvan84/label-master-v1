import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

# --- PDF GENERÁLÓ MOTOR (3x7 ív, 70x42.4mm) ---
def create_label_pdf(df, f_nev, f_tel):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    cols, rows = 3, 7
    label_w, label_h = 70 * mm, 42.4 * mm
    margin_x = (width - (cols * label_w)) / 2
    margin_y = (height - (rows * label_h)) / 2

    for i, (_, row) in enumerate(df.iterrows()):
        idx = i % (cols * rows)
        if idx == 0 and i > 0: p.showPage()
        
        c = idx % cols
        r = rows - 1 - (idx // cols)
        x = margin_x + c * label_w
        y = margin_y + r * label_h

        # SZOMBAT keret és jelzés
        prefix = str(row.get('Prefix', 'P')).upper()
        if prefix == 'Z':
            p.setLineWidth(1.5)
            p.rect(x + 2*mm, y + 2*mm, label_w - 4*mm, label_h - 4*mm)
            p.setFont("Helvetica-Bold", 10)
            p.drawRightString(x + label_w - 5*mm, y + 35*mm, "SZOMBAT")
        else:
            p.setLineWidth(0.2)
            p.rect(x + 2*mm, y + 2*mm, label_w - 4*mm, label_h - 4*mm)
            p.setFont("Helvetica-Bold", 10)
            p.drawRightString(x + label_w - 5*mm, y + 35*mm, "PÉNTEK")

        # Adatok elhelyezése
        p.setFont("Helvetica-Bold", 11)
        p.drawString(x + 5*mm, y + 35*mm, f"#{row['Sorrend']}  {row['ID']}") # ID prefix nélkül
        
        p.setFont("Helvetica-Bold", 10)
        p.drawString(x + 5*mm, y + 29*mm, str(row['Ügyintéző'])[:22])
        p.setFont("Helvetica", 9)
        p.drawRightString(x + label_w - 5*mm, y + 29*mm, str(row['Telefon']))
        
        p.setFont("Helvetica", 9)
        p.drawString(x + 5*mm, y + 24*mm, str(row['Cím'])[:40])
        
        p.setFont("Helvetica-Bold", 9)
        p.drawString(x + 5*mm, y + 16*mm, f"{str(row['Rendelés'])[:35]}")
        p.drawRightString(x + label_w - 5*mm, y + 16*mm, f"Össz: {row['Összesen']} db")

        # Futár adatok az alján
        p.setFont("Helvetica-Oblique", 7)
        p.drawCentredString(x + label_w/2, y + 6*mm, f"Futár: {f_nev} ({f_tel}) | Jó étvágyat! :)")

    p.save()
    buffer.seek(0)
    return buffer

# --- FŐ PROGRAM ---
st.sidebar.title("🚚 Szállítási adatok")
f_nev = st.sidebar.text_input("Futár neve", key="f_nev_v19")
f_tel = st.sidebar.text_input("Futár telefonszáma", key="f_tel_v19")

if f_nev and f_tel:
    # Itt a korábbi beolvasó és táblázat kezelő rész...
    # (Tételezzük fel, hogy a master_df már készen van)
    
    if st.session_state.get('master_df') is not None:
        st.divider()
        st.subheader("Letöltés")
        
        # A PDF legenerálása a memóriába
        pdf_data = create_label_pdf(st.session_state.master_df, f_nev, f_tel)
        
        # A gomb, ami TÉNYLEGESEN letölti
        st.download_button(
            label="📥 3x7-es PDF Etikettek Letöltése",
            data=pdf_data,
            file_name="interfood_etikettek.pdf",
            mime="application/pdf",
            use_container_width=True
        )
else:
    st.warning("👈 Kérlek add meg a futár adatait a kezdéshez!")
