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
    
    # 1. JÁRAT ÉS FUTÁR AZONOSÍTÁS
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
                jaratok = ["Mai Raklista"]
            else:
                # Tartalék terv: ha nincs még saját raklistája, megnézzük a nyers Adatok fület
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
            
            jaratok_szoveg = ", ".join(map(str, valasztott_jaratok))
            
            try:
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
    # ÁLLAPOT 2: DEPOZÁS (CSAK AZ ÖMLESZTETT ÁRUÁTVÉTEL ÉS HIBÁK)
    # =========================================================================
    else:
        jaratok_szoveg = ", ".join(map(str, valasztott_jaratok))
        
        # Ha még nem zárták le a depót, akkor az Áruátvétel fázis fut
        if not st.session_state.get("kiszallitas_folyamatban", False):
            st.warning(f"🔄 Áruátvétel és depózás folyamatban... ({jaratok_szoveg})")
            
            # -----------------------------------------------------------------
            # 1. LÉPÉS: ÖMLESZTETT ÁRUÁTVÉTEL CHK-LISTA
            # -----------------------------------------------------------------
            st.markdown("## 1. lépés: Ömlesztett áruátvétel")
            if 'df_sajat_raklista_init' in locals() and not df_sajat_raklista_init.empty:
                st.caption(f"Üdv, {futar_neve}! Ellenőrizd a darabszámokat a konyhai sorrend alapján:")
                
                for idx, row in df_sajat_raklista_init.iterrows():
                    cikkszam_szoveg = f" [{row['Cikkszam']}]" if str(row['Cikkszam']).strip() != "" else ""
                    st.checkbox(
                        f"**{int(row['Terv_Darabszam'])} db** - {row['Etel Neve']}{cikkszam_szoveg} — *({row['Nap']})*", 
                        key=f"check_raklista_{idx}"
                    )
                df_sajat_raklista = df_sajat_raklista_init
            else:
                st.info(f"ℹ️ Nem található raklista '{futar_neve}' névre. Generáld le az asztali gépen!")

            st.write("---")
            
            # HIBABEJELENTÉS
            with st.expander("🚨 HIÁNYZIK / SÉRÜLT / TÖBBLET VAN? (Bejelentés)"):
                all_etelek_display = [""]
                all_etelek_mapping = {}
                if 'df_sajat_raklista' in locals() and not df_sajat_raklista.empty:
                    for idx, row in df_sajat_raklista.iterrows():
                        display_szoveg = f"[{str(row['Cikkszam']).strip()}] - {str(row['Etel Neve']).strip()} ({str(row['Nap']).strip()})"
                        if display_szoveg not in all_etelek_display:
                            all_etelek_display.append(display_szoveg)
                            all_etelek_mapping[display_szoveg] = str(row['Etel Neve']).strip()
                    
                hiba_etel_display = st.selectbox("Melyik étellel van gond?", all_etelek_display, key="mob_hiba_etel_display")
                hiba_etel = hiba_etel_display.split(" (")[0] if hiba_etel_display != "" else ""
                
                hiba_db = st.number_input("Hány darab érintett?", min_value=1, value=1, key="mob_hiba_db")
                hiba_melyik_jarat = st.selectbox("Melyik járathoz tartozó doboz?", valasztott_jaratok, key="mob_hiba_jarat")
                
                hiba_tipus = st.selectbox(
                    "Hiba jellege:", 
                    ["Konyha nem adta ki (Hiány)", "Többlet (Többet kaptunk)", "Sérült csomagolás", "Megfolyt / Romlott", "Egyéb"], 
                    key="mob_hiba_tipus"
                )
                hiba_megj = st.text_input("Rövid megjegyzés:", key="mob_hiba_megj")
                
                if st.button("⚠️ HIBA BEKÜLDÉSE AZ ADMINNAK", use_container_width=True, key="mob_hiba_submit"):
                    if hiba_etel != "":
                        try:
                            hibak_sheet = sh_ugyfelkor.worksheet("Logisztikai_Hibak")
                            most_hiba = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            if hiba_tipus == "Többlet (Többet kaptunk)":
                                fokategoria = "ÁRUÁTVÉTELI TÖBBLET"
                                hiany_db, tobblet_db = 0, int(hiba_db)
                            else:
                                fokategoria = "ÁRUÁTVÉTELI HIÁNY"
                                hiany_db, tobblet_db = int(hiba_db), 0
                            
                            hibak_sheet.append_row([
                                most_hiba, hiba_melyik_jarat, fokategoria, "N/A", hiba_etel, 
                                hiany_db, tobblet_db, hiba_tipus, hiba_megj, futar_neve, "Feldolgozatlan"
                            ])
                            st.success("Sikeresen rögzítve! ✅")
                        except Exception as e:
                            st.error(f"Hiba a mentésnél: {e}")
                    else:
                        st.warning("Kérlek válaszd ki az ételt!")

            st.write("---")

            # ⏱️ ÁRUÁTVÉTEL RÖGZÍTÉSE (Csak elmenti az időt, nem kényszerít Tab-váltásra)
            if st.button("⏱️ ÁRUÁTVÉTEL VÉGE (Idő rögzítése)", use_container_width=True, type="secondary", key="futar_end_btn"):
                most = datetime.now()
                end_ido = most.strftime("%H:%M:%S")
                
                try:
                    sh_master = client.open_by_key(SHEET_ID_UGYFELKOR)
                    idok_sheet = sh_master.worksheet("Mobil_Idobelyegek")
                    sor_szam = st.session_state.idobelyeg_sor_index
                    
                    if sor_szam:
                        idok_sheet.update_cell(sor_szam, 5, end_ido)
                    
                    st.success(f"✅ Áruátvétel sikeresen lezárva: {end_ido}. Most már átválthatsz a Címekre szedés fülre!")
                except Exception as e:
                    st.error(f"Hiba az áruátvétel lezárásakor: {e}")

        # -----------------------------------------------------------------
        # 3. LÉPÉS: KISZÁLLÍTÁS
        # -----------------------------------------------------------------
        else:
            st.markdown("## 3. lépés: Kiszállítás folyamatban... 🚗💨")
            st.info(f"Sikeresen elindultál a következő járatokkal: {jaratok_szoveg}")
            st.success("Minden cím bepakolva, az áruátvétel és depózás sikeresen rögzítve lett a rendszerben.")
            
            st.write("---")
            if st.button("🏁 JÁRATOK VÉGSŐ LEZÁRÁSA (Műszak vége)", use_container_width=True, type="secondary", key="futar_final_close_btn"):
                st.session_state.aruatvetel_folyamatban = False
                st.session_state.kiszallitas_folyamatban = False
                st.session_state.idobelyeg_sor_index = None
                st.balloons()
                st.success("Műszak sikeresen lezárva! Pihenj egyet! 😊")
                time.sleep(2.0)
                st.rerun()

