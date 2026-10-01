# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import time
import json
import urllib.parse
import re
from datetime import datetime
import threading
import streamlit.components.v1 as components

# --- KAPCSOLÓDÓ CACHED OLVASÓ IMPORTÁLÁSA A KVÓTAVÉDELEMHÉZ ---
from adatbazis_modul import load_sheet_data_cached, SHEET_ID_UGYFELKOR

# --- Szigorú illesztés a rendelési kódokhoz (pl: 1-A1* vagy 4-S2) ---
ORDER_PAT = r'(\d+)-([A-Z0-9*]+)'

def render_mobil_aruatvetel(client):
    """
    1. lépés: Ömlesztett áruátvétel oldal golyóálló Google Sheets gyorsítótárral.
    """
    st.subheader("📦 Ömlesztett áruátvétel")
    
    futar_neve = st.session_state.get('user_nev', 'Te (Teszt Üzemmód)')
    f_clean = str(futar_neve).strip().lower()
    
    jaratok = []
    try:
        df_adatok_init = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
        if not df_adatok_init.empty:
            df_adatok_init.columns = [c.strip() for c in df_adatok_init.columns]
            
            if 'Feldolgozó Futár' in df_adatok_init.columns:
                if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                    jaratok = [str(j).strip() for j in df_adatok_init['Járat'].unique() if str(j).strip() != "" and str(j).lower() != "nan"]
                else:
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

    # GYORSÍTÓ PANEL AZ ÁRUÁTVÉTELHEZ
    if st.session_state.get('user_szerep') in ["admin", "superadmin", "futar", "futár"]:
        with st.expander("🛠️ TESZTELŐ & BEMUTATÓ PANEL (Gyors Áruátvétel)", expanded=False):
            if st.button("⚡ ÖSSZES ÉTEL ÁTVÉTELE ÉS CÍMEKRE SZEDÉS INDÍTÁSA", type="primary", use_container_width=True, key="admin_fast_aruatvetel_btn"):
                st.session_state.aruatvetel_folyamatban = True
                st.session_state.current_mobile_tab_state = "2. Címekre szedés 📥"
                st.query_params.update(view="mobile", active_tab="bepakolas")
                st.toast("✅ Áruátvétel azonnal teljesítve! Tovább a címekre szedésre...")
                time.sleep(0.4)
                st.rerun()

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
    else:
        jaratok_szoveg = ", ".join(map(str, valasztott_jaratok))
        if not st.session_state.get("kiszallitas_folyamatban", False):
            st.warning(f"🔄 Áruátvétel és depózás folyamatban... ({jaratok_szoveg})")
            st.markdown("## 1. lépés: Ömlesztett áruátvétel")
            
            df_raklista_init = pd.DataFrame()
            try:
                df_raklista_init = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Mobil_Raklista")
            except: pass
            
            df_sajat_raklista = pd.DataFrame()
            if df_raklista_init is not None and not df_raklista_init.empty:
                df_raklista_init.columns = [c.strip() for c in df_raklista_init.columns]
                if st.session_state.get('user_szerep') in ["admin", "superadmin"]:
                    df_sajat_raklista = df_raklista_init.copy()
                else:
                    df_sajat_raklista = df_raklista_init[df_raklista_init['Jarat_ID / Futar'].astype(str).str.strip().str.lower() == f_clean]

            if df_sajat_raklista.empty:
                st.caption("⚠️ *Összesítés generálása az Adatok munkalapból...*")
                df_adatok = st.session_state.get('mdf', pd.DataFrame())
                if df_adatok.empty:
                    df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
                
                if not df_adatok.empty:
                    df_adatok.columns = [c.strip() for c in df_adatok.columns]
                    rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
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

            if not df_sajat_raklista.empty:
                st.caption("Ellenőrizd a darabszámokat az ömlesztett raklista alapján:")
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
    """
    st.markdown(
        """
        <style>
        .block-container { padding-top: 0.8rem !important; padding-bottom: 1.5rem !important; }
        .grouped-card { background-color: #FFFFFF; border: 1px solid #139D43; border-radius: 12px; padding: 12px; margin-bottom: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
        .customer-item { background-color: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px; padding: 10px; margin-bottom: 8px; }
        </style>
        """,
        unsafe_allow_html=True
    )

    # 1. GYORSÍTÓ PANEL: Összes cím átadása az 1. ládába (reggeli gyorsindítás)
    with st.expander("⚡ GYORSÍTÓ PANEL (Összes cím berakása az 1. ládába)", expanded=False):
        if st.button("🚀 MINDEN CÍM AZ 1. LÁDÁBA ÉS KISZÁLLÍTÁS INDÍTÁSA", type="primary", use_container_width=True, key="fast_all_to_box1"):
            with st.spinner("📦 Címek berámolása az 1. ládába..."):
                try:
                    sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                    ws = sh.worksheet("Adatok")
                    rows = ws.get_all_values()
                    if rows and len(rows) > 1:
                        hdr = [c.strip() for c in rows[0]]
                        df_b = pd.DataFrame(rows[1:], columns=hdr)
                        if 'Láda' not in df_b.columns:
                            df_b['Láda'] = "1. láda"
                            hdr.append('Láda')
                        else:
                            df_b['Láda'] = "1. láda"
                        ws.clear()
                        ws.update('A1', [hdr] + df_b.values.tolist(), value_input_option='USER_ENTERED')
                        st.session_state.mdf = df_b
                except Exception as e:
                    print("Gyorsládázás hiba:", e)

            st.session_state.aruatvetel_folyamatban = True
            st.session_state.kiszallitas_folyamatban = True
            st.session_state.kiszallitas_aktiv_fullscreen = True
            st.session_state.current_mobile_tab_state = "3. Kiszállítás 🚚"
            st.query_params.update(view="mobile", active_tab="kiszallitas")
            st.toast("✅ Minden cím az 1. ládában! Kiszállítás indul...")
            time.sleep(0.3)
            st.rerun()

    # Lezárt állapot ellenőrzése
    if st.session_state.get("kiszallitas_folyamatban", False):
        st.success("🔒 A mai bepakolás le van zárva, a kiszállítás folyamatban van.")
        df_levalt = st.session_state.get('mdf', pd.DataFrame())
        if df_levalt is None or (hasattr(df_levalt, 'empty') and df_levalt.empty):
            df_levalt = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
            
        if df_levalt is not None and hasattr(df_levalt, 'empty') and not df_levalt.empty:
            df_levalt.columns = [c.strip() for c in df_levalt.columns]
            rendezes_col = 'Sorszám' if 'Sorszám' in df_levalt.columns else 'Sorrend'
            df_levalt['Sorrend_num'] = pd.to_numeric(df_levalt[rendezes_col], errors='coerce').fillna(999).astype(int)
            
            if 'Láda' not in df_levalt.columns:
                df_levalt['Láda'] = "1. láda"

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
        
        if st.button("🔓 Bepakolás újranyitása (Vészhelyzet)", use_container_width=True, key="reopen_bepakolas_emergency_btn"):
            st.session_state.kiszallitas_folyamatban = False
            st.rerun()
        return

    # Normál ládázó felület
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

                if 'Feldolgozó Futár' in df_adatok_filtered.columns:
                    if st.session_state.get('user_szerep') not in ["admin", "superadmin"]:
                        f_clean = str(futar_neve).strip().lower()
                        df_adatok_filtered = df_adatok_filtered[df_adatok_filtered['Feldolgozó Futár'].astype(str).str.strip().str.lower() == f_clean]

                if df_adatok_filtered.empty:
                    st.info("ℹ️ Nincsenek bepakolandó címek.")
                    return

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

                @st.fragment
                def render_kartyak(df_lista, cimek):
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

                        if addr_idx > 0:
                            st.markdown("<div style='margin: 8px 0; border-top: 3px dashed #139D43; opacity: 0.4;'></div>", unsafe_allow_html=True)

                        is_multi_client_stop = len(df_addr) > 1
                        total_clients_at_this_address = len(df_addr)
                        
                        if is_multi_client_stop:
                            st.markdown(f"<div style='background-color: #E0F2FE; color: #0369A1; padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; margin-bottom: 4px;'>🛍️ ÖSSZEVONT: {total_clients_at_this_address} külön vevő!</div>", unsafe_allow_html=True)

                        st.markdown(f'<h4 style="margin: 2px 0 6px 0; color: #1E3A8A; font-size: 0.95rem;">📍 Megálló: {addr}</h4>', unsafe_allow_html=True)

                        for client_order_idx, (idx, row) in enumerate(df_addr.iterrows(), start=1):
                            vevo_nev = str(row[nev_oszlop]).strip()
                            címke_szama = row[rendezes_aktiv]
                            rendeles_val = str(row[rendeles_oszlop]).strip() if rendeles_oszlop else ""
                            megjegyzes_val = str(row[megjegyzes_oszlop]).strip() if megjegyzes_oszlop else ""

                            total_items_for_this_client = 0
                            day_parts = rendeles_val.split('|')
                            for part in day_parts:
                                part = part.strip()
                                found_items = re.findall(ORDER_PAT, part)
                                for qty, code in found_items:
                                    total_items_for_this_client += int(qty)

                            badge_text = ""
                            if is_multi_client_stop:
                                badge_text = f" <span style='color: #4B5563; font-weight: 800; font-size: 0.8rem;'>[CS1 | {total_clients_at_this_address}/{client_order_idx}]</span>"

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

                            with st.container(border=True):
                                if megjegyzes_val and megjegyzes_val.lower() != "nan" and megjegyzes_val.strip() != "":
                                    st.markdown(f"<div style='font-size: 0.75rem; color: #B45309; background-color: #FFFBEB; padding: 3px 6px; border-radius: 4px; margin-bottom: 4px; border-left: 3px solid #D97706;'>📌 <i>{megjegyzes_val}</i></div>", unsafe_allow_html=True)

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
                                        kaja_string = ", ".join([f"{qty.strip()}-{code.strip()}" for qty, code in found_items])
                                        if is_szombat:
                                            szombat_sorok_list.append(f"📆 <b>{day_title}:</b> {kaja_string}")
                                        else:
                                            kaja_sorok_list.append(f"🗓️ <b>{day_title}:</b> {kaja_string}")

                                if kaja_sorok_list:
                                    st.markdown(f"<div style='font-size: 0.82rem; color: #4B5563; line-height: 1.3; margin-bottom: 6px;'>{' | '.join(kaja_sorok_list)}</div>", unsafe_allow_html=True)
                                
                                for sz_sor in szombat_sorok_list:
                                    st.markdown(f"<div style='font-size: 0.82rem; color: #DC2626; background-color: #FEF2F2; padding: 2px 4px; border-radius: 4px; margin-bottom: 6px;'>{sz_sor}</div>", unsafe_allow_html=True)

                                lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"
                                tarolt_lada_ertek = st.session_state.get(lada_tarolt_kulcs, None)
                                
                                toggle_label = f"🟢 Bepakolva ide: {tarolt_lada_ertek}" if tarolt_lada_ertek else "⚪ Bepakolás a ládába"
                                val_toggle = st.toggle(
                                    toggle_label,
                                    value=st.session_state[f"bepak_allapot_{idx}"],
                                    key=f"chk_{idx}"
                                )
                                
                                if val_toggle != st.session_state[f"bepak_allapot_{idx}"]:
                                    frissit_bepakolas_felhoben(idx, val_toggle)
                                    st.rerun()

                render_kartyak(df_adatok_filtered, rendezett_cimek)
                
                st.write("---")
                if st.button("📦 LÁDÁZÁS ÉS BEPAKOLÁS KÉSZ (Indulás)", use_container_width=True, type="primary", key="futar_bepakolas_kesz_btn"):
                    st.session_state.kiszallitas_folyamatban = True
                    mostani_ido_eta = datetime.now().strftime("%H:%M")
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
                                most = datetime.now()
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
    3. lépés: Kiszállítás nézet nagy pontosságú élő GPS-szel, kompakt UI-val,
    papír szerinti Csoport kezeléssel, üzenetküldő panellel és rendezővel.
    """
    st.session_state.kiszallitas_aktiv_fullscreen = True
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
    # 📱 ULTRA-KOMPAKT CHROME MOBIL STÍLUSOK (Hogy semmi se lógjon le)
    # ==============================================================================
    st.markdown(
        """
        <style>
        header[data-testid='stHeader'] { display: none !important; }
        .block-container {
            padding-top: max(1.6rem, env(safe-area-inset-top)) !important;
            padding-bottom: 0.2rem !important;
            padding-left: 0.35rem !important;
            padding-right: 0.35rem !important;
            max-width: 100% !important;
        }
        div[data-testid="stVerticalBlock"] { gap: 0.2rem !important; }
        div[data-testid="stCustomComponentV1"] { margin-bottom: 2px !important; }
        iframe { display: block !important; margin-bottom: 0px !important; }
        div[data-testid="stNumberInput"] { margin-top: -4px !important; margin-bottom: -2px !important; }
        </style>
        """, 
        unsafe_allow_html=True
    )

    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        df_adatok = st.session_state.get('mdf', pd.DataFrame())
        if df_adatok is None or df_adatok.empty:
            df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
            st.session_state.mdf = df_adatok
            
        if df_adatok.empty:
            st.info("Nincsenek elérhető kiszállítási adatok.")
            return

        df_adatok.columns = [c.strip() for c in df_adatok.columns]
        cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
        nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
        tel_oszlop = 'Telefon' if 'Telefon' in df_adatok.columns else 'Tel'
        rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else None
        csoport_oszlop = next((c for c in df_adatok.columns if 'csoport' in c.lower()), None)
        
        penz_oszlop = None
        for c in df_adatok.columns:
            if any(term in c.lower() for term in ['pénz', 'penz', 'fizet']):
                penz_oszlop = c
                break

        lat_oszlop = next((c for c in df_adatok.columns if c.lower() in ['szelesseg', 'latitude', 'lat']), 'Latitude')
        lon_oszlop = next((c for c in df_adatok.columns if c.lower() in ['hosszusag', 'longitude', 'lon']), 'Longitude')

        df_kiszallitas = df_adatok.copy()
        if 'Sorrend' in df_kiszallitas.columns:
            df_kiszallitas['Sorrend_num'] = pd.to_numeric(df_kiszallitas['Sorrend'], errors='coerce').fillna(999).astype(int)
            df_kiszallitas = df_kiszallitas.sort_values(by='Sorrend_num')

        # 🛡️ GOLYÓÁLLÓ AUTOMATIKUS LÁDÁZÁS (Nem engedi az üres sárga hibaoldalt!)
        bepakolt_sorok = []
        for idx_b, row_b in df_kiszallitas.iterrows():
            felhos_statusz = str(row_b.get('Státusz', '')).strip().lower()
            if felhos_statusz in ["kézbesítve", "kezbesitve", "teljesítve"]:
                st.session_state[f"kiszallitva_{idx_b}"] = True

            lada_k = f"lada_szam_tarolt_{idx_b}"
            if st.session_state.get(lada_k) is None:
                st.session_state[lada_k] = str(row_b.get('Láda', '1. láda'))
            bepakolt_sorok.append((idx_b, row_b))

        osszes_bepakolt = len(bepakolt_sorok)
        kesz_cimek = sum(1 for idx_c, _ in bepakolt_sorok if st.session_state.get(f"kiszallitva_{idx_c}", False))

        # Haladási sáv
        hatralevo_db = max(0, osszes_bepakolt - kesz_cimek)
        szazalek = int((kesz_cimek / osszes_bepakolt) * 100) if osszes_bepakolt > 0 else 0

        st.markdown(f"""
        <div style="margin-top: -6px; margin-bottom: 2px; padding: 0 2px;">
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; font-weight: 800; color: #334155;">
                <span>🚚 Kézbesítve: <b style="color: #16A34A;">{kesz_cimek}</b> / {osszes_bepakolt} ({szazalek}%)</span>
                <span>Hátralévő: <b style="color: #EA580C;">{hatralevo_db}</b></span>
            </div>
            <div style="width: 100%; background-color: #E2E8F0; height: 3.5px; border-radius: 2px; overflow: hidden; margin-top: 1px;">
                <div style="width: {szazalek}%; background: #16A34A; height: 100%;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Aktív és hátralévő megállók felmérése
        elokeszitett_sorok = [pair for pair in bepakolt_sorok if not st.session_state.get(f"kiszallitva_{pair[0]}", False)]
        
        # Kiemelt cím előresorolása, ha rákerestek
        kiemelt_id = st.session_state.get("kiemelt_ugyfel_id", None)
        if kiemelt_id:
            talalt_kiemelt = None
            for s_idx, (idx_e, row_e) in enumerate(elokeszitett_sorok):
                if str(row_e.get('ID', idx_e)).strip() == kiemelt_id:
                    talalt_kiemelt = elokeszitett_sorok.pop(s_idx)
                    break
            if talalt_kiemelt:
                elokeszitett_sorok.insert(0, talalt_kiemelt)

        if not elokeszitett_sorok:
            st.success("🎉 Minden mai címedet sikeresen teljesítetted!")
            return

        # 🗺️ Térkép klaszterek készítése
        cimek_sorban = []
        for idx_m, row_m in elokeszitett_sorok:
            m_lat = str(row_m.get(lat_oszlop, "")).strip().replace(',', '.')
            m_lon = str(row_m.get(lon_oszlop, "")).strip().replace(',', '.')
            if m_lat and m_lon and m_lat != "nan" and m_lon != "nan":
                cimek_sorban.append({
                    "id": str(row_m.get('ID', idx_m)),
                    "sorrend": int(row_m['Sorrend_num']),
                    "name": str(row_m[nev_oszlop]),
                    "address": str(row_m[cim_oszlop]),
                    "lat": float(m_lat),
                    "lon": float(m_lon)
                })

        active_map_clusters = []
        if cimek_sorban:
            cimek_sorban.sort(key=lambda x: x["sorrend"])
            aktualis_klaszter = [cimek_sorban[0]]
            for c in cimek_sorban[1:]:
                elozo = aktualis_klaszter[-1]
                c1 = re.sub(r'[\s,\./]+', '', elozo["address"].lower())
                c2 = re.sub(r'[\s,\./]+', '', c["address"].lower())
                if c["sorrend"] == (elozo["sorrend"] + 1) and (c1 in c2 or c2 in c1):
                    aktualis_klaszter.append(c)
                else:
                    all_stops = [x["sorrend"] for x in aktualis_klaszter]
                    first = aktualis_klaszter[0]
                    lbl = str(all_stops[0]) if len(all_stops) == 1 else f"{all_stops[0]}-{all_stops[-1]}"
                    rows_h = "".join([f"<div style='margin-bottom:2px;'><b>#{x['sorrend']} - {x['name']}</b></div>" for x in aktualis_klaszter])
                    pop_h = f"<div style='font-size:11px; font-family:sans-serif;'>{rows_h}<span style='color:#4B5563;'>🏠 {first['address']}</span></div>"
                    active_map_clusters.append({
                        "lat": first["lat"], "lon": first["lon"], "label": lbl,
                        "count": len(aktualis_klaszter), "popup": pop_h, "min_stop": min(all_stops)
                    })
                    aktualis_klaszter = [c]
            if aktualis_klaszter:
                all_stops = [x["sorrend"] for x in aktualis_klaszter]
                first = aktualis_klaszter[0]
                lbl = str(all_stops[0]) if len(all_stops) == 1 else f"{all_stops[0]}-{all_stops[-1]}"
                rows_h = "".join([f"<div style='margin-bottom:2px;'><b>#{x['sorrend']} - {x['name']}</b></div>" for x in aktualis_klaszter])
                pop_h = f"<div style='font-size:11px; font-family:sans-serif;'>{rows_h}<span style='color:#4B5563;'>🏠 {first['address']}</span></div>"
                active_map_clusters.append({
                    "lat": first["lat"], "lon": first["lon"], "label": lbl,
                    "count": len(aktualis_klaszter), "popup": pop_h, "min_stop": min(all_stops)
                })

        # 🗺️ 165PX MAGAS TÖMÖRÍTETT LEAFLET TÉRKÉP ÉLŐ GPS KÖVETÉSSEL
        if active_map_clusters:
            current_target = active_map_clusters[0]
            clusters_json = json.dumps(active_map_clusters, ensure_ascii=False)
            c_lat = current_target['lat']
            c_lon = current_target['lon']

            html_map = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
                <style>
                    html, body, #map {{ height: 100%; width: 100%; margin: 0; padding: 0; }}
                    .single-marker {{ background: #139D43; border: 1.5px solid white; border-radius: 50%; color: white; font-weight: bold; text-align: center; line-height: 20px; font-size: 9.5px; box-shadow: 0 2px 4px rgba(0,0,0,0.25); }}
                    .multi-marker {{ background: #0284C7; border: 2px solid white; border-radius: 12px; color: white; font-weight: 800; text-align: center; line-height: 20px; font-size: 9.5px; padding: 0 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.25); white-space: nowrap; }}
                    .current-marker {{ background: #E1251B !important; border: 2.5px solid white; border-radius: 50%; color: white; font-weight: bold; text-align: center; line-height: 23px; font-size: 11px; box-shadow: 0 3px 8px rgba(225,37,27,0.7); }}
                    .current-multi-marker {{ background: #E1251B !important; border: 2.5px solid white; border-radius: 12px; color: white; font-weight: 800; text-align: center; line-height: 22px; font-size: 11px; padding: 0 5px; box-shadow: 0 3px 8px rgba(225,37,27,0.7); white-space: nowrap; }}
                    .user-dot {{ width: 13px; height: 13px; background: #2563EB; border: 2px solid white; border-radius: 50%; box-shadow: 0 0 5px rgba(0,0,0,0.5); }}
                </style>
            </head>
            <body>
                <div id="map"></div>
                <script>
                    var clusters = {clusters_json};
                    var map = L.map('map', {{zoomControl: false}}).setView([{c_lat}, {c_lon}], 14);
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

                    clusters.forEach(function(c, index) {{
                        var isFirst = (index === 0);
                        var isMulti = (c.count > 1);
                        var iconClass = isFirst ? (isMulti ? 'current-multi-marker' : 'current-marker') : (isMulti ? 'multi-marker' : 'single-marker');
                        var iconSize = isFirst ? (isMulti ? [44, 25] : [27, 27]) : (isMulti ? [36, 21] : [21, 21]);
                        var icon = L.divIcon({{ className: iconClass, html: c.label, iconSize: iconSize }});
                        var markerOptions = {{ icon: icon }};
                        if (isFirst) markerOptions.zIndexOffset = 10000;
                        L.marker([c.lat, c.lon], markerOptions).bindPopup(c.popup).addTo(map);
                    }});

                    var userMarker = null;
                    if ("geolocation" in navigator) {{
                        navigator.geolocation.watchPosition(function(pos) {{
                            var lat = pos.coords.latitude;
                            var lng = pos.coords.longitude;
                            if (!userMarker) {{
                                userMarker = L.marker([lat, lng], {{
                                    icon: L.divIcon({{className: 'user-dot', iconSize: [13, 13]}}),
                                    zIndexOffset: 15000
                                }}).addTo(map);
                            }} else {{
                                userMarker.setLatLng([lat, lng]);
                            }}
                        }}, null, {{enableHighAccuracy: true, maximumAge: 3000}});
                    }}
                </script>
            </body>
            </html>
            """
            components.html(html_map, height=165)

        # =========================================================================
        # 🏢 CSOPORTOS LEADÁS (PAPÍR SZERINTI CSOPORT + AZONOS CÍM ALAPJÁN)
        # =========================================================================
        elso_idx, elso_row = elokeszitett_sorok[0]
        elso_csoport = str(elso_row.get(csoport_oszlop, '')).strip() if csoport_oszlop else ''
        elso_cim = str(elso_row[cim_oszlop]).strip().lower()

        azonos_csoport_vevok = []
        for s_idx, s_row in elokeszitett_sorok:
            s_csop = str(s_row.get(csoport_oszlop, '')).strip() if csoport_oszlop else ''
            s_cim = str(s_row[cim_oszlop]).strip().lower()

            if (elso_csoport not in ['', 'nan'] and s_csop == elso_csoport) or (s_cim == elso_cim):
                azonos_csoport_vevok.append((s_idx, s_row))
            else:
                break

        # TÖMEGES LEADÓ GOMB CSOPORTRA
        if len(azonos_csoport_vevok) > 1:
            st.markdown(
                f"""
                <div style="background-color: #EEF2FF; border: 1.5px solid #6366F1; border-radius: 8px; padding: 6px 10px; margin-top: 6px; margin-bottom: 4px;">
                    <div style="font-size: 12.5px; font-weight: 800; color: #3730A3;">🏢 ÖSSZEVONT MEGÁLLÓ ({len(azonos_csoport_vevok)} cím a csoportban)</div>
                    <div style="font-size: 11px; color: #4338CA;">Recepción/depónál egyetlen gombbal leadható az összes tétel.</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            if st.button(f"⚡ ÖSSZES ÁTADVA EBBEN A CSOPORTBAN ({len(azonos_csoport_vevok)} db)", type="primary", use_container_width=True, key=f"batch_lead_{elso_idx}"):
                b_ids = []
                for b_i, b_r in azonos_csoport_vevok:
                    st.session_state[f"kiszallitva_{b_i}"] = True
                    b_ids.append(str(b_r.get('ID', b_i)).strip())
                
                def _b_sync(client_ref, sheet_id_ref, id_list):
                    try:
                        sh_s = client_ref.open_by_key(sheet_id_ref)
                        ws_s = sh_s.worksheet("Adatok")
                        hdrs = ws_s.row_values(1)
                        if "Státusz" in hdrs and "ID" in hdrs:
                            s_col = hdrs.index("Státusz") + 1
                            id_col = hdrs.index("ID") + 1
                            all_i = ws_s.col_values(id_col)
                            for r_i, val_i in enumerate(all_i[1:], start=2):
                                if str(val_i).strip() in id_list:
                                    ws_s.update_cell(r_i, s_col, "Kézbesítve")
                    except Exception as err:
                        print("Csoportos szinkron hiba:", err)

                t_b = threading.Thread(target=_b_sync, args=(client, SHEET_ID_UGYFELKOR, b_ids))
                t_b.daemon = True
                t_b.start()
                st.toast("🎉 Csoport sikeresen leigazolva!")
                st.rerun()

        # =========================================================================
        # 📋 AKTUÁLIS CÍM KÁRTYÁJA (FESZES ELRENDEZÉSSEL)
        # =========================================================================
        aktualis_sor_idx, row = elokeszitett_sorok[0]
        customer_id = str(row.get('ID', '')).strip()
        vevo_neve = str(row[nev_oszlop]).strip()
        aktualis_cim = str(row[cim_oszlop]).strip()
        vevo_tel = str(row.get(tel_oszlop, '')).strip()
        aktualis_rendeles = str(row[rendeles_oszlop]).strip() if rendeles_oszlop in row else ""
        sorszam = row.get("Sorrend_num", 1)

        megjegyzes_nyers = str(row.get('Megjegyzés', row.get('Megjegyzes', ''))).strip()
        megj_html = f"<div style='font-size:11px; background:#FEF3C7; color:#92400E; padding:3px 6px; border-radius:4px; margin-top:2px;'>🔔 {megjegyzes_nyers}</div>" if megjegyzes_nyers and megjegyzes_nyers.lower() != 'nan' else ""

        lada_str = st.session_state.get(f"lada_szam_tarolt_{aktualis_sor_idx}", str(row.get('Láda', '1. láda')))

        # Kompakt kártya doboz
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%); border: 1.5px solid #93C5FD; border-radius: 8px; padding: 6px 10px; margin-top: 4px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:800; font-size:13px; color:#1E293B;">📍 #{sorszam}. Cím</span>
                <span style="background:#EEF2FF; color:#4338CA; font-size:10px; font-weight:800; padding:1px 5px; border-radius:4px;">📦 {lada_str}</span>
            </div>
            <div style="font-size:15px; font-weight:bold; color:#1E3A8A; margin-top:1px;">👤 {vevo_neve}</div>
            <div style="font-size:12px; color:#4B5563;">🏠 {aktualis_cim}</div>
            {megj_html}
            <div style="font-size:11.5px; font-weight:bold; color:#DC2626; margin-top:3px;">📦 Rendelés: {aktualis_rendeles}</div>
        </div>
        """, unsafe_allow_html=True)

        # --- ⏭️ KÖVETKEZŐ CÍM ELŐNÉZET (PREVIEW SÁV) ---
        if len(elokeszitett_sorok) > 1:
            kov_idx, kov_row = elokeszitett_sorok[1]
            kov_sorszam = kov_row.get("Sorrend_num", 2)
            kov_nev = str(kov_row[nev_oszlop]).strip()
            kov_cim = str(kov_row[cim_oszlop]).strip()
            kov_rendeles = str(kov_row[rendeles_oszlop]).strip() if rendeles_oszlop in kov_row else ""
            
            st.markdown(
                f"""
                <div style="background-color: #F8FAFC; border-left: 3.5px solid #0284C7; border: 1px solid #E2E8F0; padding: 3px 6px; border-radius: 4px; margin: 3px 0; font-size: 11px; color: #334155; display: flex; align-items: center; justify-content: space-between;">
                    <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <b>⏭️ Köv.:</b> <span style="font-weight: 700; color: #0284C7;">#{kov_sorszam}.</span> {kov_nev} <span style="color: #64748B;">({kov_cim})</span>
                    </div>
                    <span style="font-weight: 700; color: #DC2626; margin-left: 4px; flex-shrink: 0;">📦 {kov_rendeles}</span>
                </div>
                """, 
                unsafe_allow_html=True
            )

        # 📞 Telefonszám előállítása
        tarcsazhato_tel = re.sub(r'\D', '', str(vevo_tel))
        if tarcsazhato_tel.startswith("06"): tarcsazhato_tel = "+36" + tarcsazhato_tel[2:]
        elif tarcsazhato_tel.startswith("36"): tarcsazhato_tel = "+" + tarcsazhato_tel
        elif tarcsazhato_tel: tarcsazhato_tel = "+36" + tarcsazhato_tel

        maps_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(aktualis_cim)}"
        hivas_btn = f'<a href="tel:{tarcsazhato_tel}" target="_blank" style="text-decoration:none;"><button style="width:100%; height:34px; background:#22C55E; color:white; border:none; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">📞 Hívás</button></a>' if tarcsazhato_tel else '<button style="width:100%; height:34px; background:#9CA3AF; color:white; border:none; border-radius:6px; opacity:0.6;" disabled>📞 Nincs</button>'
        nav_btn = f'<a href="{maps_url}" target="_blank" style="text-decoration:none;"><button style="width:100%; height:34px; background:#3B82F6; color:white; border:none; border-radius:6px; font-weight:bold; font-size:12px; cursor:pointer;">🗺️ Navigáció</button></a>'

        # 📱 3 GOMB KÉNYSZERÍTÉSE EGYETLEN SORBA (MOBIL TÖMÖRÍTÉS)
        st.markdown(
            """
            <style>
            /* Megakadályozza, hogy mobilon egymás alá törjön a 3 gomb oszlopa */
            div[data-testid="stHorizontalBlock"]:has(button[key^="togg_msg_"]) {
                display: flex !important;
                flex-direction: row !important;
                flex-wrap: nowrap !important;
                gap: 5px !important;
                align-items: center !important;
                margin-top: 6px !important;
                margin-bottom: 4px !important;
            }
            div[data-testid="stHorizontalBlock"]:has(button[key^="togg_msg_"]) > div[data-testid="column"] {
                flex: 1 1 0px !important;
                min-width: 0 !important;
                width: 33.3% !important;
            }
            div[data-testid="stHorizontalBlock"]:has(button[key^="togg_msg_"]) button {
                width: 100% !important;
                height: 36px !important;
                font-size: 12px !important;
                padding: 0 2px !important;
                white-space: nowrap !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
            }
            </style>
            """,
            unsafe_allow_html=True
        )

        col_b1, col_b2, col_b3 = st.columns([1, 1, 1])
        with col_b1:
            st.markdown(hivas_btn, unsafe_allow_html=True)
        with col_b2:
            msg_panel_key = f"show_msg_panel_{aktualis_sor_idx}"
            if msg_panel_key not in st.session_state:
                st.session_state[msg_panel_key] = False
            if st.button("💬 Üzenet", key=f"togg_msg_{aktualis_sor_idx}", use_container_width=True):
                st.session_state[msg_panel_key] = not st.session_state[msg_panel_key]
                st.rerun()
        with col_b3:
            st.markdown(nav_btn, unsafe_allow_html=True)

        # =========================================================================
        # 💬 LENYÍLÓ ÜZENETKÜLDŐ PANEL (SMS / VIBER SABLONOKKAL)
        # =========================================================================
        if st.session_state.get(f"show_msg_panel_{aktualis_sor_idx}", False):
            with st.container(border=True):
                st.markdown("<span style='font-size: 11.5px; font-weight: bold; color: #475569;'>✉️️ Gyors üzenet küldése:</span>", unsafe_allow_html=True)
                if not tarcsazhato_tel:
                    st.warning("Nincs megadva telefonszám!")
                else:
                    sablon_opciok = [
                        "Jó napot kívánok! Megérkeztem az InterFood ebéddel a címre.",
                        "2 perc és ott vagyok az étellel...",
                        "A recepción/portán hagytam az ételt, jó étvágyat kívánok!",
                        "Itt állok a kapuban/lépcsőháznál, kérem vegye át az ételt!",
                        "✏️ Egyedi üzenetet írok..."
                    ]
                    valasztott_sablon = st.selectbox("Sablon:", sablon_opciok, key=f"sel_msg_{aktualis_sor_idx}", label_visibility="collapsed")
                    vegleges_uzenet = st.text_input("Egyedi szöveg:", value="2 perc és ott vagyok...", key=f"inp_msg_{aktualis_sor_idx}") if valasztott_sablon == "✏️ Egyedi üzenetet írok..." else valasztott_sablon
                    encoded_msg = urllib.parse.quote(vegleges_uzenet)
                    sms_link = f"sms:{tarcsazhato_tel}?body={encoded_msg}"
                    viber_link = f"viber://chat?number={urllib.parse.quote(tarcsazhato_tel)}"

                    cs1, cs2 = st.columns(2)
                    cs1.markdown(f'<a href="{sms_link}" target="_blank" style="text-decoration:none;"><button style="width:100%; height:32px; background:#0284C7; color:white; border:none; border-radius:5px; font-weight:bold; font-size:11.5px;">📨 SMS</button></a>', unsafe_allow_html=True)
                    cs2.markdown(f'<a href="{viber_link}" target="_blank" style="text-decoration:none;"><button style="width:100%; height:32px; background:#7360F2; color:white; border:none; border-radius:5px; font-weight:bold; font-size:11.5px;">🟣 Viber</button></a>', unsafe_allow_html=True)

        # =========================================================================
        # 🛠️ CÍM KORRIGÁLÁSA, ÁTRENDEZÉS & ÉLŐ GPS MENTÉS
        # =========================================================================
        with st.expander("🛠️️ Cím korrigálása & Átrendezés", expanded=False):
            st.markdown("<b>🔍 Útba eső cím azonnali aktiválása:</b>", unsafe_allow_html=True)
            options_ugras = ["--- Válassz egy megállót ---"]
            id_mapping_ugras = {}
            for idx_u, row_u in elokeszitett_sorok:
                u_id = str(row_u['ID']).strip()
                lbl_u = f"📍 #{row_u.get('Sorrend_num')} — {str(row_u[nev_oszlop]).strip()}"
                options_ugras.append(lbl_u)
                id_mapping_ugras[lbl_u] = u_id
            
            valasztott_gyorsugras = st.selectbox("Megálló keresése:", options=options_ugras, key=f"sel_jump_{aktualis_sor_idx}", label_visibility="collapsed")
            if valasztott_gyorsugras != "--- Válassz egy megállót ---":
                st.session_state.kiemelt_ugyfel_id = id_mapping_ugras[valasztott_gyorsugras]
                st.rerun()

            st.markdown("<hr style='margin:6px 0; border-top:1px dashed #D1D5DB;'>", unsafe_allow_html=True)
            st.markdown("<b>🔀 Sorrend módosítása:</b>", unsafe_allow_html=True)
            c_end, c_move = st.columns(2)
            if c_end.button("⬇️ Végére dobás", key=f"btn_end_{aktualis_sor_idx}", use_container_width=True):
                try:
                    sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                    ws_a = sh.worksheet("Adatok")
                    rows_a = ws_a.get_all_values()
                    hdr_a = rows_a[0]
                    df_s = pd.DataFrame(rows_a[1:], columns=hdr_a)
                    df_s['Sorrend'] = pd.to_numeric(df_s['Sorrend'], errors='coerce').fillna(999).astype(int)
                    df_s = df_s.sort_values(by='Sorrend').reset_index(drop=True)
                    t_idx = df_s[df_s['ID'].astype(str).str.strip() == customer_id].index[0]
                    t_row = df_s.loc[t_idx].copy()
                    df_s = df_s.drop(t_idx).reset_index(drop=True)
                    t_row['Sorrend'] = df_s['Sorrend'].max() + 1
                    df_s = pd.concat([df_s, pd.DataFrame([t_row])], ignore_index=True)
                    df_s['Sorrend'] = range(1, len(df_s) + 1)
                    ws_a.clear()
                    ws_a.update('A1', [hdr_a] + df_s.values.tolist(), value_input_option='USER_ENTERED')
                    st.session_state.pop("kiemelt_ugyfel_id", None)
                    st.session_state.mdf = df_s
                    st.cache_data.clear()
                    st.rerun()
                except Exception as err: st.error(f"Hiba: {err}")

            uj_pozicio = c_move.number_input("Új sorszám:", min_value=1, max_value=120, value=2, key=f"inp_pos_{aktualis_sor_idx}")
            if c_move.button("👉 Áthelyezés", key=f"btn_pos_{aktualis_sor_idx}", use_container_width=True):
                try:
                    sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                    ws_a = sh.worksheet("Adatok")
                    rows_a = ws_a.get_all_values()
                    hdr_a = rows_a[0]
                    df_s = pd.DataFrame(rows_a[1:], columns=hdr_a)
                    df_s['Sorrend'] = pd.to_numeric(df_s['Sorrend'], errors='coerce').fillna(999).astype(int)
                    df_s = df_s.sort_values(by='Sorrend').reset_index(drop=True)
                    t_idx = df_s[df_s['ID'].astype(str).str.strip() == customer_id].index[0]
                    t_row = df_s.loc[t_idx].copy()
                    df_s = df_s.drop(t_idx).reset_index(drop=True)
                    ins_idx = min(len(df_s), int(uj_pozicio) - 1)
                    df_s = pd.concat([df_s.iloc[:ins_idx], pd.DataFrame([t_row]), df_s.iloc[ins_idx:]], ignore_index=True)
                    df_s['Sorrend'] = range(1, len(df_s) + 1)
                    ws_a.clear()
                    ws_a.update('A1', [hdr_a] + df_s.values.tolist(), value_input_option='USER_ENTERED')
                    st.session_state.pop("kiemelt_ugyfel_id", None)
                    st.session_state.mdf = df_s
                    st.cache_data.clear()
                    st.rerun()
                except Exception as err: st.error(f"Hiba: {err}")

            st.markdown("<hr style='margin:6px 0; border-top:1px dashed #D1D5DB;'>", unsafe_allow_html=True)
            st.markdown("<b>🎯 Pontos kapu-koordináta mentése a kék pöttyel:</b>", unsafe_allow_html=True)
            
            # Közvetlen natív GPS kinyerés
            if st.button("📍 JELENLEGI GPS MENTÉSE A KAPUHOZ", use_container_width=True, key=f"save_live_gps_{aktualis_sor_idx}"):
                components.html(f"""
                <script>
                    if (navigator.geolocation) {{
                        navigator.geolocation.getCurrentPosition(function(pos) {{
                            const lat = pos.coords.latitude;
                            const lon = pos.coords.longitude;
                            const u = new URL(window.top.location.href);
                            u.searchParams.set("kapu_lat", lat);
                            u.searchParams.set("kapu_lon", lon);
                            u.searchParams.set("target_cid", "{customer_id}");
                            window.top.location.href = u.toString();
                        }}, function(err) {{
                            alert("GPS hiba: " + err.message);
                        }}, {{enableHighAccuracy: true, timeout: 5000}});
                    }}
                </script>
                """, height=0, width=0)

        # GPS Mentés Feldolgozó Hook
        if "kapu_lat" in st.query_params and "kapu_lon" in st.query_params:
            k_lat = float(st.query_params.get("kapu_lat"))
            k_lon = float(st.query_params.get("kapu_lon"))
            t_cid = st.query_params.get("target_cid", customer_id)
            try:
                sh_geo = client.open_by_key(SHEET_ID_UGYFELKOR)
                ws_geo = sh_geo.worksheet("Adatok")
                h_geo = ws_geo.row_values(1)
                lat_c = h_geo.index(lat_oszlop) + 1
                lon_c = h_geo.index(lon_oszlop) + 1
                id_c = h_geo.index("ID") + 1
                
                rows_ids = ws_geo.col_values(id_c)
                for r_idx, v_id in enumerate(rows_ids[1:], start=2):
                    if str(v_id).strip() == str(t_cid).strip():
                        ws_geo.update_cell(r_idx, lat_c, k_lat)
                        ws_geo.update_cell(r_idx, lon_c, k_lon)
                        break
                st.query_params.clear()
                st.query_params.update(view="mobile", active_tab="kiszallitas")
                st.toast(f"🎯 Pozíció sikeresen frissítve a kapuhoz: {k_lat}, {k_lon}")
                time.sleep(0.5)
                st.rerun()
            except Exception as e_geo:
                st.error(f"Koordináta mentési hiba: {e_geo}")

        # Pénzügyi mező
        elovart_osszeg = 0
        if penz_oszlop:
            try:
                tiszta_p = str(row[penz_oszlop]).replace("Ft","").replace(" ","").replace("\xa0","").strip()
                elovart_osszeg = int(float(tiszta_p))
            except: elovart_osszeg = 0

        if elovart_osszeg > 0:
            st.write(f"💵 **Fizetendő KP:** {elovart_osszeg:,} Ft")
        elif elovart_osszeg < 0:
            st.markdown(f"<div style='color:#047857; background:#ECFDF5; padding:4px 8px; border-radius:5px; font-size:12px; font-weight:bold;'>💳 <b>Túlfizetés:</b> {abs(elovart_osszeg):,} Ft (Visszaadható KP)</div>", unsafe_allow_html=True)

        atvett_osszeg = st.number_input(
            "Átvett (+) / Visszaadott (-) összeg (Ft):", 
            min_value=-50000, max_value=100000, 
            value=int(max(0, elovart_osszeg)), 
            step=50, 
            key=f"fizet_kp_{aktualis_sor_idx}"
        )

        # ✅ SIKERES KÉZBESÍTÉS GOMB (IDŐBÉLYEGGEL ÉS VALÓS GPS-SZEL)
        if st.button("✅ Sikeres kézbesítés", key=f"siker_btn_{aktualis_sor_idx}", use_container_width=True, type="primary"):
            st.session_state[f"kiszallitva_{aktualis_sor_idx}"] = True
            st.session_state.pop("kiemelt_ugyfel_id", None)
            
            most_ido = datetime.now().strftime("%H:%M:%S")
            def _async_single_save(client_ref, sheet_id_ref, cust_id_ref, ido_ref):
                try:
                    sh_one = client_ref.open_by_key(sheet_id_ref)
                    ws_one = sh_one.worksheet("Adatok")
                    hdrs = ws_one.row_values(1)
                    if "Státusz" in hdrs and "ID" in hdrs:
                        s_col = hdrs.index("Státusz") + 1
                        i_col = hdrs.index("ID") + 1
                        t_col = hdrs.index("Kezbesites_Ido") + 1 if "Kezbesites_Ido" in hdrs else None
                        
                        all_i = ws_one.col_values(i_col)
                        for r_idx, val_id in enumerate(all_i[1:], start=2):
                            if str(val_id).strip() == str(cust_id_ref).strip():
                                ws_one.update_cell(r_idx, s_col, "Kézbesítve")
                                if t_col: ws_one.update_cell(r_idx, t_col, ido_ref)
                                break
                except Exception as e_s:
                    print("Mentési hiba:", e_s)

            t_save = threading.Thread(target=_async_single_save, args=(client, SHEET_ID_UGYFELKOR, customer_id, most_ido))
            t_save.daemon = True
            t_save.start()
            
            st.toast(f"🎉 {vevo_neve} teljesítve!")
            st.rerun()

    except Exception as e:
        st.error(f"Hiba a kiszállítás modulban: {e}")
