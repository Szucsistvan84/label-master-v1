# --- PDF GENERÁLÁS (v51 - Biztos bájtokkal) ---
def create_pdf_v51(df):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    
    # Fontok betöltése
    reg_font = "DejaVuSans.ttf"
    bold_font = "DejaVuSans-Bold.ttf"
    
    if os.path.exists(reg_font) and os.path.exists(bold_font):
        pdf.add_font("DejaVu", style="", fname=reg_font)
        pdf.add_font("DejaVu", style="B", fname=bold_font)
        f_name = "DejaVu"
    else:
        st.error("Betűtípus hiba!")
        return None

    for i, row in df.iterrows():
        if i % 21 == 0: pdf.add_page()
        col, line = i % 3, (i // 3) % 7
        x, y = col * 70, line * 42.4
        
        pdf.set_xy(x + 5, y + 10)
        pdf.set_font(f_name, "B", 12)
        pdf.cell(60, 6, str(row['Ügyintéző']), 0, 1)
        
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 9)
        pdf.cell(60, 5, str(row['Cím']), 0, 1)
        
        pdf.set_x(x + 5)
        pdf.set_font(f_name, "", 7)
        pdf.multi_cell(60, 4, f"Rendelés: {row['Rendelés']}", 0)
        
    # Itt a változás: kimenet kérése bytearray-ként, majd bájtokká alakítás
    pdf_out = pdf.output()
    if isinstance(pdf_out, bytearray):
        return bytes(pdf_out)
    return pdf_out

# --- GOMB RÉSZ JAVÍTÁSA ---
if st.button("PDF ETIKETT GENERÁLÁSA", use_container_width=True):
    with st.spinner("PDF készítése..."):
        pdf_bytes = create_pdf_v51(df)
        if pdf_bytes is not None:
            # Most már biztosan bájtokat kap a gomb
            st.download_button(
                label="💾 PDF LETÖLTÉSE MOST",
                data=pdf_bytes,
                file_name="interfood_etikettek.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        else:
            st.error("Nem sikerült a PDF-et bájtokká alakítani.")
