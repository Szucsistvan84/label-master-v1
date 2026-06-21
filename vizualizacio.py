# -*- coding: utf-8 -*-
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json

def utvonal_terkep(df_napi, sheet_id=None):
    """
    Kirajzolja a napi útvonalat egy interaktív térképen.
    Összevonja az azonos koordinátájú ügyfeleket egyetlen közös buborékba,
    így ha egy címre több étel is megy, mindegyik név és sorszám láthatóvá válik.
    Támogatja a piros javító tűt és a beépített Nominatim címkeresőt.
    """
    if df_napi is None or df_napi.empty:
        st.warning("⚠️ Nincs adat az útvonal kirajzolásához!")
        return

    # 1. Biztonsági másolat készítése, hogy ne rontsuk el az eredeti táblázatot
    map_df = df_napi.copy()

    # 2. Oszlopok ellenőrzése
    if 'Lat' not in map_df.columns or 'Lon' not in map_df.columns:
        st.warning("⚠️ A táblázat nem tartalmaz 'Lat' és 'Lon' oszlopokat!")
        return

    try:
        # 3. Tizedesvesszők és típusok megtisztítása számmá alakítással
        for col in ['Lat', 'Lon']:
            map_df[col] = (
                map_df[col]
                .astype(str)
                .str.replace(',', '.', regex=False)
                .str.replace(' ', '', regex=False)
                .str.strip()
            )
            map_df[col] = pd.to_numeric(map_df[col], errors='coerce')

        # 4. Kiszűrjük azokat a sorokat, ahol nincs érvényes GPS koordináta Magyarország területén
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

        # 5. CSOPORTOSÍTÁS KOORDINÁTÁK ALAPJÁN (Azonos helyre mutató címek összevonása)
        # Kerekítjük a koordinátákat 6 tizedesjegyre az apróbb GPS-ingadozások kiküszöbölésére
        map_data['lat_round'] = map_data['latitude'].round(6)
        map_data['lon_round'] = map_data['longitude'].round(6)
        
        grouped = map_data.groupby(['lat_round', 'lon_round'])
        
        points = []
        for (lat, lon), group in grouped:
            # Sorszám szerint rendezzük a csoporton belüli ügyfeleket
            group_sorted = group.sort_values(by='Sorrend_num')
            
            clients_list = []
            indices_list = []
            
            for _, row in group_sorted.iterrows():
                raw_index = row.get('Sorrend', '•')
                try:
                    clean_index = str(int(float(raw_index)))
                except (ValueError, TypeError):
                    clean_index = str(raw_index).split('.')[0] if '.' in str(raw_index) else str(raw_index)
                
                indices_list.append(clean_index)
                clients_list.append({
                    "index": clean_index,
                    "name": str(row.get('Név', row.get('Ügyintéző', 'Névtelen Vevő'))),
                    "address": str(row.get('Cím', 'Ismeretlen Cím'))
                })
            
            # Ha egynél több ügyfél van ugyanott, akkor pl. "3+" formátumban jelezzük az ikonon
            if len(indices_list) > 1:
                display_index = f"{indices_list[0]}+"
            else:
                display_index = indices_list[0]
                
            points.append({
                "display_index": display_index,
                "first_index_num": int(group_sorted.iloc[0]['Sorrend_num']),
                "lat": float(lat),
                "lon": float(lon),
                "clients": clients_list,
                "address": clients_list[0]["address"]  # Megosztott cím
            })

        # Sorbarendezzük a csoportosított pontokat az eredeti útvonal-sorszámuk alapján,
        # így az összekötő vonal (polyline) nem fog összevissza ugrálni!
        points.sort(key=lambda x: x["first_index_num"])
        points_json = json.dumps(points, ensure_ascii=False)

        # 6. HTML + Leaflet.js sablon több-ügyfelet kezelő felugró ablakokkal
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
                /* Egyedi sorszámozott marker dizájn */
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
                .leaflet-popup-content-value {{
                    font-size: 12px;
                    line-height: 1.45;
                    max-width: 220px;
                }}
                /* Címkereső widget dizájn */
                .map-search-panel {{
                    background: white;
                    padding: 4px;
                    border-radius: 8px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
                    display: flex;
                    gap: 4px;
                    border: 1.5px solid #D1D5DB;
                }}
                .map-search-input {{
                    width: 180px;
                    padding: 6px;
                    font-size: 12px;
                    border: 1px solid #E5E7EB;
                    border-radius: 6px;
                    outline: none;
                }}
                .map-search-btn {{
                    background: #1E3A8A;
                    color: white;
                    border: none;
                    padding: 6px 10px;
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: bold;
                    cursor: pointer;
                    transition: background 0.2s;
                }}
                .map-search-btn:hover {{
                    background: #2563EB;
                }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var points = {points_json};
                var map;
                var javitoTű = null;
                
                // Helper másoló függvény a homokozó iframe vágólap eléréséhez
                window.masolGPS = function() {{
                    var copyText = document.getElementById("gps_val_input");
                    if (copyText) {{
                        copyText.select();
                        copyText.setSelectionRange(0, 99999);
                        try {{
                            document.execCommand('copy');
                            var msg = document.getElementById("copy_ok_msg");
                            if (msg) msg.style.display = "block";
                            setTimeout(function() {{
                                if (msg) msg.style.display = "none";
                            }}, 2000);
                        }} catch (err) {{
                            console.error("Nem sikerült a másolás", err);
                        }}
                    }}
                }};

                // Golyóálló piros tű lehelyező és frissítő funkció
                window.helyezRedMarker = function(latlng) {{
                    var lat = latlng.lat.toFixed(6);
                    var lon = latlng.lng.toFixed(6);

                    if (javitoTű) {{
                        javitoTű.setLatLng(latlng);
                    }} else {{
                        javitoTű = L.marker(latlng, {{
                            draggable: true,
                            icon: L.icon({{
                                iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
                                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41],
                                popupAnchor: [1, -34],
                                shadowSize: [41, 41]
                            }})
                        }}).addTo(map);

                        // Húzás végének figyelése
                        javitoTű.on('dragend', function(evt) {{
                            var drag_lat = evt.target.getLatLng().lat.toFixed(6);
                            var drag_lon = evt.target.getLatLng().lng.toFixed(6);
                            var input_field = document.getElementById('gps_val_input');
                            if (input_field) {{
                                input_field.value = drag_lat + "," + drag_lon;
                            }}
                        }});
                    }}

                    var popupHtml = `
                        <div style="font-size:12px; width:180px; text-align:center;">
                            <b style="color:#DC2626;">🎯 Új GPS Pozíció</b><br>
                            <span style="font-size:10px; color:#6B7280;">Húzd a kapura, ha nem pontos!</span><br>
                            <input type="text" id="gps_val_input" value="${{lat}},${{lon}}" style="width:100%; margin:6px 0; font-size:11px; text-align:center; font-weight:bold; border:1px solid #D1D5DB; padding:2px; border-radius:4px;" readonly><br>
                            <button onclick="window.masolGPS()" style="width:100%; background:#1E3A8A; color:white; border:none; border-radius:6px; padding:6px; font-weight:bold; cursor:pointer; font-size:11.5px; margin-top:2px;">📋 Koordináta Másolása</button>
                            <div id="copy_ok_msg" style="color:#10B981; font-weight:bold; font-size:10.5px; margin-top:4px; display:none;">✨ Sikeresen másolva a vágólapra!</div>
                        </div>
                    `;

                    javitoTű.bindPopup(popupHtml).openPopup();
                }};

                // Címkereső futtatása Nominatim API-val
                window.keresCimet = function() {{
                    var input = document.getElementById("map_address_search");
                    if (!input || !input.value.trim()) return;
                    var address = input.value.trim();
                    
                    var query = address;
                    if (!query.toLowerCase().includes("debrecen") && !query.toLowerCase().includes("ebes")) {{
                        query += ", Debrecen";
                    }}
                    if (!query.toLowerCase().includes("hungary") && !query.toLowerCase().includes("magyarország")) {{
                        query += ", Hungary";
                    }}

                    fetch("https://nominatim.openstreetmap.org/search?format=json&q=" + encodeURIComponent(query) + "&limit=1")
                        .then(response => response.json())
                        .then(data => {{
                            if (data && data.length > 0) {{
                                var lat = parseFloat(data[0].lat);
                                var lon = parseFloat(data[0].lon);
                                var targetLatLng = L.latLng(lat, lon);
                                
                                map.setView(targetLatLng, 16);
                                window.helyezRedMarker(targetLatLng);
                            }} else {{
                                alert("❌ Sajnos a megadott cím nem található! Próbáld meg egyszerűbben.");
                            }}
                        }})
                        .catch(err => {{
                            console.error("Geokódolási hiba:", err);
                        }});
                }};

                if (points.length > 0) {{
                    map = L.map('map').setView([points[0].lat, points[0].lon], 13);
                    
                    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                        attribution: '© OpenStreetMap contributors'
                    }}).addTo(map);

                    var latlngs = [];
                    var markersGroup = L.featureGroup();

                    points.forEach(function(p) {{
                        var latlng = [p.lat, p.lon];
                        latlngs.push(latlng);

                        var icon = L.divIcon({{
                            className: 'number-icon',
                            html: p.display_index,
                            iconSize: [26, 26],
                            iconAnchor: [13, 13]
                        }});

                        // Összetett HTML buborék generálása a közös címhez tartozó összes vevővel
                        var popupHtml = "<div class='leaflet-popup-content-value'>";
                        popupHtml += "<b>🏠 " + p.address + "</b>";
                        popupHtml += "<hr style='margin: 6px 0; border:0; border-top: 1px solid #E5E7EB;'>";
                        
                        p.clients.forEach(function(c) {{
                            popupHtml += "<div style='margin-bottom: 8px; border-bottom: 1px dashed #F3F4F6; padding-bottom: 4px;'>";
                            popupHtml += "<span style='color: #1E3A8A; font-weight: 800;'>🏷️ " + c.index + ". Megálló</span><br>";
                            popupHtml += "👤 <b>" + c.name + "</b>";
                            popupHtml += "</div>";
                        }});
                        
                        popupHtml = popupHtml.replace(/<div style='margin-bottom: 8px; border-bottom: 1px dashed #F3F4F6; padding-bottom: 4px;'>$/, "<div>"); // Utolsó elválasztó eltávolítása
                        popupHtml += "</div>";

                        var marker = L.marker(latlng, {{icon: icon}})
                            .bindPopup(popupHtml)
                            .addTo(map);
                            
                        markersGroup.addLayer(marker);
                    }});

                    if (latlngs.length > 1) {{
                        var polyline = L.polyline(latlngs, {{
                            color: '#2563EB',
                            weight: 4,
                            opacity: 0.8,
                            dashArray: '8, 8',
                            lineJoin: 'round'
                        }}).addTo(map);
                        
                        map.fitBounds(markersGroup.getBounds(), {{ padding: [30, 30] }});
                    }}

                    // --- NATIVE CÍMKERESŐ PANEL BEÉPÍTÉSE A TÉRKÉP BAL FELSŐ SARKÁBA ---
                    var searchControl = L.control({{position: 'topleft'}});
                    searchControl.onAdd = function (map) {{
                        var div = L.divIcon({{
                            className: 'map-search-control',
                            html: ''
                        }});
                        var container = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
                        container.innerHTML = `
                            <div class="map-search-panel" onclick="L.DomEvent.stopPropagation(event)">
                                <input type="text" id="map_address_search" class="map-search-input" placeholder="Cím keresése a térképen...">
                                <button onclick="window.keresCimet()" class="map-search-btn">🔍 Keresés</button>
                            </div>
                        `;
                        return container;
                    }};
                    searchControl.addTo(map);

                    // Térképes kattintás figyelő
                    map.on('click', function(e) {{
                        window.helyezRedMarker(e.latlng);
                    }});
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
