# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import os
import re
import pdfplumber
import datetime

# --- KAPCSOLÓDÓ SEGÉDFÜGGVÉNYEK ---
from parser_modul import parse_interfood_pdf, extract_all_meta, merge_data
from adatbazis_modul import (
    get_latest_week_from_master, sync_master_database, 
    load_futar_from_sheets, save_futar_to_sheets,
    load_etlap_from_sheets, sync_interfood_etlap, master_lista_szinkron,
    kotelezo_ugyfelkor_formatum_tisztitas,
    load_sheet_data_cached, ellenoriz_nominatim_kapcsolat, SHEET_ID_UGYFELKOR
)
from nyomtatas_modulok import create_label_pdf, create_manifest_pdf, create_raklista_pdf
from vizualizacio import utvonal_terkep
from utils import check_user_role, clean_text
from admin_modul import render_logisztikai_kozpont

# --- RENDELÉSI KÓD REGEX MINTA (Szigorú illesztés pl. 1-A1* vagy 4-S1) ---
ORDER_PAT = r'(\d+)-([A-Z0-9*]+)'

def render_mobil_sidebar_dashboard(client, SHEET_ID_UGYFELKOR, SHEET_ID):
    """
    Kirajzolja a mobil nézet élő Google Sheets adataira épülő műszerfalát.
    Szuper kompakt elrendezésben, dinamikus és név-pontos hibabejelentővel, precíz div-alapú elválasztóvonalakkal.
    """
    st.markdown(
        """
        <style>
        /* Sidebar felső sáv finomítása */
        div[data-testid="stSidebarUserContent"] {
            padding-top: 0.8rem !important;
            margin-top: -2.2rem !important;
        }
        /* Metric kártyák tömörítése */
        [data-testid="stSidebarUserContent"] [data-testid="stMetricValue"] {
            font-size: 1.05rem !important;
            font-weight: 800 !important;
            line-height: 1.1 !important;
        }
        [data-testid="stSidebarUserContent"] [data-testid="stMetricLabel"] {
            font-size: 0.68rem !important;
            font-weight: 600 !important;
            line-height: 1.1 !important;
            color: #4B5563 !important;
            margin-bottom: 2px !important;
        }
        [data-testid="stSidebarUserContent"] [data-testid="stMetric"] {
            padding: 0px !important;
            margin-bottom: 1px !important;
        }
        [data-testid="stSidebarUserContent"] div[data-testid="stVerticalBlock"] {
            gap: 0.3rem !important;
        }
        [data-testid="stSidebarUserContent"] h2 {
            font-size: 1.15rem !important;
            margin-top: 0px !important;
            margin-bottom: 4px !important;
        }
        [data-testid="stSidebarUserContent"] h3 {
            font-size: 0.85rem !important;
            margin-top: 4px !important;
            margin-bottom: 2px !important;
        }
        [data-testid="stSidebarUserContent"] hr {
            display: none !important;
            margin-top: 0px !important;
            margin-bottom: 0px !important;
        }
        [data-testid="stSidebarUserContent"] p, [data-testid="stSidebarUserContent"] span {
            margin-top: 0px !important;
            margin-bottom: 0px !important;
            line-height: 1.2 !important;
        }
        [data-testid="stSidebarUserContent"] div[data-baseweb="select"] {
            font-size: 0.8rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown("<h2 style='text-align: center; color: #1E3A8A; margin-bottom: 6px;'>📊 Mai Műszerfal</h2>", unsafe_allow_html=True)
    
    futar_nev_kiir = st.session_state.get('user_nev', 'Ismeretlen Futár')
    jarat_lista_kiir = st.session_state.get('user_jarat_lista', [])
    jarat_szoveg_kiir = ", ".join(map(str, jarat_lista_kiir)) if jarat_lista_kiir else "Nincs"
    
    st.write(f"👤 **Futár:** {futar_nev_kiir} | 🚚 **Járat:** {jarat_szoveg_kiir}")

    # Alapértelmezett elszámolási mérők
    osszes_cim = 0
    osszes_megallo = 0
    osszes_etel = 0
    forgalmi_ertek = 0
    jutalek = 0

    try:
        sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
        summary_records_df = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Mobil_Summary")
        summary_records = summary_records_df.to_dict('records') if not summary_records_df.empty else []
        
        kivalasztott = st.session_state.get('kivalasztott_datum', datetime.date.today())
        kivalasztott_iso = kivalasztott.strftime("%Y-%m-%d") if isinstance(kivalasztott, datetime.date) else str(kivalasztott)

        futar_keresett = str(futar_nev_kiir).strip().lower()

        driver_records = []
        for s_row in summary_records:
            summary_futar = str(s_row.get('Futar', s_row.get('futar', ''))).strip().lower()
            if summary_futar == futar_keresett or summary_futar == "szűcs istván":
                driver_records.append(s_row)

        if driver_records:
            matched_row = None
            for row in driver_records:
                row_date = str(row.get('Datum', row.get('datum', ''))).strip()
                if row_date == kivalasztott_iso:
                    matched_row = row
                    break
            
            if not matched_row:
                driver_records_sorted = sorted(
                    driver_records, 
                    key=lambda x: str(x.get('Datum', x.get('datum', ''))).strip(), 
                    reverse=True
                )
                matched_row = driver_records_sorted[0]
                most_recent_date_str = str(matched_row.get('Datum', matched_row.get('datum', ''))).strip()
                st.session_state['kivalasztott_datum'] = datetime.datetime.strptime(most_recent_date_str, "%Y-%m-%d").date()

            if matched_row:
                forgalmi_ertek = int(matched_row.get('Forgalom_Osszes', matched_row.get('Forgalom', 0)))
                jutalek = int(matched_row.get('Vart_Jutalek', matched_row.get('Jutalék', 0)))
                osszes_etel = int(matched_row.get('Osszes_Etel', matched_row.get('Terv_Darabszam', 0)))
                osszes_megallo = int(matched_row.get('Tervezett_Megallok', matched_row.get('Tervezett_Megallok', 0)))
                osszes_cim = int(matched_row.get('Osszes_Cim', matched_row.get('Osszes_Cim', 0)))
            
            if not matched_row:
                try:
                    df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
                    if not df_adatok.empty:
                        df_adatok.columns = [c.strip() for c in df_adatok.columns]
                        if 'Feldolgozó Futár' in df_adatok.columns:
                            df_szurt = df_adatok[df_adatok['Feldolgozó Futár'] == futar_nev_kiir]
                            osszes_cim = len(df_szurt['Cím'].unique())
                except:
                    pass
        else:
            st.error("A Mobil_Summary munkalap teljesen üres!")
            return
    except Exception as e:
        st.error(f"❌ Nem sikerült elérni a Google Sheets-et: {e}")
        return

    # Élő kiszállítási mérők a Session State-ből
    live_kesz_cimek = 0
    live_beszedett_kp = 0
    live_borravalo = 0

    for k in list(st.session_state.keys()):
        if k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres":
            idx = k.split("_")[-1]
            live_kesz_cimek += 1
            try:
                live_beszedett_kp += int(st.session_state.get(f"atvett_input_{idx}", 0))
                live_borravalo += int(st.session_state.get(f"borravalo_{idx}", 0))
            except:
                pass

    # --- 1. SEPARATOR DIV ---
    st.markdown("<div style='margin: 18px 0 12px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)

    # --- 1. SZEKCIÓ: KISZÁLLÍTÁSI HALADÁS ---
    st.subheader("🏁 Kiszállítás Haladás")
    haladas_szazalek = min(1.0, live_kesz_cimek / osszes_cim) if osszes_cim > 0 else 0.0
    st.progress(haladas_szazalek)
    st.caption(f"Teljesítve: {live_kesz_cimek} / {osszes_cim} cím ({int(haladas_szazalek * 100)}%)")
    
    # --- 2. SEPARATOR DIV ---
    st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)

    # --- 2. SZEKCIÓ: PÉNZÜGY & MENNYISÉG ---
    st.subheader("💰 Pénzügy & Mennyiség")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("📍 Tervezett megállók", f"{osszes_megallo} db")
        st.metric("🏠 Összes cím (vevő)", f"{osszes_cim} db")
    with col_s2:
        st.metric("📦 Összes étel", f"{osszes_etel} adag")
        st.metric("💵 Rakományérték", f"{forgalmi_ertek:,} Ft".replace(",", " "))
        
    # --- 3. SEPARATOR DIV ---
    st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)

    # --- 3. SZEKCIÓ: ÉLŐ SZÁLLÍTÁSI MÉRŐK ---
    st.subheader("💸 Élő Elszámolás")
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        st.metric("💵 Beszedett KP aznap", f"{live_beszedett_kp:,} Ft".replace(",", " "))
        st.metric("⭐ Várható Jutalékod", f"{jutalek:,} Ft".replace(",", " "))
    with col_l2:
        st.metric("💰 Gyűjtött borravaló", f"{live_borravalo:,} Ft".replace(",", " "))

    # --- 4. SEPARATOR DIV ---
    st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)

    # --- 4. SZEKCIÓ: SÜRGŐS HIBAJELENTŐ ---
    st.subheader("⚠️ Probléma az úton?")
    with st.expander("🚨 SÜRGŐS HIBAKÜLDÉS (Gyorsmenü)"):
        st.write("Sérült, elcserélt vagy hiányzó étel gyors bejelentése a központnak:")
        
        vevo_options = ["-- Válassz helyszínt / vevőt --"]
        vevo_items_map = {}
        
        try:
            df_adatok_all = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok")
            if not df_adatok_all.empty:
                df_adatok_all.columns = [str(c).strip() for c in df_adatok_all.columns]
                
                futar_keresett_clean = str(futar_nev_kiir).strip().lower()
                text_active_routes = [str(j).strip() for j in jarat_lista_kiir]
                
                jarat_col_name = next((c for c in df_adatok_all.columns if 'járat' in c.lower() or 'jarat' in c.lower()), None)
                if jarat_col_name and text_active_routes:
                    df_szurt = df_adatok_all[df_adatok_all[jarat_col_name].astype(str).str.strip().isin(text_active_routes)]
                else:
                    df_szurt = df_adatok_all
                
                etlap = st.session_state.get('etlap_adatok', {})
                if not etlap:
                    try:
                        etlap = load_etlap_from_sheets(SHEET_ID)
                        st.session_state.etlap_adatok = etlap
                    except:
                        etlap = {}

                label_to_prefix = {"Hé": "H", "Ke": "K", "Sze": "S", "Csü": "C", "Pé": "P", "Szo": "Z"}
                prefix_to_num = {"H": "1", "K": "2", "S": "3", "C": "4", "P": "5", "Z": "6"}
                prefix_to_nev = {"H": "Hétfő", "K": "Kedd", "S": "Szerda", "C": "Csütörtök", "P": "Péntek", "Z": "Szombat"}

                for _, r in df_szurt.iterrows():
                    nev_val = str(r.get('Név', r.get('Nev', r.get('Ügyintéző', 'Névtelen')))).strip()
                    cim_val = str(r.get('Cím', r.get('Cim', 'Ismeretlen cím'))).strip()
                    rendeles_val = str(r.get('Rendelés', r.get('Rendeles', ''))).strip()
                    
                    label_szoveg = f"{nev_val} ({cim_val})"
                    if label_szoveg not in vevo_options:
                        vevo_options.append(label_szoveg)
                    
                    vevo_kajak = ["-- Válassz érintett ételt --"]
                    day_parts = rendeles_val.split('|')
                    for part in day_parts:
                        part = part.strip()
                        prefix = ""
                        for label, pfx in label_to_prefix.items():
                            if f"{label}:" in part:
                                prefix = pfx
                                break
                        if not prefix:
                            found_codes = re.findall(ORDER_PAT, part)
                            for qty, code in found_codes:
                                vevo_kajak.append(f"{qty}x [{code.strip().upper()}]")
                            continue
                            
                        found_codes = re.findall(ORDER_PAT, part)
                        for qty, code in found_codes:
                            keresett_kod = code.replace('*', '').strip().upper()
                            num_prefix = prefix_to_num.get(prefix, "1")
                            sheets_key = f"{num_prefix}_{keresett_kod}"
                            
                            info = etlap.get(sheets_key, {}) if etlap else {}
                            etel_nev = info.get('nev', 'Ismeretlen Étel')
                            day_name = prefix_to_nev.get(prefix, '')
                            
                            display_name = f"{qty}x [{code.strip().upper()}] — {etel_nev} ({day_name})"
                            vevo_kajak.append(display_name)
                    
                    if not day_parts and rendeles_val:
                        vevo_kajak.append(rendeles_val)
                    vevo_items_map[label_szoveg] = vevo_kajak
                    
        except Exception as e_dropdown_build:
            st.sidebar.error(f"Dropdown hiba: {e_dropdown_build}")

        st_hiba_vevo_selected = st.selectbox("Melyik megállónál vagy?", options=vevo_options, key="sidebar_hiba_vevo_dropdown")
        
        kaja_options_for_selected = ["-- Válassz érintett ételt --"]
        if st_hiba_vevo_selected != "-- Válassz helyszínt / vevőt --":
            kaja_options_for_selected = vevo_items_map.get(st_hiba_vevo_selected, ["-- Válassz érintett ételt --"])
            
        st_hiba_kaja_selected = st.selectbox("Melyik étellel van gond?", options=kaja_options_for_selected, key="sidebar_hiba_kaja_dropdown")
        st_hiba_tipus = st.selectbox("Hiba jellege:", ["Sérült étel (kifolyt/kilyukadt)", "Elcserélt étel", "Hiányzó/Elhagyott étel"], key="sidebar_hiba_tipus")
        st_hiba_leiras = st.text_area("Rövid kiegészítés (opcionális):", placeholder="Pl. a doboz teteje elrepedt.", key="sidebar_hiba_leiras")
        
        if st.button("🚨 HIBA KÜLDÉSE A DISZPÉCSERNEK", type="primary", use_container_width=True, key="sidebar_hiba_submit_btn"):
            if st_hiba_vevo_selected == "-- Válassz helyszínt / vevőt --" or st_hiba_kaja_selected == "-- Válassz érintett ételt --":
                st.error("❌ Kérlek, válaszd ki a vevőt és a sérült ételt is a listából!")
            else:
                is_test_mode = st.query_params.get("test", "false") == "true" or st.session_state.get('teszt_uzemmod', False)
                if is_test_mode:
                    st.warning("🧪 **Teszt mód:** A hibát sikeresen szimuláltuk.")
                else:
                    try:
                        hibak_sheet = client.open_by_key(SHEET_ID_UGYFELKOR).worksheet("Hibajelentések")
                        most_ido = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        hibak_sheet.append_row([most_ido, futar_nev_kiir, jarat_szoveg_kiir, st_hiba_tipus, st_hiba_vevo_selected, f"Étel: {st_hiba_kaja_selected} | Leírás: {st_hiba_leiras}"])
                        st.success("✅ A hiba sikeresen rögzítve! A diszpécserek azonnal értesültek róla.")
                    except Exception as e:
                        st.error(f"Mentési hiba: {e}")


def render_desktop_sidebar_controls(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, LOG_FILE):
    st.header("⚙️ Kezelés")
    is_admin = st.session_state.user_szerep in ["admin", "superadmin"]
    if is_admin:
        admin_funkcio = st.radio("📌 Válassz funkciót:", ["📋 Raklista & Étlap Kezelés", "🚚 Logisztikai Közenter & Stand"])
    else:
        admin_funkcio = "📋 Raklista & Étlap Kezelés"
    
    st.divider()
    st.session_state.c_n = st.text_input("Futár Neve", st.session_state.c_n)
    st.session_state.c_p = st.text_input("Telefonszám", st.session_state.c_p)
    kivalasztott_datum = st.date_input("📅 Kiszállítás dátuma (Névnaphoz)", key="kivalasztott_datum")
    
    st.divider()
    if 'teszt_uzemmod' not in st.session_state: st.session_state.teszt_uzemmod = False
    st.session_state.teszt_uzemmod = st.toggle("🧪 TESZT ÜZEMMÓD (Nincs mentés)", value=st.session_state.teszt_uzemmod)
    if st.session_state.teszt_uzemmod: st.warning("⚠️ Adatbázis mentés letiltva!")
    st.divider()

    if is_admin:
        st.subheader("🛡️ Adminisztrációs Központ")
        
        status_code, status_msg = ellenoriz_nominatim_kapcsolat()
        if status_code == "OK":
            st.success(f"📡 GPS Szerver: {status_msg}")
        elif status_code == "BLOCKED":
            st.error(f"📡 GPS Szerver: {status_msg}")
            st.warning("ℹ️ A felhős IP letiltva. Automatikus ArcGIS geokódolás van érvényben (golyóálló tartalék)!")
        else:
            st.warning(f"📡 GPS Szerver: {status_msg}")
            
        # ==============================================================================
        # 🛰️ GPS BATCH PÓTLÓ ESZKÖZ - MINDEN ADMINNAK LÁTHATÓ ÉS ELÉRHETŐ!
        # ==============================================================================
        with st.expander("🛰️ GPS Koordináták Tömeges Pótlása"):
            st.write("Megkeresi azokat az ügyfeleket a törzsadatbázisban, akiknek nincs mentett koordinátája, és automatikusan pótolja azokat az ArcGIS geokódoló segítségével (max 20 menetben).")
            if st.button("🛰️ HIÁNYZÓ GPS-EK AUTOMATIKUS PÓTLÁSA", key="desktop_batch_gps_btn", use_container_width=True):
                from adatbazis_modul import batch_potol_hianyozo_gps
                batch_potol_hianyozo_gps(client, SHEET_ID_UGYFELKOR)

        ev_most, het_most = get_latest_week_from_master(SHEET_ID_MASTER, client)
        if het_most < 24:
            st.error(f"⚠️ Étlap figyelmeztetés: Csak a **{het_most}. hétig** van feltöltve!")
            if st.button("🔄 Master Frissítése"):
                with st.spinner("Frissítés..."):
                    sync_master_database(SHEET_ID_MASTER, 2026, het_most + 1, 24)
                    st.rerun()
        else:
            st.success("✅ Étlapok naprakészek.")

        with st.expander("👤 Felhasználó Kezelés"):
            if 'futar_df' not in st.session_state: st.session_state.futar_df = load_futar_from_sheets(SHEET_ID_UGYFELKOR)
            df_to_edit = st.session_state.futar_df.astype(str)
            edited_df_users = st.data_editor(df_to_edit, use_container_width=True, num_rows="dynamic", key="user_editor")
            if st.button("💾 Módosítások mentése", key="user_save_btn"):
                with st.spinner("Mentés..."):
                    if save_futar_to_sheets(edited_df_users, SHEET_ID_UGYFELKOR):
                        st.session_state.futar_df = edited_df_users
                        st.success("Sikeres mentés!")
                        st.rerun()
                        
        # ==============================================================================
        # 🚨 SZUPERADMIN VESZÉLYES ZÓNA (MANUÁLIS TISZTÍTÁS ÉS OVERRIDE)
        # ==============================================================================
        if st.session_state.get('user_szerep') == "superadmin":
            with st.expander("🚨 Szuperadmin Veszélyes Zóna"):
                st.write("Ezzel a gombbal manuálisan kikényszerítheted a teljes Google Sheets ügyféllista tisztítását és koordináta-egységesítését.")
                if st.button("🚨 FUTTASD A GOOGLE SHEETS NAGYTAKARÍTÁST", key="superadmin_nagytakaritas_btn", use_container_width=True):
                    try:
                        with st.spinner("⏳ Adatbázis letöltése és elemzése..."):
                            sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                            worksheet = sh.worksheet("Ugyfelkor")
                            rows = worksheet.get_all_values()
                            
                            if not rows:
                                st.warning("A táblázat üres!")
                            else:
                                header = rows[0]
                                df_ugyfel = pd.DataFrame(rows[1:], columns=header)
                                df_cleaned = kotelezo_ugyfelkor_formatum_tisztitas(df_ugyfel)
                                
                                worksheet.clear()
                                worksheet.update('A1', [header] + df_cleaned.values.tolist(), value_input_option='USER_ENTERED')
                                st.success("🎉 SIKER! Az ügyfélkör adatbázis teljesen megtisztítva és egységesítve lett!")
                                st.balloons()
                                if 'ugyfelkor_df' in st.session_state:
                                    del st.session_state['ugyfelkor_df']
                                st.rerun()
                    except Exception as e:
                        st.error(f"Hiba a takarítás során: {e}")
                        
    return admin_funkcio

def process_uploaded_pdfs(up_files, client, sheet_id, ugyfelkor_sheet_id, kivalasztott_datum):
    import pandas as pd
    for key in ['ready_label_pdf', 'ready_manifest_pdf', 'ready_raklista_pdf']:
        if key in st.session_state: del st.session_state[key]
            
    meta_auto = extract_all_meta(up_files)
    st.session_state.meta_data = meta_auto
    ev, het = meta_auto.get('ev'), meta_auto.get('het')

    if ev and het:
        session_key = f"sync_{ev}_{het}"
        if session_key not in st.session_state:
            with st.spinner(f"Étlap szinkronizálása ({ev}/W{het})..."):
                sync_interfood_etlap(ev, het, sheet_id)
                st.session_state[session_key] = True

    with st.spinner("Étlap adatok beolvasása..."):
        etlap_adatok = load_etlap_from_sheets(sheet_id)
        st.session_state.etlap_adatok = etlap_adatok
        napi_kodok = set()
        for kulcs in etlap_adatok.keys():
            parts = kulcs.split("_")
            if len(parts) > 1: napi_kodok.add(parts[1].strip().upper())
        st.session_state.napi_etlap_kodok = napi_kodok

    all_rows = []
    if 'user_jarat_lista' not in st.session_state: st.session_state.user_jarat_lista = []

    for f in up_files:
        f.seek(0)
        egyedi_jarat_re = re.compile(r'(\d{2,4})\.\s*járat|Nyomtatta:\s*(\d{2,4})')
        with pdfplumber.open(f) as p_test:
            t_test = p_test.pages[0].extract_text() or ""
            m_test = egyedi_jarat_re.search(t_test)
            fajl_sajat_jarata = (m_test.group(1) or m_test.group(2)) if m_test else None
        
        if fajl_sajat_jarata and fajl_sajat_jarata not in st.session_state.user_jarat_lista:
            st.session_state.user_jarat_lista.append(fajl_sajat_jarata)

        f.seek(0)
        rows, _ = parse_interfood_pdf(f, napi_kodok)
        if rows:
            for r in rows: r['Járat'] = fajl_sajat_jarata if fajl_sajat_jarata else ""
            all_rows.extend(rows)

    if all_rows:
        df_temp = merge_data(all_rows)
        with st.spinner("Ügyféladatok szinkronizálása..."):
            mentett_meta = st.session_state.get('meta_data', None)
            tartalek_jarat = mentett_meta['jaratok'][0] if mentett_meta and mentett_meta.get('jaratok') else None
            df_temp, m_df_friss = master_lista_szinkron(df_temp, ugyfelkor_sheet_id, client, jarat_szam=tartalek_jarat)
            st.session_state.ugyfelkor_df = m_df_friss
        st.session_state.mdf = df_temp
        
        try:
            api_datum_kulcs = str(meta_auto.get('datum_kulcs', meta_auto.get('datum', kivalasztott_datum))).strip()
            aktualis_futar = str(st.session_state.get('user_nev', 'Szűcs István')).strip()
            feltoltott_jaratok = [j for j in df_temp['Járat'].dropna().astype(str).str.strip().unique().tolist() if j != "" and j.lower() != 'nan'] if 'Járat' in df_temp.columns else []
            jarat_szoveg = ", ".join(feltoltott_jaratok) if feltoltott_jaratok else "Nincs"

            szamitott_osszes_megallo = szamitott_osszes_cim = 0
            if 'Cím' in df_temp.columns:
                if 'Feldolgozó Futár' in df_temp.columns:
                    df_futar_szurt = df_temp[df_temp['Feldolgozó Futár'].astype(str).str.strip().str.lower() == aktualis_futar.lower()]
                    if not df_futar_szurt.empty:
                        szamitott_osszes_megallo = int(df_futar_szurt['Cím'].astype(str).str.strip().nunique())
                        szamitott_osszes_cim = len(df_futar_szurt)
                if szamitott_osszes_megallo == 0:
                    szamitott_osszes_megallo = int(df_temp['Cím'].astype(str).str.strip().nunique())
                    szamitott_osszes_cim = len(df_temp)

            label_to_prefix = {"Hé": "H", "Ke": "K", "Sze": "S", "Csü": "C", "Pé": "P", "Szo": "Z"}
            prefix_to_num = {"H": "1", "K": "2", "S": "3", "C": "4", "P": "5", "Z": "6"}
            etlap = st.session_state.get('etlap_adatok', {})

            counts = {}
            for _, r in df_temp.iterrows():
                order_str = str(r.get('Rendelés_Full', r.get('Rendelés', '')))
                day_parts = order_str.split('|')
                for part in day_parts:
                    part = part.strip()
                    prefix = ""
                    for label, pfx in label_to_prefix.items():
                        if f"{label}:" in part:
                            prefix = pfx
                            break
                    if not prefix: continue
                    
                    found = re.findall(ORDER_PAT, part)
                    for qty, code in found:
                        full_key = f"{prefix}_{code.strip().upper()}"
                        counts[full_key] = counts.get(full_key, 0) + int(qty)

            szamitott_osszes_etel = szamitott_total_ertek = 0
            for full_key, db in counts.items():
                prefix = full_key.split('_')[0]
                code_label = full_key.split('_')[1]
                keresett_kod = code_label.replace('*', '').strip()
                num_prefix = prefix_to_num.get(prefix, "1")
                sheets_key = f"{num_prefix}_{keresett_kod}"
                info = etlap.get(sheets_key, {})
                nyers_ar = str(info.get('ar', '0')).replace('Ft', '').replace(' ', '').replace('\xa0', '').strip()
                ar = int(nyers_ar) if nyers_ar and nyers_ar.isdigit() else 0
                szamitott_osszes_etel += db
                szamitott_total_ertek += (db * ar)

            szamitott_kp_forgalom = 0
            ertek_col = next((c for c in df_temp.columns if any(x in c.lower() for x in ['érték', 'ertek', 'forgalom', 'összeg', 'fizetendő', 'fizetendo', 'pénz', 'penz', 'összesen'])), None)
            if ertek_col:
                for v in df_temp[ertek_col].dropna():
                    v_str = str(v).replace('Ft', '').replace(' ', '').replace('\xa0', '').replace('.', '').strip()
                    if v_str.isdigit() or (v_str.startswith('-') and v_str[1:].isdigit()): szamitott_kp_forgalom += int(v_str)

            regi_beszedett_kp = regi_borravalo = 0
            try:
                summary_records_df = load_sheet_data_cached(client, ugyfelkor_sheet_id, "Mobil_Summary")
                if not summary_records_df.empty:
                    futar_keresett_clean = str(aktualis_futar).strip().lower()
                    for s_row in summary_records_df.to_dict('records'):
                        row_date = str(s_row.get('Datum', s_row.get('datum', ''))).strip()
                        summary_futar = str(s_row.get('Futar', s_row.get('futar', ''))).strip().lower()
                        if row_date == api_datum_kulcs and (summary_futar == futar_keresett_clean or summary_futar == "szűcs istván"):
                            regi_beszedett_kp = int(pd.to_numeric(s_row.get('Beszedett_KP', 0), errors='coerce'))
                            regi_borravalo = int(pd.to_numeric(s_row.get('Borravalo', 0), errors='coerce'))
                            break
            except: pass
            szamitott_borravalo = int(st.session_state.get('futar_borravalo', regi_borravalo))
        except Exception as e_calc:
            api_datum_kulcs, aktualis_futar, jarat_szoveg, szamitott_osszes_megallo = str(kivalasztott_datum), "Szűcs István", "Hiba", 0
            szamitott_osszes_cim = szamitott_osszes_etel = szamitott_total_ertek = szamitott_kp_forgalom = regi_beszedett_kp = szamitott_borravalo = 0

        szamitott_jutalek = 0
        try:
            sh_ugyfelkor = client.open_by_key(ugyfelkor_sheet_id if ugyfelkor_sheet_id else sheet_id)
            fejlec = ["Datum", "Futar", "Jaratok", "Tervezett_Megallok", "Osszes_Cim", "Osszes_Etel", "Forgalom_Osszes", "Beszedett_KP", "Borravalo", "Vart_Jutalek"]
            ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary") if "Mobil_Summary" in [w.title for w in sh_ugyfelkor.worksheets()] else sh_ugyfelkor.add_worksheet("Mobil_Summary", rows=500, cols=len(fejlec))
            summary_records = ws_summary.get_all_records()
            ma_dt = datetime.datetime.strptime(api_datum_kulcs, "%Y-%m-%d")
            het_kezdete = ma_dt - datetime.timedelta(days=ma_dt.weekday())
            het_vege = het_kezdete + datetime.timedelta(days=6)
            eheti_eddigi_forgalom, existing_row_index = 0, None
            
            for idx, row in enumerate(summary_records, start=2):
                r_date_str = str(row.get('Datum', '')).strip()
                r_futar = str(row.get('Futar', '')).strip().lower()
                if r_futar == aktualis_futar.lower():
                    try:
                        r_dt = datetime.strptime(r_date_str, "%Y-%m-%d")
                        if het_kezdete <= r_dt <= het_vege:
                            if r_date_str == api_datum_kulcs: existing_row_index = idx
                            else: eheti_eddigi_forgalom += int(pd.to_numeric(row.get('Forgalom_Osszes', 0), errors='coerce'))
                    except: pass
            teljes_eheti_forgalom = eheti_eddigi_forgalom + szamitott_total_ertek
            
            if teljes_eheti_forgalom >= 2100000:
                jutalek_kulcs = 0.14
                st.balloons()
                st.session_state['show_weekly_bonus_celebration'] = {'futar': aktualis_futar, 'forgalom': teljes_eheti_forgalom, 'jutalek': int(szamitott_total_ertek * 0.14)}
            else:
                jutalek_kulcs = 0.13
                st.session_state['show_weekly_bonus_celebration'] = None
            szamitott_jutalek = int(round(szamitott_total_ertek * jutalek_kulcs))
        except: szamitott_jutalek = int(round(szamitott_total_ertek * 0.13))

        st.session_state.meta_data.update({'datum_kulcs': api_datum_kulcs, 'osszes_megallo': szamitott_osszes_megallo, 'osszes_cim': szamitott_osszes_cim, 'osszes_etel': szamitott_osszes_etel, 'total_ertek': szamitott_total_ertek, 'kp_forgalom': szamitott_kp_forgalom, 'borravalo': szamitott_borravalo, 'futar_jutalek': szamitott_jutalek})

        if not st.session_state.get('teszt_uzemmod', False):
            try:
                uj_adat_sor = [api_datum_kulcs, aktualis_futar, jarat_szoveg, int(szamitott_osszes_megallo), int(szamitott_osszes_cim), int(szamitott_osszes_etel), int(szamitott_total_ertek), int(regi_beszedett_kp), int(szamitott_borravalo), int(szamitott_jutalek)]
                if existing_row_index:
                    ws_summary.update(f"A{existing_row_index}:J{existing_row_index}", [uj_adat_sor])
                else:
                    ws_summary.append_row(uj_adat_sor)
                st.cache_data.clear()
            except: pass
        if feltoltott_jaratok: st.session_state.aktiv_jaratok = feltoltott_jaratok
        st.success("🎉 Menetterv sikeresen feldolgozva és szinkronizálva!")


def render_desktop_main_content(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, admin_funkcio, is_admin):
    kivalasztott_datum = st.session_state.get('kivalasztott_datum', datetime.date.today())
    st.session_state['SHEET_ID_UGYFELKOR'] = SHEET_ID_UGYFELKOR
    st.session_state['SHEET_ID_MASTER'] = SHEET_ID_MASTER
    st.session_state['sheet_id'] = SHEET_ID_UGYFELKOR

    # --- SIKERES JUTALÉKÜNNEPLŐ KÁRTYA (AAA KONTRASZTÚ FORMÁZÁSSAL) ---
    if st.session_state.get('show_weekly_bonus_celebration'):
        bonus_data = st.session_state['show_weekly_bonus_celebration']
        st.markdown(f"""
        <div style="background: #FFFBEB !important; background: linear-gradient(135deg, #FEF3C7 0%, #FCD34D 100%) !important; padding: 25px !important; border-radius: 15px !important; text-align: center !important; color: #78350F !important; margin-bottom: 25px !important; box-shadow: 0 10px 20px rgba(120,53,15,0.12) !important; border: 2px solid #F59E0B !important; position: relative !important; overflow: hidden !important; font-family: sans-serif !important;">
            <div style="font-size: 40px !important; margin-bottom: 10px !important; line-height: 1 !important;">👑🏆🍾</div>
            <h2 style="margin: 0 0 10px 0 !important; color: #78350F !important; font-weight: 900 !important; font-size: 24px !important; border: none !important; line-height: 1.2 !important; text-shadow: none !important; font-family: sans-serif !important;">GRATULÁLUNK, {bonus_data['futar'].upper()}!</h2>
            <p style="font-size: 16px !important; margin: 10px 0 12px 0 !important; color: #78350F !important; font-weight: bold !important; line-height: 1.4 !important; text-shadow: none !important; font-family: sans-serif !important;">
                Elérted a heti bónusz álomhatárt! Az eheti összesített rakományod értéke elérte a <b style="color: #B45309 !important; font-size: 18px !important; font-weight: 900 !important;">{bonus_data['forgalom']:,} Ft</b>-ot!
            </p>
            <div style="background-color: rgba(120, 53, 15, 0.08) !important; display: inline-block !important; padding: 10px 25px !important; border-radius: 50px !important; font-weight: 800 !important; font-size: 15px !important; margin-top: 5px !important; border: 1.5px solid #78350F !important; color: #78350F !important; letter-spacing: 0.5px !important; font-family: sans-serif !important;">
                ⭐ EMELT BÓNUSZ SÁV: 14% JUTALÉK AKTIVÁLVA! ⭐
            </div>
        </div>
        """.replace(",", " "), unsafe_allow_html=True)

    if is_admin and admin_funkcio == "🚚 Logisztikai Közenter & Stand":
        try: render_logisztikai_kozpont(client.open_by_key(SHEET_ID_UGYFELKOR))
        except Exception as e: st.error(f"Hiba: {e}")
        return

    st.subheader("📄 Új PDF-ek")
    up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
    if up_files and st.button("🚀 FELDOLGOZÁS", type="primary", key="pdf_process_btn"):
        process_uploaded_pdfs(up_files, client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, kivalasztott_datum)

    st.divider()

    if st.session_state.mdf is not None and not st.session_state.mdf.empty:
        role = check_user_role()
        df_view = st.session_state.mdf.copy()
        if role == "futar" and 'user_jarat_lista' in st.session_state:
            df_view = df_view[df_view['Járat'].astype(str).isin([str(j) for j in st.session_state.user_jarat_lista])].copy()
        
        if df_view.empty:
            st.warning("✉️ Nincsenek aktív címeid mára.")
        else:
            if 'Sorrend' not in df_view.columns: df_view['Sorrend'] = range(1, len(df_view) + 1)
            df_view['Sorrend'] = pd.to_numeric(df_view['Sorrend'], errors='coerce').fillna(999.0).astype(float)
            for col in df_view.columns:
                if col != 'Sorrend': df_view[col] = df_view[col].astype(str).replace(['nan', 'None', '<NA>', '0.0', '0'], '')

            df_view = df_view.sort_values(by='Sorrend').reset_index(drop=True)
            preferred_order = ["Sorrend", "Ügyintéző", "Cím", "Telefon", "Pénz", "Rendelés", "Csoport", "Megjegyzés", "temp_id"]
            final_column_order = [c for c in preferred_order if c in df_view.columns] + [c for c in df_view.columns if c not in preferred_order]
            df_view = df_view[final_column_order]
                    
            edited_df = st.data_editor(df_view, column_order=final_column_order, column_config={"Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f", step=0.1), "temp_id": None}, num_rows="dynamic", use_container_width=True, hide_index=True)

            with st.expander("🗺️ Útvonal megtekintése a térképen", expanded=False):
                utvonal_terkep(df_napi=edited_df, sheet_id=SHEET_ID_UGYFELKOR) 
                
                # ==============================================================================
                # 🎯 GPS GYORS-MENTŐ ASSZISZTENS PANEL KÖZVETLENÜL A TÉRKÉP ALATT
                # ==============================================================================
                st.write("")
                st.markdown("### 🛰️ Térképes GPS Gyors-Mentő")
                st.markdown(
                    """
                    💡 **Hogyan használd?** 1. Kattints a fenti térképen a helyes pontra (pl. a ház tetejére).
                    2. A felugró piros tűnél kattints a **'Koordináta Másolása'** gombra.
                    3. Válaszd ki alább az ügyfelet, illeszd be a koordinátát, és nyomj a Mentésre!
                    """
                )
                
                col_ast1, col_ast2 = st.columns([1.5, 1])
                with col_ast1:
                    ugyfel_nevek = ["-- Válassz ügyfelet a mentéshez --"]
                    for _, r in edited_df.iterrows():
                        if str(r['Név']).strip() != "":
                            ugyfel_nevek.append(f"{r['ID']} - {r['Név']} ({r['Cím']})")
                        
                    valasztott_ugyfel_str = st.selectbox("Melyik ügyfél koordinátáját javítod?", ugyfel_nevek, key="gps_assistant_selectbox")
                    
                with col_ast2:
                    beillesztett_gps = st.text_input("Másolt koordináta beillesztése (Paste):", placeholder="Pl. 47.531234,21.624123", key="gps_assistant_input")
                    
                if st.button("💾 ÚJ GPS KOORDINÁTA MENTÉSE AZ ADATBÁZISOKBA", key="save_edited_data_btn_assistant", use_container_width=True):
                    try:
                        import re
                        sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                        
                        # Tisztítsuk meg a beillesztett GPS-t (kiszűrjük a számokat tizedesponttal)
                        gps_match = re.findall(r'[-+]?\d*\.\d+|\d+', beillesztett_gps)
                        if len(gps_match) >= 2:
                            uj_lat, uj_lon = gps_match[0], gps_match[1]
                            target_id = valasztott_ugyfel_str.split(" - ")[0].strip()
                            
                            # 🎯 JAVÍTÁS: TISZTÍTOTT ID MEGHATÁROZÁSA A TÖRZSTÁBLÁHOZ (PREFIX NÉLKÜL, pl: S-428612 -> 428612)
                            target_id_clean = "".join(filter(str.isdigit, target_id.split('-')[-1]))
                            
                            # 1. Mentés az Ugyfelkor törzstáblába
                            ws_ugyfel = sh.worksheet("Ugyfelkor")
                            teljes_adat = ws_ugyfel.get_all_values()
                            fejlec = teljes_adat[0]
                            
                            ugyfel_row_idx = None
                            for u_idx, u_rec in enumerate(teljes_adat[1:], start=2):
                                # Biztonság kedvéért a törzstábla ID-ját is prefix és tizedes-mentesen vetjük össze
                                db_id_clean = "".join(filter(str.isdigit, str(u_rec[0]).strip().split('-')[-1]))
                                if db_id_clean == target_id_clean:
                                    ugyfel_row_idx = u_idx
                                    break
                                    
                            if ugyfel_row_idx:
                                u_lat_idx = fejlec.index('Lat') + 1
                                u_lon_idx = fejlec.index('Lon') + 1
                                
                                ws_ugyfel.update_cell(ugyfel_row_idx, u_lat_idx, f"'{uj_lat}")
                                ws_ugyfel.update_cell(ugyfel_row_idx, u_lon_idx, f"'{uj_lon}")
                                
                                # 2. Ha az Adatok táblában is szerepel az ügyfél ID-ja mára, oda is elmentjük az azonnali térkép-frissülésért
                                try:
                                    ws_adatok = sh.worksheet("Adatok")
                                    headers_adatok = ws_adatok.row_values(1)
                                    a_id_idx = headers_adatok.index('ID')
                                    a_lat_idx = headers_adatok.index('Lat') + 1
                                    a_lon_idx = headers_adatok.index('Lon') + 1
                                    
                                    adatok_vals = ws_adatok.get_all_values()
                                    for a_row_idx, a_rec in enumerate(adatok_vals[1:], start=2):
                                        rec_id_clean = "".join(filter(str.isdigit, str(a_rec[a_id_idx]).split('-')[-1]))
                                        if rec_id_clean == target_id_clean:
                                            ws_adatok.update_cell(a_row_idx, a_lat_idx, uj_lat)
                                            ws_adatok.update_cell(a_row_idx, a_lon_idx, uj_lon)
                                except Exception as e_a:
                                    logger.warning(f"Napi Adatok frissítési hiba: {e_a}")
                                
                                st.success(f"🎉 SIKER! {valasztott_ugyfel_str.split(' - ')[1]} koordinátája véglegesen elmentve!")
                                st.balloons()
                                st.cache_data.clear()
                                time.sleep(1.0)
                                st.rerun()
                            else:
                                st.error("❌ Nem találom az ügyfelet a törzstáblában!")
                        else:
                            st.error("❌ Érvénytelen koordináta formátum! Használj 'lat, lon' formátumot (tizedesponttal).")
                    except Exception as e_assistant:
                        st.error(f"Hiba a mentés során: {e_assistant}")

            st.subheader("🗄️ Ügyfélkör kezelése")
            gomb_col1, gomb_col2 = st.columns(2)

            with gomb_col1:
                if st.button("🔄 Sorrend frissítése és újrasorszámozás", use_container_width=True, key="seq_refresh_btn"):
                    edited_df['Sorrend'] = pd.to_numeric(edited_df['Sorrend'], errors='coerce').fillna(999)
                    edited_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
                    edited_df['Sorrend'] = range(1, len(edited_df) + 1)
                    st.session_state.mdf = edited_df
                    st.success("Sorrend frissítve!")
                    st.rerun()

            with gomb_col2:
                if st.button("💾 Módosított adatok mentése", use_container_width=True, key="save_edited_data_btn"):
                    try:
                        sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                        ws_ugyfel = sh.worksheet("Ugyfelkor")
                        teljes_adat = ws_ugyfel.get_all_values()
                        fejlec = teljes_adat[0] if isinstance(teljes_adat, list) and len(teljes_adat) > 0 else []
                        if not fejlec:
                            fejlec = teljes_adat[0]
                        sheets_id_map = {str(teljes_adat[i][0]).strip(): i for i in range(1, len(teljes_adat))}
                        edited_df_clean = edited_df.copy()
                        edited_df_clean['ID'] = edited_df_clean['ID'].astype(str).str.strip()
                        mod_count = 0
                        
                        for _, row in edited_df_clean.iterrows():
                            current_id = row['ID']
                            if current_id in sheets_id_map:
                                s_idx = sheets_id_map[current_id]
                                teljes_adat[s_idx][1] = str(row['Név']).strip()
                                teljes_adat[s_idx][2] = str(row['Cím']).strip()
                                teljes_adat[s_idx][5] = str(row['Telefon']).strip()
                                teljes_adat[s_idx][6] = str(row['Csoport']).strip()
                                teljes_adat[s_idx][7] = str(row['Megjegyzés']).strip()
                                mod_count += 1
                        if mod_count > 0:
                            df_cleaned = kotelezo_ugyfelkor_formatum_tisztitas(pd.DataFrame(teljes_adat[1:], columns=fejlec))
                            ws_ugyfel.update('A1', [fejlec] + df_cleaned.values.tolist(), value_input_option='RAW')
                            st.success(f"🎉 Összesen {mod_count} ügyfél sikeresen elmentve!")
                            st.balloons()
                            st.rerun()
                    except Exception as e: st.error(f"Hiba: {e}")

            st.divider()
            meta = st.session_state.meta_data if isinstance(st.session_state.meta_data, dict) else {}
            meta['datum_iso'] = str(kivalasztott_datum)
            aktualis_jaratok = ", ".join(meta.get('jaratok', [])) if meta.get('jaratok') else "N/A"
            st.info(f"Észlelt járatok: **{aktualis_jaratok}** | {meta.get('ev', '')}. {meta.get('het', '')}. hét")

            if st.button("🚀 DOKUMENTUMOK GENERÁLÁSA", type="primary", use_container_width=True, key="doc_gen_btn"):
                with st.spinner("⏳ PDF-ek generálása..."):
                    try:
                        st.session_state['ready_label_pdf'] = create_label_pdf(edited_df, st.session_state.c_n, st.session_state.c_p, meta, st.session_state.etelek_master_df, pd.DataFrame(), pd.DataFrame(), st.session_state.etlap_api_df).getvalue()
                        st.session_state['ready_manifest_pdf'] = create_manifest_pdf(edited_df, st.session_state.c_n, meta).getvalue()
                        st.session_state['ready_raklista_pdf'] = create_raklista_pdf(edited_df, aktualis_jaratok, meta, client.open_by_key(SHEET_ID_UGYFELKOR)).getvalue()
                        st.success("✅ Minden dokumentum sikeresen elkészült!")
                    except Exception as e: st.error(f"Hiba: {e}")

            if st.session_state.get('ready_label_pdf'):
                st.write("### 📥 Letöltések:")
                dl_c1, dl_c2, dl_c3 = st.columns(3)
                dl_c1.download_button("📄 ETIKETTEK LETÖLTÉSE", data=st.session_state['ready_label_pdf'], file_name="etikettek.pdf", mime="application/pdf", use_container_width=True, key="dl_labels")
                dl_c2.download_button("📋 MENETTERV LETÖLTÉSE", data=st.session_state['ready_manifest_pdf'], file_name="menetterv.pdf", mime="application/pdf", use_container_width=True, key="dl_manifest")
                dl_c3.download_button("📊 RAKLISTA LETÖLTÉSE", data=st.session_state['ready_raklista_pdf'], file_name="raklista.pdf", mime="application/pdf", use_container_width=True, key="dl_raklista")

            st.write("---")
            st.subheader("📱 Mobil Terminál")
            alap_url = "https://interfood-menetterv-etikett-generator.streamlit.app"
            jarat_id = ",".join(str(j) for j in meta.get('jaratok', [])) if meta.get('jaratok') else ""
            if not jarat_id and 'valasztott_jarat' in st.session_state:
                jarat_id = str(st.session_state.valasztott_jarat)
            
            mobil_link = f"{alap_url}/?view=mobile&jarat={jarat_id}"
            if st.session_state.get('teszt_uzemmod', False):
                mobil_link += "&test=true"
            
            import qrcode
            from io import BytesIO
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(mobil_link)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = BytesIO()
            img.save(buf, format="PNG")
            byte_im = buf.getvalue()
            
            qr_col1, qr_col2 = st.columns([2, 1])
            with qr_col1:
                if st.session_state.get('teszt_uzemmod', False):
                    st.warning("🧪 **A QR-kód TESZT ÜZEMMÓDRA van felkészítve!**")
                st.markdown(f"""
                💡 **Szkenneld be ezt a QR-kódot a telefonoddal**, hogy megnyisd a **Futár Terminált**!
                * A futár azonnal eléri a mobil terminált.
                * Nincs papír, nincs elírás.
                Direkt link: [{mobil_link}]({mobil_link})
                """)
            with qr_col2:
                st.image(byte_im, width=150)
