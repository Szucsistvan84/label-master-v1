# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import time
import urllib.parse
import re
import datetime
from datetime import datetime as dt
from streamlit_js_eval import get_geolocation

# --- KAPCSOLÓDÓ CACHED OLVASÓ IMPORTÁLÁSA A KVÓTAVÉDELEMHÉZ ---
from adatbazis_modul import load_sheet_data_cached, SHEET_ID_UGYFELKOR

# --- Szigorú illesztés a rendelési kódokhoz (pl: 1-A1* vagy 4-S2) ---
ORDER_PAT = r'(\d+)-([A-Z0-9*]+)'

# Nap előtagok barátságos feloldása
DAY_PREFIX_MAP = {
    "Hé": "Hétfő",
    "Ke": "Kedd",
    "Sze": "Szerda",
    "Csü": "Csütörtök",
    "Pé": "Péntek",
    "Szo": "Szombat"
}

# ISO nap sorszámok a pontos dátumszámításhoz
DAY_TO_ISO = {
    "Hétfő": 1,
    "Kedd": 2,
    "Szerda": 3,
    "Csütörtök": 4,
    "Péntek": 5,
    "Szombat": 6,
    "Vasárnap": 7
}

def get_day_with_exact_date(day_name):
    """
    Kiszámolja az aktuális feldolgozott hét alapján a nap pontos naptári dátumát.
    Pl. "Szombat" -> "📅 Szombat (jún. 13.):"
    """
    try:
        meta = st.session_state.get('meta_data', {})
        year_val = meta.get('ev')
        week_val = meta.get('het')
        if year_val and week_val:
            year = int(year_val)
            week = int(week_val)
            iso_day = DAY_TO_ISO.get(day_name)
            if iso_day:
                import datetime as dt_lib
                date_obj = dt_lib.date.fromisocalendar(year, week, iso_day)
                months_hu = {
                    1: "jan.", 2: "febr.", 3: "márc.", 4: "ápr.", 5: "máj.", 6: "jún.",
                    7: "júl.", 8: "aug.", 9: "szept.", 10: "okt.", 11: "nov.", 12: "dec."
                }
                month_str = months_hu.get(date_obj.month, f"{date_obj.month:02d}.")
                return f"📅 {day_name} ({month_str} {date_obj.day}.):"
    except:
        pass
    return f"📅 {day_name}:"

