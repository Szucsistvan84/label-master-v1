# --- PDF GENERÁLÁS (Javított kimenettel) ---
def create_pdf_v49(df):
    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=False)
        
        reg_font = "DejaVuSans.ttf"
        bold_font = "DejaVuSans-Bold.ttf"
        
        # Ellenőrzés, hogy léteznek-e a fájlok
        if not os.path.exists(reg_font):
            st.error(f"Hiányzik: {reg_font}")
            return None

        pdf.add_font("DejaVu", style="", fname=reg_font)
        pdf.add_font("DejaVu", style="B", fname=bold_font)
        
        for i, row in df.iterrows():
            if i % 21 == 0: pdf.add_page()
            col, line = i % 3, (i // 3) % 7
            x, y = col * 70, line * 42.4
            
            pdf.set_xy(x + 5, y + 10)
            pdf.set_font("DejaVu", "B", 12)
            pdf.cell(60, 6, str(row['Ügyintéző']), 0, 1)
            
            pdf.set_x(x + 5)
            pdf.set_font("DejaVu", "", 9)
            pdf.cell(60, 5, str(row['Cím']), 0, 1)
            
            pdf.set_x(x + 5)
            pdf.set_font("DejaVu", "", 7)
            pdf.multi_cell(60, 4, f"Rend: {row['Rendelés']}", 0)
            
        # FONTOS: Az output-ot bájtokként kérjük le!
        return pdf.output() 
    except Exception as e:
        st.error(f"PDF hiba: {e}")
        return None

# --- GOMB RÉSZ A KÓD VÉGÉN ---
if st.button("PDF ELŐÁLLÍTÁSA"):
    pdf_output = create_pdf_v49(df)
    if pdf_output:
        # Az fpdf2 output-ja már bytes típusú, ha nem adunk meg fájlnevet
        st.download_button(
            label="LETÖLTÉS MOST",
            data=pdf_output,
            file_name="interfood_etikettek.pdf",
            mime="application/pdf"
        )