def render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR):
    """
    client: Hitelesített gspread kliens
    SHEET_ID_UGYFELKOR: Az ügyfélkör Google Sheet ID-ja
    """
    st.markdown("## 2. lépés: Címekre szedés (Bepakolás)")
    st.caption("💡 Pakolás fordított sorrendben! A csoportosított címeket szedd egy szatyorba a gyorsabb leadásért.")
    
    # --- Thermoláda számláló ---
    if 'mobil_lada_szam' not in st.session_state:
        st.session_state.mobil_lada_szam = 1
        
    col_lada1, col_lada2 = st.columns([2, 1])
    with col_lada1:
        st.metric("📦 Aktuális Thermoláda:", f"{st.session_state.mobil_lada_szam}. láda")
    with col_lada2:
        if st.button("➕ Következő láda", key="mob_next_lada_btn", use_container_width=True):
            st.session_state.mobil_lada_szam += 1
            st.rerun()

    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        
        if valasztott_jaratok:
            sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
            adatok_sheet = sh_ugyfelkor.worksheet("Adatok")
            df_adatok = pd.DataFrame(adatok_sheet.get_all_records())
            
            if not df_adatok.empty:
                df_adatok.columns = [c.strip() for c in df_adatok.columns]
                
                jarat_oszlop_neve = 'Járat' if 'Járat' in df_adatok.columns else df_adatok.columns[0]
                
                # Szűrés
                if "Mai Raklista" in valasztott_jaratok:
                    futar_oszlop = 'Feldolgozó Futár' if 'Feldolgozó Futár' in df_adatok.columns else 'Futár'
                    df_jarat_adatok = df_adatok[df_adatok[futar_oszlop].astype(str).str.strip() == st.session_state.get('user_nev', '').strip()] if futar_oszlop in df_adatok.columns else df_adatok
                else:
                    df_jarat_adatok = df_adatok[df_adatok[jarat_oszlop_neve].astype(str).str.strip().isin(valasztott_jaratok)]
                
                if not df_jarat_adatok.empty:
                    df_forditott = df_jarat_adatok.iloc[::-1].copy()
                    
                    cim_oszlop = 'Cím' if 'Cím' in df_forditott.columns else df_forditott.columns[3]
                    nev_oszlop = 'Név' if 'Név' in df_forditott.columns else df_forditott.columns[1]
                    rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_forditott.columns else ('Kosár' if 'Kosár' in df_forditott.columns else None)
                    
                    # 👥 CSOPORTOSÍTÁS: Teljes Cím + Teljes Megjegyzés kulcsként
                    egyedi_csoportok = []
                    # Segédtérkép, amiben eltároljuk a cím-megjegyzés párosokat a későbbi szűréshez
                    for _, row in df_forditott.iterrows():
                        cim = str(row[cim_oszlop]).strip()
                        megj = str(row.get('Megjegyzés', '')).strip()
                        # A kulcsot úgy képezzük, hogy egyedi legyen, de nem splitteljük
                        azonosito = (cim, megj)
                        
                        if azonosito not in egyedi_csoportok:
                            egyedi_csoportok.append(azonosito)
                    
                    st.write("---")
                    osszes_megallo = len(egyedi_csoportok)
                    
                    # Ciklus: Visszafelé számozással
                    for i, (aktualis_cim, aktualis_megj) in enumerate(egyedi_csoportok):
                        megallo_sorszam = osszes_megallo - i
                        
                        # Szűrés a pontos párra
                        df_csoport = df_forditott[
                            (df_forditott[cim_oszlop].astype(str).str.strip() == aktualis_cim) & 
                            (df_forditott.get('Megjegyzés', '').astype(str).str.strip() == aktualis_megj)
                        ]
                        
                        with st.container(border=True):
                            st.markdown(f"### 📦 {megallo_sorszam}. Megálló")
                            st.markdown(f"📍 **Cím:** {aktualis_cim}")
                            if aktualis_megj:
                                st.warning(f"📝 **Megjegyzés:** {aktualis_megj}")
                            
                            if len(df_csoport) > 1:
                                st.info(f"💡 Ide {len(df_csoport)} rendelés megy egy szatyorba!")
                            
                            for idx, row in df_csoport.iterrows():
                                st.write(f"👤 **Név:** {row[nev_oszlop]}")
                                if rendeles_oszlop and str(row[rendeles_oszlop]).strip() != "":
                                    st.markdown(f"📋 **Rendelés:**\n```\n{row[rendeles_oszlop]}\n```")
                                
                                # Kulcsok az állapothoz
                                bepakolt_kulcs = f"bepak_allapot_{idx}"
                                lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"
                                
                                # Inicializálás
                                if bepakolt_kulcs not in st.session_state:
                                    st.session_state[bepakolt_kulcs] = False
                                    st.session_state[lada_tarolt_kulcs] = None
                                
                                # Ha már be van pakolva, a rögzített értéket írjuk ki, különben csak "Bepakolva"
                                label_text = f"Bepakolva: {st.session_state[lada_tarolt_kulcs]}" if st.session_state[bepakolt_kulcs] else "Bepakolás a ládába"
                                
                                # A checkbox "on_change" eseményt használunk a st.rerun() helyett
                                def log_lada(i=idx):
                                    if st.session_state[f"chk_{i}"]:
                                        st.session_state[f"bepak_allapot_{i}"] = True
                                        st.session_state[f"lada_szam_tarolt_{i}"] = f"{st.session_state.mobil_lada_szam}. láda"
                                    else:
                                        st.session_state[f"bepak_allapot_{i}"] = False
                                        st.session_state[f"lada_szam_tarolt_{i}"] = None

                                st.checkbox(
                                    label_text, 
                                    value=st.session_state[bepakolt_kulcs], 
                                    key=f"chk_{idx}",
                                    on_change=log_lada # Ez a kulcs: nem kell rerun, csak frissíti az értéket!
                                )

                                if len(df_csoport) > 1:
                                    st.write("---")
                            
                    st.success("🎉 Minden kártyát átnéztél? Irány a 3. fül!")
                else:
                    st.warning("Nem található cím a kiválasztott járatokhoz.")
            else:
                st.error("Az Adatok munkalap üres!")
        else:
            st.info("ℹ️ Első lépésként válaszd ki a járatodat az 1. fülön!")
            
    except Exception as e:
        st.error(f"Hiba a címek betöltésekor: {e}")
