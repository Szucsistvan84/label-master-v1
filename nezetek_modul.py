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
    kotelezo_ugyfelkor_formatum_tisztitas
)
from nyomtatas_modulok import create_label_pdf, create_manifest_pdf, create_raklista_pdf
from vizualizacio import utvonal_terkep
from utils import check_user_role, clean_text
from admin_modul import render_logisztikai_kozpont

def render_mobil_sidebar_dashboard(client, SHEET_ID_UGYFELKOR, SHEET_ID):
    """Kirajzolja a mobil nézet élő Google Sheets adataira épülő műszerfalát."""
    st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>📊 Mai Műszerfal</h2>", unsafe_allow_html=True)
    
    futar_nev_kiir = st.session_state.get('user_nev', 'Ismeretlen Futár')
    jarat_lista_kiir = st.session_state.get('user_jarat_lista', [])
    jarat_szoveg_kiir = ", ".join(map(str, jarat_lista_kiir)) if jarat_lista_kiir else "Nincs"
    
    st.write(f"👤 **Futár:** {futar_nev_kiir}")
    st.write(f"🚚 **Járat(ok):** {jarat_szoveg_kiir}")
    st.write("---")

    osszes_cim = 0
    osszes_megallo = 0
    osszes_etel = 0
    forgalmi_ertek = 0
    jutalek = 0

    try:
        sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
        ws_raklista = sh_ugyfelkor.worksheet("Mobil_Raklista")
        raklista_adatok = ws_raklista.get_all_records()
        
        if raklista_adatok:
            df_mobil_calc = pd.DataFrame(raklista_adatok)
            df_mobil_calc.columns = [c.strip() for c in df_mobil_calc.columns]
            
            futar_keresett = str(futar_nev_kiir).strip().lower()
            df_mobil_calc['Futar_Kereso'] = df_mobil_calc['Jarat_ID / Futar'].astype(str).str.strip().str.lower()
            df_sajat = df_mobil_calc[df_mobil_calc['Futar_Kereso'] == futar_keresett]
            
            if df_sajat.empty:
                felhasznalo_jaratai = [str(j).strip() for j in jarat_lista_kiir]
                if "4002" in felhasznalo_jaratai or "4002" == str(st.session_state.get('user_jarat', '')):
                    df_sajat = df_mobil_calc[df_mobil_calc['Futar_Kereso'] == "szűcs istván"]

            if not df_sajat.empty:
                osszes_etel = int(pd.to_numeric(df_sajat['Terv_Darabszam'], errors='coerce').sum())
                
                try:
                    ws_adatok = sh_ugyfelkor.worksheet("Adatok")
                    df_adatok_all = pd.DataFrame(ws_adatok.get_all_records())
                    
                    if not df_adatok_all.empty:
                        df_adatok_all.columns = [str(c).strip() for c in df_adatok_all.columns]
                        
                        jarat_col_name = None
                        for c in df_adatok_all.columns:
                            if 'járat' in c.lower() or 'jarat' in c.lower():
                                jarat_col_name = c
                                break
                        
                        aktiv_jaratok = st.session_state.get('szurt_jaratok', [])
                        if not aktiv_jaratok and 'jarat_id' in st.session_state:
                            aktiv_jaratok = [st.session_state['jarat_id']]
                        
                        aktiv_jaratok_str = [str(j).strip() for j in aktiv_jaratok]
                        
                        if jarat_col_name and aktiv_jaratok_str:
                            df_futar_cimei = df_adatok_all[df_adatok_all[jarat_col_name].astype(str).str.strip().isin(aktiv_jaratok_str)]
                            
                            if not df_futar_cimei.empty:
                                cim_col_name = None
                                for c in df_futar_cimei.columns:
                                    if 'cím' in c.lower() or 'cim' in c.lower():
                                        cim_col_name = c
                                        break
                                
                                if cim_col_name:
                                    osszes_megallo = int(df_futar_cimei[cim_col_name].astype(str).str.strip().nunique())
                                    osszes_cim = len(df_futar_cimei)
                                else:
                                    osszes_cim = len(df_futar_cimei)
                                    osszes_megallo = osszes_cim
                except:
                    pass
                
                if osszes_cim == 0:
                    for c in df_sajat.columns:
                        if 'cím' in c.lower() or 'cim' in c.lower():
                            osszes_megallo = int(df_sajat[c].nunique())
                            osszes_cim = len(df_sajat[c])
                            break
                
                try:
                    ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary")
                    summary_records = ws_summary.get_all_records()
                    
                    for s_row in summary_records:
                        summary_futar = str(s_row.get('Futar', s_row.get('futar', ''))).strip().lower()
                        if summary_futar == "szűcs istván" or summary_futar == futar_keresett:
                            forgalmi_ertek = int(s_row.get('Forgalom', 0))
                            jutalek = int(s_row.get('Jutalek', s_row.get('Jutalék', 0)))
                            break
                except:
                    meta_forras = st.session_state.get('meta_data', {})
                    if isinstance(meta_forras, dict) and meta_forras.get('total_ertek', 0) > 0:
                        forgalmi_ertek = meta_forras.get('total_ertek', 0)
                        jutalek = meta_forras.get('futar_jutalek', 0)
    except Exception as e_global_dashboard:
        st.sidebar.error(f"⚠️ Műszerfal hiba: {e_global_dashboard}")

    # Statisztikai kártyák megjelenítése
    st.subheader("💰 Pénzügy & Mennyiség")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("📍 Tervezett megállók", f"{osszes_megallo} db")
        st.metric("🏠 Összes cím (ügyfél)", f"{osszes_cim} db")
    with col_s2:
        st.metric("📦 Összes étel", f"{osszes_etel} adag")
        st.metric("💵 Forgalom", f"{forgalmi_ertek:,} Ft".replace(",", " "))
        
    st.metric("⭐ Várható Jutalékod", f"{jutalek:,} Ft".replace(",", " "))
    st.write("---")

    # Kiszállítási haladás folyamatjelző
    st.subheader("🏁 Kiszállítás Haladás")
    kesz_cimek_szama = sum(1 for k in st.session_state.keys() if k.startswith("kiszallitott_statusz_") and st.session_state[k] == "Sikeres")
    
    haladas_szazalek = min(1.0, kesz_cimek_szama / osszes_cim) if osszes_cim > 0 else 0.0
    st.progress(haladas_szazalek)
    st.caption(f"Teljesítve: {kesz_cimek_szama} / {osszes_cim} cím ({int(haladas_szazalek * 100)}%)")
    st.write("---")

    # Sürgős hibajelentés útközben
    st.subheader("⚠️ Probléma az úton?")
    with st.expander("🚨 SÜRGŐS HIBABEJELENTÉS"):
        st.write("Sérült, elcserélt vagy elhagyott étel esetén itt jelezheted a központnak:")
        
        st_hiba_tipus = st.selectbox("Hiba jellege:", ["Sérült étel (kifolyt/kilyukadt)", "Elcserélt étel", "Hiányzó/Elhagyott étel"], key="sidebar_hiba_tipus")
        st_hiba_vevo = st.text_input("Vevő neve / Címe:", placeholder="Pl. Kovács Péter, Fő utca 12.", key="sidebar_hiba_vevo")
        st_hiba_leiras = st.text_area("Rövid leírás (Melyik étel?):", placeholder="Pl. A zóna rántott hús doboza elrepedt, kifolyt.", key="sidebar_hiba_leiras")
        
        if st.button("🚨 HIBA KÜLDÉSE A DISZPÉCSERNEK", type="primary", use_container_width=True, key="sidebar_hiba_submit_btn"):
            if not st_hiba_vevo or not st_hiba_leiras:
                st.error("❌ Kérlek, add meg a vevőt és a leírást!")
            else:
                is_test_mode = st.query_params.get("test", "false") == "true" or st.session_state.get('teszt_uzemmod', False)
                if is_test_mode:
                    st.warning("🧪 **Teszt mód:** A hibát rögzítettük.")
                else:
                    try:
                        hibak_sheet = client.open_by_key(SHEET_ID_UGYFELKOR).worksheet("Hibajelentések")
                        most_ido = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        hibak_sheet.append_row([most_ido, futar_nev_kiir, jarat_szoveg_kiir, st_hiba_tipus, st_hiba_vevo, st_hiba_leiras])
                        st.success("✅ A hiba elküldve!")
                    except Exception as e:
                        st.error(f"Mentési hiba: {e}")


