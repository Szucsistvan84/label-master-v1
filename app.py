import streamlit as st
from pypdf import PdfReader
import re

# --- KONFIGURÁCIÓ ---
LABEL_WIDTH = 70  # mm
LABEL_HEIGHT = 42.4  # mm
ROWS = 7
COLS = 3

st.set_page_config(page_title="Interfood Etikett Generátor", layout="centered")

st.title("🚚 Interfood Menetterv Generátor")
st.subheader("4002-es járat és társai")

# 1. FUTÁR ADATOK BEKÉRÉSE (Kötelező)
with st.sidebar:
    st.header("Futár beállítások")
    futar_neve = st.text_input("Saját neved (Marketinghez):", placeholder="pl. Szűcs István")
    futar_tel = st.text_input("Telefonszámod:", placeholder="pl. +36 20 886 8971")
    
    if not futar_neve or not futar_tel:
        st.warning("⚠️ Add meg a neved és számod a folytatáshoz!")

# 2. PDF FELTÖLTÉS (Drag & Drop)
uploaded_file = st.file_uploader("Dobd be a menetterv PDF-et", type="pdf")

if uploaded_file and futar_neve and futar_tel:
    # Itt a háttérben a kód elkezdi feldolgozni a PDF-et
    # (A PDF beolvasó logika a konkrét PDF struktúrádhoz lesz igazítva)
    
    st.success("✅ PDF beolvasva!")

    # 3. NÉV-ELLENŐRZŐ SZAMÁRVEZETŐ
    st.header("📋 Adatellenőrzés")
    
    # Példa adat (Hegedűs-Szenteczki esetére)
    gyanus_nevek = [{"id": "465258", "nev": "Hegedűs-Szenteczki", "cim": "Nádsíp u. 6."}]
    
    st.write("Az alábbi nevek hiányosnak tűnnek. Kérlek pótold a keresztnevet!")
    javitott_nevek = {}
    for item in gyanus_nevek:
        col1, col2 = st.columns([1, 2])
        col1.write(f"ID: {item['id']}")
        javitott_nevek[item['id']] = col2.text_input(f"Keresztnév a '{item['nev']}' névhez:", key=item['id'])

    # 4. P+SZ PÁROSÍTÁSOK KIMUTATÁSA
    st.info("💡 Találtam 8 db Péntek + Szombat összevont címet.")

    # 5. GENERÁLÁS GOMB
    if st.button("✨ ETIKETTEK GENERÁLÁSA (PDF)"):
        # Itt készül el az SVG-alapú PDF
        # A kód a (kulcs) szöveget automatikusan # karakterre cseréli
        st.balloons()
        st.download_button(
            label="💾 Kész etikettek letöltése",
            data=b"Ide jon a generalt PDF tartalom",
            file_name="nyomtatando_etikettek.pdf",
            mime="application/pdf"
        )
        
        st.write(f"**Instrukció:** Tegyél be 5 db etikett lapot a nyomtatóba címkével LEFELÉ!")