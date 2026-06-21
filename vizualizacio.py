# -*- coding: utf-8 -*-
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json

def utvonal_terkep(df_napi, sheet_id=None):
    """
    Kirajzolja a napi útvonalat egy interaktív térképen.
    Sorszámozott Leaflet.js markereket használ egész számként formázva,
    és összekötő vonallal mutatja meg a kézbesítési sorrendet.
    """
    if df_napi is None or df_napi.empty:
        st.warning("⚠️ Nincs adat az útvonal kirajzolásához!")
        return

    # 1. Biztonsági másolat készítése
    map_df = df_napi.copy()

    # 2. Oszlopok ellenőrzése
    if 'Lat' not in map_df.columns or 'Lon' not in map_df.columns:
        st.warning("⚠️ A táblázat nem tartalmaz 'Lat' and 'Lon' oszlopokat!")
        return

    try:
        # 3. Tizedesvesszők és típusok megtisztítása
        for col in ['Lat', 'Lon']:
            map_df[col] = (
                map_df[col]
                .astype(str)
                .str.replace(',', '.', regex=False)
                .str.replace(' ', '', regex=False)
                .str.strip()
            )
            map_df[col] = pd.to_numeric(map_df[col], errors='coerce')

        # 4. Érvényes koordináták szűrése és sorszám szerinti szigorú növekvő rendezés
        map_df['latitude'] = map_df['Lat']
        map_df['longitude'] = map_df['Lon']
        
        map_data = map_df.dropna(subset=['latitude', 'longitude']).copy()
        map_data = map_data[
            (map_data['latitude'] > 45.0) & (map_data['latitude'] < 49.0) &
            (map_data['longitude'] > 16.0) & (map_data['longitude'] < 23.5)
        ]

        if 'Sorrend' in map_data.columns:
            map_data['Sorrend_num'] = pd.to_numeric(map_data['Sorrend'], errors='coerce').fillna(999)
            map_data = map_data.sort_values(by='Sorrend_num', ascending=True)

        if map_data.empty:
            st.warning("⚠️ Nincs megjeleníthető érvényes GPS koordináta a mai listán!")
            return

        # 5. Adatsorok átalakítása tiszta JSON formátumba a JavaScript számára (egész sorszámokkal)
        points = []
        for _, row in map_data.iterrows():
            raw_index = row.get('Sorrend', '•')
            try:
                # Kényszerített egész számmá alakítás (pl. 1.0 -> 1)
                clean_index = str(int(float(raw_index)))
            except (ValueError, TypeError):
                # Fallback, ha nem lebegőpontos szám lenne
                clean_index = str(raw_index).split('.')[0] if '.' in str(raw_index) else str(raw_index)
            
            points.append({
                "index": clean_index if clean_index.strip() != "" else "•",
                "lat": float(row['latitude']),
                "lon": float(row['longitude']),
                "name": str(row.get('Név', row.get('Ügyintéző', 'Névtelen Vevő'))),
                "address": str(row.get('Cím', 'Ismeretlen Cím'))
            })

        points_json = json.dumps(points, ensure_ascii=False)

        # 6. Szuper-biztonságos HTML + Leaflet.js sablon
        html_map_code = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                html, body, #map {{
                    height: 100%;
                    width: 100%;
                    margin: 0;
                    padding: 0;
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                }}
                #map {{
                    height: 480px;
                    border-radius: 12px;
                    border: 1.5px solid #E5E7EB;
                    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                }}
                /* Egyedi, modern sorszámozott marker dizájn */
                .number-icon {{
                    background: #1E3A8A;
                    border: 2px solid #FFFFFF;
                    border-radius: 50%;
                    color: #FFFFFF;
                    font-weight: 800;
                    text-align: center;
                    line-height: 22px;
                    font-size: 11px;
                    box-shadow: 0 4px 8px rgba(30, 58, 138, 0.4);
                    transition: transform 0.2s ease;
                }}
                .number-icon:hover {{
                    transform: scale(1.15);
                    background: #2563EB;
                }}
                /* Leaflet Popup buborék stílusos finomítása */
                .leaflet-popup-content-value {{
                    font-size: 12px;
                    line-height: 1.4;
                }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var points = {points_json};
                
                if (points.length > 0) {{
                    // Térkép inicializálása az első megálló koordinátáival
                    var map = L.map('map').setView([points[0].lat, points[0].lon], 13);
                    
                    // Elegáns, tiszta, modern utcatérkép réteg betöltése
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                        attribution: '© OpenStreetMap contributors'
                    }}).addTo(map);

                    var latlngs = [];
                    var markersGroup = L.featureGroup();

                    points.forEach(function(p) {{
                        var latlng = [p.lat, p.lon];
                        latlngs.push(latlng);

                        // Egyedi sorszámozott kör ikon létrehozása
                        var icon = L.divIcon({{
                            className: 'number-icon',
                            html: p.index,
                            iconSize: [26, 26],
                            iconAnchor: [13, 13]
                        }});

                        var marker = L.marker(latlng, {{icon: icon}})
                            .bindPopup("<div class='leaflet-popup-content-value'><b>📍 " + p.index + ". Megálló</b><br><b>👤 " + p.name + "</b><br>🏠 " + p.address + "</div>")
                            .addTo(map);
                            
                        markersGroup.addLayer(marker);
                    }});

                    // Szaggatott, sötétkék útvonalvezető vonal kirajzolása (Sequence Path)
                    if (latlngs.length > 1) {{
                        var polyline = L.polyline(latlngs, {{
                            color: '#2563EB',
                            weight: 4,
                            opacity: 0.8,
                            dashArray: '8, 8',
                            lineJoin: 'round'
                        }}).addTo(map);
                        
                        // Automatikus zoomolás és térképigazítás, hogy az összes megálló egyszerre látszódjon
                        map.fitBounds(markersGroup.getBounds(), {{ padding: [30, 30] }});
                    }}
                }}
            </script>
        </body>
        </html>
        """

        # HTML térkép komponens beágyazása a Streamlit felületre
        st.markdown(f"🗺️ **Aktív megállók a térképen:** {len(map_data)} cím")
        components.html(html_map_code, height=490)
        
    except Exception as e:
        st.error(f"❌ Hiba a térkép kirajzolása során: {e}")