def render_desktop_sidebar_controls(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, LOG_FILE):
    """Rendereli az asztali nézet adminisztrációs és vezérlési oldalsávját."""
    st.header("⚙️ Kezelés")
    is_admin = st.session_state.user_szerep in ["admin", "superadmin"]
    
    if is_admin:
        admin_funkcio = st.radio(
            "📌 Válassz funkciót:",
            ["📋 Raklista & Étlap Kezelés", "🚚 Logisztikai Központ & Stand"]
        )
    else:
        admin_funkcio = "📋 Raklista & Étlap Kezelés"
    
    st.divider()
    st.session_state.c_n = st.text_input("Futár Neve", st.session_state.c_n)
    st.session_state.c_p = st.text_input("Telefonszám", st.session_state.c_p)
    kivalasztott_datum = st.date_input("📅 Kiszállítás dátuma (Névnaphoz)", key="kivalasztott_datum")
    
    st.divider()
    if 'teszt_uzemmod' not in st.session_state:
        st.session_state.teszt_uzemmod = False
        
    st.session_state.teszt_uzemmod = st.toggle(
        "🧪 TESZT ÜZEMMÓD (Nincs mentés)", 
        value=st.session_state.teszt_uzemmod, 
        help="Ha bekapcsolod, sem a PDF feldolgozás, sem a mobil terminál nem fog írni a Google Sheets-be!"
    )
    
    if st.session_state.teszt_uzemmod:
        st.warning("⚠️ Adatbázis mentés letiltva (Asztali + Mobil)!")
    
    st.divider()

    if is_admin:
        st.subheader("🛡️ Adminisztrációs Központ")
        # JAVÍTÁS: Átadjuk a client objektumot!
        ev_most, het_most = get_latest_week_from_master(client, SHEET_ID_MASTER)
        
        if het_most < 24:
            st.error(f"⚠️ Étlap figyelmeztetés: Csak a **{het_most}. hétig** van feltöltve!")
            if st.button("🔄 Master Frissítése a 24. hétig"):
                with st.spinner("Szinkronizálás folyamatban..."):
                    # JAVÍTÁS: Átadjuk a client objektumot!
                    sync_master_database(client, SHEET_ID_MASTER, 2026, het_most + 1, 24)
                    st.success("Sikeres frissítés!")
                    st.rerun()
        else:
            st.success(f"✅ Étlapok naprakészek ({het_most}. hétig betöltve).")

        with st.expander("🛠 Master Adatbázis Karbantartás"):
            target_year = st.number_input("Év", min_value=2024, max_value=2030, value=2026)
            start_w = st.number_input("Kezdő hét", min_value=1, max_value=52, value=1)
            end_w = st.number_input("Záró hét", min_value=1, max_value=52, value=17)
            if st.button("🚀 Master Adatbázis Építése"):
                with st.spinner("Szinkronizálás..."):
                    # JAVÍTÁS: Átadjuk a client objektumot!
                    sync_master_database(client, SHEET_ID_MASTER, target_year, start_w, end_w)
                    st.success("Kész!")

        with st.expander("👤 Felhasználó Kezelés"):
            if 'futar_df' not in st.session_state:
                # JAVÍTÁS: Átadjuk a client objektumot!
                st.session_state.futar_df = load_futar_from_sheets(client, SHEET_ID_UGYFELKOR)

            df_to_edit = st.session_state.futar_df.astype(str)
            edited_df_users = st.data_editor(
                df_to_edit,
                column_config={
                    "Szerep": st.column_config.SelectboxColumn(
                        "Szerep",
                        options=["futar", "admin", "superadmin"],
                        required=True,
                    ),
                    "PIN_Kod": st.column_config.TextColumn(
                        "PIN_Kod",
                        required=True
                    )
                },
                use_container_width=True,
                num_rows="dynamic",
                key="user_editor"
            )

            if st.button("💾 Módosítások mentése", key="save_users_btn"):
                with st.spinner("Mentés..."):
                    # JAVÍTÁS: Átadjuk a client objektumot!
                    if save_futar_to_sheets(client, edited_df_users, SHEET_ID_UGYFELKOR):
                        st.session_state.futar_df = edited_df_users
                        st.success("Sikeres mentés!")
                        st.rerun()
                    else:
                        st.error("Hiba történt.")

        with st.expander("💻 Fejlesztői eszközök"):
            if st.button("Log fájl mutatása", use_container_width=True):
                if os.path.exists(LOG_FILE):
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        st.text_area("Naplóbejegyzések", "".join(f.readlines()[-100:]), height=200)
            if st.button("🗑️ Log törlése", use_container_width=True):
                if os.path.exists(LOG_FILE):
                    os.remove(LOG_FILE)
                    st.success("Napló törölve.")
                    
    return admin_funkcio


