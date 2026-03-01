import streamlit as st
import tabula
import pandas as pd
import io
import os

# Oldalbeállítás
st.set_page_status = "wide"
st.title("Interfood Tabula Extractor v76")
st.write("Ez a verzió táblázatként próbálja beolvasni a PDF-et, pont mint az Excel Power Query.")

f = st.file_uploader("Töltsd fel az eredeti Interfood PDF-et", type="pdf")

if f:
    with st.spinner('Táblázatok keresése... Ez eltarthat fél percig is.'):
        try:
            # Ideiglenesen elmentjük a fájlt, mert a tabula szereti a fizikai elérési utat
            with open("temp_file.pdf", "wb") as temp_pdf:
                temp_pdf.write(f.read())

            # Beolvasás 'stream' módban (ez felel meg a Power Query-nek)
            # A 'guess=True' megpróbálja kitalálni az oszlopokat
            dfs = tabula.read_pdf("temp_file.pdf", pages='all', multiple_tables=True, stream=True, guess=True)
            
            if dfs:
                # Összefűzzük az összes oldalt egy nagy táblázatba
                raw_df = pd.concat(dfs, ignore_index=True)
                
                # Takarítás: töröljük a teljesen üres oszlopokat és sorokat
                raw_df = raw_df.dropna(how='all', axis=0).dropna(how='all', axis=1)
                
                st.success(f"Siker! Találtam {len(raw_df)} sort a táblázatban.")
                
                # Megmutatjuk a nyers eredményt
                st.subheader("Beolvasott adatok előnézete:")
                st.dataframe(raw_df)
                
                # Excel export előkészítése
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    raw_df.to_excel(writer, index=False, sheet_name='Interfood_Export')
                
                st.download_button(
                    label="💾 NYERS EXCEL LETÖLTÉSE",
                    data=output.getvalue(),
                    file_name="interfood_tabula_export.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

                st.info("💡 Ha ez az Excel jól néz ki (vannak oszlopok), akkor szólj, és rárakjuk az etikett-generáló gombot!")
                
            else:
                st.warning("A Tabula nem talált strukturált táblázatot. Próbáljuk meg 'lattice' módban?")
                if st.button("Próba 'lattice' módban (vonalas táblázatokhoz)"):
                    dfs_lattice = tabula.read_pdf("temp_file.pdf", pages='all', lattice=True)
                    st.write(dfs_lattice)

            # Takarítás
            if os.path.exists("temp_file.pdf"):
                os.remove("temp_file.pdf")

        except Exception as e:
            st.error(f"Hiba történt a beolvasás során: {str(e)}")
            st.info("Tipp: Győződj meg róla, hogy a Java telepítve van a gépeden!")