def parse_order_by_days(rendeles_szoveg):
    """
    Intelligensen napok szerint csoportosítja a rendelési tételeket.
    Visszaad egy szótárt: {"Péntek": [("1", "M")], "Szombat": [("1", "M")]}
    """
    day_groups = {}
    if not rendeles_szoveg or str(rendeles_szoveg).strip() == "" or str(rendeles_szoveg).lower() == "nan":
        return day_groups
        
    parts = str(rendeles_szoveg).split('|')
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        # Megkeressük az előtagot, pl: "Pé:" vagy "Szo:"
        prefix_match = re.match(r'^([^:]+)\s*:', part)
        if prefix_match:
            raw_prefix = prefix_match.group(1).strip()
            clean_day = DAY_PREFIX_MAP.get(raw_prefix, raw_prefix)
            content_part = part[prefix_match.end():]
            found_items = re.findall(ORDER_PAT, content_part)
            if found_items:
                if clean_day not in day_groups:
                    day_groups[clean_day] = []
                day_groups[clean_day].extend(found_items)
        else:
            found_items = re.findall(ORDER_PAT, part)
            if found_items:
                if "Egyéb" not in day_groups:
                    day_groups["Egyéb"] = []
                day_groups["Egyéb"].extend(found_items)
                
    return day_groups

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
    # ÁLLAPOT 1: AZ ÁRÚÁTVÉTEL ÉS IDŐMÉRÉS MÉG EL SINCS INDÍTVA
    # =========================================================================
    if not st.session_state.aruatvetel_folyamatban:
        st.info("💡 Pakolás előtt indítsd el az áruátvételt a pontos munkaidő-méréshez.")
        if st.button("🚀 ÁRUÁTVÉTEL INDÍTÁSA", use_container_width=True, type="primary", key="futar_start_btn"):
            most = dt.now()
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
                        # --- TESZT ÜZEMMÓD ELLENŐRZÉSE ---
                        if st.session_state.get('teszt_uzemmod', False):
                            st.warning("🧪 **Teszt üzemmód aktív mobilon is!** A hibabejelentést sikeresen szimuláltuk, de a Google Sheets-be (Logisztikai_Hibak) NEM mentettünk semmit.")
                        else:
                            # ÉLES MENTÉS
                            try:
                                sh_ugyfelkor = client.open_by_key(SHEET_ID_UGYFELKOR)
                                hibak_sheet = sh_ugyfelkor.worksheet("Logisztikai_Hibak")
                                most_hiba = dt.now().strftime("%Y-%m-%d %H:%M:%S")
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
                                
                                # Töröljük a gyorsítótárat a frissülésért!
                                st.cache_data.clear()
                                
                                st.success("Sikeresen rögzítve! ✅")
                            except Exception as e:
                                st.error(f"Hiba a mentésnél: {e}")
                    else:
                        st.warning("Kérlek válaszd ki az ételt!")

            st.write("---")

            # ⏱️ ÁRUÁTVÉTEL RÖGZÍTÉSE
            if st.button("⏱️ ÁRUÁTVÉTEL VÉGE (Idő rögzítése)", use_container_width=True, type="secondary", key="futar_end_btn"):
                most = dt.now()
                end_ido = most.strftime("%H:%M:%S")
                
                try:
                    sh_master = client.open_by_key(SHEET_ID_UGYFELKOR)
                    idok_sheet = sh_master.worksheet("Mobil_Idobelyegek")
                    sor_szam = st.session_state.idobelyeg_sor_index
                    
                    if sor_szam:
                        idok_sheet.update_cell(sor_szam, 4, end_ido)
                    
                    st.cache_data.clear() # Gyorsítótár törlése a sikeres lezárás után
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
                st.cache_data.clear() # Gyorsítótár törlése a műszak végén
                st.balloons()
                st.success("Műszak sikeresen lezárva! Pihenj egyet! 😊")
                time.sleep(2.0)
                st.rerun()

