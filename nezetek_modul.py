# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import os
import re
import pdfplumber
import datetime
import time

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


def render_mobil_sidebar_dashboard(client, SHEET_ID_UGYFELKOR):
    """
    Kirajzolja a mobil nézet élő Google Sheets adataira épülő műszerfalát.
    Tiszta almodul verzió hibamentes foteles mérőkkel, lezárt HTML tagekkel,
    beépített Hibabejelentővel és Kijelentkezés gombbal.
    """
    import base64
    import re
    import datetime
    import os
    import time
    import pandas as pd
    import streamlit as st

    st.markdown(
        """
        <style>
        /* Elsődleges gombok - Interfood Zöld */
        .stButton > button[kind="primary"] {
            background-color: #139D43 !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: bold !important;
        }
        /* Danger gombok - Interfood Piros */
        button[key*="logout"], button[key*="dl_"], button[key*="reset"], button[key*="delete"], button[key*="mobil_logout_btn"] {
            background-color: #E1251B !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            color: white !important;
        }

        /* Műszerfal felső részének teljes letömörítése, az üresség kiiktatása */
        div[data-testid="stSidebarUserContent"] {
            padding-top: 0rem !important;
            margin-top: -3.8rem !important;
        }
        /* Metric kártyák tömörítése */
        [data-testid="stSidebarUserContent"] [data-testid="stMetricValue"] {
            font-size: 1.05rem !important;
            font-weight: 800 !important;
            color: #139D43 !important;
        }
        [data-testid="stSidebarUserContent"] [data-testid="stMetricLabel"] {
            font-size: 0.68rem !important;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # --- BASE64 LOGÓ INJEKTÁLÁS ---
    if os.path.exists("interfood-logo.png"):
        try:
            with open("interfood-logo.png", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            st.markdown(
                f"""
                <div style="display: flex; justify-content: center; width: 100%; margin-bottom: 8px;">
                    <img src="data:image/png;base64,{encoded_string}" style="width: 75px; height: auto;">
                </div>
                """,
                unsafe_allow_html=True
            )
        except:
            st.markdown("<h3 style='text-align: center; color: #139D43; margin-top:0;'>🟢 Interfood</h3>",
                        unsafe_allow_html=True)
    else:
        st.markdown("<h3 style='text-align: center; color: #139D43; margin-top:0;'>🟢 Interfood</h3>",
                    unsafe_allow_html=True)

    st.markdown(
        "<h2 style='text-align: center; color: #139D43; margin-bottom: 6px; font-size: 1.15rem;'>📊 Mai Műszerfal</h2>",
        unsafe_allow_html=True)

    futar_nev_kiir = st.session_state.get('user_nev', 'Ismeretlen Futár')
    jarat_lista_kiir = st.session_state.get('user_jarat_lista', [])
    jarat_szoveg_kiir = ", ".join(map(str, jarat_lista_kiir)) if jarat_lista_kiir else "Nincs"

    futar_tel_kiir = st.session_state.get('user_tel', '')
    tel_resz = f" | 📞 {futar_tel_kiir}" if futar_tel_kiir else ""

    st.write(f"👤 **Futár:** {futar_nev_kiir}{tel_resz}<br>🚚 **Járat:** {jarat_szoveg_kiir}", unsafe_allow_html=True)

    # Inicializáljuk a mérőket
    osszes_cim = 0
    osszes_megallo = 0
    osszes_etel = 0
    forgalmi_ertek = 0
    jutalek = 0

    try:
        from adatbazis_modul import SHEET_ID_MASTER, load_etlap_from_sheets

        sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
        ws_adatok = sh_ugyfelkor.worksheet("Adatok")
        all_rows = ws_adatok.get_all_values()

        futar_keresett = str(futar_nev_kiir).strip().lower()

        driver_records = []
        if all_rows:
            header = all_rows[0]
            futar_col_key = None
            for k in header:
                if str(k).strip().lower() in ['futár', 'futar', 'feldolgozó futár', 'feldolgozo futar']:
                    futar_col_key = k
                    break

            if futar_col_key:
                futar_idx = header.index(futar_col_key)
                # DataFrame-szerű szűrés dict listává alakítva
                for row in all_rows[1:]:
                    if len(row) > futar_idx and str(row[futar_idx]).strip().lower() == futar_keresett:
                        driver_records.append(dict(zip(header, row)))

        # 💡 FOTELES TESZT ÜZEMMÓD AUTOMATIKUS ÁTKAPCSOLÓ
        if not driver_records and len(all_rows) > 1:
            header = all_rows[0]
            driver_records = [dict(zip(header, row)) for row in all_rows[1:]]
            st.markdown(
                """
                <div style="background-color: #FEF3C7; border-left: 4px solid #D97706; padding: 10px; border-radius: 6px; margin: 10px 0; width: 100%;">
                    <p style="margin: 0; font-weight: bold; color: #92400E; font-size: 0.85rem;">🧪 Szimulációs Nézet Aktív</p>
                    <p style="margin: 2px 0 0 0; color: #78350F; font-size: 0.78rem; line-height: 1.3;">
                        A menetterv teljes statisztikáját látod dinamikusan betöltve a hivatalos raklista-összesítő motor alapján.
                    </p>
                </div>
                """,
                unsafe_allow_html=True
            )

        # 📊 RAKLISTA ÖSSZESÍTŐ MOTOR INTEGRÁCIÓ
        osszes_cim = len(driver_records)
        egyedi_cimek = set(str(r.get('Cím', r.get('Cim', ''))).strip() for r in driver_records)
        osszes_megallo = len(egyedi_cimek)

        etlap = st.session_state.get('etlap_adatok', {})
        if not etlap:
            try:
                etlap = load_etlap_from_sheets(SHEET_ID_MASTER)
                st.session_state.etlap_adatok = etlap
            except:
                etlap = {}

        label_to_prefix = {"Hé": "H", "Ke": "K", "Sze": "S", "Csü": "C", "Pé": "P", "Szo": "Z"}
        prefix_to_num = {"H": "1", "K": "2", "S": "3", "C": "4", "P": "5", "Z": "6"}
        ORDER_PAT = r'(\d+)-([A-Z0-9\*]+)'

        counts = {}
        for r in driver_records:
            order_str = str(r.get('Rendelés_Full', r.get('Rendeles_Full', r.get('Rendelés', r.get('Rendeles', '')))))
            day_parts = order_str.split('|')
            for part in day_parts:
                part = part.strip()
                prefix = ""
                for label, pfx in label_to_prefix.items():
                    if f"{label}:" in part:
                        prefix = pfx
                        break
                if not prefix:
                    continue

                found = re.findall(ORDER_PAT, part)
                for qty, code in found:
                    full_key = f"{prefix}_{code.strip().upper()}"
                    counts[full_key] = counts.get(full_key, 0) + int(qty)

        for full_key, db in counts.items():
            prefix = full_key.split('_')[0]
            code_label = full_key.split('_')[1]

            keresett_kod = code_label.replace('*', '').strip()
            num_prefix = prefix_to_num.get(prefix, "1")
            sheets_key = f"{num_prefix}_{keresett_kod}"

            info = etlap.get(sheets_key, {})
            nyers_ar = str(info.get('ar', '0')).replace('Ft', '').replace(' ', '').strip()
            ar = int(nyers_ar) if nyers_ar and nyers_ar.isdigit() else 0

            osszes_etel += db
            forgalmi_ertek += (db * ar)

        jutalek = int(forgalmi_ertek * 0.13)

    except Exception as e:
        st.sidebar.error(f"Hiba az adatok dinamikus számításakor: {e}")
        return

    # Élő kiszállítási mérők kiszámítása a Session State-ből
    live_kesz_cimek = sum(1 for k in st.session_state.keys() if
                          k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres")
    live_beszedett_kp = 0
    live_borravalo = 0

    for k in list(st.session_state.keys()):
        if k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres":
            idx = k.split("_")[-1]
            try:
                live_beszedett_kp += int(st.session_state.get(f"atvett_input_{idx}", 0))
                live_borravalo += int(st.session_state.get(f"borravalo_{idx}", 0))
            except:
                pass

    # 🛰️ MULTI-TENANT: Dinamikus bérlői pénznem lekérése
    penznem = st.session_state.get('tenant_currency', 'Ft')

    # --- SZEKCIÓK MEGJELENÍTÉSE ---
    st.markdown("<div style='margin: 18px 0 12px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
    st.subheader("🏁 Kiszállítás Haladás")
    haladas_szazalek = min(1.0, live_kesz_cimek / osszes_cim) if osszes_cim > 0 else 0.0
    st.progress(haladas_szazalek)
    st.caption(f"Teljesítve: {live_kesz_cimek} / {osszes_cim} cím ({int(haladas_szazalek * 100)}%)")

    st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
    st.subheader("💰 Pénzügy & Mennyiség")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("📍 Tervezett megállók", f"{osszes_megallo} db")
        st.metric("🏠 Összes cím (vevő)", f"{osszes_cim} db")
    with col_s2:
        st.metric("📦 Összes étel", f"{osszes_etel} adag")
        st.metric("💵 Rakományérték", f"{forgalmi_ertek:,} {penznem}".replace(",", " "))

    st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
    st.subheader("💸 Élő Elszámolás")
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        st.metric("💵 Beszedett KP aznap", f"{live_beszedett_kp:,} {penznem}".replace(",", " "))
        st.metric("⭐ Várható Jutalékod", f"{jutalek:,} {penznem}".replace(",", " "))
    with col_l2:
        st.metric("💰 Gyűjtött borravaló", f"{live_borravalo:,} {penznem}".replace(",", " "))

    # ==============================================================================
    # 🚨 1. LÉPÉS: HIBABEJELENTŐ INTEGRÁCIÓ PONTOSAN A MŰSZERFAL ALÁ
    # ==============================================================================
    st.markdown("<div style='margin: 14px 0 10px 0; border-top: 1.5px solid #E5E7EB;'></div>", unsafe_allow_html=True)
    with st.expander("🚨 Hiba / Probléma bejelentése"):
        st.write("Valami nem működik? Írd le röviden, és az adminisztrátor azonnal látni fogja!")
        hiba_szoveg = st.text_area("Hiba részletei:", key="futar_hiba_input_field", placeholder="Pl: A 12-es címnél nem nyílik meg a Waze...")
        
        if st.button("📩 HIBAKÜLDÉS ÉLESBEN", key="futar_hiba_submit_btn", use_container_width=True, type="secondary"):
            if hiba_szoveg.strip():
                try:
                    sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                    try:
                        ws_idok = sh.worksheet("Mobil_Idobelyegek")
                        now_log = datetime.datetime.now()
                        ws_idok.append_row([now_log.strftime("%Y-%m-%d"), "HIBAJELENTÉS", futar_nev_kiir, hiba_szoveg.strip(), now_log.strftime("%H:%M:%S")])
                    except:
                        pass
                    st.success("🎉 Hibajelentés sikeresen rögzítve!")
                    time.sleep(1.0)
                    st.rerun()
                except Exception as e_hibalog:
                    st.error(f"Mentési hiba: {e_hibalog}")
            else:
                st.warning("Kérjük, írd le a hibát küldés előtt!")

    # ==============================================================================
    # 🚪 2. LÉPÉS: GOLYÓÁLLÓ MOBIL KIJELENTKEZÉS GOMB (A címsort is teljesen letakarítja)
    # ==============================================================================
    st.markdown("---")
    if st.button("🚪 Kijelentkezés a terminálból", key="mobil_logout_btn", use_container_width=True):
        st.query_params.clear()
        st.session_state.bejelentkezve = False
        st.session_state.user_nev = None
        st.session_state.user_szerep = None
        st.session_state.user_tel = None
        st.session_state.user_jarat_lista = []
        st.rerun()

def render_desktop_sidebar_controls(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, LOG_FILE):
    """
    Kirajzolja a kezelő oldalsávot az asztali nézetben.
    """
    st.markdown(
        """
        <style>
        /* Elsődleges gombok (Feldolgozás, Mentés, Generálás) - Interfood Zöld */
        .stButton > button[kind="primary"] {
            background-color: #139D43 !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: bold !important;
            transition: all 0.3s ease !important;
        }
        .stButton > button[kind="primary"]:hover {
            background-color: #0E7F35 !important;
            box-shadow: 0 4px 12px rgba(19, 157, 67, 0.3) !important;
        }
        /* Másodlagos gombok */
        .stButton > button[kind="secondary"] {
            border-radius: 8px !important;
            font-weight: 500 !important;
            transition: all 0.2s ease !important;
        }
        /* Danger gombok (Kijelentkezés, Letöltések) - Interfood Piros */
        button[key*="logout"], button[key*="dl_"], button[key*="reset"], button[key*="delete"], button[key*="superadmin_"], button[key*="test_reset"] {
            background-color: #E1251B !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: bold !important;
        }
        button[key*="logout"]:hover, button[key*="dl_"]:hover, button[key*="reset"]:hover, button[key*="test_reset"]:hover {
            background-color: #B81D17 !important;
            box-shadow: 0 4px 12px rgba(225, 37, 27, 0.3) !important;
        }
        /* File feltöltő zöld kerettel */
        [data-testid="stFileUploader"] {
            border: 2px dashed #139D43 !important;
            border-radius: 10px !important;
            padding: 10px !important;
            background-color: #F9FBF9 !important;
        }
        /* Kiemelt mérőszámok zöldítése */
        [data-testid="stMetricValue"] {
            color: #139D43 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Fejléc: Logó
    if os.path.exists("interfood-logo.png"):
        st.image("interfood-logo.png", width=110)
    else:
        st.markdown("<h3 style='color: #139D43; margin: 0;'>🟢 Interfood</h3>", unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)

    # 🚪 Kijelentkezés gomb
    if st.button("🚪 Kilépés a rendszerből", key="desktop_sidebar_logout_clean_btn", use_container_width=True):
        st.query_params.clear()
        st.session_state.bejelentkezve = False
        st.session_state.user_nev = None
        st.session_state.user_szerep = None
        st.session_state.user_tel = None
        st.rerun()

    # Futár adatai
    futar_nev = st.session_state.get('user_nev', 'Ismeretlen Futár')
    futar_tel = st.session_state.get('user_tel') or st.query_params.get('token_tel', '')

    if futar_tel and not st.session_state.get('user_tel'):
        st.session_state.user_tel = futar_tel

    st.markdown(
        f"""
        <div style="background-color: #F3F4F6; padding: 10px; border-radius: 8px; margin-top: 5px; margin-bottom: 10px; border-left: 4px solid #139D43;">
            <p style="margin: 0; font-weight: bold; color: #1F2937; font-size: 1rem;">👤 {futar_nev}</p>
            <p style="margin: 2px 0 0 0; color: #4B5563; font-size: 0.88rem;">📞 {futar_tel if futar_tel else "Nincs telefonszám"}</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    is_admin = st.session_state.user_szerep in ["admin", "superadmin"]

    st.header("⚙️ Kezelés")
    if is_admin:
        admin_funkcio = st.sidebar.radio("📌 Válassz funkciót:",
                                         ["📋 Raklista & Étlap Kezelés", "🚚 Logisztikai Közenter & Stand"])
    else:
        admin_funkcio = "📋 Raklista & Étlap Kezelés"

    st.divider()

    # PDF menettervek feltöltése
    st.subheader("📄 Menetterv PDF-ek")
    up_files = st.file_uploader("Menettervek feltöltése:", accept_multiple_files=True, type=['pdf'],
                                key="sidebar_pdf_uploader")

    kivalasztott_datum = st.session_state.get('kivalasztott_datum', datetime.date.today())

    if up_files:
        if st.button("🚀 PDF-EK FELDOLGOZÁSA", type="primary", use_container_width=True, key="sidebar_pdf_process_btn"):
            process_uploaded_pdfs(up_files, client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, kivalasztott_datum)
            st.rerun()

    st.divider()

    if is_admin:
        st.subheader("🚚 Aktív Futár Kiválasztása")
        futar_df = load_futar_from_sheets(SHEET_ID_UGYFELKOR)
        if not futar_df.empty:
            futar_df.columns = [c.strip() for c in futar_df.columns]
            courier_names = sorted(futar_df['Név'].dropna().astype(str).unique().tolist())

            if st.session_state.c_n not in courier_names:
                courier_names.insert(0, st.session_state.c_n)

            selected_courier = st.selectbox(
                "Futár kiválasztása (Admin):",
                options=courier_names,
                index=courier_names.index(st.session_state.c_n),
                key="sidebar_admin_courier_select"
            )

            if selected_courier:
                st.session_state.c_n = selected_courier
                matching_row = futar_df[futar_df['Név'] == selected_courier]
                if not matching_row.empty:
                    phone_val = str(matching_row.iloc[0].get('Telefon', '+36 20 886 8971')).strip()
                    if phone_val and phone_val != "nan":
                        st.session_state.c_p = phone_val
        else:
            st.session_state.c_n = st.text_input("Futár Neve", st.session_state.c_n)
            st.session_state.c_p = st.text_input("Telefonszám", st.session_state.c_p)

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

        with st.expander("🛰️ GPS Koordináták Tömeges Pótlása"):
            st.write(
                "Megkeresi azokat az ügyfeleket a törzsadatbázisban, akiknek nincs mentett koordinátája, és automatikusan pótolja azokat az ArcGIS geokódoló segítségével (max 20 menetben).")
            if st.button("🛰️ HIÁNYZÓ GPS-EK AUTOMATIKUS PÓTLÁSA", key="desktop_batch_gps_btn",
                         use_container_width=True):
                from adatbazis_modul import batch_potol_hianyozo_gps
                batch_potol_hianyozo_gps(client, SHEET_ID_UGYFELKOR)

        st.markdown("---")
        st.markdown("#### 📅 Étlapok Előrejelzése & Frissítése")

        ev_most, het_most = get_latest_week_from_master(SHEET_ID_MASTER, client)
        st.write(f"Legutolsó Master hét az adatbázisban: **W{het_most}**")

        col_w1, col_w2 = st.columns(2)
        with col_w1:
            target_start_week = st.number_input("Kezdő hét:", min_value=1, max_value=53,
                                                value=int(het_most) if het_most > 0 else 24, step=1,
                                                key="admin_sync_start_w")
        with col_w2:
            target_end_week = st.number_input("Záró (előre 3 hét):", min_value=1, max_value=53,
                                              value=int(het_most + 3) if het_most > 0 else 27, step=1,
                                              key="admin_sync_end_w")

        if st.button("🔄 MEGHATÁROZOTT HETEK LETÖLTÉSE", key="sidebar_manual_master_sync_btn", use_container_width=True):
            with st.spinner(f"⏳ Étlapok és új ételek letöltése W{target_start_week} és W{target_end_week} között..."):
                success = sync_master_database(SHEET_ID_MASTER, 2026, target_start_week, target_end_week)
                if success:
                    st.success("🎉 A kijelölt hetek és az új ételek sikeresen szinkronizálva a Master Adatbázisba!")
                    st.balloons()
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("❌ Hiba történt a letöltés során. Ellenőrizd az Interfood API kapcsolatot!")
        st.markdown("---")

        with st.expander("👤 Felhasználó Kezelés"):
            if 'futar_df' not in st.session_state: st.session_state.futar_df = load_futar_from_sheets(
                SHEET_ID_UGYFELKOR)
            df_to_edit = st.session_state.futar_df.astype(str)
            edited_df_users = st.data_editor(df_to_edit, use_container_width=True, num_rows="dynamic",
                                             key="user_editor")
            if st.button("💾 Módosítások mentése", key="user_save_btn"):
                with st.spinner("Mentés..."):
                    if save_futar_to_sheets(edited_df_users, SHEET_ID_UGYFELKOR):
                        st.session_state.futar_df = edited_df_users
                        st.success("Sikeres mentés!")
                        st.rerun()

        if st.session_state.get('user_szerep') == "superadmin":
            with st.expander("🚨 Szuperadmin Veszélyes Zóna"):
                st.write(
                    "Ezzel a gombbal manuálisan kikényszerítheted a teljes Google Sheets ügyféllista tisztítását és koordináta-egységesítését.")
                if st.button("🚨 FUTTASD A GOOGLE SHEETS NAGYTAKARÍTÁST", key="superadmin_nagytakaritas_btn",
                             use_container_width=True):
                    try:
                        with st.spinner("⏳ Adatbázis letöltése és elemzése..."):
                            sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                            worksheet = sh.worksheet("Ugyfelkor")
                            rows = worksheet.get_all_values()

                            if not rows:
                                m = "A táblázat üres!"
                                st.warning(m)
                            else:
                                header = rows[0]
                                df_ugyfel = pd.DataFrame(rows[1:], columns=header)
                                df_cleaned = kotelezo_ugyfelkor_formatum_tisztitas(df_ugyfel)

                                worksheet.clear()
                                worksheet.update('A1', [header] + df_cleaned.values.tolist(),
                                                 value_input_option='USER_ENTERED')
                                st.success(
                                    "🎉 SIKER! Az ügyfélkör adatbázis teljesen megtisztítva és egységesítve lett!")
                                st.balloons()
                                if 'ugyfelkor_df' in st.session_state:
                                    del st.session_state['ugyfelkor_df']
                                st.rerun()
                    except Exception as e:
                        st.error(f"Hiba a takarítás során: {e}")

                st.write("---")
                st.write("🗑️ **Tesztadatok Teljes Resetelése**")
                st.write(
                    "Kiüríti a napi 'Adatok' táblát, a 'Mobil_Summary' táblát és a 'Mobil_Idobelyegek' táblát (csak a fejléceket hagyja meg), valamint törli a helyi memóriát. Tökéletes új teszt futamok indítása előtt!")
                if st.button("🚨 TESZTADATOK TÖRLÉSE (Adatok & Summary reset)", key="superadmin_test_reset_btn",
                             use_container_width=True):
                    try:
                        with st.spinner("⏳ Adatbázisok takarítása..."):
                            sh = client.open_by_key(SHEET_ID_UGYFELKOR)

                            # 1. Adatok tisztítása
                            ws_adatok = sh.worksheet("Adatok")
                            adatok_headers = ws_adatok.row_values(1)
                            ws_adatok.clear()
                            ws_adatok.append_row(adatok_headers)

                            # 2. Mobil_Summary tisztítása
                            ws_summary = sh.worksheet("Mobil_Summary")
                            summary_headers = ws_summary.row_values(1)
                            ws_summary.clear()
                            ws_summary.append_row(summary_headers)

                            # 3. Mobil_Idobelyegek tisztítása
                            try:
                                ws_idok = sh.worksheet("Mobil_Idobelyegek")
                                idok_headers = ws_idok.row_values(1)
                                ws_idok.clear()
                                ws_idok.append_row(idok_headers)
                            except:
                                pass

                            # 4. Mobil_Raklista tisztítása
                            try:
                                ws_raklista = sh.worksheet("Mobil_Raklista")
                                rak_headers = ws_raklista.row_values(1)
                                ws_raklista.clear()
                                ws_raklista.append_row(rak_headers)
                            except:
                                pass

                            # Helyi session state takarítás
                            for k in list(st.session_state.keys()):
                                if any(x in k for x in
                                       ["kiszallitva_", "kiszallitott_statusz_", "bepak_allapot_", "lada_szam_tarolt_",
                                        "borravalo_", "atvett_input_", "chk_"]):
                                    st.session_state.pop(k, None)

                            st.session_state.mdf = None
                            st.session_state.kiszallitas_folyamatban = False
                            st.session_state.aruatvetel_folyamatban = False

                            st.cache_data.clear()
                            st.success("🎉 Minden tesztadat sikeresen törölve! Tiszta lappal indulhat a nap.")
                            st.balloons()
                            time.sleep(1.0)
                            st.rerun()
                    except Exception as e:
                        st.error(f"Hiba a reset során: {e}")

    return admin_funkcio


def render_desktop_main_content(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, admin_funkcio, is_admin):
    kivalasztott_datum = st.session_state.get('kivalasztott_datum', datetime.date.today())
    st.session_state['SHEET_ID_UGYFELKOR'] = SHEET_ID_UGYFELKOR
    st.session_state['SHEET_ID_MASTER'] = SHEET_ID_MASTER
    st.session_state['sheet_id'] = SHEET_ID_UGYFELKOR

    # Jutalékünneplő kártya
    if st.session_state.get('show_weekly_bonus_celebration'):
        bonus_data = st.session_state['show_weekly_bonus_celebration']
        st.markdown(f"""
        <div style="background: #FFFBEB !important; background: linear-gradient(135deg, #FEF3C7 0%, #FCD34D 100%) !important; padding: 25px !important; border-radius: 15px !important; text-align: center !important; color: #78350F !important; margin-bottom: 25px !important; box-shadow: 0 10px 20px rgba(120,53,15,0.12) !important; border: 2px solid #F59E0B !important; position: relative !important; overflow: hidden !important; font-family: sans-serif !important;">
            <div style="font-size: 40px !important; margin-bottom: 10px !important; line-height: 1 !important;">👑🏆🍾</div>
            <h2 style="margin: 0 0 10px 0 !important; color: #78350F !important; font-weight: 900 !important; font-size: 24px !important; border: none !important; line-height: 1.2 !important; text-shadow: none !important; font-family: sans-serif !important;">GRATULÁLUNK, {bonus_data['futar'].upper()}!</h2>
            <p style="font-size: 16px !important; margin: 10px 0 12px 0 !important; color: #78350F !important; font-weight: bold !important; line-height: 1.4 !important; text-shadow: none !important; font-family: sans-serif !important;">
                Elérted a heti bónusz álomhatárt! Az eheti összesített rakományod értéke alcanzo a <b style="color: #B45309 !important; font-size: 18px !important; font-weight: 900 !important;">{bonus_data['forgalom']:,} Ft</b>-ot!
            </p>
            <div style="background-color: rgba(120, 53, 15, 0.08) !important; display: inline-block !important; padding: 10px 25px !important; border-radius: 50px !important; font-weight: 800 !important; font-size: 15px !important; margin-top: 5px !important; border: 1.5px solid #78350F !important; color: #78350F !important; letter-spacing: 0.5px !important; font-family: sans-serif !important;">
                ⭐ EMELT BÓNUSZ SÁV: 14% JUTALÉK AKTIVÁLVA! ⭐
            </div>
        </div>
        """.replace(",", " "), unsafe_allow_html=True)

    if is_admin and admin_funkcio == "🚚 Logisztikai Közenter & Stand":
        try:
            render_logisztikai_kozpont(client.open_by_key(SHEET_ID_UGYFELKOR))
        except Exception as e:
            st.error(f"Hiba: {e}")
        return

    st.divider()

    if st.session_state.mdf is not None and not st.session_state.mdf.empty:
        role = check_user_role()
        df_view = st.session_state.mdf.copy()
        if role == "futar" and 'user_jarat_lista' in st.session_state:
            df_view = df_view[
                df_view['Járat'].astype(str).isin([str(j) for j in st.session_state.user_jarat_lista])].copy()

        if df_view.empty:
            st.warning("✉️ Nincsenek active címeid mára.")
        else:
            if 'Sorrend' not in df_view.columns: df_view['Sorrend'] = range(1, len(df_view) + 1)
            df_view['Sorrend'] = pd.to_numeric(df_view['Sorrend'], errors='coerce').fillna(999.0).astype(float)
            for col in df_view.columns:
                if col != 'Sorrend': df_view[col] = df_view[col].astype(str).replace(
                    ['nan', 'None', '<NA>', '0.0', '0'], '')

            df_view = df_view.sort_values(by='Sorrend').reset_index(drop=True)
            preferred_order = ["Sorrend", "Ügyintéző", "Cím", "Telefon", "Pénz", "Rendelés", "Csoport", "Megjegyzés",
                               "temp_id"]
            final_column_order = [c for c in preferred_order if c in df_view.columns] + [c for c in df_view.columns if
                                                                                         c not in preferred_order]
            df_view = df_view[final_column_order]

            edited_df = st.data_editor(df_view, column_order=final_column_order, column_config={
                "Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f", step=0.1), "temp_id": None},
                                       num_rows="dynamic", use_container_width=True, hide_index=True)

            with st.expander("🗺️ Útvonal megtekintése a térképen", expanded=False):
                utvonal_terkep(df_napi=edited_df, sheet_id=SHEET_ID_UGYFELKOR)

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

                    valasztott_ugyfel_str = st.selectbox("Melyik ügyfél koordinátáját javítod?", ugyfel_nevek,
                                                         key="gps_assistant_selectbox")

                with col_ast2:
                    beillesztett_gps = st.text_input("Másolt koordináta beillesztése (Paste):",
                                                     placeholder="Pl. 47.531234,21.624123", key="gps_assistant_input")

                if st.button("💾 ÚJ GPS KOORDINÁTA MENTÉSE AZ ADATBÁZISOKBA", key="save_edited_data_btn_assistant",
                             use_container_width=True):
                    try:
                        import re
                        sh = client.open_by_key(SHEET_ID_UGYFELKOR)

                        gps_match = re.findall(r'[-+]?\d*\.\d+|\d+', beillesztett_gps)
                        if len(gps_match) >= 2:
                            uj_lat, uj_lon = gps_match[0], gps_match[1]
                            target_id = valasztott_ugyfel_str.split(" - ")[0].strip()
                            target_id_clean = "".join(filter(str.isdigit, target_id.split('-')[-1]))

                            # Mentés az Ugyfelkor törzstáblába
                            ws_ugyfel = sh.worksheet("Ugyfelkor")
                            teljes_adat = ws_ugyfel.get_all_values()
                            fejlec = teljes_adat[0]

                            ugyfel_row_idx = None
                            for u_idx, u_rec in enumerate(teljes_adat[1:], start=2):
                                db_id_clean = "".join(filter(str.isdigit, str(u_rec[0]).strip().split('-')[-1]))
                                if db_id_clean == target_id_clean:
                                    ugyfel_row_idx = u_idx
                                    break

                            if ugyfel_row_idx:
                                u_lat_idx = fejlec.index('Lat') + 1
                                u_lon_idx = fejlec.index('Lon') + 1

                                ws_ugyfel.update_cell(ugyfel_row_idx, u_lat_idx, f"'{uj_lat}")
                                ws_ugyfel.update_cell(ugyfel_row_idx, u_lon_idx, f"'{uj_lon}")

                                # Mentés az Adatok táblába
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
                                    pass

                                st.success(
                                    f"🎉 SIKER! {valasztott_ugyfel_str.split(' - ')[1]} koordinátája véglegesen elmentve!")
                                st.balloons()
                                st.cache_data.clear()
                                time.sleep(1.0)
                                st.rerun()
                            else:
                                st.error("❌ Nem találom az ügyfelet a törzstáblában!")
                        else:
                            st.error(
                                "❌ Érvénytelen koordináta formátum! Használj 'lat, lon' formátumot (tizedesponttal).")
                    except Exception as e_assistant:
                        st.error(f"Hiba a mentés során: {e_assistant}")

            st.subheader("🗄️ Ügyfélkör kezelése")
            gomb_col1, gomb_col2 = st.columns(2)

            with gomb_col1:
                if st.button("🔄 Sorrend frissítése és újrasorszámozás", use_container_width=True,
                             key="seq_refresh_btn"):
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
                            df_cleaned = kotelezo_ugyfelkor_formatum_tisztitas(
                                pd.DataFrame(teljes_adat[1:], columns=fejlec))
                            ws_ugyfel.update('A1', [fejlec] + df_cleaned.values.tolist(), value_input_option='RAW')
                            st.success(f"🎉 Összesen {mod_count} ügyfél sikeresen elmentve!")
                            st.balloons()
                            st.rerun()
                    except Exception as e:
                        st.error(f"Hiba: {e}")

            st.divider()
            meta = st.session_state.meta_data if isinstance(st.session_state.meta_data, dict) else {}
            meta['datum_iso'] = str(kivalasztott_datum)
            aktualis_jaratok = ", ".join(meta.get('jaratok', [])) if meta.get('jaratok') else "N/A"
            st.info(f"Észlelt járatok: **{aktualis_jaratok}** | {meta.get('ev', '')}. {meta.get('het', '')}. hét")

            if st.session_state.get('user_nev'):
                st.session_state.c_n = st.session_state.user_nev
            if st.session_state.get('user_tel'):
                st.session_state.c_p = st.session_state.user_tel

            if st.button("🚀 DOKUMENTUMOK GENERÁLÁSA", type="primary", use_container_width=True, key="doc_gen_btn"):
                with st.spinner("⏳ Menetterv és egyedi sorrend rögzítése a felhőben..."):
                    try:
                        sh_sync = client.open_by_key(SHEET_ID_UGYFELKOR)
                        ws_adatok_sync = sh_sync.worksheet("Adatok")
                        
                        df_mobilra = edited_df.copy()
                        df_mobilra['Sorszám'] = range(1, len(df_mobilra) + 1)
                        df_mobilra = df_mobilra.astype(str)
                        
                        ws_adatok_sync.clear()
                        ws_adatok_sync.update(range_name='A1', values=[df_mobilra.columns.tolist()] + df_mobilra.values.tolist(), value_input_option='USER_ENTERED')
                        
                        st.cache_data.clear()
                        st.toast("📱 A végleges sorrend sikeresen szinkronizálva a mobil terminállal!", icon="✅")
                    except Exception as e_mobil_sync:
                        st.error(f"❌ Hiba a mobil sorrend szinkronizálásakor: {e_mobil_sync}")

                with st.spinner("⏳ PDF-ek generálása..."):
                    try:
                        st.session_state['ready_label_pdf'] = create_label_pdf(
                            edited_df,
                            st.session_state.c_n,
                            st.session_state.c_p,
                            meta,
                            st.session_state.etelek_master_df,
                            st.session_state.get('nevnapok_df', pd.DataFrame()),
                            st.session_state.get('keresztnevek_df', pd.DataFrame()),
                            st.session_state.etlap_api_df
                        ).getvalue()
                        st.session_state['ready_manifest_pdf'] = create_manifest_pdf(edited_df, st.session_state.c_n,
                                                                                     st.session_state.c_p,
                                                                                     meta).getvalue()
                        st.session_state['ready_raklista_pdf'] = create_raklista_pdf(edited_df, aktualis_jaratok, meta,
                                                                                     client.open_by_key(
                                                                                         SHEET_ID_UGYFELKOR)).getvalue()
                        st.success("✅ Minden dokumentum sikeresen elkészült!")
                    except Exception as e:
                        st.error(f"Hiba: {e}")

            if st.session_state.get('ready_label_pdf'):
                st.write("### 📥 Letöltések:")
                dl_c1, dl_c2, dl_c3 = st.columns(3)
                dl_c1.download_button("📄 ETIKETTEK LETÖLTÉSE", data=st.session_state['ready_label_pdf'],
                                      file_name="etikettek.pdf", mime="application/pdf", use_container_width=True,
                                      key="dl_labels")
                dl_c2.download_button("📋 MENETTERV LETÖLTÉSE", data=st.session_state['ready_manifest_pdf'],
                                      file_name="menetterv.pdf", mime="application/pdf", use_container_width=True,
                                      key="dl_manifest")
                dl_c3.download_button("📊 RAKLISTA LETÖLTÉSE", data=st.session_state['ready_raklista_pdf'],
                                      file_name="raklista.pdf", mime="application/pdf", use_container_width=True,
                                      key="dl_raklista")

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
