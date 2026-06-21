# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd

def utvonal_terkep(df_napi, sheet_id=None):
    """
    Kirajzolja a napi útvonalat a térképen.
    Biztonságosan tisztítja a koordinátákat (támogatja a tizedesvesszőt is),
    kiszűri a hibás adatokat, és egy esztétikus térképet jelenít meg.
    """
    if df_napi is None or df_napi.empty:
        st.warning("⚠️ Nincs adat az útvonal kirajzolásához!")
        return

    # 1. Biztonsági másolat készítése, hogy az eredeti táblázat formázása ne sérüljön
    map_df = df_napi.copy()

    # 2. Oszlopok ellenőrzése
    if 'Lat' not in map_df.columns or 'Lon' not in map_df.columns:
        st.warning("⚠️ A táblázat nem tartalmaz 'Lat' és 'Lon' oszlopokat!")
        return

    try:
        # 3. Tisztítás: tizedesvesszők kicserélése pontra, szóközök és rejtett karakterek eltávolítása
        for col in ['Lat', 'Lon']:
            map_df[col] = (
                map_df[col]
                .astype(str)
                .str.replace(',', '.', regex=False)
                .str.replace(' ', '', regex=False)
                .str.strip()
            )
            # Biztonságos számmá alakítás (a nem konvertálható szövegek NaN-t kapnak)
            map_df[col] = pd.to_numeric(map_df[col], errors='coerce')

        # 4. Kisbetűs oszlopok létrehozása (Streamlit st.map kompatibilitás)
        map_df['latitude'] = map_df['Lat']
        map_df['longitude'] = map_df['Lon']

        # 5. Érvényes koordináták szűrése (Magyarország határai kb: lat: 45.0 - 49.0, lon: 16.0 - 23.5)
        map_data = map_df.dropna(subset=['latitude', 'longitude']).copy()
        map_data = map_data[
            (map_data['latitude'] > 45.0) & (map_data['latitude'] < 49.0) &
            (map_data['longitude'] > 16.0) & (map_data['longitude'] < 23.5)
        ]

        if map_data.empty:
            st.warning("⚠️ Nincs megjeleníthető érvényes GPS koordináta a mai listán! (Minden koordináta üres vagy hibás formátumú)")
            return

        # 6. Térkép kirajzolása
        st.markdown(f"🗺️ **Aktív megállók a térképen:** {len(map_data)} cím")
        
        # Streamlit beépített, modern, sötétkék pontokkal ellátott térképe
        st.map(map_data, latitude='latitude', longitude='longitude', size=25, color='#1E3A8A')
        
    except Exception as e:
        st.error(f"❌ Hiba a térkép kirajzolása során: {e}")