def process_uploaded_pdfs(up_files, client, sheet_id, ugyfelkor_sheet_id, kivalasztott_datum):
    """
    Feltöltött PDF-ek teljes körű feldolgozása, metaadat kinyerése, 
    Sheets szinkronizáció, statisztika és jutalékszámítás, valamint history logolás.
    """
    # 💥 Régi PDF-ek törlése a memóriából
    for key in ['ready_label_pdf', 'ready_manifest_pdf', 'ready_raklista_pdf']:
        if key in st.session_state:
            del st.session_state[key]
            
    meta_auto = extract_all_meta(up_files)
    st.session_state.meta_data = meta_auto
    
    ev = meta_auto.get('ev')
    het = meta_auto.get('het')

    if ev and het:
        session_key = f"sync_{ev}_{het}"
        if session_key not in st.session_state:
            with st.spinner(f"Étlap szinkronizálása ({ev}/W{het})..."):
                # JAVÍTÁS: Átadjuk a client objektumot!
                sync_interfood_etlap(client, ev, het, sheet_id)
                st.session_state[session_key] = True

    with st.spinner("Étlap adatok beolvasása..."):
        # JAVÍTÁS: Átadjuk a client objektumot!
        etlap_adatok = load_etlap_from_sheets(client, sheet_id)
        st.session_state.etlap_adatok = etlap_adatok

        napi_kodok = set()
        for kulcs in etlap_adatok.keys():
            parts = kulcs.split("_")
            if len(parts) > 1:
                napi_kodok.add(parts[1].strip().upper())
        st.session_state.napi_etlap_kodok = napi_kodok

    all_rows = []
    if 'user_jarat_lista' not in st.session_state:
        st.session_state.user_jarat_lista = []

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
            for r in rows:
                r['Járat'] = fajl_sajat_jarata if fajl_sajat_jarata else ""
            all_rows.extend(rows)

    if all_rows:
        df_temp = merge_data(all_rows)
        with st.spinner("Ügyféladatok szinkronizálása..."):
            mentett_meta = st.session_state.get('meta_data', None)
            if mentett_meta and isinstance(mentett_meta, dict) and mentett_meta.get('jaratok'):
                tartalek_jarat = mentett_meta['jaratok'][0]
            else:
                tartalek_jarat = None
            
            df_temp, m_df_friss = master_lista_szinkron(df_temp, ugyfelkor_sheet_id, client, jarat_szam=tartalek_jarat)
            st.session_state.master_df = m_df_friss
        
        st.session_state.mdf = df_temp
        
        # --- STATISZTIKÁK DINAMIKUS KISZÁMÍTÁSA ---
        try:
            api_datum_kulcs = str(meta_auto.get('datum_kulcs', meta_auto.get('datum', kivalasztott_datum))).strip()
            aktualis_futar = str(st.session_state.get('user_nev', 'Szűcs István')).strip()
            
            feltoltott_jaratok = []
            if 'Járat' in df_temp.columns:
                feltoltott_jaratok = df_temp['Járat'].dropna().astype(str).str.strip().unique().tolist()
                feltoltott_jaratok = [j for j in feltoltott_jaratok if j != "" and j.lower() != 'nan']
            jarat_szoveg = ", ".join(feltoltott_jaratok) if feltoltott_jaratok else "Nincs"

            szamitott_osszes_megallo = 0
            szamitott_osszes_cim = 0
            
            if 'Cím' in df_temp.columns:
                if 'Feldolgozó Futár' in df_temp.columns:
                    df_futar_szurt = df_temp[df_temp['Feldolgozó Futár'].astype(str).str.strip().str.lower() == aktualis_futar.lower()]
                    if not df_futar_szurt.empty:
                        szamitott_osszes_megallo = int(df_futar_szurt['Cím'].astype(str).str.strip().nunique())
                        szamitott_osszes_cim = len(df_futar_szurt)
                
                if szamitott_osszes_megallo == 0:
                    szamitott_osszes_megallo = int(df_temp['Cím'].astype(str).str.strip().nunique())
                    szamitott_osszes_cim = len(df_temp)
            else:
                st.warning("⚠️ A feltöltött adatokban nem található 'Cím' oszlop, a megállók száma 0 lett.")

            szamitott_osszes_etel = 0
            darab_col = None
            for c in df_temp.columns:
                if 'darab' in c.lower() or 'adag' in c.lower() or 'mennyiseg' in c.lower() or 'db' in c.lower():
                    darab_col = c
                    break
                    
            if darab_col:
                szamitott_osszes_etel = int(pd.to_numeric(df_temp[darab_col], errors='coerce').sum())
            else:
                st.warning("⚠️ Nem található darabszám vagy adag oszlop, az ételek száma 0 lett.")

            szamitott_total_ertek = 0
            szamitott_kp_forgalom = 0
            szamitott_borravalo = int(st.session_state.get('futar_borravalo', 0))
            
            ertek_col = None
            for c in df_temp.columns:
                if 'érték' in c.lower() or 'ertek' in c.lower() or 'forgalom' in c.lower() or 'összeg' in c.lower():
                    ertek_col = c
                    break
                    
            if ertek_col:
                szamitott_total_ertek = int(pd.to_numeric(df_temp[ertek_col], errors='coerce').sum())
                szamitott_kp_forgalom = szamitott_total_ertek
            else:
                st.error("❌ Nem sikerült kiszámítani a napi forgalmat (hiányzó érték oszlop)! A pénzügyi mutatók 0-zva lettek.")

        except Exception as e_calc:
            st.error(f"⚠️ Hiba történt a statisztikák kiszámítása közben: {e_calc}")
            api_datum_kulcs = str(kivalasztott_datum)
            aktualis_futar = str(st.session_state.get('user_nev', 'Szűcs István'))
            jarat_szoveg = "Hiba"
            szamitott_osszes_megallo = szamitott_osszes_cim = szamitott_osszes_etel = 0
            szamitott_total_ertek = szamitott_kp_forgalom = szamitott_borravalo = 0

        # --- JUTALÉK BÓNUSZ SÁV SZÁMÍTÁS ---
        szamitott_jutalek = 0
        try:
            target_sheet_id = ugyfelkor_sheet_id if ugyfelkor_sheet_id else sheet_id
            sh_ugyfelkor = client.open_by_key(target_sheet_id)
            
            fejlec = ["Datum", "Futar", "Jaratok", "Tervezett_Megallok", "Osszes_Cim", "Osszes_Etel", "Forgalom_Osszes", "Beszedett_KP", "Borravalo", "Vart_Jutalek"]
            
            if "Mobil_Summary" in [w.title for w in sh_ugyfelkor.worksheets()]:
                ws_summary = sh_ugyfelkor.worksheet("Mobil_Summary")
                summary_records = ws_summary.get_all_records()
            else:
                ws_summary = sh_ugyfelkor.add_worksheet("Mobil_Summary", rows=500, cols=len(fejlec))
                ws_summary.append_row(fejlec)
                summary_records = []

            ma_dt = datetime.datetime.strptime(api_datum_kulcs, "%Y-%m-%d")
            het_kezdete = ma_dt - datetime.timedelta(days=ma_dt.weekday())
            het_vege = het_kezdete + datetime.timedelta(days=6)
            
            eheti_eddigi_forgalom = 0
            existing_row_index = None
            
            for idx, row in enumerate(summary_records, start=2):
                r_date_str = str(row.get('Datum', '')).strip()
                r_futar = str(row.get('Futar', '')).strip().lower()
                
                if r_futar == aktualis_futar.lower():
                    try:
                        r_dt = datetime.datetime.strptime(r_date_str, "%Y-%m-%d")
                        if het_kezdete <= r_dt <= het_vege:
                            if r_date_str == api_datum_kulcs:
                                existing_row_index = idx
                            else:
                                eheti_eddigi_forgalom += int(pd.to_numeric(row.get('Forgalom_Osszes', 0), errors='coerce'))
                    except:
                        pass
                        
            teljes_eheti_forgalom = eheti_eddigi_forgalom + szamitott_total_ertek
            
            if teljes_eheti_forgalom >= 2100000:
                jutalek_kulcs = 0.14
                st.info(f"🎉 Gratulálunk! Az eheti összesített forgalom ({teljes_eheti_forgalom:,} Ft) elérte a limitet, a mai napra 14% jutalék jár!")
            else:
                jutalek_kulcs = 0.13
                
            szamitott_jutalek = int(round(szamitott_total_ertek * jutalek_kulcs))

        except Exception as e_futar_logic:
            st.error(f"⚠️ Nem sikerült ellenőrizni a heti jutaléksávot, alapértelmezett 13%-al számolunk. Hiba: {e_futar_logic}")
            szamitott_jutalek = int(round(szamitott_total_ertek * 0.13))

        # Memória frissítése
        if 'meta_data' not in st.session_state or not isinstance(st.session_state.meta_data, dict):
            st.session_state.meta_data = {}
        st.session_state.meta_data.update({
            'datum_kulcs': api_datum_kulcs,
            'osszes_megallo': szamitott_osszes_megallo,
            'osszes_cim': szamitott_osszes_cim,
            'osszes_etel': szamitott_osszes_etel,
            'total_ertek': szamitott_total_ertek,
            'kp_forgalom': szamitott_kp_forgalom,
            'borravalo': szamitott_borravalo,
            'futar_jutalek': szamitott_jutalek
        })

        # --- GOOGLE SHEETS MENTÉS / UPDATE ---
        if not st.session_state.get('teszt_uzemmod', False):
            try:
                uj_adat_sor = [
                    api_datum_kulcs, aktualis_futar, jarat_szoveg,
                    int(szamitott_osszes_megallo), int(szamitott_osszes_cim), int(szamitott_osszes_etel),
                    int(szamitott_total_ertek), int(szamitott_kp_forgalom), int(szamitott_borravalo), int(szamitott_jutalek)
                ]
                
                if existing_row_index:
                    cell_range = f"A{existing_row_index}:J{existing_row_index}"
                    ws_summary.update(cell_range, [uj_adat_sor])
                    st.success(f"🔄 Mobil_Summary sikeresen FRISSÍTVE: {api_datum_kulcs} - {aktualis_futar}")
                else:
                    ws_summary.append_row(uj_adat_sor)
                    st.success(f"➕ Új napi rekord HOZZÁADVA a Mobil_Summary-hez: {api_datum_kulcs} - {aktualis_futar}")
                    
            except Exception as sheets_error:
                st.error(f"⚠️ Nem sikerült az adatok feltöltése a Google Sheets-be: {sheets_error}")
        else:
            st.info("🧪 Teszt üzemmód aktív: A mentés átugorva.")
            
        if feltoltott_jaratok:
            st.session_state.aktiv_jaratok = feltoltott_jaratok
        
        st.success("🎉 A menettervek feldolgozása és a felhő szinkronizáció sikeresen megtörtént!")


