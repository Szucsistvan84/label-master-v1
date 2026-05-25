# mobil_modulok.py
import streamlit as st
import pandas as pd
from datetime import datetime
import time

def render_mobil_aruatvetel(client):
    """
    client: Az app.py-ból átadott, már hitelesített gspread kliens
    """
    st.subheader("📦 Ömlesztett áruátvétel")
    
    # Pontos Google Sheet ID-k a konfigurációdból
    SHEET_ID_MASTER = "1bZrtgqROYijYhyFOFrqYeSTUAsGqZU6GLijObJ1En0o"
    SHEET_ID_UGYFELKOR = "1nK0OLzVzEFY5bSLhMFfGgs4tOgMEueBgXeb9JUbLSN8"
    
    # 1. JÁRAT ÉS FUTÁR AZONOSÍTÁS (Az Ügyfélkör DB 'Adatok' munkalapjából)
    try:
        # Megnyitjuk az Ügyfélkör táblázatot az ID alapján a te klienseddel
        sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
        adatok_sheet = sh_ugyfelkor.worksheet("Adatok")
        
        adatok_data = adatok_sheet.get_all_records()
        df_adatok = pd.DataFrame(adatok_data)
        
        if not df_adatok.empty:
            df_adatok.columns = [c.strip() for c in df_adatok.columns]
            jaratok = [j for j in df_adatok['Járat'].unique() if str(j).strip() != ""]
        else:
            st.error("Az Adatok munkalap üres az Ügyfélkör DB-ben!")
            return
    except Exception as e:
        st.error(f"❌ Nem sikerült beolvasni az Adatok munkalapot az Ügyfélkör DB-ből: {e}")
        return

    # Futár neve a munkamenetből
    futar_neve = st.session_state.get('user_nev', 'Te (Teszt Üzemmód)')
    
    # 🔄 TÖBBJÁRATOS JAVÍTÁS: Selectbox helyett Multiselect az összevont járatokhoz
    valasztott_jaratok = st.multiselect(
        "Válaszd ki a mai járataidat (többet is választhatsz összevonás esetén):", 
        options=jaratok,
        default=[jaratok[0]] if jaratok else [],
        key="mob_jarat_select"
    )
    
    if not valasztott_jaratok:
        st.warning("⚠️ Kérlek, válassz ki legalább egy járatot a folytatáshoz!")
        return

    st.write("---")

    # Session State állapotok inicializálása
    if "aruatvetel_folyamatban" not in st.session_state:
        st.session_state.aruatvetel_folyamatban = False
    if "idobelyeg_sor_index" not in st.session_state:
        st.session_state.idobelyeg_sor_index = None

    # =========================================================================
    # ÁLLAPOT 1: AZ ÁRÚÁTVÉTEL MÉG NINCS ELINDÍTVA
    # =========================================================================
    if not st.session_state.aruatvetel_folyamatban:
        st.info("💡 Pakolás előtt indítsd el az áruátvételt a pontos munkaidő-méréshez.")
        if st.button("🚀 ÁRUÁTVÉTEL INDÍTÁSA", use_container_width=True, type="primary", key="futar_start_btn"):
            most = datetime.now()
            start_ido = most.strftime("%H:%M:%S")
            mai_datum = most.strftime("%Y-%m-%d")
            
            # Járatok összefűzése egy szöveggé a Google Sheet-be (pl: "4002, 4003")
            jaratok_szoveg = ", ".join(map(str, valasztott_jaratok))
            
            try:
                sh_master = client.open_by_key(SHEET_ID_MASTER)
                idok_sheet = sh_master.worksheet("Mobil_Idobelyegek")
                idok_sheet.append_row([mai_datum, jaratok_szoveg, futar_neve, start_ido, ""])
                
                st.session_state.idobelyeg_sor_index = len(idok_sheet.get_all_values())
                st.session_state.aruatvetel_folyamatban = True
                st.success(f"Áruátvétel elindítva a következő járatokhoz: {jaratok_szoveg} ({start_ido})")
                time.sleep(1.0)
                st.rerun()
            except Exception as e:
                st.error(f"Hiba a Mobil_Idobelyegek írásakor a Master Sheetbe: {e}")

    # =========================================================================
    # ÁLLAPOT 2: AZ ÁRUÁTVÉTEL FOLYAMATBAN VAN
    # =========================================================================
    else:
        jaratok_szoveg = ", ".join(map(str, valasztott_jaratok))
        st.warning(f"🔄 Áruátvétel folyamatban... (Összevont járatok: {jaratok_szoveg})")
        
        # 🟢 JAVÍTÁS: .isin() függvényt használunk, így az ÖSSZES kijelölt járat cikkét lekérjük egyszerre!
        df_jarat_cikkek = df_adatok[df_adatok['Járat'].isin(valasztott_jaratok)]
        
        if not df_jarat_cikkek.empty and 'Étel Neve' in df_jarat_cikkek.columns:
            if 'Mennyiség' in df_jarat_cikkek.columns:
                df_jarat_cikkek['Mennyiség'] = pd.to_numeric(df_jarat_cikkek['Mennyiség'], errors='coerce').fillna(1)
                df_osszesitett = df_jarat_cikkek.groupby('Étel Neve')['Mennyiség'].sum().reset_index(name='Szükséges DB')
            else:
                df_osszesitett = df_jarat_cikkek.groupby('Étel Neve').size().reset_index(name='Szükséges DB')
            
            st.markdown("### 📦 Összevont, beemelendő ételek listája:")
            st.caption("A rendszer automatikusan összeadta a járatok darabszámait!")
            
            for idx, row in df_osszesitett.iterrows():
                st.checkbox(f"**{int(row['Szükséges DB'])} db** - {row['Étel Neve']}", key=f"check_cikk_{idx}")
        else:
            st.info("Nem találhatók ételek a kiválasztott járatokhoz a mai napon.")

        st.write("---")
        
        # HIBABEJELENTÉS (A Master Sheet 'Logisztikai_Hibak' munkalapjára)
        with st.expander("🚨 HIÁNYZIK / SÉRÜLT VALAMI? (Hiba bejelentése)"):
            st.write("Ha a konyha kevesebbet adott le, vagy sérült az étel, itt jelentsd be azonnal:")
            
            all_etelek = [""] + list(df_jarat_cikkek['Étel Neve'].unique()) if not df_jarat_cikkek.empty else [""]
            hiba_etel = st.selectbox("Melyik étellel van gond?", all_etelek, key="mob_hiba_etel")
            hiba_db = st.number_input("Hány darab érintett?", min_value=1, value=1, key="mob_hiba_db")
            
            # Megadjuk, melyik konkrét járatból hiányzik, ha fontos az adminnak
            hiba_melyik_jarat = st.selectbox("Melyik járathoz tartozó doboz?", valasztott_jaratok, key="mob_hiba_jarat")
            hiba_tipus = st.selectbox("Hiba jellege:", ["Konyha nem adta ki (Hiány)", "Sérült csomagolás", "Megfolyt / Romlott", "Egyéb"], key="mob_hiba_tipus")
            hiba_megj = st.text_input("Rövid megjegyzés:", key="mob_hiba_megj")
            
            if st.button("⚠️ HIBA BEKÜLDÉSE AZ ADMINNAK", use_container_width=True, key="mob_hiba_submit"):
                if hiba_etel != "":
                    try:
                        sh_master = client.open_by_key(SHEET_ID_MASTER)
                        hibak_sheet = sh_master.worksheet("Logisztikai_Hibak")
                        most_hiba = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        hibak_sheet.append_row([
                            most_hiba, hiba_melyik_jarat, "ÁRUÁTVÉTELI HIÁNY", "N/A", hiba_etel, 
                            int(hiba_db), 0, hiba_tipus, hiba_megj, futar_neve, "Feldolgozatlan"
                        ])
                        st.success("Hiba sikeresen rögzítve! Az admin már látja a központban. ✅")
                    except Exception as e:
                        st.error(f"Nem sikerült menteni a hibát a Master Sheetbe: {e}")
                else:
                    st.warning("Kérlek válaszd ki az ételt!")

        st.write("---")

        # ÁRUÁTVÉTEL LEZÁRÁSA
        if st.button("🏁 ÁRUÁTVÉTEL LEZÁRÁSA & INDULÁS", use_container_width=True, type="secondary", key="futar_end_btn"):
            most = datetime.now()
            end_ido = most.strftime("%H:%M:%S")
            
            try:
                sh_master = client.open_by_key(SHEET_ID_MASTER)
                idok_sheet = sh_master.worksheet("Mobil_Idobelyegek")
                sor_szam = st.session_state.idobelyeg_sor_index
                
                if sor_szam:
                    idok_sheet.update_cell(sor_szam, 5, end_ido)
                
                st.session_state.aruatvetel_folyamatban = False
                st.session_state.idobelyeg_sor_index = None
                st.success(f"Áruátvétel sikeresen lezárva: {end_ido}. Jó utat! 🚗💨")
                time.sleep(1.0)
                st.rerun()
            except Exception as e:
                st.error(f"Hiba az áruátvétel lezárásakor: {e}")