def render_mobil_bepakolas(client, SHEET_ID_UGYFELKOR):
    # --- FEJLESZTETT CSS AZ AUTOMATIKUS TÖRDELÉSHEZ, NAGYOBB BETŰKHÖZ ÉS EXTRA KOMPAKT ELRENDEZÉSHEZ ---
    st.markdown(
        """
        <style>
        /* Szuper kompakt margóbeállítások mobilon */
        .block-container {
            padding-top: 0.5rem !important;
            padding-bottom: 0.8rem !important;
            padding-left: 0.4rem !important;
            padding-right: 0.4rem !important;
        }
        
        /* Összepréselt kártya a felesleges fehér sávok ellen */
        .grouped-card {
            background-color: #FFFFFF;
            border: 1px solid #D1D5DB;
            border-radius: 12px;
            padding: 8px 10px;
            margin-bottom: 5px; /* Szigorú, minimális térköz */
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }
        
        /* Sárga bónusz tipp banner a közös megállóknak */
        .group-tip {
            background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%);
            border: 1px solid #FCD34D;
            color: #92400E;
            padding: 6px 10px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: bold;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        /* Normál (Hétköznapi / Pénteki) tétel pille - NEM félkövér */
        .item-badge-weekday {
            display: inline-block;
            background-color: #EFF6FF;
            color: #1E40AF;
            border: 1px solid #BFDBFE;
            padding: 3px 8px;
            border-radius: 12px;
            margin: 2px;
            font-size: 13px;
            font-weight: 500; /* Medium, de nem félkövér! */
            white-space: nowrap;
        }
        
        /* Hétvégi (Szombati) tétel pille - HATÁROZOTTAN FÉLKÖVÉR és elegáns rózsaszínes háttér */
        .item-badge-weekend {
            display: inline-block;
            background-color: #FFF1F2;
            color: #9F1239;
            border: 1px solid #FECDD3;
            padding: 3px 8px;
            border-radius: 12px;
            margin: 2px;
            font-size: 13px;
            font-weight: 800; /* Erősen félkövér! */
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            white-space: nowrap;
        }
        
        /* Egyedi vevő doboz a csoportosított kártyán belül */
        .customer-item {
            background-color: #F9FAFB;
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            padding: 6px 8px;
            margin-bottom: 4px; /* Szigorú, minimális térköz a vevők között */
        }
        
        /* Szorosabb térköz a checkboxoknak */
        .stCheckbox {
            margin-bottom: 0px !important;
            padding-bottom: 0px !important;
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
            
            # Éles, korlátlan lekérés helyett a beépített cache-ből töltjük be az ügyfélkört!
            df_adatok = load_sheet_data_cached(client, SHEET_ID_UGYFELKOR, "Adatok") 
            
            if not df_adatok.empty:
                df_adatok.columns = [c.strip() for c in df_adatok.columns]
                cim_oszlop = 'Cím' if 'Cím' in df_adatok.columns else df_adatok.columns[3]
                nev_oszlop = 'Név' if 'Név' in df_adatok.columns else df_adatok.columns[1]
                rendeles_oszlop = 'Rendelés' if 'Rendelés' in df_adatok.columns else ('Kosár' if 'Kosár' in df_adatok.columns else None)
                
                # Biztosítjuk a Sorrend (etikett sorszám) oszlop meglétét
                if 'Sorrend' not in df_adatok.columns:
                    df_adatok['Sorrend'] = range(1, len(df_adatok) + 1)
                df_adatok['Sorrend'] = pd.to_numeric(df_adatok['Sorrend'], errors='coerce').fillna(999).astype(int)

                # Intelligens, dinamikus helyettesítő járat lefejtő motor!
                actual_filter_routes = []
                futar_neve = st.session_state.get('user_nev', 'Szűcs István')
                futar_neve_lower = str(futar_neve).strip().lower()

                for j in valasztott_jaratok:
                    if j in ["Mai Raklista", "Nincs elérhető járat", "Alapértelmezett Járat"]:
                        # 1. Megnézzük az Adatok fülön, hogy melyik járatok vannak ehhez a futárhoz rendelve ma
                        if 'Feldolgozó Futár' in df_adatok.columns:
                            routes_from_data = df_adatok[df_adatok['Feldolgozó Futár'].astype(str).str.strip().str.lower() == futar_neve_lower]['Járat'].unique()
                            actual_filter_routes.extend([str(r).strip() for r in routes_from_data if str(r).strip() != "" and str(r).lower() != "nan"])
                        
                        # 2. Ha az Adatok fül még üres, akkor az alapértelmezett profil járatokat vesszük elő (fallback)
                        if not actual_filter_routes:
                            actual_filter_routes.extend([str(r).strip() for r in st.session_state.get("user_jarat_lista", [])])
                    else:
                        actual_filter_routes.append(j)
                actual_filter_routes = list(set(actual_filter_routes))

                # 🔒 JÁRAT SZŰRÉS: Csak a futár járatcsoportjai alapján szűrjük az Adatok fület!
                jarat_col_name = next((c for c in df_adatok.columns if 'járat' in c.lower() or 'jarat' in c.lower()), None)
                if jarat_col_name:
                    df_adatok_filtered = df_adatok[df_adatok[jarat_col_name].astype(str).str.strip().isin(actual_filter_routes)].copy()
                else:
                    df_adatok_filtered = df_adatok.copy()

                if df_adatok_filtered.empty:
                    st.info("ℹ️ Nincsenek bepakolandó címek a járatodhoz.")
                    return

                # --- FORDÍTOTT SORRENDŰ CSOPORTOSÍTÁS ---
                # Kiszámoljuk az egyedi címek legmagasabb Sorrendjét, és csökkenő sorrendbe rendezzük a fordított pakolásért
                addr_max_sorrend = df_adatok_filtered.groupby(cim_oszlop)['Sorrend'].max().reset_index()
                addr_max_sorrend = addr_max_sorrend.sort_values(by='Sorrend', ascending=False)
                rendezett_cimek = addr_max_sorrend[cim_oszlop].tolist()

                # St.fragment az azonnali, villanásmentes checkbox pipálásokért
                @st.fragment
                def render_kartyak(df_lista, cimek):
                    for addr_idx, addr in enumerate(cimek):
                        # Leszűrjük a címhez tartozó megrendeléseket, és fordított etikett sorrendbe állítjuk
                        df_addr = df_lista[df_lista[cim_oszlop] == addr].sort_values(by='Sorrend', ascending=False)
                        
                        show_card = False
                        for idx, row in df_addr.iterrows():
                            bepakolt_kulcs = f"bepak_allapot_{idx}"
                            lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"
                            
                            # Biztosítjuk, hogy a session state-ben mindenképp létrejöjjön a kulcs beolvasás előtt!
                            if bepakolt_kulcs not in st.session_state:
                                st.session_state[bepakolt_kulcs] = False
                            if lada_tarolt_kulcs not in st.session_state:
                                st.session_state[lada_tarolt_kulcs] = None
                            
                            if not st.session_state[bepakolt_kulcs] or st.session_state.mutasd_bepakoltat:
                                show_card = True

                        if not show_card:
                            continue

                        # --- CSOPORTOSÍTOTT KÁRTYA KIÍRÁSA ---
                        st.markdown(f"""
                        <div class="grouped-card">
                            <div style="font-size: 15.5px; font-weight: bold; color: #1E3A8A; margin-bottom: 4px;">📍 Megálló: {addr}</div>
                        """, unsafe_allow_html=True)

                        # Bónusz tipp, ha több csomag is megy az adott címre
                        if len(df_addr) > 1:
                            st.markdown(f"""
                            <div class="group-tip">
                                💡 Tipp: Erre a címre {len(df_addr)} db rendelés megy! Szedheted őket egy közös szatyorba.
                            </div>
                            """, unsafe_allow_html=True)

                        # A címhez tartozó vevők és rendeléseik kilistázása a kártyán belül
                        for idx, row in df_addr.iterrows():
                            vevo_nev = str(row[nev_oszlop]).strip()
                            címke_szama = row['Sorrend']
                            megj = str(row.get('Megjegyzés', '')).strip()
                            rendeles_szoveg = str(row[rendeles_oszlop]).strip() if rendeles_oszlop else ""
                            
                            st.markdown(f"""
                            <div class="customer-item">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px;">
                                    <span style="font-size: 14.5px; font-weight: bold; color: #374151;">👤 {vevo_nev}</span>
                                    <span style="font-size: 12.5px; background-color: #E5E7EB; color: #374151; padding: 1px 5px; border-radius: 4px; font-weight: bold;">🏷️ Címke #{címke_szama}</span>
                                </div>
                            """, unsafe_allow_html=True)

                            if megj and megj != "nan" and megj != "":
                                st.markdown(f'<div style="font-size: 12.5px; color: #D97706; font-style: italic; margin-bottom: 3px;">📝 Megjegyzés: {megj}</div>', unsafe_allow_html=True)

                            # --- ÉTELEK NAP SZERINTI CSOPORTOSÍTÁSA ---
                            day_groups = parse_order_by_days(rendeles_szoveg)
                            
                            if day_groups:
                                badges_html = '<div style="margin-top: 4px; margin-bottom: 4px;">'
                                for day, items in day_groups.items():
                                    is_weekend = (day in ["Szombat", "Vasárnap"])
                                    badge_class = "item-badge-weekend" if is_weekend else "item-badge-weekday"
                                    exact_day_title = get_day_with_exact_date(day)
                                    
                                    # Címkének megfelelő formázás: Hétvégi tétel bold, hétköznapi normál
                                    bold_style = "font-weight: bold;" if is_weekend else "font-weight: normal; color: #4B5563;"
                                    badges_html += f'<div style="font-size: 13.5px; {bold_style} margin-top: 4px; margin-bottom: 2px;">{exact_day_title}</div>'
                                    badges_html += '<div style="display: flex; flex-wrap: wrap; gap: 2px;">'
                                    for qty, code in items:
                                        badges_html += f'<span class="{badge_class}">{qty}x {code}</span>'
                                    badges_html += '</div>'
                                badges_html += '</div>'
                                st.markdown(badges_html, unsafe_allow_html=True)
                            elif rendeles_szoveg and rendeles_szoveg != "nan" and rendeles_szoveg != "":
                                st.markdown(f'<div style="font-size: 12.5px; color: #4B5563;">📋 {rendeles_szoveg}</div>', unsafe_allow_html=True)

                            st.markdown('</div>', unsafe_allow_html=True)

                            # Checkbox kezelése a vevő alá rendelve
                            bepakolt_kulcs = f"bepak_allapot_{idx}"
                            lada_tarolt_kulcs = f"lada_szam_tarolt_{idx}"

                            if bepakolt_kulcs not in st.session_state:
                                st.session_state[bepakolt_kulcs] = False
                            if lada_tarolt_kulcs not in st.session_state:
                                st.session_state[lada_tarolt_kulcs] = None

                            def log_lada(i=idx):
                                if st.session_state[f"chk_{i}"]:
                                    st.session_state[f"bepak_allapot_{i}"] = True
                                    st.session_state[f"lada_szam_tarolt_{i}"] = f"{st.session_state.mobil_lada_szam}. láda"
                                else:
                                    st.session_state[f"bepak_allapot_{i}"] = False
                                    st.session_state[f"lada_szam_tarolt_{i}"] = None

                            tarolt_lada_ertek = st.session_state.get(lada_tarolt_kulcs, None)
                            label_text = f"Bepakolva: {tarolt_lada_ertek}" if tarolt_lada_ertek else f"Bepakolás a ládába ({vevo_nev})"
                            
                            st.checkbox(label_text, value=st.session_state[bepakolt_kulcs], key=f"chk_{idx}", on_change=log_lada)

                        st.markdown('</div>', unsafe_allow_html=True)

                # Kártyák kirajzolása
                render_kartyak(df_adatok_filtered, rendezett_cimek)
                
                # ==============================================================================
                # 🏁 BEPAKOLÁS LEZÁRÁSA
                # ==============================================================================
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
                            
                            most = dt.now()
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
    st.markdown("## 🚚 3. lépés: Kiszállítás és Elszámolás")
    st.caption("💡 Mindig a soron következő legfrissebb címet látod. Használd a gyorsgombokat!")

    try:
        valasztott_jaratok = [str(j).strip() for j in st.session_state.get("mob_jarat_select", [])]
        if not valasztott_jaratok:
            st.info("ℹ️ Válaszd ki a járatodat az 1. fülön!")
            return

        # JAVÍTÁS: Éles hívások helyett a gyorsítótárból töltjük be az Adatokat a 429-es hiba elkerülésére!
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

        # JAVÍTÁS: Virtuális járatnevek lefejtése a szűréshez valós járatszámokra a kiszállításnál is!
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

        # Szűrjük az adatokat a bejelentkezett járatokra a felesleges címek elkerülésére
        jarat_col_name = next((c for c in df_adatok.columns if 'járat' in c.lower() or 'jarat' in c.lower()), None)
        if jarat_col_name:
            df_kiszallitas = df_adatok[df_adatok[jarat_col_name].astype(str).str.strip().isin(actual_filter_routes)].copy()
        else:
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
            
            # 💰 Borravaló élő összesítő a menü sávban
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

            with st.container(border=True):
                st.markdown(f"### 📍 {sorszam}. Cím — `{melyik_lada}`")
                st.subheader(f"👤 {vevo_neve}")
                st.markdown(f"🏠 **Cím:** {aktualis_cim}")
                if aktualis_megj and aktualis_megj != "nan": 
                    st.warning(f"📝 **Megjegyzés:** {aktualis_megj}")
                
                # --- 🛒 KOSÁR TARTALMA (Pill stílusban leképezve a kiszállításnál is!) ---
                if rendeles_oszlop and str(row[rendeles_oszlop]).strip() != "" and str(row[rendeles_oszlop]).strip() != "nan":
                    st.markdown("📦 **Átadandó termékek:**")
                    day_groups = parse_order_by_days(str(row[rendeles_oszlop]).strip())
                    if day_groups:
                        badges_html = '<div style="margin-top: 4px; margin-bottom: 4px;">'
                        for day, items in day_groups.items():
                            is_weekend = (day in ["Szombat", "Vasárnap"])
                            badge_class = "item-badge-weekend" if is_weekend else "item-badge-weekday"
                            exact_day_title = get_day_with_exact_date(day)
                            
                            # Címkének megfelelő formázás a kiszállításnál is
                            bold_style = "font-weight: bold;" if is_weekend else "font-weight: normal; color: #4B5563;"
                            badges_html += f'<div style="font-size: 13.5px; {bold_style} margin-top: 4px; margin-bottom: 2px;">{exact_day_title}</div>'
                            badges_html += '<div style="display: flex; flex-wrap: wrap; gap: 2px;">'
                            for qty, code in items:
                                badges_html += f'<span class="{badge_class}">{qty}x {code}</span>'
                            badges_html += '</div>'
                        badges_html += '</div>'
                        st.markdown(badges_html, unsafe_allow_html=True)
                    else:
                        st.code(str(row[rendeles_oszlop]).strip(), language="text")
                
                # --- 🗺️ OPENSTREETMAP BEÁGYAZÁS ---
                if saved_lat and saved_lon and saved_lat != "nan" and saved_lon != "nan":
                    embed_url = f"https://www.google.com/maps/search/?api=1&query={saved_lat},{saved_lon}&zoom=16&layers=M"
                else:
                    clean_address = f"{aktualis_cim}, Hungary"
                    encoded_osm = urllib.parse.quote(clean_address)
                    embed_url = f"https://maps.google.com/maps?q={encoded_osm}&zoom=16&layers=M"
                
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
                    if loc and 'coords' in loc:
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
                        st.warning("⏳ Várakozás valós GPS jelre... (Mobilon, térerő mellett fog azonnal megjelenni, asztali gépen nem elérhető).")

                st.write("---")
                
                # --- 💰 INTELLIGENS BORRAVALÓ SZÁMÍTÁS ---
                elovart_osszeg = 0
                if penz_oszlop:
                    nyers_penz = str(row[penz_oszlop]).replace("Ft", "").replace(" ", "").replace("\xa0", "").strip()
                    try:
                        elovart_osszeg = int(pd.to_numeric(nyers_penz, errors='coerce'))
                    except:
                        elovart_osszeg = 0
                        
                st.markdown(f"💵 **Fizetendő összeg:** `{elovart_osszeg:,} Ft`" if elovart_osszeg > 0 else "💵 **Fizetendő összeg:** `Nincs megadva (0 Ft)`")
                
                # Input mező az átvett összegnek (Alapértelmezetten pontosan annyi, amennyit kérünk)
                atvett_osszeg = st.number_input(
                    "💰 Ügyféltől átvett készpénz (Ft):",
                    min_value=0,
                    value=int(elovart_osszeg),
                    step=50,
                    key=f"atvett_input_{idx}"
                )
                
                # Borravaló számítása: Kapott - Elvárt
                szamitott_borravalo = 0
                if atvett_osszeg > elovart_osszeg:
                    szamitott_borravalo = atvett_osszeg - elovart_osszeg
                    st.success(f"➕ Észlelt borravaló ezen a címen: **{szamitott_borravalo:,} Ft**")
                elif atvett_osszeg < elovart_osszeg and atvett_osszeg > 0:
                    st.warning(f"⚠️ Figyelem! Kevesebb pénzt kaptál, mint a számla összege ({elovart_osszeg - atvett_osszeg:,} Ft hiány)!")

                # --- LEZÁRÁS ---
                if st.button("✅ Cím sikeresen átadva", key=f"siker_{idx}", use_container_width=True, type="primary"):
                    st.session_state[f"borravalo_{idx}"] = szamitott_borravalo
                    st.session_state[f"kiszallitva_{idx}"] = True
                    st.toast(f"🎉 {vevo_neve} sikeresen kézbesítve!")
                    st.rerun()
            
            break
            
        else:
            # 🏆 Ha minden cím elfogyott, akkor összesítjük és véglegenítjük a borravalót
            teljes_napi_borravalo = sum(int(st.session_state.get(f"borravalo_{idx}", 0)) for idx, _ in bepakolt_sorok)
            st.session_state['futar_borravalo'] = teljes_napi_borravalo
            
            st.balloons()
            st.success(f"🏆 Szép munka! Minden mára tervezett címet sikeresen kézbesítettél!")
            st.info(f"💰 A mai napon összegyűjtött összes borravalód: **{teljes_napi_borravalo:,} Ft**, ez automatikusan hozzáadásra kerül a záró elszámolásodhoz!")
            
            if st.button("🔄 Teszt adatok törlése (Újraindítás)", use_container_width=True):
                for k in list(st.session_state.keys()):
                    if "kiszallitva_" in k or "lada_szam_tarolt_" in k or "borravalo_" in k or "atvett_input_" in k:
                        del st.session_state[k]
                st.session_state['futar_borravalo'] = 0
                st.rerun()

    except Exception as e:
        st.error(f"Hiba a kiszállítás futtatásakor: {e}")