def render_desktop_main_content(client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, admin_funkcio, is_admin):
    """Rendereli az asztali nézet fő munkaterületét (táblázat, térkép, mentések és letöltések)."""
    kivalasztott_datum = st.session_state.get('kivalasztott_datum', datetime.date.today())

    if is_admin and admin_funkcio == "🚚 Logisztikai Központ & Stand":
        if client:
            try:
                logisztika_sheet_objektum = client.open_by_key(SHEET_ID_UGYFELKOR)
                render_logisztikai_kozpont(logisztika_sheet_objektum)
            except Exception as sheet_err:
                st.error(f"❌ Nem sikerült megnyitni a Google Táblázatot: {sheet_err}")
        else:
            st.error("❌ A Google Sheets kapcsolat nincs inicializálva!")
        return

    # --- RAKLISTA GENERÁLÁS ÉS ÉTLAP KEZELÉS ---
    st.subheader("📄 Új PDF-ek")
    up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
    
    if up_files:
        if st.button("🚀 FELDOLGOZÁS", type="primary"):
            process_uploaded_pdfs(up_files, client, SHEET_ID_MASTER, SHEET_ID_UGYFELKOR, kivalasztott_datum)

    st.divider()

    # --- TÁBLÁZATSZERKESZTŐ ÉS FŐLAP ---
    if st.session_state.mdf is not None and not st.session_state.mdf.empty:
        role = check_user_role()
        df_view = st.session_state.mdf.copy()

        if role == "futar" and 'user_jarat_lista' in st.session_state:
            df_view = df_view[df_view['Járat'].astype(str).isin([str(j) for j in st.session_state.user_jarat_lista])].copy()
        
        if df_view.empty:
            st.warning(f"✉️ Kedves {st.session_state.user_nev}! A mai napra nincsenek aktív címeid.")
        else:
            if 'Sorrend' not in df_view.columns:
                df_view['Sorrend'] = range(1, len(df_view) + 1)
            
            df_view['Sorrend'] = pd.to_numeric(df_view['Sorrend'], errors='coerce').fillna(999.0).astype(float)
            for col in df_view.columns:
                if col != 'Sorrend':
                    df_view[col] = df_view[col].astype(str).replace(['nan', 'None', '<NA>', '0.0', '0'], '')

            df_view = df_view.sort_values(by='Sorrend').reset_index(drop=True)

            preferred_order = ["Sorrend", "Ügyintéző", "Cím", "Telefon", "Pénz", "Rendelés", "Csoport", "Megjegyzés", "temp_id"]
            actual_cols = df_view.columns.tolist()
            final_column_order = [c for c in preferred_order if c in actual_cols] + [c for c in actual_cols if c not in preferred_order]
            df_view = df_view[final_column_order]
                    
            edited_df = st.data_editor(
                df_view,
                column_order=final_column_order, 
                column_config={
                    "Sorrend": st.column_config.NumberColumn("Sorrend", help="Tizedes érték is megengedett (pl: 88.5)", format="%.1f", step=0.1),
                    "Csoport": st.column_config.TextColumn("Csoport"),
                    "Pénz": st.column_config.TextColumn("Pénz"),
                    "temp_id": None, 
                },
                num_rows="dynamic",
                key=f"editor_{st.session_state.editor_key}",
                use_container_width=True,
                hide_index=True
            )

            # Térkép integráció
            with st.expander("🗺️ Útvonal megtekintése a térképen", expanded=False):
                utvonal_terkep(df_napi=edited_df) 
            
            st.subheader("🗄️ Ügyfélkör kezelése")
            gomb_col1, gomb_col2 = st.columns(2)

            with gomb_col1:
                if st.button("🔄 Sorrend frissítése és újrasorszámozás", use_container_width=True):
                    edited_df['Sorrend'] = pd.to_numeric(edited_df['Sorrend'], errors='coerce').fillna(999)
                    edited_df = edited_df.sort_values('Sorrend').reset_index(drop=True)
                    edited_df['Sorrend'] = range(1, len(edited_df) + 1)
                    st.session_state.mdf = edited_df
                    st.session_state.editor_key += 1
                    st.success("🔄 Sorrend frissítve!")
                    st.rerun()

            with gomb_col2:
                if st.button("💾 Módosított adatok mentése", use_container_width=True):
                    try:
                        sh = client.open_by_key(SHEET_ID_UGYFELKOR)
                        ws_ugyfel = sh.worksheet("Ugyfelkor")
                        teljes_adat = ws_ugyfel.get_all_values()
                        
                        if not teljes_adat:
                            st.error("❌ A Google Sheets táblázat üres!")
                            st.stop()
                            
                        fejlec = teljes_adat[0]
                        id_idx = fejlec.index("ID") if "ID" in fejlec else 0
                        nev_idx = fejlec.index("Név") if "Név" in fejlec else (fejlec.index("Nev") if "Nev" in fejlec else 1)
                        cim_idx = fejlec.index("Cím") if "Cím" in fejlec else (fejlec.index("Cim") if "Cim" in fejlec else 2)
                        tel_idx = fejlec.index("Telefon") if "Telefon" in fejlec else 5
                        csop_idx = fejlec.index("Csoport") if "Csoport" in fejlec else 6
                        megj_idx = fejlec.index("Megjegyzés") if "Megjegyzés" in fejlec else (fejlec.index("Megjegyzes") if "Megjegyzes" in fejlec else 7)
                        
                        sheets_id_map = {str(teljes_adat[i][id_idx]).strip(): i for i in range(1, len(teljes_adat))}
                        
                        def tiszta_id_szoveg(val):
                            if pd.isna(val) or val == '': return ''
                            val_str = str(val).strip()
                            if val_str.endswith('.0'): val_str = val_str[:-2]
                            return val_str

                        edited_df_clean = edited_df.copy()
                        if 'ID' not in edited_df_clean.columns:
                            edited_df_clean = edited_df_clean.reset_index()
                            if 'index' in edited_df_clean.columns: edited_df_clean = edited_df_clean.rename(columns={'index': 'ID'})
                            elif 'level_0' in edited_df_clean.columns: edited_df_clean = edited_df_clean.rename(columns={'level_0': 'ID'})

                        if 'ID' not in edited_df_clean.columns:
                            st.error("⚠️ Nem található ID oszlop!")
                            st.stop()
                            
                        edited_df_clean['ID'] = edited_df_clean['ID'].apply(tiszta_id_szoveg)
                        mod_count = 0
                        
                        for _, row in edited_df_clean.iterrows():
                            current_id = row['ID']
                            if not current_id or current_id not in sheets_id_map: continue
                            
                            s_idx = sheets_id_map[current_id]
                            cols = row.index.tolist()
                            
                            if 'Név' in cols: teljes_adat[s_idx][nev_idx] = str(row['Név']).strip()
                            if 'Cím' in cols: teljes_adat[s_idx][cim_idx] = str(row['Cím']).strip()
                            if 'Telefon' in cols: teljes_adat[s_idx][tel_idx] = str(row['Telefon']).strip()
                            if 'Csoport' in cols: teljes_adat[s_idx][csop_idx] = str(row['Csoport']).strip()
                            if 'Megjegyzés' in cols: teljes_adat[s_idx][megj_idx] = str(row['Megjegyzés']).strip()
                            
                            mod_count += 1
                            
                            for k in ['ugyfelkor_df', 'mdf', 'master_ugyfelkor_df']:
                                if k in st.session_state and st.session_state[k] is not None:
                                    try:
                                        df = st.session_state[k]
                                        if not df.empty and 'ID' in df.columns:
                                            mask = df['ID'].astype(str) == str(current_id)
                                            if 'Név' in cols: df.loc[mask, 'Név'] = str(row['Név']).strip()
                                            if 'Cím' in cols: df.loc[mask, 'Cím'] = str(row['Cím']).strip()
                                            if 'Telefon' in cols: df.loc[mask, 'Telefon'] = str(row['Telefon']).strip()
                                            if 'Megjegyzés' in cols: df.loc[mask, 'Megjegyzés'] = str(row['Megjegyzés']).strip()
                                    except:
                                        pass

                        if mod_count > 0:
                            df_clean = pd.DataFrame(teljes_adat[1:], columns=fejlec)
                            df_cleaned = kotelezo_ugyfelkor_formatum_tisztitas(df_clean)
                            final_list = [fejlec] + df_cleaned.values.tolist()
                            ws_ugyfel.update('A1', final_list, value_input_option='RAW')
                            
                            if 'google_data_loaded' in st.session_state:
                                del st.session_state['google_data_loaded']
                                
                            st.success(f"🎉 Siker! Összesen {mod_count} ügyfél elmentve a felhőbe!")
                            st.balloons()
                            st.rerun()
                    except Exception as err:
                        st.error(f"Hiba a mentés során: {err}")

            st.divider()

            # --- DOKUMENTUM LETÖLTÉSEK SZAKASZ ---
            meta = st.session_state.meta_data if isinstance(st.session_state.meta_data, dict) else {}
            meta['datum_iso'] = str(kivalasztott_datum)
            jaratok_listaja = meta.get('jaratok', [])
            aktualis_jaratok = ", ".join(jaratok_listaja) if jaratok_listaja else "N/A"
            st.info(f"Észlelt járatok: **{aktualis_jaratok}** | Időpont: **{meta.get('ev', '')}. {meta.get('het', '')}. hét**")

            # Kellék Debug Panel
            with st.expander("🔍 Kellék Kereső Debug Panel (Fázis 3)", expanded=True):
                api_kulcs = meta.get('api_datum_kulcs', 'NINCS')
                st.write(f"Kiválasztott API dátum kulcs: `{api_kulcs}`")
                
                etlap_api_df = st.session_state.get('etlap_api_df', None)
                if etlap_api_df is not None:
                    keresett_nap_szamokkal = "".join(filter(str.isdigit, api_kulcs))
                    napi_oszlop = None
                    for col in etlap_api_df.columns:
                        clean_col_name = str(col).replace('\r', '').replace('\n', ' ').strip()
                        col_szamok = "".join(filter(str.isdigit, clean_col_name))
                        if keresett_nap_szamokkal and keresett_nap_szamokkal in col_szamok:
                            napi_oszlop = col
                            break
                    
                    if napi_oszlop:
                        st.success(f"✔ Megtalált napi oszlop: `{napi_oszlop.replace('\n', ' ')}`")
                        
                        for idx, r in edited_df.dropna(subset=['Rendelés_Full']).iterrows():
                            rendeles_szoveg = str(r.get('Rendelés_Full', ''))
                            if '*' in rendeles_szoveg:
                                st.write(f"**Ügyfél:** {r.get('Név', 'Névtelen')} (Sor: {idx}) ➔ Rendelés: `{rendeles_szoveg}`")
                                reszek = [x.strip() for x in rendeles_szoveg.replace('|', ',').replace('Pé:', '').replace('Szo:', '').split(',') if x.strip()]
                                for resz in reszek:
                                    if '*' in resz:
                                        kod_match = re.search(r'-([A-Z0-9]+)\*', resz.upper()) or re.search(r'([A-Z0-9]+)\*', resz.upper())
                                        if kod_match:
                                            t_kod = kod_match.group(1).strip()
                                            st.write(f"  • Kód: `{t_kod}`")
                                            e_sor = etlap_api_df[etlap_api_df.iloc[:, 0].astype(str).str.strip().str.startswith(t_kod, na=False)]
                                            if not e_sor.empty:
                                                etel_nev = str(e_sor.iloc[0][napi_oszlop]).strip()
                                                tisztitott_nev = clean_text(etel_nev)
                                                st.write(f"    ➔ 🍲 API Ételnév: `{etel_nev}`")
                                                master_df = st.session_state.get('master_df', None)
                                                if master_df is not None:
                                                    m_row = master_df[master_df['Tisztított Név'] == tisztitott_nev]
                                                    if not m_row.empty:
                                                        st.success(f"    ➔ 🎉 **KELLÉK: {m_row.iloc[0].get('Kellék', 'ÜRES')}**")
                                                    else:
                                                        st.error("    ➔ ❌ Nem található a Master_Adatbazisban!")
                    else:
                        st.error("❌ Nem található ehhez a naphoz tartozó étlap oszlop!")
                else:
                    st.error("Az Etlap_API nincs betöltve!")

            # PDF Előkészítés
            st.write("")
            if st.button("🚀 DOKUMENTUMOK ÉS RAKLISTA GENERÁLÁSA", type="primary", use_container_width=True):
                with st.spinner("⏳ PDF-ek generálása folyamatban..."):
                    if 'nevnapok_df' not in st.session_state or st.session_state.nevnapok_df.empty:
                        st.session_state.nevnapok_df = pd.DataFrame()
                        st.session_state.keresztnevek_df = pd.DataFrame()

                    try:
                        label_pdf_buf = create_label_pdf(
                            edited_df, st.session_state.c_n, st.session_state.c_p, meta, 
                            st.session_state.etelek_master_df, st.session_state.nevnapok_df, 
                            st.session_state.keresztnevek_df, st.session_state.etlap_api_df
                        )
                        st.session_state['ready_label_pdf'] = label_pdf_buf.getvalue() if label_pdf_buf else None
                        
                        manifest_pdf_buf = create_manifest_pdf(edited_df, st.session_state.c_n, meta)
                        st.session_state['ready_manifest_pdf'] = manifest_pdf_buf.getvalue() if manifest_pdf_buf else None
                        
                        raklista_pdf_buf = create_raklista_pdf(edited_df, aktualis_jaratok, meta, client.open_by_key(SHEET_ID_UGYFELKOR))
                        st.session_state['ready_raklista_pdf'] = raklista_pdf_buf.getvalue() if raklista_pdf_buf else None
                        st.success("✅ Minden dokumentum sikeresen elkészült!")
                    except Exception as pdf_err:
                        st.error(f"❌ Hiba PDF generálásnál: {pdf_err}")

            # Letöltési gombok megjelenítése
            if st.session_state.get('ready_label_pdf') and st.session_state.get('ready_manifest_pdf') and st.session_state.get('ready_raklista_pdf'):
                st.write("### 📥 Elkészült fájlok letöltése:")
                dl_c1, dl_c2, dl_c3 = st.columns(3)
                dl_c1.download_button("📄 ETIKETTEK LETÖLTÉSE", data=st.session_state['ready_label_pdf'], file_name="etikettek.pdf", mime="application/pdf", use_container_width=True)
                dl_c2.download_button("📋 MENETTERV LETÖLTÉSE", data=st.session_state['ready_manifest_pdf'], file_name="menetterv.pdf", mime="application/pdf", use_container_width=True)
                dl_c3.download_button("📊 RAKLISTA LETÖLTÉSE", data=st.session_state['ready_raklista_pdf'], file_name="raklista.pdf", mime="application/pdf", use_container_width=True)

            # QR kód generálás a mobilhoz
            st.write("---")
            st.subheader("📱 Mobil Terminál Indítása")
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
                * A futár azonnal eléri a digitális áruátvételt és ládázást a **{jarat_id if jarat_id else 'választott'}** járaton.
                * Direkt link: [{mobil_link}]({mobil_link})
                """)
            with qr_col2:
                st.image(byte_im, caption="Szkenneld be a mobil nézethez", width=180)
