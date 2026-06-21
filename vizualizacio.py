# -*- coding: utf-8 -*-
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json

def utvonal_terkep(df_napi, sheet_id=None):
    """
    Kirajzolja a napi útvonalat egy interaktív térképen.
    Sorszámozott Leaflet.js markereket használ egész számként formázva.
    Támogatja az interaktív kattintást, a piros tű lerakását és az egykattintásos koordináta másolást.
    Beépített, kényelmes Nominatim címkeresővel rendelkezik a térképen belül!
    """
    if df_napi is None or df_napi.empty:
        st.warning("⚠️ Nincs adat az útvonal kirajzolásához!")
        return

    # 1. Biztonsági másolat készítése
    map_df = df_napi.copy()

    # 2. Oszlopok ellenőrzése
    if 'Lat' not in map_df.columns or 'Lon' not in map_df.columns:
        st.warning("⚠️ A táblázat nem tartalmaz 'Lat' és 'Lon' oszlopokat!")
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

        # 4. Kiszűrjük azokat a sorokat, ahol nincs érvényes GPS koordináta
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
                clean_index = str(int(float(raw_index)))
            except (ValueError, TypeError):
                clean_index = str(raw_index).split('.')[0] if '.' in str(raw_index) else str(raw_index)
            
            points.append({
                "index": clean_index if clean_index.strip() != "" else "•",
                "lat": float(row['latitude']),
                "lon": float(row['longitude']),
                "name": str(row.get('Név', row.get('Ügyintéző', 'Névtelen Vevő'))),
                "address": str(row.get('Cím', 'Ismeretlen Cím'))
            })

        points_json = json.dumps(points, ensure_ascii=False)

        # 6. Szuper-biztonságos HTML + Leaflet.js sablon interaktív kattintás- és címkereső-figyelővel
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
                    line-height: 1.4;
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
                
                // Helper másoló függvény a homokozó iframe korlátok megkerülésére (Textarea trükk)
                window.masolGPS = function() {{
                    var copyText = document.getElementById("gps_val_input");
                    if (copyText) {{
                        copyText.select();
                        copyText.setSelectionRange(0, 99999);
                        try {
                            document.execCommand('copy');
                            var msg = document.getElementById("copy_ok_msg");
                            if (msg) msg.style.display = "block";
                            setTimeout(function() {{
                                if (msg) msg.style.display = "none";
                            }}, 2000);
                        } catch (err) {{
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
                            html: p.index,
                            iconSize: [26, 26],
                            iconAnchor: [13, 13]
                        }});

                        var marker = L.marker(latlng, {{icon: icon}})
                            .bindPopup("<div class='leaflet-popup-content-value'><b>📍 " + p.index + ". Megálló</b><br><b>👤 " + p.name + "</b><br>🏠 " + p.address + "</div>")
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
                        var div = L.DomUtil.create('div', 'map-search-panel');
                        div.innerHTML = `
                            <input type="text" id="map_address_search" class="map-search-input" placeholder="Cím keresése a térképen..." onkeypress="if(event.key === 'Enter') window.keresCimet()">
                            <button onclick="window.keresCimet()" class="map-search-btn">🔍</button>
                        `;
                        L.DomEvent.disableClickPropagation(div);
                        return div;
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
