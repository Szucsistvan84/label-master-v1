# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import time
import urllib.parse
import re
from datetime import datetime
from streamlit_js_eval import get_geolocation

# --- KAPCSOLÓDÓ CACHED OLVASÓ IMPORTÁLÁSA A KVÓTAVÉDELEMHÉZ ---
from adatbazis_modul import load_sheet_data_cached, SHEET_ID_UGYFELKOR

# --- Szigorú illesztés a rendelési kódokhoz (pl: 1-A1* vagy 4-S2) ---
ORDER_PAT = r'(\d+)-([A-Z0-9*]+)'

def render_mobil_aruatvetel(client):
    """
    Ömlesztett áruátvétel oldal golyóálló Google Sheets API gyorsítótárral.
    """
    st.subheader("📦 Ömlesztett áruátvétel")
    
    futar_neve = st.session_state.get('user_nev', 'Te (Teszt Üzemmód)')
    jaratok = []
    df_sajat_raklista_init = pd.DataFrame()

    try:
        # JAVÍTÁS: Közvetlen olvasás helyett a gyorsítótárból olvassuk be a Raklistát a 429-es hibák ellen!
        df_raklista_init = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Mobil_Raklista")
        
        if not df_raklista_init.empty:
            df_raklista_init.columns = [c.strip() for c in df_raklista_init.columns]
            
            # 🔒 Szűrés a bejelentkezett futárra
            df_sajat_raklista_init = df_raklista_init[df_raklista_init['Jarat_ID / Futar'] == futar_neve]
            
            if not df_sajat_raklista_init.empty:
                jaratok = ["Mai Raklista"]
            else:
                # Tartalék terv: ha nincs még saját raklistája, a cached Adatok fület nézzük meg
                try:
                    df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
                    if not df_adatok.empty:
                        df_adatok.columns = [c.strip() for c in df_adatok.columns]
                        if 'Feldolgozó Futár' in df_adatok.columns:
                            df_szurt = df_adatok[df_adatok['Feldolgozó Futár'] == futar_neve]
                            jaratok = [str(j).strip() for j in df_szurt['Járat'].unique() if str(j).strip() != ""]
                        else:
                            jaratok = [str(j).strip() for j in df_adatok['Járat'].unique() if str(j).strip() != ""]
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
    # ÁLLAPOT 1: AZ ÁRÚÁTVÉTEL ÉS IDŐMÉRÉS ÉG EL SINCS INDÍTVA
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
                
                # Mivel írtunk a Google Sheets-be, töröljük a gyorsítótárat a friss adatokért!
                st.cache_data.clear()
                
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
                        display_szoveg = f"[{str(row['Cikkszam']).strip()} - {str(row['Etel Neve']).strip()} ({str(row['Nap']).strip()})"
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
                        if st.session_state.get('teszt_uzemmod', False):
                            st.warning("🧪 **Teszt üzemmód aktív mobilon is!** A hibabejelentést sikeresen szimuláltuk, de a Google Sheets-be (Logisztikai_Hibak) NEM mentettünk semmit.")
                        else:
                            try:
                                sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
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
                                
                                st.cache_data.clear()
                                st.success("Sikeresen rögzítve! ✅")
                            except Exception as e:
                                st.error(f"Hiba a mentésnél: {e}")
                    else:
                        st.warning("Kérlek válaszd ki az ételt!")

            st.write("---")

            # ⏱️ ÁRUÁTVÉTEL RÖGZÍTÉSE
            if st.button("⏱️ ÁRUÁTVÉTEL VÉGE (Idő rögzítése)", use_container_width=True, type="secondary", key="futar_end_btn"):
                most = datetime.now()
                end_ido = most.strftime("%H:%M:%S")
                
                try:
                    sh_master = client.open_by_key(SHEET_ID_UGYFELKOR)
                    idok_sheet = sh_master.worksheet("Mobil_Idobelyegek")
                    sor_szam = st.session_state.idobelyeg_sor_index
                    
                    if sor_szam:
                        idok_sheet.update_cell(sor_szam, 4, end_ido)
                    
                    st.cache_data.clear()
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
                st.cache_data.clear()
                st.balloons()
                st.success("Műszak sikeresen lezárva! Pihenj egyet! 😊")
                time.sleep(2.0)
                st.rerun()

