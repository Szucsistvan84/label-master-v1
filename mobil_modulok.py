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
    
    # 1. JÁRAT ÉS FUTÁR AZONOSÍTÁS (Most már közvetlenül a friss Mobil_Raklista fülből)
    futar_neve = st.session_state.get('user_nev', 'Te (Teszt Üzemmód)')
    jaratok = []
    df_sajat_raklista_init = pd.DataFrame()

    try:
        sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
        raklista_sheet = sh_ugyfelkor.worksheet("Mobil_Raklista")
        df_raklista_init = pd.DataFrame(raklista_sheet.get_all_records())
        
        if not df_raklista_init.empty:
            df_raklista_init.columns = [c.strip() for c in df_raklista_init.columns]
            
            # 🔒 Szűrés a bejelentkezett futárra
            df_sajat_raklista_init = df_raklista_init[df_raklista_init['Jarat_ID / Futar'] == futar_neve]
            
            if not df_sajat_raklista_init.empty:
                # Kigyűjtjük a napokat vagy az elérhető egyedi azonosítókat, ha szükséges.
                # Mivel az asztali PDF-ből jövünk, a járatválasztót fixen kitölthetjük vagy 
                # alapértelmezetté tehetjük, hogy ne kelljen a futárnak keresgélnie.
                jaratok = ["Mai Raklista"]
            else:
                # Ha nincs még saját raklistája generálva, megnézzük a nyers Adatok fület tartaléknak
                try:
                    adatok_sheet = sh_ugyfelkor.worksheet("Adatok")
                    df_adatok = pd.DataFrame(adatok_sheet.get_all_records())
                    if not df_adatok.empty:
                        df_adatok.columns = [c.strip() for c in df_adatok.columns]
                        if 'Feldolgozó Futár' in df_adatok.columns:
                            df_szurt = df_adatok[df_adatok['Feldolgozó Futár'] == futar_neve]
                            jaratok = [str(j) for j in df_szurt['Járat'].unique() if str(j).strip() != ""]
                        else:
                            jaratok = [str(j) for j in df_adatok['Járat'].unique() if str(j).strip() != ""]
                except:
                    jaratok = ["Alapértelmezett Járat"]
        else:
            st.error("A Mobil_Raklista munkalap teljesen üres a Google Sheetben!")
            return
    except Exception as e:
        st.error(f"❌ Nem sikerült elérni a Google Sheets-et: {e}")
        return

    # 🔄 TÖBBJÁRATOS JAVÍTÁS: Dinamikus multiselect
    if not jaratok:
        jaratok = ["Nincs elérhető járat"]
        
    valasztott_jaratok = st.multiselect(
        "Válaszd ki a mai járataidat:", 
        options=jaratok,
        default=[jaratok[0]],
        key="mob_jarat_select"
    )
    
    if not valasztott_jaratok:
        st.warning("⚠️ Kérlek, válassz ki legalább egy járatot a folytatáshoz!")
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
                # 🔄 JAVÍTÁS: SHEET_ID_MASTER helyett SHEET_ID_UGYFELKOR-t nyitunk meg
                sh_master = client.open_by_key(SHEET_ID_UGYFELKOR)
                idok_sheet = sh_master.worksheet("Mobil_Idobelyegek")
                idok_sheet.append_row([mai_datum, jaratok_szoveg, futar_neve, start_ido, ""])
                
                st.session_state.idobelyeg_sor_index = len(idok_sheet.get_all_values())
                st.session_state.aruatvetel_folyamatban = True
                st.success(f"Áruátvétel elindítva a következő járatokhoz: {jaratok_szoveg} ({start_ido})")
                time.sleep(1.0)
                st.rerun()
            except Exception as e:
                st.error(f"Hiba a Mobil_Idobelyegek írásakor az Ügyfélkör Sheetbe: {e}")

    # =========================================================================
    # ÁLLAPOT 2: AZ ÁRUÁTVÉTEL FOLYAMATBAN VAN (ÚJ, OPTIMALIZÁLT VERZIÓ)
    # =========================================================================
    else:
        jaratok_szoveg = ", ".join(map(str, valasztott_jaratok))
        st.warning(f"🔄 Áruátvétel folyamatban... ({jaratok_szoveg})")
        
        # A modul tetején már beolvasott adatot használjuk fel újra
        if 'df_sajat_raklista_init' in locals() and not df_sajat_raklista_init.empty:
            st.markdown("### 📦 Összesített, beemelendő ételek listája:")
            st.caption(f"Üdv, {futar_neve}! A konyhai raklistád alapján cikkszámozva:")
            
            # Kilistázzuk a tiszta adatokat checkbox formájában
            for idx, row in df_sajat_raklista_init.iterrows():
                cikkszam_szoveg = f" [{row['Cikkszam']}]" if str(row['Cikkszam']).strip() != "" else ""
                st.checkbox(
                    f"**{int(row['Terv_Darabszam'])} db** - {row['Etel Neve']}{cikkszam_szoveg} — *({row['Nap']})*", 
                    key=f"check_raklista_{idx}"
                )
            
            # Elmentjük lokális változóba a hibabejelentő listájához
            df_sajat_raklista = df_sajat_raklista_init
        else:
            st.info(f"ℹ️ Nem található hozzárendelt raklista '{futar_neve}' névre a mai napon. Kérlek, generáld le a PDF-et az asztali gépen!")
            else:
                st.error("A Mobil_Raklista munkalap üres a Google Sheetben!")
                
        except Exception as e:
            st.error(f"Hiba a Mobil_Raklista beolvasásakor: {e}")

        st.write("---")
        
        # HIBABEJELENTÉS (A saját, tiszta ételeink alapján listázva)
        with st.expander("🚨 HIÁNYZIK / SÉRÜLT VALAMI? (Hiba bejelentése)"):
            st.write("Ha a konyha kevesebbet adott le, vagy sérült az étel, itt jelentsd be azonnal:")
            
            all_etelek = [""]
            if 'df_sajat_raklista' in locals() and not df_sajat_raklista.empty:
                all_etelek = [""] + list(df_sajat_raklista['Etel Neve'].unique())
                
            hiba_etel = st.selectbox("Melyik étellel van gond?", all_etelek, key="mob_hiba_etel")
            hiba_db = st.number_input("Hány darab érintett?", min_value=1, value=1, key="mob_hiba_db")
            hiba_melyik_jarat = st.selectbox("Melyik járathoz tartozó doboz?", valasztott_jaratok, key="mob_hiba_jarat")
            hiba_tipus = st.selectbox("Hiba jellege:", ["Konyha nem adta ki (Hiány)", "Sérült csomagolás", "Megfolyt / Romlott", "Egyéb"], key="mob_hiba_tipus")
            hiba_megj = st.text_input("Rövid megjegyzés:", key="mob_hiba_megj")
            
            if st.button("⚠️ HIBA BEKÜLDÉSE AZ ADMINNAK", use_container_width=True, key="mob_hiba_submit"):
                if hiba_etel != "":
                    try:
                        hibak_sheet = sh_ugyfelkor.worksheet("Logisztikai_Hibak")
                        most_hiba = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        hibak_sheet.append_row([
                            most_hiba, hiba_melyik_jarat, "ÁRUÁTVÉTELI HIÁNY", "N/A", hiba_etel, 
                            int(hiba_db), 0, hiba_tipus, hiba_megj, futar_neve, "Feldolgozatlan"
                        ])
                        st.success("Hiba sikeresen rögzítve! ✅")
                    except Exception as e:
                        st.error(f"Nem sikerült menteni a hibát: {e}")
                else:
                    st.warning("Kérlek válaszd ki az ételt!")

        st.write("---")

        # ÁRUÁTVÉTEL LEZÁRÁSA
        if st.button("🏁 ÁRUÁTVÉTEL LEZÁRÁSA & INDULÁS", use_container_width=True, type="secondary", key="futar_end_btn"):
            most = datetime.now()
            end_ido = most.strftime("%H:%M:%S")
            
            try:
                # 🔄 JAVÍTÁS: SHEET_ID_MASTER helyett SHEET_ID_UGYFELKOR-t nyitunk meg
                sh_master = client.open_by_key(SHEET_ID_UGYFELKOR)
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
