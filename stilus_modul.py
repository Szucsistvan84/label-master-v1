# -*- coding: utf-8 -*-
import streamlit as st

def alkalmaz_mobil_status_bar():
    """
    Injektálja a HTML fejléceket, amik megakadályozzák, hogy a Chrome 
    elrejtse a telefon felső állapotjelző sávját (Status Bar).
    Így az óra és az akku töltöttsége látható marad vezetés közben!
    """
    st.markdown(
        """
        <meta name="apple-mobile-web-app-status-bar-style" content="default">
        <meta name="theme-color" content="#FFFFFF">
        """,
        unsafe_allow_html=True
    )

def alkalmaz_tisztitott_felulet_css():
    """
    Golyóálló CSS injektálás, ami eltünteti a felesleges Streamlit elemeket,
    de szigorúan MEGHAGYJA a bal felső sidebar nyitógombot!
    """
    st.markdown(
        """
        <style>
        /* 1. Az alsó 'Made with Streamlit' lábléc teljes eltüntetése */
        footer {visibility: hidden !important; display: none !important;}
        [data-testid="stFooter"] {visibility: hidden !important; display: none !important;}
        
        /* 2. A jobb felső Deploy gomb és Hamburger menü radírozása */
        .stDeployButton {display: none !important;}
        #MainMenu {visibility: hidden !important; display: none !important;}
        [data-testid="stAppDeployButton"] {display: none !important;}
        [data-testid="stHeaderActionElements"] {visibility: hidden !important; display: none !important;}
        
        /* 3. Felső vékony dekorációs csík elrejtése */
        [data-testid="stDecoration"] {display: none !important;}
        
        /* 4. Biztosítjuk, hogy a SIDEBAR nyíl ikonja látható és kattintható maradjon */
        [data-testid="stSidebarCollapseButton"] {
            visibility: visible !important;
            display: inline-flex !important;
        }

        /* 5. Margók igazítása mobilra, hogy ne legyen felesleges üres fehér sáv fentről */
        .block-container {
            padding-top: 2rem !important;
            padding-bottom: 1rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def alkalmaz_wolt_gomb_stilus():
    """
    Globális CSS tuning, ami a kis gyári Streamlit gombokat nagy, 
    lekerekített, ujjal könnyen eltalálható, modern logisztikai gombokká alakítja.
    """
    st.markdown(
        """
        <style>
        [data-testid="stButton"] button {
            width: 100% !important;
            height: 55px !important;
            font-size: 18px !important;
            font-weight: bold !important;
            border-radius: 12px !important;
            background: linear-gradient(135deg, #1E88E5, #1565C0) !important; /* Szép kék Wolt-os átmenet */
            color: white !important;
            border: none !important;
            box-shadow: 0px 4px 8px rgba(0,0,0,0.1) !important;
            transition: transform 0.1s ease, box-shadow 0.1s ease !important;
        }
        
        /* Kattintási (érintési) effekt visszajelzésként a futárnak */
        [data-testid="stButton"] button:active {
            transform: scale(0.97) !important;
            box-shadow: 0px 2px 4px rgba(0,0,0,0.1) !important;
        }
        
        /* A piros/figyelmeztető gombok (pl. Hiba jelentése) egyedi stílusa */
        div.stButton > button:has(div:contains("Hiba")) {
            background: linear-gradient(135deg, #E53935, #C62828) !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

def rendereld_wolt_ugyfel_kartya(id_kod, nev, cim, telefon, megjegyzes, rendeles):
    """
    Egy HTML alapú, Wolt/Foodora ihlette vizuális kártya, ami gyönyörűen, 
    áttekinthetően strukturálja az ügyfél adatait a mobil képernyőn.
    """
    # Ha van megjegyzés, kap egy kiemelt sárgás buborékot, mint a profi appokban
    megjegyzes_html = ""
    if megjegyzes and megjegyzes.strip():
        megjegyzes_html = f'''
        <div style="background-color: #FFF9C4; border-left: 4px solid #FBC02D; padding: 8px; border-radius: 6px; margin-top: 8px; font-size: 14px; color: #57606f;">
            ⚠️ <b>Megjegyzés:</b> {megjegyzes}
        </div>
        '''

    st.markdown(
        f'''
        <div style="background-color: white; border-radius: 14px; padding: 16px; margin-bottom: 12px; box-shadow: 0px 2px 6px rgba(0,0,0,0.08); border: 1px solid #E0E0E0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="background-color: #E3F2FD; color: #0D47A1; font-weight: bold; padding: 4px 8px; border-radius: 6px; font-size: 13px;">🆔 {id_kod}</span>
                <a href="tel:{telefon}" style="text-decoration: none; background-color: #4CAF50; color: white; font-weight: bold; padding: 6px 12px; border-radius: 20px; font-size: 13px; display: inline-flex; align-items: center; gap: 4px;">📞 Hívás</a>
            </div>
            <h3 style="margin: 4px 0px; color: #2C3E50; font-size: 18px;">{nev}</h3>
            <div style="color: #7F8C8D; font-size: 14px; margin-bottom: 6px;">📍 <b>Cím:</b> {cim}</div>
            <div style="background-color: #F5F5F5; padding: 10px; border-radius: 8px; font-size: 14px; border: 1px dashed #BDBDBD;">
                🛒 <b>Rendelés:</b> <span style="color: #2E7D32; font-weight: bold;">{rendeles}</span>
            </div>
            {megjegyzes_html}
        </div>
        ''',
        unsafe_allow_html=True
    )