def render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR):
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 1.5rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        .grouped-card {
            background-color: #FFFFFF;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            padding: 10px;
            margin-bottom: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .group-tip {
            background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%);
            border: 1px solid #FCD34D;
            color: #92400E;
            padding: 6px 10px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: bold;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .item-badge {
            display: inline-block;
            background-color: #EFF6FF;
            color: #1E40AF;
            border: 1px solid #BFDBFE;
            padding: 2px 6px;
            border-radius: 12px;
            margin: 2px;
            font-size: 11px;
            font-weight: bold;
            white-space: nowrap;
        }
        .customer-item {
            background-color: #F9FAFB;
            border: 1px solid #F3F4F6;
            border-radius: 8px;
            padding: 8px;
            margin-bottom: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown("## 2. lépés: Címke és láda rendező (Címekre szedés)")
    st.caption("💡 Pakolás fordított sorrendben! A csoportosított címeket szedd egy szatyorba.")

    if 'mobil_lada_szam' not in st.session_state: st.session_state.mobil_lada_szam = 1
    if "mutasd_bepakoltat" not in st.session_state: st.session_state.mutasd_bepakoltat = False

    col_info, col_gomb1, col_gomb2 = st.columns([1, 1.2, 1.2])
    
    with col_info:
        st.metric("📦 Aktuális:", f"{st.session_state.mobil_lada_szam}. láda")
        
    with col_gomb1:
        if st.button("➕ Következő láda", use_container_width=True, key="bepak_fofelulet_kov_lada_btn"):
            st.session_state.mobil_lada_szam += 1
            st.rerun()
            
    with col_gomb2:
        gomb_szoveg = "🔍 Rejtsd a kész" if st.session_state.mutasd_bepakoltat else "🔍 Mutasd a kész"
        if st.button(gomb_szoveg, use_container_width=True, key="bepak_fofelulet_elrejtes_btn"):
            st.session_state.mutasd_bepakoltat = not st.session_state.mutasd_bepakoltat
            st.rerun()
            
    st.write("---") 

    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        if valasztott_jaratok:
            df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok") 
            
            if not df_adatok.empty:
                df_adatok.columns = [c.strip() for c in df_adatok.columns]
                cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
                nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
                rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
                
                if 'Sorrend' not in df_adatok.columns:
                    df_adatok['Sorrend'] = range(1, len(df_adatok) + 1)
                df_adatok['Sorrend'] = pd.to_numeric(df_adatok['Sorrend'], errors='coerce').fillna(999).astype(int)

                actual_filter_routes = []
                futar_neve = st.session_state.get('user_nev', 'Szűcs István')
                futar_neve_lower = str(futar_neve).strip().lower()

                for j in valasztott_jaratok:
                    if j in ["Mai Raklista", "Nincs elérhető járat", "Alapértelmezett Járat"]:
                        if 'Feldolgozó Futár' in df_adatok.columns:
                            routes_from_data = df_adatok[df_adatok['Feldolgozó Futár'].astype(str).str.strip().str.lower() == futar_neve_lower]['Járat'].unique()
                            actual_filter_routes.extend([str(r).strip() for r in routes_from_data if str(r).strip() != "" and str(r).lower() != "nan"])
                        
                        if not actual_filter_routes:
                            actual_filter_routes.extend([str(r).strip() for r in st.session_state.get("user_jarat_lista", [])])
                    else:
                        actual_filter_routes.append(j)
                actual_filter_routes = list(set(actual_filter_routes))

                jarat_col_name = next((c for c in df_adatok.columns if 'járat' in c.lower() or 'jarat' in c.lower()), None)
                if jarat_col_name:
                    df_adatok_filtered = df_adatok[df_adatok[jarat_col_name].astype(str).str.strip().isin(actual_filter_routes)].copy()
                else:
                    df_adatok_filtered = df_adatok.copy()

                if 'Feldolgozó Futár' in df_adatok_filtered.columns:
                    df_adatok_filtered = df_adatok_filtered[df_adatok_filtered['Feldolgozó Futár'].astype(str).str.strip().str.lower() == futar_neve_lower]

                if df_adatok_filtered.empty:
                    st.info("ℹ️ Nincsenek bepakolandó címek a járatodhoz.")
                    return

                # Admin gyorstöltés panel
                if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                    with st.expander("🛠️ ADMIN TESZTELŐ PANEL (Gyors Bepakolás)", expanded=True):
                        st.markdown(f"**Kedves {futar_neve}!** Ezt a panelt csak te látod adminisztrátorként a tesztelés megkönnyítésére.")
                        
                        col_fast1, col_fast2 = st.columns(2)
                        with col_fast1:
                            if st.button("⚡ ÖSSZES CÍM BEPAKOLÁSA AZONNAL", type="primary", use_container_width=True, key="admin_fast_pack_btn"):
                                with st.spinner("⏳ Minden tétel bepakolása folyamatban..."):
                                    for idx in df_adatok_filtered.index:
                                        st.session_state[f"bepak_allapot_{idx}"] = True
                                        st.session_state[f"lada_szam_tarolt_{idx}"] = "1. láda"
                                        st.session_state[f"chk_{idx}"] = True
                                        st.session_state[f"kiszallitva_{idx}"] = False
                                        st.session_state[f"kiszallitott_statusz_{idx}"] = "Folyamatban"
                                        st.session_state[f"borravalo_{idx}"] = 0
                                        if f"atvett_input_{idx}" in st.session_state:
                                            st.session_state[f"atvett_input_{idx}"] = 0
                                            
                                    st.session_state.kiszallitas_folyamatban = True
                                    st.session_state['futar_borravalo'] = 0
                                    
                                    if not st.session_state.get('teszt_uzemmod', False):
                                        try:
                                            kivalasztott = st.session_state.get('kivalasztott_datum', datetime.today().date())
                                            api_datum_kulcs = kivalasztott.strftime("%Y-%m-%d") if isinstance(kivalasztott, datetime.date) else str(kivalasztott)
                                            sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
                                            ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary")
                                            summary_records = ws_summary.get_all_records()
                                            
                                            futar_keresett_clean = str(futar_neve).strip().lower()
                                            existing_row_index = None
                                            for r_idx, row in enumerate(summary_records, start=2):
                                                r_date_str = str(row.get('Datum', '')).strip()
                                                r_futar = str(row.get('Futar', '')).strip().lower()
                                                if r_date_str == api_datum_kulcs and (r_futar == futar_keresett_clean or r_futar == "szűcs istván"):
                                                    existing_row_index = r_idx
                                                    break
                                            
                                            if existing_row_index:
                                                ws_summary.update_cell(existing_row_index, 8, 0)
                                                ws_summary.update_cell(existing_row_index, 9, 0)
                                                st.cache_data.clear()
                                        except Exception as e_sh_reset:
                                            st.write(f"⚠️ Nem sikerült a Google Sheets valós idejű szinkronizációja: {e_sh_reset}")
                                            
                                    st.success("🎉 Összes tétel sikeresen bepakolva az 1. lábába! Indulhat a kiszállítás!")
                                    time.sleep(1.0)
                                    st.rerun()
                        with col_fast2:
                            if st.button("🧹 BEPAKOLÁSOK RESETÁLÁSA", type="secondary", use_container_width=True, key="admin_fast_reset_btn"):
                                for idx in df_adatok_filtered.index:
                                    st.session_state[f"bepak_allapot_{idx}"] = False
                                    st.session_state[f"lada_szam_tarolt_{idx}"] = None
                                    st.session_state[f"chk_{idx}"] = False
                                    st.session_state[f"kiszallitva_{idx}"] = False
                                    st.session_state[f"kiszallitott_statusz_{idx}"] = "Folyamatban"
                                    st.session_state[f"borravalo_{idx}"] = 0
                                    if f"atvett_input_{idx}" in st.session_state:
                                        st.session_state[f"atvett_input_{idx}"] = 0
                                        
                                st.session_state.kiszallitas_folyamatban = False
                                st.session_state['futar_borravalo'] = 0
                                
                                if not st.session_state.get('teszt_uzemmod', False):
                                    try:
                                        kivalasztott = st.session_state.get('kivalasztott_datum', datetime.today().date())
                                        api_datum_kulcs = kivalasztott.strftime("%Y-%m-%d") if isinstance(kivalasztott, datetime.date) else str(kivalasztott)
                                        sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
                                        ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary")
                                        summary_records = ws_summary.get_all_records()
                                        
                                        futar_keresett_clean = str(futar_neve).strip().lower()
                                        existing_row_index = None
                                        for r_idx, row in enumerate(summary_records, start=2):
                                            r_date_str = str(row.get('Datum', '')).strip()
                                            r_futar = str(row.get('Futar', '')).strip().lower()
                                            if r_date_str == api_datum_kulcs and (r_futar == futar_keresett_clean or r_futar == "szűcs istván"):
                                                existing_row_index = r_idx
                                                break
                                        
                                        if existing_row_index:
                                            ws_summary.update_cell(existing_row_index, 8, 0)
                                            ws_summary.update_cell(existing_row_index, 9, 0)
                                            st.cache_data.clear()
                                    except Exception as e_sh_reset:
                                        st.write(f"⚠️ Nem sikerült a Google Sheets valós idejű szinkronizációja: {e_sh_reset}")
                                        
                                st.warning("🧹 Minden korábbi bepakolás sikeresen kiürítve!")
                                time.sleep(1.0)
                                st.rerun()
                        st.write("")

                addr_max_sorrend = df_adatok_filtered.groupby(cim_oszlop)['Sorrend'].max().reset_index()
                addr_max_sorrend = addr_max_sorrend.sort_values(by='Sorrend', ascending=False)
                rendezett_cimek = addr_max_sorrend[cim_oszlop].tolist()

                def log_lada():
                    # Segédfüggvény a ládázáshoz, ami rögzíti a megállók állapotát
                    for row_idx in df_adatok_filtered.index:
                        bep_k = f"bepak_allapot_{row_idx}"
                        chk_k = f"chk_{row_idx}"
                        lada_k = f"lada_szam_tarolt_{row_idx}"
                        if st.session_state.get(chk_k, False):
                            if not st.session_state.get(bep_k, False):
                                st.session_state[bep_k] = True
                                st.session_state[lada_k] = f"{st.session_state.mobil_lada_szam}. láda"
                        else:
                            if st.session_state.get(bep_k, False):
                                st.session_state[bep_k] = False
                                st.session_state[lada_k] = None

                @st.fragment
                def render_kartyak(df_lista, cimek):
                    for addr_idx, addr in enumerate(cimek):
                        df_addr = df_lista[df_lista[cim_oszlop] == addr].sort_values(by='Sorrend', ascending=False)
                        
                        show_card = False
                        for idx, row in df_addr.iterrows():
                            bepakolt_kulcs = f"bepak_allapot_{idx}"
                            lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"
                            
                            if bepakolt_kulcs not in st.session_state:
                                st.session_state[bepakolt_kulcs] = False
                            if lada_tarolt_kulcs not in st.session_state:
                                st.session_state[lada_tarolt_kulcs] = None
                            
                            if not st.session_state[bepakolt_kulcs] or st.session_state.mutasd_bepakoltat:
                                show_card = True

                        if not show_card:
                            continue

                        st.markdown(f"""
                        <div class="grouped-card">
                            <div style="font-size: 16px; font-weight: bold; color: #1E3A8A; margin-bottom: 4px;">📍 Megálló: {addr}</div>
                        """, unsafe_allow_html=True)

                        if len(df_addr) > 1:
                            st.markdown(f"""
                            <div class="group-tip">
                                💡 Tipp: Erre a címre {len(df_addr)} db rendelés megy! Szedheted őket egy közös szatyorba.
                            </div>
                            """, unsafe_allow_html=True)

                        for idx, row in df_addr.iterrows():
                            vevo_nev = str(row[nev_oszlop]).strip()
                            címke_szama = row['Sorrend']
                            megj = str(row.get('Megjegyzés', '')).strip()
                            rendeles_val = str(row[rendeles_oszlop]).strip() if rendeles_oszlop else ""
                            
                            tetel_darabszam = 0
                            found_items_count = re.findall(ORDER_PAT, rendeles_val)
                            if found_items_count:
                                tetel_darabszam = sum(int(qty) for qty, _ in found_items_count)
                            else:
                                tetel_darabszam = 1 if rendeles_val != "" and rendeles_val.lower() != "nan" else 0

                            st.markdown(f"""
                            <div class="customer-item">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                    <span style="font-size: 13.5px; font-weight: bold; color: #374151;">👤 {vevo_nev}</span>
                                    <span style="font-size: 11.5px; background-color: #E5E7EB; color: #374151; padding: 2px 6px; border-radius: 6px; font-weight: bold;">
                                        🏷️ Címke #{címke_szama} | 📦 {tetel_darabszam} db
                                    </span>
                                </div>
                            """, unsafe_allow_html=True)

                            if megj and megj != "nan" and megj != "":
                                st.markdown(f'<div style="font-size: 11.5px; color: #D97706; font-style: italic; margin-bottom: 4px;">📝 Megjegyzés: {megj}</div>', unsafe_allow_html=True)

                            day_parts = rendeles_val.split('|')
                            for part in day_parts:
                                part = part.strip()
                                if not part: continue
                                
                                is_szombat = "Szo:" in part or "Szombat:" in part
                                day_title = ""
                                if "Hé:" in part: day_title = "🗓️ Hétfő:"
                                elif "Ke:" in part: day_title = "🗓️ Kedd:"
                                elif "Sze:" in part: day_title = "🗓️ Szerda:"
                                elif "Csü:" in part: day_title = "🗓️ Csütörtök:"
                                elif "Pé:" in part: day_title = "🗓️ Péntek:"
                                elif "Szo:" in part: day_title = "📆 Szombat (Hétvége):"
                                
                                if day_title:
                                    style_szoveg = "color: #DC2626; font-weight: bold;" if is_szombat else "color: #4B5563; font-weight: 500;"
                                    st.markdown(f'<div style="font-size: 11.5px; {style_szoveg} margin-top: 4px; margin-bottom: 2px;">{day_title}</div>', unsafe_allow_html=True)

                                found_items = re.findall(ORDER_PAT, part)
                                if found_items:
                                    badges_html = '<div style="margin-top: 2px; margin-bottom: 4px; display: flex; flex-wrap: wrap;">'
                                    for qty, code in found_items:
                                        style_kaja = "font-weight: 900; background-color: #FEF2F2; color: #991B1B; border: 1px solid #FCA5A5;" if is_szombat else "font-weight: normal; background-color: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE;"
                                        badges_html += f'<span class="item-badge" style="{style_kaja}">{qty}x {code}</span>'
                                    badges_html += '</div>'
                                    st.markdown(badges_html, unsafe_allow_html=True)
                                elif part and part != "nan" and part != "":
                                    style_plain = "font-weight: bold; color: #991B1B;" if is_szombat else "font-weight: normal; color: #4B5563;"
                                    st.markdown(f'<div style="font-size: 12px; {style_plain}">📋 {part}</div>', unsafe_allow_html=True)

                            st.markdown('</div>', unsafe_allow_html=True)

                            bepakolt_kulcs = f"bepak_allapot_{idx}"
                            lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"

                            if bepakolt_kulcs not in st.session_state:
                                st.session_state[bepakolt_kulcs] = False
                            if lada_tarolt_kulcs not in st.session_state:
                                st.session_state[lada_tarolt_kulcs] = None

                            tarolt_lada_ertek = st.session_state.get(lada_tarolt_kulcs, None)
                            label_text = f"🟢 Bepakolva ide: {tarolt_lada_ertek}" if tarolt_lada_ertek else f"⚪ Bepakolás a ládába ({vevo_nev})"
                            
                            st.toggle(label_text, value=st.session_state[bepakolt_kulcs], key=f"chk_{idx}", on_change=log_lada)
                            st.write("")

                        st.markdown('</div>', unsafe_allow_html=True)
                        st.write("---")

                render_kartyak(df_adatok_filtered, rendezett_cimek)
                
                st.write("")
                st.write("---")
                st.subheader("🏁 Bepakolás Lezárása")
                st.info("Ha minden címet berendeztél a ládákba, zárd le a fázist az induláshoz!")
                
                if st.button("📦 LÁDÁZÁS ÉS BEPAKOLÁS KÉSZ (Indulás)", use_container_width=True, type="primary", key="futar_bepakolas_kesz_btn"):
                    st.session_state.kiszallitas_folyamatban = True
                    
                    if st.session_state.get('teszt_uzemmod', False) or st.query_params.get("test", "false") == "true":
                        st.warning("🧪 **Teszt üzemmód aktív!** A bepakolás lezárását sikeresen szimuláltuk. A Google Sheets-be NEM mentettünk időbélyeget.")
                        time.sleep(2.0)
                        st.rerun()
                    else:
                        try:
                            sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
                            idok_sheet = sh_ugyfelkor.worksheet("Mobil_Idobelyegek")
                            
                            most = datetime.now()
                            bepakolas_vege_ido = most.strftime("%H:%M:%S")
                            mai_datum = most.strftime("%Y-%m-%d")
                            futar_neve = st.session_state.get('user_nev', 'Ismeretlen Futár')
                            jarat_szoveg = ", ".join(map(str, valasztott_jaratok))
                            
                            sor_szam = st.session_state.get('idobelyeg_sor_index')
                            if sor_szam:
                                idok_sheet.update_cell(sor_szam, 6, bepakolas_vege_ido)
                            else:
                                idok_sheet.append_row([mai_datum, jarat_szoveg, futar_neve, "", bepakolas_vege_ido])
                            
                            st.success(f"🎉 Bepakolás lezárva ({bepakolas_vege_ido})! Jó utat kívánunk! 🚚")
                            time.sleep(1.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Hiba az éles időbélyeg mentésekor: {e}")
                            time.sleep(2.0)
                            st.rerun()
                            
            else:
                st.error("Az Adatok munkalap üres!")
        else:
            st.info("ℹ️ Válaszd ki a járatodat az 1. fülön!")
    except Exception as e:
        st.error(f"Hiba a betöltéskor: {e}")

def render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR):
    """
    Kiszállítás nézet golyóálló, teljes képernyős (Immersive) üzemmóddal,
    zéró-görgetéses elrendezéssel és letisztult dizájnnal.
    """
    if "kiszallitas_aktiv_fullscreen" not in st.session_state:
        st.session_state.kiszallitas_aktiv_fullscreen = False

    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        if not valasztott_jaratok:
            st.info("ℹ️ Válaszd ki a járatodat az 1. fülön!")
            return

        df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
        
        if df_adatok.empty:
            st.error("Az Adatok munkalap üres!")
            return

        df_adatok.columns = [c.strip() for c in df_adatok.columns]
        cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
        nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
        tel_oszlop = 'Telefon' if 'Telefon' in df_adatok.columns else 'Tel'
        rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
        
        penz_oszlop = None
        for c in df_adatok.columns:
            if 'pénz' in c.lower() or 'penz' in c.lower() or 'fizet' in c.lower() or 'tartozas' in c.lower() or 'összeg' in c.lower():
                penz_oszlop = c
                break

        lat_oszlop = 'Latitude' if 'Latitude' in df_adatok.columns else 'Lat'
        lon_oszlop = 'Longitude' if 'Longitude' in df_adatok.columns else 'Lon'

        actual_filter_routes = []
        futar_neve = st.session_state.get('user_nev', 'Szűcs István')
        futar_neve_lower = str(futar_neve).strip().lower()

        for j in valasztott_jaratok:
            if j in ["Mai Raklista", "Nincs elérhető járat", "Alapértelmezett Járat"]:
                if 'Feldolgozó Futár' in df_adatok.columns:
                    routes_from_data = df_adatok[df_adatok['Feldolgozó Futár'].astype(str).str.strip().str.lower() == futar_neve_lower]['Járat'].unique()
                    actual_filter_routes.extend([str(r).strip() for r in routes_from_data if str(r).strip() != "" and str(r).lower() != "nan"])
                if not actual_filter_routes:
                    actual_filter_routes.extend([str(r).strip() for r in st.session_state.get("user_jarat_lista", [])])
            else:
                actual_filter_routes.append(j)
        actual_filter_routes = list(set(actual_filter_routes))

        jarat_col_name = next((c for c in df_adatok.columns if 'járat' in c.lower() or 'jarat' in c.lower()), None)
        if jarat_col_name:
            df_kiszallitas = df_adatok[df_adatok[jarat_col_name].astype(str).str.strip().isin(actual_filter_routes)].copy()
        else:
            df_kiszallitas = df_adatok.copy()

        if 'Feldolgozó Futár' in df_kiszallitas.columns:
            df_kiszallitas = df_kiszallitas[df_kiszallitas['Feldolgozó Futár'].astype(str).str.strip().str.lower() == futar_neve_lower]

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

        # Normal view
        if not st.session_state.kiszallitas_aktiv_fullscreen:
            st.markdown("## 🚚 3. lépés: Kiszállítás és Elszámolás")
            
            live_kesz_cimek_count = sum(1 for idx, _ in bepakolt_sorok if st.session_state.get(f"kiszallitva_{idx}", False))
            st.info(f"📋 **Állapot jelentés:**\n* Bepakolt címek száma: **{osszes_bepakolt} megálló**\n* Már teljesített: **{live_kesz_cimek_count} megálló**")
            
            st.write("")
            if st.button("▶️ KISZÁLLÍTÁS MEGKEZDÉSE (Teljes Képernyő)", type="primary", use_container_width=True, key="start_kiszallitas_fullscreen_btn"):
                st.session_state.kiszallitas_aktiv_fullscreen = True
                st.rerun()
                
            st.write("---")
            return

        # Immersive view
        st.markdown(
            """
            <style>
            header[data-testid="stHeader"] { display: none !important; }
            div[data-testid="stTabBar"] { display: none !important; }
            div.block-container {
                padding-top: 0.2rem !important;
                padding-bottom: 0.2rem !important;
                padding-left: 0.4rem !important;
                padding-right: 0.4rem !important;
            }
            h1, h2 { display: none !important; }
            </style>
            """,
            unsafe_allow_html=True
        )

        col_status, col_exit = st.columns([3, 1.2])
        with col_status:
            st.markdown(
                f"""
                <div style="display: flex; gap: 8px; align-items: center; height: 100%;">
                    <span style="font-size: 15px; font-weight: 800; color: #1E3A8A; background-color: #EFF6FF; border: 1px solid #BFDBFE; padding: 4px 10px; border-radius: 8px;">
                        🚗 Cím: {kesz_cimek + 1}/{osszes_bepakolt}
                    </span>
                </div>
                """, 
                unsafe_allow_html=True
            )
        with col_exit:
            if st.button("⏸️ Normál", key="exit_fullscreen_active_btn", use_container_width=True):
                st.session_state.kiszallitas_aktiv_fullscreen = False
                st.rerun()

        with st.sidebar:
            st.markdown("### 📊 Mai folyamat")
            haladas_szazalek = kesz_cimek / osszes_bepakolt if osszes_bepakolt > 0 else 0
            st.progress(haladas_szazalek)
            st.metric("Kézbesítve:", f"{kesz_cimek} / {osszes_bepakolt} megálló")
            
            aktualis_napi_borravalo = sum(int(st.session_state.get(f"borravalo_{idx}", 0)) for idx, _ in bepakolt_sorok)
            st.metric("Gyűjtött borravaló eddig:", f"{aktualis_napi_borravalo:,} Ft")
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

            st.markdown(
                f"""
                <div style="background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%); border: 1.5px solid #93C5FD; border-radius: 12px; padding: 8px 12px; margin-bottom: 6px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 13.5px; font-weight: bold; color: #1E40AF; background-color: #FFFFFF; padding: 2px 8px; border-radius: 6px; border: 1.2px solid #BFDBFE;">
                            📍 {sorszam}. Megálló — {melyik_lada}
                        </span>
                    </div>
                    <div style="font-size: 17.5px; font-weight: 900; color: #111827; margin-top: 4px;">👤 {vevo_neve}</div>
                    <div style="font-size: 14px; font-weight: bold; color: #374151; margin-top: 2px; line-height: 1.15;">🏠 {aktualis_cim}</div>
                </div>
                """, 
                unsafe_allow_html=True
            )

            if aktualis_megj and aktualis_megj != "nan" and aktualis_megj != "": 
                st.markdown(
                    f"""
                    <div style="background-color: #FFFBEB; border: 1.2px solid #FCD34D; color: #92400E; padding: 4px 10px; border-radius: 8px; font-size: 12px; margin-bottom: 6px; font-weight: bold;">
                        📝 <b>Megjegyzés:</b> {aktualis_megj}
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
            
            if rendeles_oszlop and str(row[rendeles_oszlop]).strip() != "" and str(row[rendeles_oszlop]).strip() != "nan":
                day_parts = str(row[rendeles_oszlop]).strip().split('|')
                for part in day_parts:
                    part = part.strip()
                    if not part: continue
                    
                    is_szombat = "Szo:" in part or "Szombat:" in part
                    day_title = ""
                    if "Hé:" in part: day_title = "🗓️ Hétfő:"
                    elif "Ke:" in part: day_title = "🗓️ Kedd:"
                    elif "Sze:" in part: day_title = "🗓️ Szerda:"
                    elif "Csü:" in part: day_title = "🗓️ Csütörtök:"
                    elif "Pé:" in part: day_title = "🗓️ Péntek:"
                    elif "Szo:" in part: day_title = "📆 Szombat (Hétvége):"
                    
                    if day_title:
                        style_szoveg = "color: #DC2626; font-weight: bold;" if is_szombat else "color: #4B5563; font-weight: bold;"
                        st.markdown(f'<div style="font-size: 11px; {style_szoveg} margin-top: 2px; margin-bottom: 1px;">{day_title}</div>', unsafe_allow_html=True)
                        
                    found_items = re.findall(ORDER_PAT, part)
                    if found_items:
                        badges_html = '<div style="margin-top: 1px; margin-bottom: 3px; display: flex; flex-wrap: wrap;">'
                        for qty, code in found_items:
                            style_kaja = "font-weight: 900; background-color: #FEF2F2; color: #991B1B; border: 1px solid #FCA5A5; font-size: 11.5px;" if is_szombat else "font-weight: normal; background-color: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE; font-size: 11.5px;"
                            badges_html += f'<span class="item-badge" style="{style_kaja}">{qty}x {code}</span>'
                        badges_html += '</div>'
                        st.markdown(badges_html, unsafe_allow_html=True)
                    elif part and part != "nan" and part != "":
                        style_plain = "font-weight: bold; color: #991B1B; font-size: 11.5px;" if is_szombat else "font-weight: normal; color: #4B5563; font-size: 11.5px;"
                        st.markdown(f'<div style="font-size: 11.5px; {style_plain}">📋 {part}</div>', unsafe_allow_html=True)
            
            # --- 🗺️ GOLYÓÁLLÓ OPENSTREETMAP EMBED MOBILRA ---
            if saved_lat and saved_lon and saved_lat != "nan" and saved_lon != "nan":
                # Ha van GPS koordináta, az OSM export linkjét használjuk tiszta HTTPS-en, fix piros markerrel!
                lat_f = float(saved_lat)
                lon_f = float(saved_lon)
                # Kiszámolunk egy finom ablakot a pont köré (kb. zoom 16-os szint)
                delta = 0.003
                embed_url = f"https://www.openstreetmap.org/export/embed.html?bbox={lon_f-delta}%2C{lat_f-delta}%2C{lon_f+delta}%2C{lat_f+delta}&layer=mapnik&marker={lat_f}%2C{lon_f}"
            else:
                # Fallback: ha csak cím van, a Google tiszta HTTPS beágyazó linkjét hívjuk meg
                encoded_nav = urllib.parse.quote(f"{aktualis_cim}, Debrecen, Hungary")
                embed_url = f"https://maps.google.com/maps?q={encoded_nav}&t=&z=16&ie=UTF8&iwloc=&output=embed"
            
            # --- TISZTÍTOTT, SÁVMENTES IFRAME MEGJELENÍTÉS ---
            html_tisztitott_map = f"""
            <div style="width: 100%; height: 150px; overflow: hidden; border-radius: 10px; border: 1.5px solid #93C5FD;">
                <iframe 
                    width="100%" 
                    height="190px" 
                    src="{embed_url}" 
                    frameborder="0" 
                    scrolling="no" 
                    marginheight="0" 
                    marginwidth="0" 
                    style="margin-bottom: -40px; border: none;">
                </iframe>
            </div>
            """
            
            # Megjelenítés a Streamlit komponensben
            st.components.v1.html(html_tisztitott_map, height=160)

            col_tel, col_gps = st.columns(2)
            
            with col_tel:
                if vevo_tel and vevo_tel != "nan":
                    st.markdown(
                        f'<a href="tel:{vevo_tel}" target="_blank">'
                        f'<button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:8px; font-weight:bold; font-size:14.5px; cursor:pointer;">'
                        f'📞 Telefonos Hívás'
                        f'</button></a>', unsafe_allow_html=True
                    )
                else:
                    st.button("📞 Nincs telefonszám", disabled=True, use_container_width=True)
                    
            with col_gps:
                nav_target = f"{saved_lat},{saved_lon}" if (saved_lat and saved_lon and saved_lat != "nan") else aktualis_cim
                encoded_nav = urllib.parse.quote(nav_target)
                maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_nav}"
                
                st.markdown(
                    f'<a href="{maps_url}" target="_blank">'
                    f'<button style="width:100%; height:38px; background-color:#4285F4; color:white; border:none; border-radius:8px; font-weight:bold; font-size:14.5px; cursor:pointer;">'
                    f'🗺️ GPS Navigáció'
                    f'</button></a>', unsafe_allow_html=True
                )

            # ==============================================================================
            # 🎯 KAPU RÖGZÍTÉS ÉS DUPLÁZOTT ÉLES SZINKRONIZÁCIÓ (Napi + Törzs Ugyfelkor!)
            # ==============================================================================
            with st.expander("🎯 Kapu rögzítése (GPS koordináta)"):
                loc = get_geolocation()
                if loc and 'coords' in loc:
                    curr_lat = loc['coords']['latitude']
                    curr_lon = loc['coords']['longitude']
                    st.info(f"Észlelt GPS koordináta: `{curr_lat}, {curr_lon}`")
                    
                    if st.button("💾 Új koordináta elmentése", key=f"save_geo_{idx}", use_container_width=True):
                        try:
                            sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                            
                            # 1. MENTÉS AZ ADATOK TÁBLÁBA (Napi futó lista)
                            ws_adatok = sh.worksheet("Adatok")
                            headers_adatok = ws_adatok.row_values(1)
                            lat_col_idx = headers_adatok.index(lat_oszlop) + 1
                            lon_col_idx = headers_adatok.index(lon_oszlop) + 1
                            sheet_row = int(idx) + 2
                            ws_adatok.update_cell(sheet_row, lat_col_idx, curr_lat)
                            ws_adatok.update_cell(sheet_row, lon_col_idx, curr_lon)
                            
                            # 2. MENTÉS AZ UGYFELKOR TÖRZSTÁBLÁBA (Örökre!)
                            customer_id = str(row['ID']).strip()
                            ws_ugyfelkor = sh.worksheet("Ugyfelkor")
                            ugyfel_records = ws_ugyfelkor.get_all_records()
                            
                            ugyfel_row_idx = None
                            for u_idx, u_rec in enumerate(ugyfel_records, start=2):
                                rec_id = str(u_rec.get('ID', '')).strip().split('.')[0]
                                if rec_id == customer_id:
                                    ugyfel_row_idx = u_idx
                                    break
                            
                            if ugyfel_row_idx:
                                ugyfel_headers = ws_ugyfelkor.row_values(1)
                                u_lat_idx = ugyfel_headers.index('Lat') + 1
                                u_lon_idx = ugyfel_headers.index('Lon') + 1
                                ws_ugyfelkor.update_cell(ugyfel_row_idx, u_lat_idx, f"'{curr_lat}")
                                ws_ugyfelkor.update_cell(ugyfel_row_idx, u_lon_idx, f"'{curr_lon}")
                                st.toast("🎯 GPS koordináta szinkronizálva az Ügyfélkör törzsadatbázisba is!")
                            
                            st.cache_data.clear()
                            st.success("🎯 Pozíció sikeresen elmentve mindkét adatbázisba!")
                            st.rerun()
                        except Exception as geo_err:
                            st.error(f"Sheets írási hiba: {geo_err}")
                else:
                    st.caption("⏳ Várakozás valós GPS jelre...")

            # Fizetés
            elovart_osszeg = 0
            if penz_oszlop:
                nyers_penz = str(row[penz_oszlop]).replace("Ft", "").replace(" ", "").replace("\xa0", "").strip()
                try:
                    elovart_osszeg = int(pd.to_numeric(nyers_penz, errors='coerce'))
                except:
                    elovart_osszeg = 0
            
            if elovart_osszeg > 0:
                st.markdown(f"💵 <b>Fizetendő összeg:</b> <span style='font-size:15px; color:#DC2626; font-weight:bold;'>{elovart_osszeg:,} Ft</span>", unsafe_allow_html=True)
            else:
                st.markdown("💵 <b>Fizetendő összeg:</b> <span style='color:#10B981; font-weight:bold; font-size:14.5px;'>Előre fizetve (0 Ft)</span>", unsafe_allow_html=True)
            
            atvett_osszeg = st.number_input(
                "💰 Ügyféltől átvett készpénz (Ft):",
                min_value=0,
                value=int(elovart_osszeg),
                step=50,
                key=f"atvett_input_{idx}",
                label_visibility="collapsed"
            )
            
            szamitott_borravalo = 0
            if atvett_osszeg > elovart_osszeg:
                szamitott_borravalo = atvett_osszeg - elovart_osszeg
                st.success(f"➕ Borravaló: **{szamitott_borravalo:,} Ft**")
            elif atvett_osszeg < elovart_osszeg and atvett_osszeg > 0:
                st.warning(f"⚠️ {elovart_osszeg - atvett_osszeg:,} Ft hiány!")

            if st.button("✅ Cím sikeresen átadva (Kézbesítve)", key=f"siker_{idx}", use_container_width=True, type="primary"):
                st.session_state[f"borravalo_{idx}"] = szamitott_borravalo
                st.session_state[f"kiszallitva_{idx}"] = True
                st.session_state[f"kiszallitott_statusz_{idx}"] = "Sikeres"
                
                if not st.session_state.get('teszt_uzemmod', False):
                    try:
                        osszes_beszedett_kp_most = 0
                        osszes_borravalo_most = 0
                        for k in list(st.session_state.keys()):
                            if k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres":
                                live_idx = k.split("_")[-1]
                                try:
                                    osszes_beszedett_kp_most += int(st.session_state.get(f"atvett_input_{live_idx}", 0))
                                    osszes_borravalo_most += int(st.session_state.get(f"borravalo_{live_idx}", 0))
                                except:
                                    pass
                        
                        kivalasztott = st.session_state.get('kivalasztott_datum', datetime.today().date())
                        api_datum_kulcs = kivalasztott.strftime("%Y-%m-%d") if isinstance(kivalasztott, datetime.date) else str(kivalasztott)
                        
                        sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
                        ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary")
                        summary_records = ws_summary.get_all_records()
                        
                        futar_keresett_clean = str(futar_neve).strip().lower()
                        existing_row_index = None
                        for r_idx, row in enumerate(summary_records, start=2):
                            r_date_str = str(row.get('Datum', '')).strip()
                            r_futar = str(row.get('Futar', '')).strip().lower()
                            if r_date_str == api_datum_kulcs and (r_futar == futar_keresett_clean or r_futar == "szűcs istván"):
                                existing_row_index = r_idx
                                break
                        
                        if existing_row_index:
                            ws_summary.update_cell(existing_row_index, 8, osszes_beszedett_kp_most)
                            ws_summary.update_cell(existing_row_index, 9, osszes_borravalo_most)
                            st.cache_data.clear()
                            st.toast("☁️ Pénzügyi adatok élőben szinkronizálva a felhőbe!")
                    except Exception as e_live_sync:
                        st.write(f"⚠️ Nem sikerült a Google Sheets valós idejű szinkronizációja: {e_live_sync}")
                
                st.toast(f"🎉 {vevo_neve} sikeresen kézbesítve!")
                st.rerun()
            
            break
            
        else:
            teljes_napi_borravalo = sum(int(st.session_state.get(f"borravalo_{idx}", 0)) for idx, _ in bepakolt_sorok)
            st.session_state['futar_borravalo'] = teljes_napi_borravalo
            
            st.balloons()
            st.success(f"🏆 Szép munka! Minden mára tervezett címet sikeresen kézbesítettél!")
            st.info(f"💰 A mai napon összegyűjtött összes borravalód: **{teljes_napi_borravalo:,} Ft**, ez automatikusan elmentésre került!")
            
            if st.button("🔄 Teszt adatok törlése (Újraindítás)", use_container_width=True):
                for k in list(st.session_state.keys()):
                    if "kiszallitva_" in k or "lada_szam_tarolt_" in k or "borravalo_" in k or "atvett_input_" in k or "kiszallitott_statusz_" in k:
                        del st.session_state[k]
                st.session_state['futar_borravalo'] = 0
                st.session_state.kiszallitas_folyamatban = False
                st.session_state.kiszallitas_aktiv_fullscreen = False
                st.rerun()

    except Exception as e:
        st.error(f"Hiba a kiszállítás futtatásakor: {e}")
