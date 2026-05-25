import streamlit as st
import pandas as pd
import time
import urllib.parse
from datetime import datetime
from streamlit_js_eval import get_geolocation

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

# --- 1. ADATOK GYORSÍTÓTÁRA (CACHE) ---
# Ez gondoskodik róla, hogy ne töltsön másodpercekig a Google Sheets minden kattintásnál.
# ttl=600 azt jelenti, hogy 10 percig a memóriából dolgozik, utána frissít automatikusan.
@st.cache_data(ttl=600)
def get_mobil_adatok_cached(_client, sheet_id):  # <- Ide került az alsó vonal!
    sh = _client.open_by_key(sheet_id)
    return pd.DataFrame(sh.worksheet("Adatok").get_all_records())

# --- 2. A GYORSÍTOTT MOBIL FÜGGVÉNY ---
def render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR):
    # --- VEZÉRLÉS AZ OLDALSÁVBAN (FIXEN RÖGZÍTVE) ---
    with st.sidebar:
        st.markdown("### 📦 Pakolás vezérlés")
        
        if 'mobil_lada_szam' not in st.session_state: st.session_state.mobil_lada_szam = 1
        if "mutasd_bepakoltat" not in st.session_state: st.session_state.mutasd_bepakoltat = False
        
        st.metric("📦 Aktuális láda:", f"{st.session_state.mobil_lada_szam}. láda")
        
        # A fejléc gomboknál kell a rerun, hogy azonnal átrendezze a nézetet
        if st.button("➕ Következő láda", use_container_width=True):
            st.session_state.mobil_lada_szam += 1
            st.rerun()
            
        gomb_szoveg = "🔍 Rejtsd a kész" if st.session_state.mutasd_bepakoltat else "🔍 Mutasd a kész"
        if st.button(gomb_szoveg, use_container_width=True):
            st.session_state.mutasd_bepakoltat = not st.session_state.mutasd_bepakoltat
            st.rerun()
        st.write("---")

    # --- FŐ TARTALOM ---
    st.markdown("## 2. lépés: Címekre szedés (Bepakolás)")
    st.caption("💡 Pakolás fordított sorrendben! A csoportosított címeket szedd egy szatyorba.")

    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        if valasztott_jaratok:
            
            # --- ITT MEGHÍVJUK A JAVÍTOTT FÜGGVÉNYT ---
            df_adatok = get_mobil_adatok_cached(client, SHEET_ID_UGYFELKOR) 
            
            if not df_adatok.empty:
                df_adatok.columns = [c.strip() for c in df_adatok.columns]
                cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
                nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
                rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
                
                # Szűrés (Ha van rá szükség) és Fordított sorrend
                df_forditott = df_adatok.iloc[::-1].copy()
                
                # --- AZ ÖSSZES SOR FELDOLGOZÁSA EGYENKÉNT (Szigorú számozás) ---
                osszes_megallo = len(df_forditott)
                
                # St.fragment-be zárjuk a kártyákat, így a pipálás csak ezen a blokkon belül fut le villámgyorsan
                @st.fragment
                def render_kartyak(df_lista):
                    for i, (idx, row) in enumerate(df_lista.iterrows()):
                        megallo_sorszam = osszes_megallo - i
                        aktualis_cim = str(row[cim_oszlop]).strip()
                        aktualis_megj = str(row.get('Megjegyzés', '')).strip()

                        # Állapotkezelés (egyetlen sorhoz)
                        bepakolt_kulcs = f"bepak_allapot_{idx}"
                        lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"
                        if bepakolt_kulcs not in st.session_state:
                            st.session_state[bepakolt_kulcs] = False
                            st.session_state[lada_tarolt_kulcs] = None
                        
                        # Ha el van rejtve, folytatás (skip)
                        if st.session_state[bepakolt_kulcs] and not st.session_state.mutasd_bepakoltat:
                            continue

                        with st.container(border=True):
                            st.markdown(f"### 📦 {megallo_sorszam}. Címke")
                            st.markdown(f"📍 **Cím:** {aktualis_cim}")
                            if aktualis_megj: st.warning(f"📝 **Megjegyzés:** {aktualis_megj}")
                            
                            st.write(f"👤 **Név:** {row[nev_oszlop]}")
                            if rendeles_oszlop and str(row[rendeles_oszlop]).strip() != "":
                                st.markdown(f"📋 **Rendelés:**\n```\n{row[rendeles_oszlop]}\n```")
                            
                            # Checkbox logika (Nincs st.rerun(), így azonnali és villanásmentes)
                            def log_lada(i=idx):
                                if st.session_state[f"chk_{i}"]:
                                    st.session_state[f"bepak_allapot_{i}"] = True
                                    st.session_state[f"lada_szam_tarolt_{i}"] = f"{st.session_state.mobil_lada_szam}. láda"
                                else:
                                    st.session_state[f"bepak_allapot_{i}"] = False
                                    st.session_state[f"lada_szam_tarolt_{i}"] = None

                            label = f"Bepakolva: {st.session_state[lada_tarolt_kulcs]}" if st.session_state[bepakolt_kulcs] else "Bepakolás a ládába"
                            st.checkbox(label, value=st.session_state[bepakolt_kulcs], key=f"chk_{idx}", on_change=log_lada)
                            st.write("---")
                
                # Kártyák kirajzolása
                render_kartyak(df_forditott)
                
            else:
                st.error("Az Adatok munkalap üres!")
        else:
            st.info("ℹ️ Válaszd ki a járatodat az 1. fülön!")
    except Exception as e:
        st.error(f"Hiba a betöltéskor: {e}")

