# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import time
import json
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
    INTELLIGENS FALLBACK MOTOR: Ha a Mobil_Raklista üres (aggregációs hiba), 
    az Adatok fülből élőben építi fel az ömlesztett darabszámokat, így a futár SOHA nem akad el!
    """
    st.subheader("📦 Ömlesztett áruátvétel")
    
    futar_neve = st.session_state.get('user_nev', 'Te (Teszt Üzemmód)')
    f_clean = str(futar_neve).strip().lower()
    
    # 1. JÁRATVÁLASZTÓ KINYERÉSE (Ha még nincs sessionben, Adatok alapján inicializáljuk)
    jaratok = []
    try:
        df_adatok_init = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
        if not df_adatok_init.empty:
            df_adatok_init.columns = [c.strip() for c in df_adatok_init.columns]
            
            if 'Feldolgozó Futár' in df_adatok_init.columns:
                # JAVÍTÁS: Név helyett itt is a hivatalos szerepkört ellenőrizzük (Profi verzió)
                if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                    jaratok = [str(j).strip() for j in df_adatok_init['Járat'].unique() if str(j).strip() != "" and str(j).lower() != "nan"]
                else:
                    f_clean = str(futar_neve).strip().lower()
                    df_szurt = df_adatok_init[df_adatok_init['Feldolgozó Futár'].astype(str).str.strip().str.lower() == f_clean]
                    jaratok = [str(j).strip() for j in df_szurt['Járat'].unique() if str(j).strip() != ""]
            else:
                jaratok = [str(j).strip() for j in df_adatok_init['Járat'].unique() if str(j).strip() != ""]
    except:
        jaratok = ["Alapértelmezett Járat"]

    if not jaratok: jaratok = ["Nincs elérhető járat"]

    if "mob_jarat_select" not in st.session_state:
        st.session_state.mob_jarat_select = [jaratok[0]]

    valasztott_jaratok = st.multiselect(
        "Válaszd ki a mai járataidat:", 
        options=jaratok,
        default=st.session_state.mob_jarat_select,
        key="mob_jarat_select_live"
    )
    st.session_state.mob_jarat_select = valasztott_jaratok

    if not valasztott_jaratok:
        st.warning("⚠️ Kérlek, válassz ki legalább egy járatot a folytatáshoz!")
        return

    st.write("---")

    if "aruatvetel_folyamatban" not in st.session_state:
        st.session_state.aruatvetel_folyamatban = False
    if "idobelyeg_sor_index" not in st.session_state:
        st.session_state.idobelyeg_sor_index = None

    # --- 🛠️ ADMIN SEBESSÉGI PANEL (Gyors átugrás teszteléshez) ---
    if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
        with st.expander("🛠️ ADMIN TESZTELŐ PANEL (Gyors Áruátvétel)", expanded=False):
            if st.button("⚡ ÖSSZES ÉTEL ÁTVÉTELE ÉS TOVÁBBLÉPÉS", type="primary", use_container_width=True, key="admin_fast_aruatvetel_btn"):
                st.session_state.aruatvetel_folyamatban = True
                st.session_state.current_mobile_tab_state = "2. Címekre szedés 📥"
                st.toast("🚀 Áruátvétel szimulálva!")
                time.sleep(0.5)
                st.rerun()

    # =========================================================================
    # ÁLLAPOT 1: INICIALIZÁLÁS ÉS START
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
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Hiba az időbélyeg írásakor: {e}")
    
    # =========================================================================
    # ÁLLAPOT 2: CKK-LISTA MEGJELENÍTÉSE (FELHŐS VAGY MOCK LIVE)
    # =========================================================================
    else:
        jaratok_szoveg = ", ".join(map(str, valasztott_jaratok))
        if not st.session_state.get("kiszallitas_folyamatban", False):
            st.warning(f"🔄 Áruátvétel és depózás folyamatban... ({jaratok_szoveg})")
            st.markdown("## 1. lépés: Ömlesztett áruátvétel")
            
            # Megpróbáljuk betölteni a gyári konyhai listát
            df_raklista_init = pd.DataFrame()
            try:
                df_raklista_init = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Mobil_Raklista")
            except: pass
            
            # --- 🛰️ JOGOSULTSÁG ALAPÚ HELYETTESÍTÉSI MOTOR (PROFI VERZIÓ) ---
            df_sajat_raklista = pd.DataFrame()
            if df_raklista_init is not None and not df_raklista_init.empty:
                df_raklista_init.columns = [c.strip() for c in df_raklista_init.columns]
                
                # Ha a bejelentkezett felhasználó admin vagy superadmin, átengedjük
                if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                    df_sajat_raklista = df_raklista_init.copy()
                else:
                    # Normál futár: szigorú név-egyezés az eredeti logikád szerint
                    f_clean = str(futar_neve).strip().lower()
                    df_sajat_raklista = df_raklista_init[df_raklista_init['Jarat_ID / Futar'].astype(str).str.strip().str.lower() == f_clean]

            # 🚨 🛰️ VÉSZHELYZETI ENGINE: HA AZ ASZTALI KÓD MIATT ÜRES A RAKLISTA, ÉLŐBEN GENERÁLJUK!
            if df_sajat_raklista.empty:
                st.caption("⚠️ *Konyhai Mobil_Raklista üres. Biztonsági Fallback motor indul: Élő összesítés az Adatok fülből...*")
                df_adatok = st.session_state.get('mdf', pd.DataFrame())
                if df_adatok.empty:
                    df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
                
                if not df_adatok.empty:
                    df_adatok.columns = [c.strip() for c in df_adatok.columns]
                    rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
                    
                    # Csak a kiválasztott járatok rendeléseit összegezzük
                    df_jarat_adatok = df_adatok[df_adatok['Járat'].astype(str).str.strip().isin(valasztott_jaratok)]
                    
                    live_counts = {}
                    if rendeles_oszlop:
                        for _, row in df_jarat_adatok.iterrows():
                            r_val = str(row[rendeles_oszlop]).strip()
                            for qty, code in re.findall(ORDER_PAT, r_val):
                                live_counts[code] = live_counts.get(code, 0) + int(qty)
                    
                    if live_counts:
                        mock_rows = []
                        for code, total_qty in live_counts.items():
                            mock_rows.append({
                                "Terv_Darabszam": total_qty,
                                "Etel Neve": f"Étel kód: {code} (Élőben összeszámolva)",
                                "Cikkszam": code,
                                "Nap": "Ma"
                            })
                        df_sajat_raklista = pd.DataFrame(mock_rows)

            # Checkboxok kirajzolása
            if not df_sajat_raklista.empty:
                st.caption(f"Ellenőrizd a darabszámokat az ömlesztett raklista alapján:")
                for idx, row in df_sajat_raklista.iterrows():
                    cikkszam_szoveg = f" [{row['Cikkszam']}]" if str(row['Cikkszam']).strip() != "" else ""
                    st.checkbox(
                        f"**{int(row['Terv_Darabszam'])} db** - {row['Etel Neve']}{cikkszam_szoveg} — *({row['Nap']})*", 
                        key=f"check_raklista_{idx}"
                    )
            else:
                st.error("❌ Nem sikerült adatot kinyerni a táblázatból.")

            st.write("---")
            with st.expander("🚨 HIÁNYZIK / SÉRÜLT / TÖBBLET VAN? (Bejelentés)"):
                all_etelek_display = [""]
                all_etelek_mapping = {}
                if not df_sajat_raklista.empty:
                    for idx, row in df_sajat_raklista.iterrows():
                        display_szoveg = f"[{str(row['Cikkszam']).strip()}] - {str(row['Etel Neve']).strip()}"
                        if display_szoveg not in all_etelek_display:
                            all_etelek_display.append(display_szoveg)
                    
                hiba_etel_display = st.selectbox("Melyik étellel van gond?", all_etelek_display, key="mob_hiba_etel_display")
                hiba_etel = hiba_etel_display.split("] - ")[1] if "]" in hiba_etel_display else ""
                hiba_db = st.number_input("Hány darab érintett?", min_value=1, value=1, key="mob_hiba_db")
                hiba_melyik_jarat = st.selectbox("Melyik járathoz tartozó doboz?", valasztott_jaratok, key="mob_hiba_jarat")
                hiba_tipus = st.selectbox("Hiba jellege:", ["Konyha nem adta ki (Hiány)", "Többlet (Többet kaptunk)", "Sérült csomagolás", "Megfolyt / Romlott", "Egyéb"], key="mob_hiba_tipus")
                hiba_megj = st.text_input("Rövid megjegyzés:", key="mob_hiba_megj")
                
                if st.button("⚠️ HIBA BEKÜLDÉSE AZ ADMINNAK", use_container_width=True, key="mob_hiba_submit"):
                    if hiba_etel != "":
                        try:
                            sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
                            hibak_sheet = sh_ugyfelkor.worksheet("Logisztikai_Hibak")
                            most_hiba = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            hiany_db, tobblet_db = (int(hiba_db), 0) if "Hiány" in hiba_tipus else (0, int(hiba_db))
                            
                            hibak_sheet.append_row([
                                most_hiba, hiba_melyik_jarat, hiba_tipus, "N/A", hiba_etel, 
                                hiany_db, tobblet_db, hiba_tipus, hiba_megj, futar_neve, "Feldolgozatlan"
                            ])
                            st.cache_data.clear()
                            st.success("Sikeresen rögzítve! ✅")
                        except Exception as e:
                            st.error(f"Hiba a mentésnél: {e}")

            st.write("---")
            if st.button("⏱️ ÁRUÁTVÉTEL VÉGE (Idő rögzítése)", use_container_width=True, type="secondary", key="futar_end_btn"):
                most = datetime.now()
                end_ido = most.strftime("%H:%M:%S")
                try:
                    sh_master = client.open_by_key(SHEET_ID_UGYFELKOR)
                    idok_sheet = sh_master.worksheet("Mobil_Idobelyegek")
                    sor_szam = st.session_state.idobelyeg_sor_index
                    if sor_szam:
                        idok_sheet.update_cell(sor_szam, 4, end_ido)
                    
                    st.session_state.current_mobile_tab_state = "2. Címekre szedés 📥"
                    st.cache_data.clear()
                    st.success(f"✅ Áruátvétel sikeresen lezárva: {end_ido}.")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Hiba az áruátvétel lezárásakor: {e}")

def render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR):
    """
    2. lépés: Bepakolás felület. Szigorúan a Streamliten véglegesített Sorszám szerint rendezve.
    Tiszta CS1 | X/Y részcsomag jelöléssel, megjegyzésekkel és összevont megálló tippekkel.
    """
    import re
    import pandas as pd
    import streamlit as st
    import datetime
    import time

    st.markdown(
        """
        <style>
        .block-container { padding-top: 1rem !important; padding-bottom: 1.5rem !important; }
        .grouped-card { background-color: #FFFFFF; border: 1px solid #139D43; border-radius: 12px; padding: 12px; margin-bottom: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
        .customer-item { background-color: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px; padding: 10px; margin-bottom: 8px; }
        </style>
        """,
        unsafe_allow_html=True
    )

    # ==============================================================================
    # 🔍 LEZÁRT ÁLLAPOT: DINAMIKUS LÁDA- ÉS CÍMKERESŐ TÁBLÁZAT
    # ==============================================================================
    if st.session_state.get("kiszallitas_folyamatban", False):
        st.success("🔒 A mai bepakolás le van zárva, a kiszállítás folyamatban van.")
        
        df_levalt = st.session_state.get('mdf', pd.DataFrame())
        if df_levalt is None or (hasattr(df_levalt, 'empty') and df_levalt.empty):
            df_levalt = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
            
        if df_levalt is not None and hasattr(df_levalt, 'empty') and not df_levalt.empty:
            df_levalt.columns = [c.strip() for c in df_levalt.columns]
            
            rendezes_col = 'Sorszám' if 'Sorszám' in df_levalt.columns else 'Sorrend'
            df_levalt['Sorrend_num'] = pd.to_numeric(df_levalt[rendezes_col], errors='coerce').fillna(999).astype(int)
            
            futar_neve_lower = str(st.session_state.get('user_nev', 'Szűcs István')).strip().lower()
            if 'Feldolgozó Futár' in df_levalt.columns:
                df_levalt = df_levalt[df_levalt['Feldolgozó Futár'].astype(str).str.strip().str.lower() == futar_neve_lower]
            
            df_search = df_levalt[df_levalt['Láda'].astype(str).str.contains("láda", case=False, na=False)].copy()
            df_search = df_search.sort_values(by='Sorrend_num')
            
            search_data = []
            for idx_s, row_s in df_search.iterrows():
                search_data.append({
                    "🎯 Sorszám": f"#{row_s['Sorrend_num']}",
                    "📦 Láda Helye": str(row_s['Láda']),
                    "👤 Ügyfél": str(row_s.get('Név', row_s.get('Ügyintéző', 'Vevő'))),
                    "🏠 Cím": str(row_s.get('Cím', ''))
                })
            
            if search_data:
                df_view = pd.DataFrame(search_data)
                kereso_kifejezes = st.text_input("🔍 Gyorskeresés a raktérben (Név vagy láda):", key="lada_gyorskereso_input")
                if kereso_kifejezes:
                    df_view = df_view[
                        df_view['👤 Ügyfél'].str.contains(kereso_kifejezes, case=False) | 
                        df_view['📦 Láda Helye'].str.contains(kereso_kifejezes, case=False) |
                        df_view['🏠 Cím'].str.contains(kereso_kifejezes, case=False)
                    ]
                st.dataframe(df_view, use_container_width=True, hide_index=True)
            else:
                st.info("Nincsenek ládába pakolt tételek regisztrálva.")
        else:
            st.error("⚠️ Nem sikerült betölteni a kiszállítási adatokat.")
        
        if st.button("🔓 Bepakolás újranyitása (Vészhelyzet)", use_container_width=True, key="reopen_bepakolas_emergency_btn"):
            st.session_state.kiszallitas_folyamatban = False
            st.rerun()
        return

    # ==============================================================================
    # NYITOTT ÁLLAPOT: NORMÁL LÁDÁZÓ FELÜLET
    # ==============================================================================
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
            df_adatok = st.session_state.get('mdf', pd.DataFrame())
            if df_adatok is None or df_adatok.empty:
                df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok") 
            
            if not df_adatok.empty:
                df_adatok.columns = [c.strip() for c in df_adatok.columns]
                cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
                nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
                rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
                megjegyzes_oszlop = 'Megjegyzés' if 'Megjegyzés' in df_adatok.columns else ('Megjegyzes' if 'Megjegyzes' in df_adatok.columns else None)
                
                # 🎯 KÉNYSZERÍTETT SORREND BEOLVASÁSA: Szigorúan az asztali Sorszám oszlopot követjük!
                rendezes_aktiv = 'Sorszám' if 'Sorszám' in df_adatok.columns else 'Sorrend'
                if rendezes_aktiv not in df_adatok.columns:
                    df_adatok[rendezes_aktiv] = range(1, len(df_adatok) + 1)
                
                df_adatok[rendezes_aktiv] = pd.to_numeric(df_adatok[rendezes_aktiv], errors='coerce').fillna(999).astype(int)

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

                # Jogosultsági szűrés
                if 'Feldolgozó Futár' in df_adatok_filtered.columns:
                    if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                        pass 
                    else:
                        f_clean = str(futar_neve).strip().lower()
                        df_adatok_filtered = df_adatok_filtered[df_adatok_filtered['Feldolgozó Futár'].astype(str).str.strip().str.lower() == f_clean]

                if df_adatok_filtered.empty:
                    st.info("ℹ️ Nincsenek bepakolandó címek.")
                    return

                # Megállók egyedi címeinek lekérése a kényszerített Sorszám szerint rendezve
                addr_max_sorrend = df_adatok_filtered.groupby(cim_oszlop)[rendezes_aktiv].max().reset_index()
                addr_max_sorrend = addr_max_sorrend.sort_values(by=rendezes_aktiv, ascending=True)
                rendezett_cimek = addr_max_sorrend[cim_oszlop].tolist()

                def frissit_bepakolas_felhoben(idx_to_update, check_value):
                    status_str = "Bepakolva" if check_value else "Folyamatban"
                    lada_str = f"{st.session_state.mobil_lada_szam}. láda" if check_value else ""
                    st.session_state[f"bepak_allapot_{idx_to_update}"] = check_value
                    st.session_state[f"lada_szam_tarolt_{idx_to_update}"] = lada_str if check_value else None
                    if 'mdf' in st.session_state and st.session_state.mdf is not None:
                        st.session_state.mdf.at[idx_to_update, 'Státusz'] = status_str
                        st.session_state.mdf.at[idx_to_update, 'Láda'] = lada_str

                ORDER_PAT = r'(\d+)-([A-Z0-9\*]+)'

                @st.fragment
                def render_kartyak(df_lista, cimek):
                    # 🔀 1. PONT: MEGFORDÍTOTT BEPAKOLÁSI SORREND (A menetterv vége kerül legfelülre a listában!)
                    forditott_cimek = cimek[::-1]
                    
                    for addr_idx, addr in enumerate(forditott_cimek):
                        df_addr = df_lista[df_lista[cim_oszlop] == addr].sort_values(by=rendezes_aktiv, ascending=True)
                        show_card = False
                        
                        for idx_k, row_k in df_addr.iterrows():
                            bepakolt_kulcs = f"bepak_allapot_{idx_k}"
                            lada_tarolt_kulcs = f"lada_szam_tarolt_{idx_k}"
                            
                            db_statusz = str(row_k.get('Státusz', 'Folyamatban')).strip()
                            db_lada = str(row_k.get('Láda', '')).strip()
                            
                            if bepakolt_kulcs not in st.session_state:
                                st.session_state[bepakolt_kulcs] = (db_statusz == "Bepakolva" or "láda" in db_lada.lower())
                            if lada_tarolt_kulcs not in st.session_state:
                                st.session_state[lada_tarolt_kulcs] = db_lada if ("láda" in db_lada.lower()) else None
                            
                            if not st.session_state[bepakolt_kulcs] or st.session_state.mutasd_bepakoltat:
                                show_card = True

                        if not show_card: continue

                        # 🔀 VIZUÁLIS ELVÁLASZTÓ VONAL A MEGÁLLÓK KÖZÖTT (Tömörített)
                        if addr_idx > 0:
                            st.markdown("<div style='margin: 8px 0; border-top: 3px dashed #139D43; opacity: 0.4;'></div>", unsafe_allow_html=True)

                        # 🛍️ ÖSSZEVONT MEGÁLLÓ JELZÉSE
                        is_multi_client_stop = len(df_addr) > 1
                        total_clients_at_this_address = len(df_addr)
                        
                        if is_multi_client_stop:
                            st.markdown(f"<div style='background-color: #E0F2FE; color: #0369A1; padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; margin-bottom: 4px;'>🛍️ ÖSSZEVONT: {total_clients_at_this_address} külön vevő!</div>", unsafe_allow_html=True)

                        # MEGÁLLÓ CÍM KIEMELÉSE VIZUÁLISAN
                        st.markdown(f'<h4 style="margin: 2px 0 6px 0; color: #1E3A8A; font-size: 0.95rem;">📍 Megálló: {addr}</h4>', unsafe_allow_html=True)

                        # Vevők listázása a megállón binnen
                        for client_order_idx, (idx, row) in enumerate(df_addr.iterrows(), start=1):
                            vevo_nev = str(row[nev_oszlop]).strip()
                            címke_szama = row[rendezes_aktiv]
                            rendeles_val = str(row[rendeles_oszlop]).strip() if rendeles_oszlop else ""
                            megjegyzes_val = str(row[megjegyzes_oszlop]).strip() if megjegyzes_oszlop else ""

                            # 🔢 TÉTELSZÁM KISZÁMÍTÁSA
                            total_items_for_this_client = 0
                            day_parts = rendeles_val.split('|')
                            for part in day_parts:
                                part = part.strip()
                                found_items = re.findall(ORDER_PAT, part)
                                for qty, code in found_items:
                                    total_items_for_this_client += int(qty)

                            # Részcsomag jelölő (CS1 | X/Y)
                            badge_text = ""
                            if is_multi_client_stop:
                                badge_text = f" <span style='color: #4B5563; font-weight: 800; font-size: 0.8rem;'>[CS1 | {total_clients_at_this_address}/{client_order_idx}]</span>"

                            # Név balra, sorszám és tételek jobbra zárva egyetlen tiszta sorban
                            st.markdown(
                                f"""
                                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; margin-bottom: 2px; padding: 2px 0;">
                                    <div style="font-size: 0.9rem; font-weight: bold; color: #111827;">👤 {vevo_nev}{badge_text}</div>
                                    <div style="font-size: 0.8rem; color: #4B5563; font-weight: 600; text-align: right;">
                                        <span style="background-color: #E5E7EB; padding: 2px 6px; border-radius: 4px; margin-right: 4px;">#{címke_szama}</span>
                                        <span style="background-color: #139D43; color: white; padding: 2px 6px; border-radius: 4px;">🔢 {total_items_for_this_client} db</span>
                                    </div>
                                </div>
                                """, 
                                unsafe_allow_html=True
                            )

                            # 🎯 ATOMBIZTOS STREAMLIT DOBOZ BELSEJE
                            with st.container(border=True):
                                # 📌 MINIMALIZÁLT MEGJEGYZÉS DOBOZ
                                if megjegyzes_val and megjegyzes_val.lower() != "nan" and megjegyzes_val.strip() != "":
                                    st.markdown(f"<div style='font-size: 0.75rem; color: #B45309; background-color: #FFFBEB; padding: 3px 6px; border-radius: 4px; margin-bottom: 4px; border-left: 3px solid #D97706;'>📌 <i>{megjegyzes_val}</i></div>", unsafe_allow_html=True)

                                # 📋 SORFOLYTONOS NAPOK ÉS ÉTELEK
                                kaja_sorok_list = []
                                szombat_sorok_list = []

                                for part in day_parts:
                                    part = part.strip()
                                    if not part: continue
                                    is_szombat = "Szo:" in part or "Szombat:" in part
                                    
                                    day_title = ""
                                    if "Hé:" in part: day_title = "Hétfő"
                                    elif "Ke:" in part: day_title = "Kedd"
                                    elif "Sze:" in part: day_title = "Szerda"
                                    elif "Csü:" in part: day_title = "Csütörtök"
                                    elif "Pé:" in part: day_title = "Péntek"
                                    elif "Szo:" in part: day_title = "Szombat"
                                    
                                    found_items = re.findall(ORDER_PAT, part)
                                    if found_items:
                                        kaja_string = ", ".join([f"{qty.strip()}-{code.strip()}" for qty, code in found_orders])
                                        
                                        if is_szombat:
                                            szombat_sorok_list.append(f"📆 <b>{day_title}:</b> {kaja_string}")
                                        else:
                                            kaja_sorok_list.append(f"🗓️ <b>{day_title}:</b> {kaja_string}")

                                # Hétköznapok kirajzolása
                                if kaja_sorok_list:
                                    st.markdown(f"<div style='font-size: 0.82rem; color: #4B5563; line-height: 1.3; margin-bottom: 6px;'>{' | '.join(kaja_sorok_list)}</div>", unsafe_allow_html=True)
                                
                                # Szombat kiemelt sorban
                                for sz_sor in szombat_sorok_list:
                                    st.markdown(f"<div style='font-size: 0.82rem; color: #DC2626; background-color: #FEF2F2; padding: 2px 4px; border-radius: 4px; margin-bottom: 6px;'>{sz_sor}</div>", unsafe_allow_html=True)

                                # 🔀 ABSZOLÚT FIX GOLYÓÁLLÓ ELRENDEZÉS EGYETLEN HTML BLOKKBAN
                                lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"
                                tarolt_lada_ertek = st.session_state.get(lada_tarolt_kulcs, None)
                                
                                # 🟢/⚪ Lámpácska és a szöveg összerakása dinamikusan
                                if tarolt_lada_ertek:
                                    label_text = f"🟢 Bepakolva ide: {tarolt_lada_ertek}"
                                else:
                                    label_text = "⚪ Bepakolás a ládába"
                                
                                # CSS trükk: Elrendezzük a HTML-t egy sorba, és közéjük szúrjuk be a Streamlit gombot widgetként
                                st.markdown(
                                    f"""
                                    <style>
                                    /* Előírjuk a kapcsolót tartalmazó Streamlit konténernek, hogy tolja magát jobbra és maradjon egy sorban */
                                    div[data-testid="stBlock"] {{
                                        display: flex !important;
                                        flex-direction: row !important;
                                        justify-content: space-between !important;
                                        align-items: center !important;
                                        width: 100% !important;
                                    }}
                                    </style>
                                    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; margin-top: 4px;">
                                        <div style="font-size: 0.85rem; font-weight: bold; color: #374151; text-align: left;">{label_text}</div>
                                    </div>
                                    """, 
                                    unsafe_allow_html=True
                                )
                                
                                # Ez a gomb fog beilleszkedni a fenti stílus miatt szorosan a jobb szélre, kényszerítve egyetlen sorba!
                                val_toggle = st.toggle("Láda", value=st.session_state[f"bepak_allapot_{idx}"], key=f"chk_{idx}", label_visibility="collapsed")
                                
                                if val_toggle != st.session_state[f"bepak_allapot_{idx}"]:
                                    frissit_bepakolas_felhoben(idx, val_toggle)
                                    st.rerun()

                render_kartyak(df_adatok_filtered, rendezett_cimek)
                
                st.write("---")
                if st.button("📦 LÁDÁZÁS ÉS BEPAKOLÁS KÉSZ (Indulás)", use_container_width=True, type="primary", key="futar_bepakolas_kesz_btn"):
                    st.session_state.kiszallitas_folyamatban = True
                    
                    import datetime
                    mostani_ido_eta = datetime.datetime.now().strftime("%H:%M")
                    st.session_state.reggeli_indulas_pontos = mostani_ido_eta
                    
                    if st.session_state.get('teszt_uzemmod', False) or st.query_params.get("test", "false") == "true":
                        st.warning("🧪 Teszt üzemmód!")
                        time.sleep(1.0)
                        st.session_state.current_mobile_tab_state = "3. Kiszállítás 🚚"
                        st.query_params.clear()
                        st.query_params.update(view="mobile", active_tab="kiszallitas")
                        st.rerun()
                    else:
                        with st.spinner("⏳ Mentés a felhőbe és ETA indítása..."):
                            try:
                                sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                                
                                try:
                                    ws_futar_sync = sh.worksheet("Futárok")
                                    futar_rows_sync = ws_futar_sync.get_all_records()
                                    fejlec_futar_sync = ws_futar_sync.row_values(1)
                                    
                                    for idx_f, f_row in enumerate(futar_rows_sync, start=2):
                                        if str(f_row.get('Név', '')).strip().lower() == str(futar_neve).strip().lower():
                                            indulas_col_idx = fejlec_futar_sync.index('Reggeli_Indulas') + 1
                                            ws_futar_sync.update_cell(idx_f, indulas_col_idx, mostani_ido_eta)
                                            break
                                except Exception as e_futar_time:
                                    print(f"Nem sikerült a Futárok fül frissítése: {e_futar_time}")

                                ws_adatok = sh.worksheet("Adatok")
                                adatok_rows = ws_adatok.get_all_values()
                                
                                header = adatok_rows[0]
                                df_save = pd.DataFrame(adatok_rows[1:], columns=header)
                                
                                for idx_m in df_adatok_filtered.index:
                                    lada_k = f"lada_szam_tarolt_{idx_m}"
                                    if st.session_state.get(lada_k):
                                        u_id = str(df_adatok_filtered.loc[idx_m, 'ID']).strip()
                                        df_save.loc[df_save['ID'].astype(str).str.strip() == u_id, 'Láda'] = st.session_state[lada_k]
                                        df_save.loc[df_save['ID'].astype(str).str.strip() == u_id, 'Státusz'] = "Folyamatban"
                                
                                ws_adatok.clear()
                                ws_adatok.update('A1', [header] + df_save.values.tolist(), value_input_option='USER_ENTERED')
                                
                                idok_sheet = sh.worksheet("Mobil_Idobelyegek")
                                most = datetime.datetime.now()
                                bepakolas_vege_ido = most.strftime("%H:%M:%S")
                                mai_datum = most.strftime("%Y-%m-%d")
                                jarat_szoveg = ", ".join(map(str, valasztott_jaratok))
                                
                                idok_sheet.append_row([mai_datum, jarat_szoveg, futar_neve, "", bepakolas_vege_ido])
                                
                                st.cache_data.clear()
                                st.session_state.current_mobile_tab_state = "3. Kiszállítás 🚚"
                                st.query_params.clear()
                                st.query_params.update(view="mobile", active_tab="kiszallitas")
                                st.rerun()
                            except Exception as e_save_all:
                                st.error(f"Hiba: {e_save_all}")
            else:
                st.error("Az Adatok munkalap üres!")
        else:
            st.info("ℹ️ Válaszd ki a járatodat az 1. fülön!")
    except Exception as e:
        st.error(f"Hiba: {e}")

def render_mobil_kiszallitas(client, SHEET_ID_UGYFELKOR):
    """
    Kiszállítás nézet többmarkeres Leaflet.js térképpel és rögzítéssel.
    """
    if "kiszallitas_aktiv_fullscreen" not in st.session_state:
        st.session_state.kiszallitas_aktiv_fullscreen = False

    futar_neve = st.session_state.get('user_nev', 'Szűcs István')

    # ==============================================================================
    # 🛰️ INTERAKTÍV ÁTSORRENDEZŐ MOTOR
    # ==============================================================================
    query_params = st.query_params
    if "action" in query_params and "target_id" in query_params:
        action = query_params["action"]
        target_id = str(query_params["target_id"]).strip()
        
        try:
            sh = client.open_by_key(SHEET_ID_UGYFELKOR)
            ws_adatok = sh.worksheet("Adatok")
            adatok_rows = ws_adatok.get_all_values()
            
            if adatok_rows and len(adatok_rows) > 1:
                header_adatok = adatok_rows[0]
                df_sheets = pd.DataFrame(adatok_rows[1:], columns=header_adatok)
                df_sheets['Sorrend'] = pd.to_numeric(df_sheets['Sorrend'], errors='coerce').fillna(999).astype(int)
                df_sheets = df_sheets.sort_values(by='Sorrend').reset_index(drop=True)
                
                target_idx = df_sheets[df_sheets['ID'].astype(str).str.strip() == target_id].index
                if not target_idx.empty:
                    t_idx = target_idx[0]
                    target_row = df_sheets.loc[t_idx].copy()
                    
                    if action == "move_end":
                        max_sorrend = df_sheets['Sorrend'].max()
                        df_sheets = df_sheets.drop(t_idx).reset_index(drop=True)
                        target_row['Sorrend'] = max_sorrend + 1
                        df_sheets = pd.concat([df_sheets, pd.DataFrame([target_row])], ignore_index=True)
                    elif action == "move_to" and "pos" in query_params:
                        target_pos = max(1, int(query_params["pos"]))
                        df_sheets = df_sheets.drop(t_idx).reset_index(drop=True)
                        insert_idx = min(len(df_sheets), target_pos - 1)
                        df_left = df_sheets.iloc[:insert_idx]
                        df_right = df_sheets.iloc[insert_idx:]
                        df_sheets = pd.concat([df_left, pd.DataFrame([target_row]), df_right], ignore_index=True)
                    
                    df_sheets['Sorrend'] = range(1, len(df_sheets) + 1)
                    ws_adatok.clear()
                    ws_adatok.update('A1', [header_adatok] + df_sheets.values.tolist(), value_input_option='USER_ENTERED')
                    
                    st.session_state.mdf = df_sheets
                    st.cache_data.clear()
                    st.query_params.clear()
                    st.query_params.update(view="mobile", active_tab="kiszallitas")
                    st.rerun()
        except Exception as e:
            st.error(f"Sikertelen rendezés: {e}")

    # ==============================================================================
    # ADATOK BEOLVASÁSA ÉS KISZÁLLÍTÁSI LOGIKA
    # ==============================================================================
    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        if not valasztott_jaratok:
            st.info("ℹ️ Válaszd ki a járatodat az 1. fülön!")
            return

        df_adatok = st.session_state.get('mdf', pd.DataFrame())
        if df_adatok is None or df_adatok.empty:
            df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
        
        if df_adatok.empty: return

        df_adatok.columns = [c.strip() for c in df_adatok.columns]
        cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
        nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
        tel_oszlop = 'Telefon' if 'Telefon' in df_adatok.columns else 'Tel'
        rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else None
        
        penz_oszlop = None
        for c in df_adatok.columns:
            if 'pénz' in c.lower() or 'penz' in c.lower() or 'fizet' in c.lower():
                penz_oszlop = c
                break

        lat_oszlop = 'Latitude' if 'Latitude' in df_adatok.columns else 'Lat'
        lon_oszlop = 'Longitude' if 'Longitude' in df_adatok.columns else 'Lon'

        df_kiszallitas = df_adatok.copy()
        if 'Sorrend' in df_kiszallitas.columns:
            df_kiszallitas['Sorrend_num'] = pd.to_numeric(df_kiszallitas['Sorrend'], errors='coerce').fillna(999).astype(int)
            df_kiszallitas = df_kiszallitas.sort_values(by='Sorrend_num')

        bepakolt_sorok = []
        for idx_b, row_b in df_kiszallitas.iterrows():
            lada_k = f"lada_szam_tarolt_{idx_b}"
            felhos_lada = str(row_b.get('Láda', ''))
            if st.session_state.get(lada_k) is not None or "láda" in felhos_lada.lower():
                if st.session_state.get(lada_k) is None:
                    st.session_state[lada_k] = felhos_lada
                bepakolt_sorok.append((idx_b, row_b))

        if not bepakolt_sorok:
            st.warning("⚠️ Nincs még bepakolt címed!")
            return

        osszes_bepakolt = len(bepakolt_sorok)
        kesz_cimek = sum(1 for idx_c, _ in bepakolt_sorok if st.session_state.get(f"kiszallitva_{idx_c}", False))

        if not st.session_state.kiszallitas_aktiv_fullscreen:
            st.markdown("## 🚚 3. lépés: Kiszállítás és Elszámolás")
            st.info(f" Megállók: {osszes_bepakolt} | Teljesítve: {kesz_cimek}")
            if st.button("▶️ KISZÁLLÍTÁS MEGKEZDÉSE (Teljes Képernyő)", type="primary", use_container_width=True):
                st.session_state.kiszallitas_aktiv_fullscreen = True
                st.rerun()
            return

        st.markdown("<style>header[data-testid='stHeader'] { display: none !important; } div[data-testid='stTabBar'] { display: none !important; }</style>", unsafe_allow_html=True)

        active_map_points = []
        current_target_point = None

        for idx_m, row_m in bepakolt_sorok:
            if st.session_state.get(f"kiszallitva_{idx_m}", False): continue
            m_lat = str(row_m.get(lat_oszlop, "")).strip().replace(',', '.')
            m_lon = str(row_m.get(lon_oszlop, "")).strip().replace(',', '.')
            
            if m_lat and m_lon and m_lat != "nan" and m_lon != "nan":
                pt = {
                    "id": str(row_m.get('ID', idx_m)),
                    "sorrend": int(row_m['Sorrend_num']),
                    "name": str(row_m[nev_oszlop]),
                    "address": str(row_m[cim_oszlop]),
                    "lat": float(m_lat),
                    "lon": float(m_lon)
                }
                active_map_points.append(pt)
                if current_target_point is None: current_target_point = pt

        if active_map_points:
            points_json = json.dumps(active_map_points, ensure_ascii=False)
            c_lat = current_target_point['lat'] if current_target_point else 47.5316
            c_lon = current_target_point['lon'] if current_target_point else 21.6244
            
            # --- 1. PONT FIX: TÉRKERET FINOMHANGOLÁS (NINCS MARGÓ, EMELT TÉRKÉP MAGASSÁG) ---
            html_map_code = """
            <!DOCTYPE html>
            <html>
            <head>
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
                <style>html, body, #map { height: 100%; width: 100%; margin: 0; } #map { height: 210px; }
                .active-marker { background: #139D43; border: 1.5px solid white; border-radius: 50%; color: white; font-weight: bold; text-align: center; line-height: 19px; font-size: 9.5px; }
                .current-marker { background: #E1251B; border: 2px solid white; border-radius: 50%; color: white; font-weight: bold; text-align: center; line-height: 23px; font-size: 11px; }
                </style>
            </head>
            <body>
                <div id="map"></div>
                <script>
                    var points = __POINTS_JSON__;
                    var map = L.map('map', {zoomControl: false}).setView([__C_LAT__, __C_LON__], 14);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

                    points.forEach(function(p, index) {
                        var isCurrent = (index === 0);
                        var iconClass = isCurrent ? 'current-marker' : 'active-marker';
                        var iconSize = isCurrent ? [26, 26] : [22, 22];

                        var icon = L.divIcon({ className: iconClass, html: p.sorrend, iconSize: iconSize });
                        var popupHtml = `
                            <div style="font-size:11px; font-family:sans-serif;">
                                <b>#${p.sorrend} - ${p.name}</b><br>
                                ${p.address}
                            </div>
                        `;
                        L.marker([p.lat, p.lon], {icon: icon}).bindPopup(popupHtml).addTo(map);
                    });
                </script>
            </body>
            </html>
            """
            html_map_code = html_map_code.replace("__POINTS_JSON__", points_json)
            html_map_code = html_map_code.replace("__C_LAT__", str(c_lat))
            html_map_code = html_map_code.replace("__C_LON__", str(c_lon))

            # Beágyazás nulla felesleges fehér térközzel
            st.components.v1.html(f'<div style="width: 100%; height: 210px; overflow: hidden; border-radius: 12px; border: 1.5px solid #93C5FD; margin-top: -10px; margin-bottom: -10px;"><iframe width="100%" height="210px" src="data:text/html;charset=utf-8,{urllib.parse.quote(html_map_code)}" frameborder="0" scrolling="no" style="border: none;"></iframe></div>', height=212)

        # --- 📋 2. ALAP-LISTA ÖSSZEÁLLÍTÁS ---
        elokeszitett_sorok = []
        for idx_p, row_p in bepakolt_sorok:
            if st.session_state.get(f"kiszallitva_{idx_p}", False): continue
            elokeszitett_sorok.append((idx_p, row_p))

        # --- 📋 3. HA VAN KIEMELT ÜGYFÉL, AZT ELŐRE RAKJUK A LISTÁBAN ---
        kiemelt_id = st.session_state.get("kiemelt_ugyfel_id", None)
        if kiemelt_id:
            talalt_kiemelt = None
            for s_idx, (idx_e, row_e) in enumerate(elokeszitett_sorok):
                if str(row_e.get('ID', idx_e)).strip() == kiemelt_id:
                    talalt_kiemelt = elokeszitett_sorok.pop(s_idx)
                    break
            if talalt_kiemelt:
                elokeszitett_sorok.insert(0, talalt_kiemelt)

        # --- 📋 4. KÁRTYÁK KIRAJZOLÁSA ---
        for sorszam, (idx, row) in enumerate(elokeszitett_sorok, 1):
            melyik_lada = st.session_state.get(f"lada_szam_tarolt_{idx}")
            if not melyik_lada: melyik_lada = str(row.get('Láda', 'Nincs láda'))
            
            aktualis_cim = str(row[cim_oszlop]).strip()
            vevo_neve = str(row[nev_oszlop]).strip()
            vevo_tel = str(row.get(tel_oszlop, '')).strip()
            customer_id = str(row['ID']).strip()
            aktualis_rendeles = str(row[rendeles_oszlop]).strip() if rendeles_oszlop in row else "Nincs adat"
            
            eredeti_sorszam = int(row["Sorrend_num"])
            
            # 4. PONT FIX: MATEMATIKAI DARABSZÁM ÖSSZEGZÉS A REDUNDÁNS ADAT HELYETT
            osszes_db = 0
            try:
                darabok = re.findall(r'(\d+)-', aktualis_rendeles)
                osszes_db = sum(int(d) for d in darabok)
            except:
                osszes_db = 1
                
            if eredeti_sorszam != sorszam:
                sorszam_felirat = f"📍 #{sorszam}. megálló <span style='font-size:11px; color:#EA580C;'>(Átrendezve)</span> — {melyik_lada}"
            else:
                sorszam_felirat = f"📍 #{sorszam}. megálló — {melyik_lada}"

            is_kiemelt = (customer_id == kiemelt_id)
            bg_style = "background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%); border: 2.5px solid #F59E0B;" if is_kiemelt else "background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%); border: 1.5px solid #93C5FD;"
            kiemelt_szoveg = "⚠️ <b>TÉRKÉPEN KIJELÖLT CÍM!</b><br>" if is_kiemelt else ""

            # Letisztított kártya az összesített darabszámmal, felesleges dobozszám nélkül
            html_kartyadisz = f"""<div style="{bg_style} border-radius: 12px; padding: 10px 14px; margin-top: 8px;">{kiemelt_szoveg}<b>{sorszam_felirat}</b><br><span style="font-size:18px; font-weight:bold; color:#1E3A8A;">👤 {vevo_neve}</span><br><span style="font-size:14px; color:#4B5563;">🏠 {aktualis_cim}</span><br><hr style="margin: 6px 0; border: 0; border-top: 1px solid #BFDBFE;"><span style="font-size:13px; font-weight:bold; color:#4B5563;">🛍️ Összes rendelési tétel: {osszes_db} db</span><br><span style="font-size:14px; font-weight:bold; color:#DC2626;">📦 Rendelés: {aktualis_rendeles}</span></div>"""
            st.markdown(html_kartyadisz, unsafe_allow_html=True)
            
            # Gombok egy sorban
            maps_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(aktualis_cim)}"
            hivas_html = f'<a href="tel:{vevo_tel}" target="_blank" style="width:100%; text-decoration:none;"><button style="width:100%; height:38px; background-color:#25D366; color:white; border:none; border-radius:8px; font-weight:bold; font-size:14px; cursor:pointer;">📞 Hívás</button></a>' if vevo_tel and vevo_tel != "nan" else '<button style="width:100%; height:38px; background-color:#9CA3AF; color:white; border:none; border-radius:8px; font-weight:bold; font-size:14px; opacity:0.5;" disabled>📞 Nincs tel.</button>'
            nav_html = f'<a href="{maps_url}" target="_blank" style="width:100%; text-decoration:none;"><button style="width:100%; height:38px; background-color:#4285F4; color:white; border:none; border-radius:8px; font-weight:bold; font-size:14px; cursor:pointer;">🗺️ Navigáció</button></a>'
            
            st.markdown(f"""
            <div style="display: flex; gap: 8px; width: 100%; margin-top: 6px; margin-bottom: 4px;">
                <div style="flex: 1;">{hivas_html}</div>
                <div style="flex: 1;">{nav_html}</div>
            </div>
            """, unsafe_allow_html=True)

            # --- 2. PONT FIX: AZ ÖSSZES FUNKCIÓ (KERESŐ + SORSZÁMOZÓ) EGYETLEN EXPANDER ALATT ---
            with st.expander("🛠️ Cím korrigálása és Átrendezés"):
                
                # Gyorsaktiváló kereső (Itt lakik legfelül!)
                st.markdown("<b>🔍 Útba eső cím/bogyó gyors adatlap-aktiválása:</b>", unsafe_allow_html=True)
                options_ugras = ["--- Válassz egy megállót a kiemeléshez ---"]
                id_mapping_ugras = {}
                for idx_u, row_u in elokeszitett_sorok:
                    u_id = str(row_u['ID']).strip()
                    options_ugras.append(f"📍 #{row_u['Sorrend_num']} — {str(row_u[nev_oszlop]).strip()}")
                    id_mapping_ugras[f"📍 #{row_u['Sorrend_num']} — {str(row_u[nev_oszlop]).strip()}"] = u_id
                
                valasztott_gyorsugras = st.selectbox("Válassz ki egy bogyót a térképről:", options=options_ugras, key=f"inner_ugro_select_{idx}", label_visibility="collapsed")
                if valasztott_gyorsugras != "--- Válassz egy megállót a kiemeléshez ---":
                    st.session_state.kiemelt_ugyfel_id = id_mapping_ugras[valasztott_gyorsugras]
                    st.rerun()

                st.markdown("<hr style='margin:10px 0; border-top:1px dashed #D1D5DB;'>", unsafe_allow_html=True)

                # Sorrend módosítása
                st.markdown("<b>🔀 Megálló sorrendjének módosítása</b>", unsafe_allow_html=True)
                c_end, c_move = st.columns(2)
                
                if c_end.button("⬇️ Végére dobás", key=f"py_end_{idx}", use_container_width=True):
                    try:
                        sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                        ws_adatok = sh.worksheet("Adatok")
                        rows = ws_adatok.get_all_values()
                        header = rows[0]
                        df_s = pd.DataFrame(rows[1:], columns=header)
                        df_s['Sorrend'] = pd.to_numeric(df_s['Sorrend'], errors='coerce').fillna(999).astype(int)
                        df_s = df_s.sort_values(by='Sorrend').reset_index(drop=True)
                        t_idx = df_s[df_s['ID'].astype(str).str.strip() == customer_id].index[0]
                        target_row = df_s.loc[t_idx].copy()
                        df_s = df_s.drop(t_idx).reset_index(drop=True)
                        target_row['Sorrend'] = df_s['Sorrend'].max() + 1
                        df_s = pd.concat([df_s, pd.DataFrame([target_row])], ignore_index=True)
                        df_s['Sorrend'] = range(1, len(df_s) + 1)
                        ws_adatok.clear()
                        ws_adatok.update('A1', [header] + df_s.values.tolist(), value_input_option='USER_ENTERED')
                        st.session_state.pop("kiemelt_ugyfel_id", None)
                        st.session_state.mdf = df_s
                        st.cache_data.clear()
                        st.success("Sikeresen a végére dobva!")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as err: st.error(f"Hiba: {err}")
                
                uj_pozicio = c_move.number_input("Helyezés sorszáma:", min_value=1, max_value=100, value=2, key=f"py_num_{idx}")
                if c_move.button("👉 Áthelyezés ide", key=f"py_move_btn_{idx}", use_container_width=True):
                    try:
                        sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                        ws_adatok = sh.worksheet("Adatok")
                        rows = ws_adatok.get_all_values()
                        header = rows[0]
                        df_s = pd.DataFrame(rows[1:], columns=header)
                        df_s['Sorrend'] = pd.to_numeric(df_s['Sorrend'], errors='coerce').fillna(999).astype(int)
                        df_s = df_s.sort_values(by='Sorrend').reset_index(drop=True)
                        t_idx = df_s[df_s['ID'].astype(str).str.strip() == customer_id].index[0]
                        target_row = df_s.loc[t_idx].copy()
                        df_s = df_s.drop(t_idx).reset_index(drop=True)
                        insert_idx = min(len(df_s), int(uj_pozicio) - 1)
                        df_left = df_s.iloc[:insert_idx]
                        df_right = df_s.iloc[insert_idx:]
                        df_s = pd.concat([df_left, pd.DataFrame([target_row]), df_right], ignore_index=True)
                        df_s['Sorrend'] = range(1, len(df_s) + 1)
                        ws_adatok.clear()
                        ws_adatok.update('A1', [header] + df_s.values.tolist(), value_input_option='USER_ENTERED')
                        st.session_state.pop("kiemelt_ugyfel_id", None)
                        st.session_state.mdf = df_s
                        st.cache_data.clear()
                        st.success(f"Sikeresen áthelyezve a(z) {uj_pozicio}. helyre!")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as err: st.error(f"Hiba: {err}")

                st.markdown("<hr style='margin:10px 0; border-top:1px dashed #D1D5DB;'>", unsafe_allow_html=True)
                
                # GPS Kapu rögzítése
                st.markdown("<b>🎯 Kapu rögzítése (GPS koordináta)</b>", unsafe_allow_html=True)
                loc = get_geolocation()
                if loc and 'coords' in loc:
                    curr_lat = loc['coords']['latitude']
                    curr_lon = loc['coords']['longitude']
                    st.caption(f"Észlelt GPS: `{curr_lat}, {curr_lon}`")
                    if st.button("💾 Új koordináta mentése", key=f"save_geo_{idx}", use_container_width=True):
                        try:
                            sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                            ws_adatok = sh.worksheet("Adatok")
                            headers_adatok = ws_adatok.row_values(1)
                            lat_col_idx = headers_adatok.index(lat_oszlop) + 1
                            lon_col_idx = headers_adatok.index(lon_oszlop) + 1
                            sheet_row = int(idx) + 2
                            ws_adatok.update_cell(sheet_row, lat_col_idx, curr_lat)
                            ws_adatok.update_cell(sheet_row, lon_col_idx, curr_lon)
                            
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
                            st.cache_data.clear()
                            st.success("🎯 Pozíció sikeresen elmentve!")
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as geo_err: st.error(f"Sheets hiba: {geo_err}")
                else:
                    st.caption("⏳ Várakozás éles GPS jelre...")

            # --- PÉNZÜGYI RÉSZ ÉS KÉZBESÍTÉS ---
            elovart_osszeg = 0
            if penz_oszlop:
                try: elovart_osszeg = int(float(str(row[penz_oszlop]).replace("Ft","").replace(" ","").strip()))
                except: elovart_osszeg = 0
            
            if elovart_osszeg > 0:
                st.write(f"💵 **Fizetendő KP:** {elovart_osszeg:,} Ft")
            
            atvett_osszeg = st.number_input("Átvett összeg:", min_value=0, value=int(elovart_osszeg), step=50, key=f"atvett_input_{idx}")
            
            if st.button("✅ Sikeres kézbesítés", key=f"siker_{idx}", use_container_width=True, type="primary"):
                st.session_state[f"kiszallitva_{idx}"] = True
                st.session_state.pop("kiemelt_ugyfel_id", None)
                st.toast(f"🎉 {vevo_neve} teljesítve!")
                st.rerun()
            break
            
    except Exception as e:
        st.error(f"Hiba a kiszállítás futtatásakor: {e}")
