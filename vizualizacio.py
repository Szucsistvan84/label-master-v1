# vizualizacio.py
import streamlit as st
import pandas as pd
import folium
import folium.plugins
from streamlit_folium import st_folium
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import urllib.parse

def utvonal_terkep(df_napi, sheet_id=None, client=None):
    """
    Kiszállítási útvonal térképes megjelenítése Folium-mal és koordináta karbantartás.
    KIZÁRÓLAG a hajszálpontosan egyező koordinátájú ügyfeleket vonja össze.
    """
    # A biztonságos tisztítót importáljuk (feltételezve, hogy a tisztitók modulban lakik, 
    # vagy ha az app.py-ban hagytad, importálható onnan. Itt most helyben is definiálhatjuk, 
    # ha szükséges, vagy importáljuk a leendő helyéről)
    try:
        from utils import biztonsagos_koordinata_tisztito
    except ImportError:
        # Ha még nincs utils, egyelőre legyen itt a fallback, hogy ne szálljon el
        def biztonsagos_koordinata_tisztito(v):
            if pd.isna(v) or str(v).strip() == "": return None
            v_str = str(v).replace("'", "").replace('"', '').replace(",", ".").strip()
            try: return round(float(v_str), 6)
            except: return None

    st.subheader("🗺️ Tervezett Kiszállítási Útvonal")
    
    # Session state és kliens ellenőrzése
    actual_client = st.session_state.get('client') if 'client' in st.session_state else client
    actual_sheet_id = st.session_state.get('sheet_id') if 'sheet_id' in st.session_state else sheet_id

    if not actual_client or isinstance(actual_client, str):
        st.error("❌ A Google Sheets kliens nincs inicializálva!")
        return
    if not actual_sheet_id:
        st.error("❌ A Google Sheets ID hiányzik!")
        return

    # 1. Google Sheets törzslista beolvasása
    try:
        sh = actual_client.open_by_key(actual_sheet_id)
        ws = sh.worksheet("Ugyfelkor")
        df_torzs = pd.DataFrame(ws.get_all_records())
    except Exception as e:
        st.error(f"Nem sikerült beolvasni az Ugyfelkor törzslistát: {e}")
        return

    # 2. Adatok összefésülése
    df_valid_gps = df_napi.copy()
    if 'ID' in df_valid_gps.columns and 'ID' in df_torzs.columns:
        df_valid_gps['ID'] = df_valid_gps['ID'].astype(str).str.strip()
        df_torzs['ID'] = df_torzs['ID'].astype(str).str.strip()
        
        cols_to_drop = [c for c in ['Lat', 'Lon', 'Név', 'Cím'] if c in df_valid_gps.columns]
        df_megtisztitott = df_valid_gps.drop(columns=cols_to_drop)
        df_valid_gps = pd.merge(df_megtisztitott, df_torzs[['ID', 'Név', 'Cím', 'Lat', 'Lon']], on='ID', how='left')

    # Koordináták tisztítása és számmá alakítása
    for col in ['Lat', 'Lon']:
        if col in df_valid_gps.columns:
            df_valid_gps[col] = df_valid_gps[col].astype(str).str.replace("'", "").str.replace('"', '').str.replace(",", ".").str.strip()
            df_valid_gps[col] = pd.to_numeric(df_valid_gps[col], errors='coerce')

    # Csak a valós, jó koordináták megtartása
    df_jo_gps = df_valid_gps[df_valid_gps['Lat'].notna() & df_valid_gps['Lon'].notna()].copy()
    df_jo_gps = df_jo_gps[(df_jo_gps['Lat'] >= -90) & (df_jo_gps['Lat'] <= 90) & (df_jo_gps['Lon'] >= -180) & (df_jo_gps['Lon'] <= 180)]

    if df_jo_gps.empty:
        st.info("💡 Nincs megjeleníthető koordináta a térképen.")
        m = folium.Map(location=[47.5316, 21.6273], zoom_start=12)
    else:
        if 'Sorrend' in df_jo_gps.columns:
            df_jo_gps['Kijelzendo_Sorrend'] = pd.to_numeric(df_jo_gps['Sorrend'], errors='coerce')
        else:
            df_jo_gps['Kijelzendo_Sorrend'] = range(1, len(df_jo_gps) + 1)
            
        df_jo_gps = df_jo_gps.sort_values(by='Kijelzendo_Sorrend')
        m = folium.Map(location=[df_jo_gps.iloc[0]['Lat'], df_jo_gps.iloc[0]['Lon']], zoom_start=14)

        # --- SEBÉSZI PONTOSSÁGÚ TÖMBHÁZ CSOPORTOSÍTÁS ---
        df_jo_gps['Coord_Key'] = df_jo_gps['Lat'].astype(str) + "_" + df_jo_gps['Lon'].astype(str)
        
        vonal_pontok = []
        utolso_pont = None
        megallok = []
        
        for coord_key, group in df_jo_gps.groupby('Coord_Key', sort=False):
            group = group.sort_values(by='Kijelzendo_Sorrend')
            sorszamok = group['Kijelzendo_Sorrend'].astype(int).tolist()
            
            if len(sorszamok) > 1:
                tol_ig_szoveg = f"{min(sorszamok)}-{max(sorszamok)}"
            else:
                tol_ig_szoveg = str(sorszamok[0])
                
            megallok.append({
                'lat': group.iloc[0]['Lat'],
                'lon': group.iloc[0]['Lon'],
                'tol_ig': tol_ig_szoveg,
                'ugyfelek': group.to_dict('records'),
                'elso_sorszam': min(sorszamok)
            })
            
        megallok = sorted(megallok, key=lambda x: x['elso_sorszam'])
        
        for megallo in megallok:
            aktualis_pont = [megallo['lat'], megallo['lon']]
            if utolso_pont is None or utolso_pont != aktualis_pont:
                vonal_pontok.append(aktualis_pont)
                utolso_pont = aktualis_pont

        if len(vonal_pontok) >= 2:
            try:
                folium.plugins.AntPath(
                    locations=vonal_pontok, dash_array=[10, 20], delay=1000,
                    color='#0072ff', pulse_color='#ffffff', weight=5, opacity=0.8
                ).add_to(m)
            except:
                folium.PolyLine(vonal_pontok, color="#0072ff", weight=4, opacity=0.7).add_to(m)

        for megallo in megallok:
            cím = megallo['ugyfelek'][0].get('Cím', megallo['ugyfelek'][0].get('Cim', 'Nincs cím'))
            
            popup_html = f"""
            <div style="font-family: Arial, sans-serif; min-width: 210px;">
                <h4 style="margin:0 0 5px 0; color:#0072ff;">📭 Megállópont: {megallo['tol_ig']}</h4>
                <p style="margin:0 0 10px 0; font-size:12px; color:#555;"><b>Cím:</b> {cím}</p>
                <table style="width:100%; border-collapse: collapse; font-size:12px;">
                    <tr style="background:#f0f0f0; font-weight:bold;">
                        <th style="padding:3px; border:1px solid #ddd;">Sor.</th>
                        <th style="padding:3px; border:1px solid #ddd;">Név</th>
                        <th style="padding:3px; border:1px solid #ddd;">ID</th>
                    </tr>
            """
            for u in megallo['ugyfelek']:
                u_nev = u.get('Név', u.get('Nev', u.get('Ügyintéző', 'Ismeretlen')))
                u_sor = int(u['Kijelzendo_Sorrend'])
                popup_html += f"""
                    <tr>
                        <td style="padding:3px; border:1px solid #ddd; text-align:center; font-weight:bold;">{u_sor}</td>
                        <td style="padding:3px; border:1px solid #ddd;">{u_nev}</td>
                        <td style="padding:3px; border:1px solid #ddd; text-align:center; color:#777;">{u['ID']}</td>
                    </tr>
                """
            popup_html += "</table></div>"

            doboz_szelesseg = "38px" if "-" in megallo['tol_ig'] else "26px"
            
            folium.Marker(
                location=[megallo['lat'], megallo['lon']],
                popup=folium.Popup(popup_html, max_width=350),
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        position: relative;
                        background-color: #0072ff;
                        color: white;
                        border: 2px solid white;
                        border-radius: 13px;
                        width: {doboz_szelesseg};
                        height: 26px;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        font-weight: bold;
                        font-size: 11px;
                        white-space: nowrap;
                        padding: 0 4px;
                        box-shadow: 0px 2px 5px rgba(0,0,0,0.4);
                        transform: translate(-50%, -50%);
                    ">{megallo['tol_ig']}</div>
                    """
                )
            ).add_to(m)

    st_folium(m, width=700, height=500, returned_objects=[])

    # --- ÁLLANDÓ KOORDINÁTA KARBANTARTÓ PANEL ---
    st.markdown("---")
    st.subheader("🛠️ Ügyfél Koordináták Karbantartása / Javítása")
    
    with st.expander("⚠️ VESZÉLYES ZÓNA: Google Sheets Adatbázis Formátum Javítása"):
        st.write("Ez a gomb végigmegy a teljes Google Sheets táblázatodon, és az összes elrontott dupla aposztrófos koordinátát átalakítja szóló aposztrófos formátumra – mindezt EGYETLEN API hívással.")
        
        if st.button("🚨 FUTTASD A GOOGLE SHEETS NAGYTAKARÍTÁST"):
            try:
                with st.spinner("⏳ Adatbázis letöltése és elemzése..."):
                    if "gcp_service_account" in st.secrets:
                        creds_dict = dict(st.secrets["gcp_service_account"])
                    else:
                        creds_dict = dict(st.secrets)

                    if "private_key" in creds_dict: 
                        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
                        
                    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                    client = gspread.authorize(creds)

                    sheet = client.open_by_key(actual_sheet_id)
                    worksheet = sheet.worksheet("Ugyfelkor")
                    rows = worksheet.get_all_values()

                    if not rows:
                        st.warning("A táblázat üres!")
                    else:
                        header = rows[0]
                        lat_idx = header.index("Lat") if "Lat" in header else -1
                        lon_idx = header.index("Lon") if "Lon" in header else -1

                        if lat_idx == -1 or lon_idx == -1:
                            st.error("❌ Nem találom a 'Lat' vagy 'Lon' oszlopot a táblázatban!")
                        else:
                            javitott_db = 0
                            frissitando_cellak = []
                            
                            for idx, row_data in enumerate(rows[1:], start=2):
                                if len(row_data) <= max(lat_idx, lon_idx): continue
                                    
                                nyers_lat = str(row_data[lat_idx]).strip()
                                nyers_lon = str(row_data[lon_idx]).strip()
                                
                                uj_lat, uj_lon = None, None
                                
                                tiszta_lat = biztonsagos_koordinata_tisztito(nyers_lat)
                                if tiszta_lat is not None:
                                    uj_lat = f"'{str(tiszta_lat).replace('.', ',')}"
                                        
                                tiszta_lon = biztonsagos_koordinata_tisztito(nyers_lon)
                                if tiszta_lon is not None:
                                    uj_lon = f"'{str(tiszta_lon).replace('.', ',')}"

                                valtozott = False
                                if uj_lat and uj_lat != nyers_lat:
                                    frissitando_cellak.append(gspread.Cell(row=idx, col=lat_idx + 1, value=uj_lat))
                                    valtozott = True
                                if uj_lon and uj_lon != nyers_lon:
                                    frissitando_cellak.append(gspread.Cell(row=idx, col=lon_idx + 1, value=uj_lon))
                                    valtozott = True
                                    
                                if valtozott: javitott_db += 1

                            if frissitando_cellak:
                                with st.spinner(f"⏳ {len(frissitando_cellak)} cella egységesítése a felhőben..."):
                                    worksheet.update_cells(frissitando_cellak, value_input_option='USER_ENTERED')
                                st.success(f"🎉 SIKER! Összesen {javitott_db} ügyfél koordinátája lett javítva!")
                            else:
                                st.info("✨ Az adatbázis már teljesen tiszta!")
                            
                            if 'ugyfelkor_df' in st.session_state:
                                del st.session_state['ugyfelkor_df']
                            st.rerun()
            except Exception as e:
                st.error(f"Hiba a takarítás során: {e}")
    
    # Lusta betöltés pajzs
    if 'ugyfelkor_df' not in st.session_state or st.session_state.ugyfelkor_df.empty:
        with st.spinner("🔄 Teljes ügyfélkör betöltése a Google Sheets-ből..."):
            try:
                if "gcp_service_account" in st.secrets:
                    creds_dict = dict(st.secrets["gcp_service_account"])
                else:
                    creds_dict = dict(st.secrets)
                if "private_key" in creds_dict: 
                    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
                creds = Credentials.from_service_account_info(creds_dict, scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"])
                client = gspread.authorize(creds)
                
                sh_ugyfel = client.open_by_key(actual_sheet_id)
                ws_ugyfelkor = sh_ugyfel.worksheet("Ugyfelkor")
                
                try: records = ws_ugyfelkor.get_all_records(value_render_option='UNFORMATTED_VALUE')
                except: records = ws_ugyfelkor.get_all_records()
                if records:
                    tisztitott_master = pd.DataFrame(records)
                    tisztitott_master.columns = [c.strip() for c in tisztitott_master.columns]
                    
                    if 'Lat' in tisztitott_master.columns:
                        tisztitott_master['Lat'] = tisztitott_master['Lat'].apply(biztonsagos_koordinata_tisztito)
                    if 'Lon' in tisztitott_master.columns:
                        tisztitott_master['Lon'] = tisztitott_master['Lon'].apply(biztonsagos_koordinata_tisztito)
                    
                    st.session_state.ugyfelkor_df = tisztitott_master
            except Exception as e:
                st.error(f"Nem sikerült elérni a Google Sheets ügyfélkört: {e}")

    if 'ugyfelkor_df' in st.session_state and not st.session_state.ugyfelkor_df.empty:
        df_karbantartas_forras = st.session_state.ugyfelkor_df
    else:
        df_karbantartas_forras = df_valid_gps

    if not df_karbantartas_forras.empty:
        df_rendezett_karbantartas = df_karbantartas_forras.copy()
        df_rendezett_karbantartas['Karbantarto_Nev'] = df_rendezett_karbantartas.apply(
            lambda r: f"⚠️ [HIÁNYZÓ GPS] {r['ID']} - {r.get('Név', r.get('Nev', r.get('Ügyintéző', 'Ismeretlen')))} ({r.get('Cím', r.get('Cim', 'Nincs cím'))})"
            if pd.isna(r['Lat']) or pd.isna(r['Lon']) or str(r['Lat']).strip() == "" or float(str(r['Lat']).replace("'", "").replace(",", ".").strip()) > 90
            else f"📍 [Térképen van] {r['ID']} - {r.get('Név', r.get('Nev', r.get('Ügyintéző', 'Ismeretlen')))} ({r.get('Cím', r.get('Cim', 'Nincs cím'))})", axis=1
        )
        
        lista_opciok = df_rendezett_karbantartas['Karbantarto_Nev'].tolist()
        kivallasztott = st.selectbox("Válaszd ki a javítani vagy pótolni kívánt ügyfelet:", lista_opciok)
        
        if kivallasztott:
            kiv_id = kivallasztott.split("] ")[1].split(" - ")[0].strip()
            talalatok = df_karbantartas_forras[df_karbantartas_forras['ID'] == kiv_id]
            
            if not talalatok.empty:
                kiv_sor = talalatok.iloc[0]
                aktualis_cim = kiv_sor.get('Cím', kiv_sor.get('Cim', 'Nincs cím'))
                aktualis_nev = kiv_sor.get('Név', kiv_sor.get('Nev', kiv_sor.get('Ügyintéző', 'Ismeretlen')))
            else:
                st.warning("⚠️ Adatok frissülnek, kérlek válassz újra!")
                aktualis_cim, aktualis_nev = "Frissítés alatt...", "Frissítés alatt..."

            if 'kiv_sor' in locals() and kiv_sor is not None:
                sor_dict = kiv_sor.to_dict() if hasattr(kiv_sor, 'to_dict') else dict(kiv_sor)
                biztonsagos_lat = sor_dict.get('Lat', 'Nincs adat')
                biztonsagos_lon = sor_dict.get('Lon', 'Nincs adat')
                if pd.isna(biztonsagos_lat) or str(biztonsagos_lat).strip() == "": biztonsagos_lat = 'Nincs adat'
                if pd.isna(biztonsagos_lon) or str(biztonsagos_lon).strip() == "": biztonsagos_lon = 'Nincs adat'
            else:
                biztonsagos_lat, biztonsagos_lon = "Nincs adat", "Nincs adat"
            
            form_col, map_col = st.columns([1.2, 1])
            
            with form_col:
                st.info(f"**Kiválasztva:** {aktualis_nev}\n* **Cím:** {aktualis_cim}\n* **Jelenlegi GPS:** Lat: `{biztonsagos_lat}`, Lon: `{biztonsagos_lon}`")
                
                with st.form("gps_javito_form_vegleges", clear_on_submit=False):
                    akt_lat = str(biztonsagos_lat).replace("'", "").strip() if biztonsagos_lat != 'Nincs adat' else ""
                    akt_lon = str(biztonsagos_lon).replace("'", "").strip() if biztonsagos_lon != 'Nincs adat' else ""
                    
                    try:
                        valid_lat_test = float(akt_lat.replace(",", "."))
                        alap_ertek = f"{akt_lat}, {akt_lon}" if valid_lat_test <= 90 and akt_lat and akt_lon else ""
                    except: alap_ertek = ""
                    
                    st.markdown("**Másold be a Google Maps-ről kapott értéket egyben:**")
                    egyben_koordinata = st.text_input("Koordináták (Lat, Lon)", value=alap_ertek, placeholder="Pl: 47.530773, 21.625137")
                    submit = st.form_submit_button("💾 Koordináták mentése")
                    
                    if submit:
                        if egyben_koordinata.strip():
                            try:
                                if "," in egyben_koordinata:
                                    reszek = egyben_koordinata.split(",")
                                    nyers_lat, nyers_lon = reszek[0].strip(), reszek[1].strip()
                                else:
                                    reszek = egyben_koordinata.split()
                                    if len(reszek) >= 2: nyers_lat, nyers_lon = reszek[0].strip(), reszek[1].strip()
                                    else:
                                        st.error("❌ Nem felismerhető koordináta formátum!")
                                        st.stop()
                                
                                f_lat = round(float(nyers_lat.replace("'", "").replace('"', '').replace(",", ".").strip()), 6)
                                f_lon = round(float(nyers_lon.replace("'", "").replace('"', '').replace(",", ".").strip()), 6)
                                
                                sh = actual_client.open_by_key(actual_sheet_id)
                                ws = sh.worksheet("Ugyfelkor")
                                fejlec = ws.row_values(1)
                                lat_idx = fejlec.index("Lat") + 1 if "Lat" in fejlec else 4
                                lon_idx = fejlec.index("Lon") + 1 if "Lon" in fejlec else 5
                                
                                cell = ws.find(str(kiv_id))
                                if cell:
                                    ws.update_cell(cell.row, lat_idx, f_lat)
                                    ws.update_cell(cell.row, lon_idx, f_lon)
                                    
                                    if "Utolso_Rendeles" in fejlec:
                                        utolso_idx = fejlec.index("Utolso_Rendeles") + 1
                                        ws.update_cell(cell.row, utolso_idx, datetime.now().strftime('%Y.%m.%d'))
                                    
                                    for session_key in ['ugyfelkor_df', 'mdf', 'master_ugyfelkor_df']:
                                        if session_key in st.session_state and st.session_state[session_key] is not None:
                                            try:
                                                df = st.session_state[session_key]
                                                if not df.empty and 'ID' in df.columns:
                                                    df.loc[df['ID'].astype(str) == str(kiv_id), 'Lat'] = f_lat
                                                    df.loc[df['ID'].astype(str) == str(kiv_id), 'Lon'] = f_lon
                                            except: pass

                                    if 'google_data_loaded' in st.session_state:
                                        del st.session_state['google_data_loaded']
                                        
                                    st.success(f"✅ Siker! {aktualis_nev} koordinátái frissítve!")
                                    st.rerun()
                                else: st.error("❌ Az ügyfél ID nem található!")
                            except ValueError: st.error("❌ Érvénytelen számformátum!")
                            except Exception as save_err: st.error(f"❌ Mentési hiba: {save_err}")
                        else: st.warning("⚠️ Adj meg koordinátákat!")
            
            with map_col:
                st.write("🗺️ **Beágyazott Google Maps segédablak:**")
                biztonsagos_cim = urllib.parse.quote(str(aktualis_cim))
                maps_url = f"https://maps.google.com/maps?q={biztonsagos_cim}&t=&z=16&ie=UTF8&iwloc=&output=embed"
                st.components.v1.iframe(maps_url, height=260, scrolling=True)
