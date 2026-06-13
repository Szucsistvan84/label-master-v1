# admin_modul.py
import streamlit as st
import pandas as pd
from datetime import datetime

def render_logisztikai_kozpont(sheet):
    """
    Logisztikai és Pénzügyi Vezérlőpult kirajzolása.
    Központi adminisztráció, standolás, munkaidő és automatizált teljesítmény-ellenőrzés.
    """
    st.title("🚚 Logisztikai és Pénzügyi Vezérlőpult")
    st.caption("Központi adminisztráció, standolás, munkaidő és automatizált teljesítmény-ellenőrzés.")
    
    # 🌟 KIBŐVÍTETT FÜLEK
    tabs = st.tabs([
        "⚠️ Élő Hibák & Eltérések", 
        "💰 Futár Stand & Elszámolás", 
        "⏱️ Munkaidő Figyelő",
        "🚗 Automata KM Kontroll",
        "📊 Statisztikai Központ & Legek"
    ])
    
    # =========================================================================
    # 1. TAB: ÉLŐ HIBÁK ÉS ELTÉRÉSEK
    # =========================================================================
    with tabs[0]:
        st.subheader("Napközbeni sérülések, hiányok és jóváírások")
        try:
            hibak_sheet = sheet.worksheet("Logisztikai_Hibak")
            hibak_data = hibak_sheet.get_all_records()
            if hibak_data:
                df_hibak = pd.DataFrame(hibak_data)
                if 'Admin_Státusz' in df_hibak.columns:
                    df_hibak['Admin_Státusz'] = df_hibak['Admin_Státusz'].fillna('Feldolgozatlan')
                else:
                    df_hibak['Admin_Státusz'] = 'Feldolgozatlan'
                aktiv_hibak = df_hibak[df_hibak['Admin_Státusz'] == 'Feldolgozatlan']
                
                if not aktiv_hibak.empty:
                    st.error(f"Figyelem! {len(aktiv_hibak)} feldolgozatlan logisztikai hiba van folyamatban!")
                    st.dataframe(
                        aktiv_hibak[['Időbélyeg', 'Járat_ID', 'Ügyfél Neve', 'Cikkszám', 'Étel Neve', 'Mennyiség', 'Összérték', 'Hiba Típusa']],
                        use_container_width=True, hide_index=True
                    )
                    st.write("---")
                    valasztott_sor = st.selectbox("Válaszd ki a feldolgozott ügyfelet:", aktiv_hibak['Ügyfél Neve'].unique())
                    if st.button(f"✅ {valasztott_sor} hibájának lezárása (Jóváírva)"):
                        for idx, row in enumerate(hibak_data):
                            if row['Ügyfél Neve'] == valasztott_sor and row.get('Admin_Státusz', 'Feldolgozatlan') == 'Feldolgozatlan':
                                hibak_sheet.update_cell(idx + 2, 11, "Jóváírva")
                                st.success(f"{valasztott_sor} státusza sikeresen frissítve!")
                                st.rerun()
                else:
                    st.success("Minden logisztikai hiba fel van dolgozva! ✅")
            else:
                st.info("A logisztikai hibalista jelenleg üres.")
        except Exception as e:
            st.warning(f"A Logisztikai_Hibak fül nem elérhető vagy üres: {e}")

    # =========================================================================
    # 2. TAB: RÉSZLETEZETT FUTÁR STAND (Ügyviteli rendszer kompatibilis)
    # =========================================================================
    df_adatok_for_km = pd.DataFrame() # Helyi változó a KM fülnek fallbackként
    
    with tabs[1]:
        st.subheader("Napi pénzügyi stand járatok szerint")
        
        try:
            adatok_sheet = sheet.worksheet("Adatok")
            adatok_data = adatok_sheet.get_all_records()
            df_adatok = pd.DataFrame(adatok_data)
            df_adatok_for_km = df_adatok.copy() # Elmentjük a KM fülnek
            
            if not df_adatok.empty:
                df_adatok.columns = [c.strip() for c in df_adatok.columns]
                df_adatok['Fizetendő'] = pd.to_numeric(df_adatok['Fizetendő'], errors='coerce').fillna(0)
                
                jaratok = [j for j in df_adatok['Járat'].unique() if str(j).strip() != ""]
                valasztott_jarat = st.selectbox("Válassz járatot a standoláshoz:", jaratok)
                
                if valasztott_jarat:
                    df_jarat = df_adatok[df_adatok['Járat'] == valasztott_jarat]
                    
                    stand_kp = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'KÉSZPÉNZ']['Fizetendő'].sum()
                    stand_kartya = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'BANKKÁRTYA']['Fizetendő'].sum()
                    stand_szep = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'SZÉP KÁRTYA']['Fizetendő'].sum()
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("💵 Leadandó Készpénz", f"{int(stand_kp):,} Ft".replace(",", " "))
                    col2.metric("💳 Bankkártya bizonylat", f"{int(stand_kartya):,} Ft".replace(",", " "))
                    col3.metric("🌸 SZÉP Kártya bizonylat", f"{int(stand_szep):,} Ft".replace(",", " "))
                    
                    st.write("---")
                    st.markdown(f"### 📋 Ügyviteli pipáló lista – {valasztott_jarat} járat")
                    st.caption("A lenti listák sorrendje és összegei megegyeznek azzal, amit a futár lát a telefonján és amit az ügyviteli szoftverben kell kipipálni.")
                    
                    st.markdown("#### 💵 KÉSZPÉNZES ÜGYFELEK (Kipipálandó az ügyviteli rendszerben):")
                    df_kp_list = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'KÉSZPÉNZ']
                    
                    if not df_kp_list.empty:
                        megjelenit_kp = df_kp_list[['ID', 'Név', 'Cím', 'Fizetendő', 'Státusz']].copy()
                        megjelenit_kp['Fizetendő'] = megjelenit_kp['Fizetendő'].apply(lambda x: f"{int(x)} Ft")
                        
                        st.dataframe(
                            megjelenit_kp,
                            column_config={
                                "ID": "Ügyfélkód",
                                "Név": "Ügyfél Neve",
                                "Cím": "Szállítási Cím",
                                "Fizetendő": "Beszedett Összeg",
                                "Státusz": "Futár Státusz"
                            },
                            use_container_width=True, hide_index=True
                        )
                        st.markdown(f"**Készpénzes tételek összesen: {len(df_kp_list)} db ügyfél | Végösszeg: {int(stand_kp):,} Ft**".replace(",", " "))
                    else:
                        st.info("Ezen a járaton nincs készpénzes beszedés.")
                        
                    st.write(" ")
                    st.markdown("#### 💳 BANKKÁRTYÁS ÜGYFELEK (Bizonylatok ellenőrzéséhez):")
                    df_cc_list = df_jarat[df_jarat['Fizetési Mód'].str.upper() == 'BANKKÁRTYA']
                    if not df_cc_list.empty:
                        megjelenit_cc = df_cc_list[['ID', 'Név', 'Fizetendő', 'Státusz']].copy()
                        megjelenit_cc['Fizetendő'] = megjelenit_cc['Fizetendő'].apply(lambda x: f"{int(x)} Ft")
                        st.dataframe(megjelenit_cc, use_container_width=True, hide_index=True)
                    else:
                        st.caption("Nincs bankkártyás tétel.")
            else:
                st.info("Nincsenek szállítási adatok az Adatok munkalapon.")
        except Exception as e:
            st.error(f"Hiba a stand adatok beolvasásakor: {e}")

    # =========================================================================
    # 3. TAB: MUNKAIDŐ FIGYELŐ
    # =========================================================================
    with tabs[2]:
        st.subheader("Futárok napi időbélyegei és áruátvételi idői")
        try:
            idok_sheet = sheet.worksheet("Mobil_Idobelyegek")
            idok_data = idok_sheet.get_all_records()
            if idok_data:
                df_idok = pd.DataFrame(idok_data)
                percek = []
                for _, row in df_idok.iterrows():
                    try:
                        fmt = "%H:%M:%S"
                        if row.get('Áruátvétel_Start') and row.get('Áruátvétel_End'):
                            start = datetime.strptime(str(row['Áruátvétel_Start']).strip(), fmt)
                            end = datetime.strptime(str(row['Áruátvétel_End']).strip(), fmt)
                            kulonbseg = (end - start).seconds // 60
                            percek.append(f"{kulonbseg} perc")
                        else:
                            percek.append("Folyamatban...")
                    except:
                        percek.append("N/A")
                df_idok['Áruátvételi Idő'] = percek
                st.dataframe(df_idok, use_container_width=True, hide_index=True)
            else:
                st.info("Még nincsenek rögzített időbélyegek.")
        except Exception as e:
            st.warning(f"A Mobil_Idobelyegek fül még üres: {e}")

    # =========================================================================
    # 4. TAB: AUTOMATA KM KONTROLL (Csalásbiztos modul)
    # =========================================================================
    with tabs[3]:
        st.subheader("🚗 Automatizált Futásteljesítmény Ellenőrzés")
        st.markdown("""
        *Ez a modul a mobil terminál által visszaküldött leadási sorrend és a címek GPS koordinátái alapján automatikusan számolja a futásteljesítményt.*
        **Nincs szükség futár általi km-óra bemondásra – a rendszer a valóságot méri.**
        """)
        
        km_teszt_adat = {
            "Futár": ["Te (Teszt Üzemmód)"],
            "Járat": ["Észlelt aktív járat"],
            "Címek száma": [len(df_adatok_for_km) if not df_adatok_for_km.empty else 0],
            "Ténylegesen bejárt sorrend": ["Optimalizált (Mobil GPS / Időbélyeg szerint)"],
            "Szoftveres Útvonalhossz": ["Számítás alatt... (Jövő héten indul)"],
            "Státusz": ["🔄 Várakozás az első mobil terminálos lezárásra"]
        }
        st.dataframe(pd.DataFrame(km_teszt_adat), use_container_width=True, hide_index=True)
        st.info("💡 **Hogyan fog működni?** Amint a mobilodon elkezded kiszállítani a címeket, a rendszer rögzíti, hogy milyen sorrendben nyomtál rájuk. Ebből a modul (háttérben futó távolságmátrixszal) méterre pontosan rekonstruálja a megtett utat, kiküszöbölve a kézi trükközéseket.")

    # =========================================================================
    # 5. TAB: STATISZTIKAI KÖZPONT & LEGEK
    # =========================================================================
    with tabs[4]:
        st.subheader("📊 Vezetői Kimutatások & Futár Legek")
        st.markdown("Az adatok forrása: az **'Adatok'** munkalap történelmi szállítási és pénzügyi bejegyzései.")
        st.warning("📉 **Adatgyűjtés folyamatban:** Mivel a tesztüzem jövő héten indul, a grafikonok jelenleg mintaként illusztrálják a jövőbeli felületet.")
        
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.markdown("#### 🏆 Top Futárok (Kiszállított címek alapján)")
            demo_top_data = pd.DataFrame({
                'Futár': ['Futár Alajos', 'Futár Béla', 'Te (Előrejelzés)'],
                'Címek': [42, 38, 55]
            }).set_index('Futár')
            st.bar_chart(demo_top_data)
            st.caption("Ki teljesítette a legtöbb címet a kiválasztott időszakban?")

        with chart_col2:
            st.markdown("#### 💸 Napi Pénzügyi Volumenek (Forgalom alakulása)")
            demo_trend_data = pd.DataFrame({
                'Nap': ['Hétfő', 'Kedd', 'Szerda', 'Csütörtök', 'Péntek'],
                'Összforgalom (Ft)': [120000, 145000, 138000, 162000, 195000]
            }).set_index('Nap')
            st.line_chart(demo_trend_data)
            st.caption("A logisztika által mozgatott napi készpénz és kártyás forgalom trendje.")

        st.write("---")
        st.markdown("### 🔍 Gazdaságossági és 'Leggyengébb láncszem' Figyelő")
        
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric(label="Legjövedelmezőbb Járat", value="4002-es járat", delta="+12% forgalom")
        metric_col2.metric(label="Legtöbb Hibát Generáló Kör", value="3001-es kör", delta="5 hiba/hét", delta_color="inverse")
        metric_col3.metric(label="Legoptimálisabb Km/Cím arány", value="1.2 km / cím", delta="-0.4 km megtakarítás")
        st.info("☝️ **Vezetői döntéstámogatás:** Amint feltöltődik a Sheets történelmi adatokkal, azonnal látni fogod, ha egy járat üzemanyag- vagy időarányosan veszteségessé válik (pl. túl sokat kell autózni túl kevés címért), így azonnal be tudsz avatkozni a járatok átszervezésébe.")