# --- 3. LÉPÉS: KISZÁLLÍTÁS MODUL ---
def render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR):
    st.markdown("## 🚚 3. lépés: Kiszállítás és Elszámolás")
    st.caption("💡 Mindig a soron következő legfrissebb címet látod. Használd a gyorsgombokat!")

    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        if not valasztott_jaratok:
            st.info("ℹ️ Válaszd ki a járatodat az 1. fülön!")
            return

        df_adatok = get_mobil_adatok_cached(client, SHEET_ID_UGYFELKOR)
        
        if df_adatok.empty:
            st.error("Az Adatok munkalap üres!")
            return

        df_adatok.columns = [c.strip() for c in df_adatok.columns]
        cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
        nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
        tel_oszlop = 'Telefon' if 'Telefon' in df_adatok.columns else 'Tel'
        rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
        
        lat_oszlop = 'Latitude' if 'Latitude' in df_adatok.columns else 'Lat'
        lon_oszlop = 'Longitude' if 'Longitude' in df_adatok.columns else 'Lon'

        df_kiszallitas = df_adatok.copy()

        bepakolt_sorok = []
        for idx, row in df_kiszallitas.iterrows():
            lada_kulcs = f"lada_szam_tarolt_{idx}"
            if st.session_state.get(lada_kulcs) is not None:
                bepakolt_sorok.append((idx, row))

        if not bepakolt_sorok:
            st.warning("⚠️ Nincs még bepakolt cím a rendszerben! Előbb a 2. fülön pakolj be a ládákba.")
            return

        osszes_bepakolt = len(bepakolt_sorok)
        kesz_cimek = sum(1 for idx, _ in bepakolt_sorok if st.session_state.get(f"kiszallitva_{idx}", False))
        
        with st.sidebar:
            st.markdown("### 📊 Mai folyamat")
            haladas_szazalek = kesz_cimek / osszes_bepakolt if osszes_bepakolt > 0 else 0
            st.progress(haladas_szazalek)
            st.metric("Kézbesítve:", f"{kesz_cimek} / {osszes_bepakolt} megálló")
            st.write("---")

        for sorszam, (idx, row) in enumerate(bepakolt_sorok, 1):
            
            if st.session_state.get(f"kiszallitva_{idx}", False):
                continue 

            melyik_lada = st.session_state.get(f"lada_szam_tarolt_{idx}")
            aktualis_cim = str(row[cim_oszlop]).strip()
            vevo_neve = str(row[nev_oszlop]).strip()
            vevo_tel = str(row.get(tel_oszlop, '')).strip()
            aktualis_megj = str(row.get('Megjegyzés', '')).strip()
            
            saved_lat = str(row.get(lat_oszlop, "")).strip()
            saved_lon = str(row.get(lon_oszlop, "")).strip()

            with st.container(border=True):
                st.markdown(f"### 📍 {sorszam}. Cím — `{melyik_lada}`")
                st.subheader(f"👤 {vevo_neve}")
                st.markdown(f"🏠 **Cím:** {aktualis_cim}")
                if aktualis_megj: st.warning(f"📝 **Megjegyzés:** {aktualis_megj}")
                
                # --- 🛒 KOSÁR TARTALMA (EZ HIÁNYZOTT!) ---
                if rendeles_oszlop and str(row[rendeles_oszlop]).strip() != "" and str(row[rendeles_oszlop]).strip() != "nan":
                    st.markdown("📦 **Átadandó termékek:**")
                    st.code(str(row[rendeles_oszlop]).strip(), language="text")
                
                # --- GOLYÓÁLLÓ GOOGLE MINI TÉRKÉP URLEK ---
                # Ha van koordináta, azt adjuk át, különben a tiszta szöveges címet, országgal megerősítve
                if saved_lat and saved_lon and saved_lat != "nan" and saved_lon != "nan":
                    q_param = f"{saved_lat},{saved_lon}"
                else:
                    q_param = f"{aktualis_cim}, Hungary"
                
                encoded_q = urllib.parse.quote(q_param)
                # Ez az alternatív beágyazási URL sokkal toleránsabb a magyar címekkel szemben
                embed_url = f"https://maps.google.com/maps?q={encoded_q}&t=&z=16&ie=UTF8&iwloc=&output=embed"
                
                st.components.v1.html(
                    f'<iframe width="100%" height="220" src="{embed_url}" frameborder="0" scrolling="no" marginheight="0" marginwidth="0" style="border-radius:10px; border:1px solid #ddd;"></iframe>', 
                    height=230
                )

                # --- AKCIÓGOMBOK SORJA ---
                col_tel, col_gps = st.columns(2)
                
                with col_tel:
                    if vevo_tel and vevo_tel != "nan":
                        st.markdown(
                            f'<a href="tel:{vevo_tel}" target="_blank">'
                            f'<button style="width:100%; height:45px; background-color:#25D366; color:white; border:none; border-radius:8px; font-weight:bold; font-size:16px; cursor:pointer;">'
                            f'📞 Hívás'
                            f'</button></a>', unsafe_allow_html=True
                        )
                    else:
                        st.button("📞 Nincs telefonszám", disabled=True, use_container_width=True)
                        
                with col_gps:
                    # Navigációs gomb (külső megnyitáshoz)
                    nav_target = f"{saved_lat},{saved_lon}" if (saved_lat and saved_lon and saved_lat != "nan") else aktualis_cim
                    encoded_nav = urllib.parse.quote(nav_target)
                    maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_nav}"
                    
                    st.markdown(
                        f'<a href="{maps_url}" target="_blank">'
                        f'<button style="width:100%; height:45px; background-color:#4285F4; color:white; border:none; border-radius:8px; font-weight:bold; font-size:16px; cursor:pointer;">'
                        f'🗺️ GPS Navigáció'
                        f'</button></a>', unsafe_allow_html=True
                    )

                st.write("")
                
                # --- 🎯 KOORDINÁTA JAVÍTÁS / MENTÉS ---
                with st.expander("🎯 Pontatlan a pozíció? Kapu rögzítése"):
                    st.write("Állj meg a kapu előtt a kocsival, és mentsd el a pontos koordinátákat a jövőre nézve.")
                    
                    loc = get_geolocation()
                    
                    if loc:
                        curr_lat = loc['coords']['latitude']
                        curr_lon = loc['coords']['longitude']
                        st.info(f"Észlelt GPS koordináta: `{curr_lat}, {curr_lon}`")
                        
                        if st.button("💾 Mentés a vevőhöz a Sheets-be", key=f"save_geo_{idx}", use_container_width=True):
                            try:
                                sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                                ws = sh.worksheet("Adatok")
                                headers = ws.row_values(1)
                                
                                if lat_oszlop not in headers:
                                    ws.update_cell(1, len(headers) + 1, 'Latitude')
                                    ws.update_cell(1, len(headers) + 2, 'Longitude')
                                    headers = ws.row_values(1)
                                
                                lat_col_idx = headers.index(lat_oszlop) + 1
                                lon_col_idx = headers.index(lon_oszlop) + 1
                                
                                sheet_row = int(idx) + 2
                                ws.update_cell(sheet_row, lat_col_idx, curr_lat)
                                ws.update_cell(sheet_row, lon_col_idx, curr_lon)
                                
                                st.cache_data.clear()
                                st.success("🎯 Pozíció sikeresen elmentve!")
                                st.rerun()
                            except Exception as geo_err:
                                st.error(f"Sheets írási hiba: {geo_err}")
                    else:
                        st.caption("Engedélyezd a helymeghatározást a böngészőben (vagy teszteld telefonon gombnyomásra) a funkció használatához.")

                st.write("---")
                
                # --- LEZÁRÁS ---
                if st.button("✅ Cím sikeresen átadva", key=f"siker_{idx}", use_container_width=True, type="primary"):
                    st.session_state[f"kiszallitva_{idx}"] = True
                    st.toast(f"🎉 {vevo_neve} sikeresen kézbesítve!")
                    st.rerun()
            
            break
            
        else:
            st.balloons()
            st.success("🏆 Szép munka! Minden mára tervezett címet sikeresen kézbesítettél!")
            
            if st.button("🔄 Teszt adatok törlése (Újraindítás)", use_container_width=True):
                for k in list(st.session_state.keys()):
                    if "kiszallitva_" in k or "lada_szam_tarolt_" in k:
                        del st.session_state[k]
                st.rerun()

    except Exception as e:
        st.error(f"Hiba a kiszállítás futtatásakor: {e}")
