import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v191.0 - Fix Beléptető", layout="wide")

# --- SIDEBAR FORM: Ez kényszeríti ki a frissítést ---
with st.sidebar.form("futar_adatok"):
    st.title("🚚 Szállítási adatok")
    f_nev_input = st.text_input("Futár neve", value=st.session_state.get('f_nev', ""))
    f_tel_input = st.text_input("Futár telefonszáma", value=st.session_state.get('f_tel', ""))
    submit = st.form_submit_button("Adatok Mentése és Folytatás")
    
    if submit:
        st.session_state.f_nev = f_nev_input
        st.session_state.f_tel = f_tel_input
        st.rerun()

# --- ELLENŐRZÉS: Ha nincs meg a név vagy tel, megállunk ---
f_nev = st.session_state.get('f_nev', "")
f_tel = st.session_state.get('f_tel', "")

if not f_nev or not f_tel:
    st.title("Interfood Címke Master")
    st.warning("👈 Kérlek, add meg a **Futár adatait** a bal oldalon, majd nyomj a **Mentés** gombra!")
    st.stop()

# --- HA IDÁIG ELJUTOTTUNK, MEGY A PROGRAM ---
st.success(f"Bejelentkezve: {f_nev} | {f_tel}")
st.title("🏷️ Etikett Generátor és Rendező")

# Fájl feltöltő modul
uploaded_files = st.file_uploader("1. PDF-ek feltöltése", type="pdf", accept_multiple_files=True)

if uploaded_files:
    # Itt folytatódik a korábbi, már jól működő beolvasó kódod...
    st.info(f"{len(uploaded_files)} fájl feltöltve. Kattints a beolvasásra!")
    
    if st.button("Adatok feldolgozása"):
        # Adatkinyerés indítása
        pass
