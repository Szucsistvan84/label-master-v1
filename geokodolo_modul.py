# -*- coding: utf-8 -*-
import re
import time
import logging
from geopy.geocoders import Nominatim

logger = logging.getLogger(__name__)

def clean_address(address_str):
    """
    Megtisztítja a bejövő címet a felesleges sallangoktól (emelet, ajtó, megjegyzések),
    hogy a Nominatim API nagyobb eséllyel találja meg.
    """
    if not address_str:
        return ""
    
    # Alapvető tisztítások (íásjelek, szóközök)
    s = address_str.strip()
    
    # Levágjuk a tipikus belső címzéseket (emelet, ajtó, lakás, lépcsőház stb.)
    s = re.sub(r'\s+\d+/\d+\.?\s*(A|B|C|D)?\s*(em|fszt|ajtó|lakás|lh).*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+\d+\.?\s*(em|fszt|ajtó|lakás|lh).*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+(fszt|emelet|szint).*$', '', s, flags=re.IGNORECASE)
    
    # Levágjuk a zárójeles megjegyzéseket a cím végéről
    s = re.sub(r'\(.*\).*$', '', s)
    
    return s.strip()

def get_coordinates_3_step(address_str):
    """
    3 lépcsős geokódoló algoritmus kötelező késleltetéssel (Rate Limit védelemmel).
    1. Lépés: Teljes tisztított cím
    2. Lépés: Irányítószám nélkül (csak város + utca + házszám)
    3. Lépés: Csak utca szinten (házszám nélkül)
    """
    cleaned = clean_address(address_str)
    if not cleaned:
        return None, None

    # Egyedi User-Agent, hogy a Nominatim ne tiltson ki minket
    geolocator = Nominatim(user_agent="interfood_express_delivery_app_v3")
    
    # --- 1. LÉPÉS: Teljes tisztított cím ---
    try:
        time.sleep(1.3) # Kötelező szünet a Nominatim szabályzat miatt!
        location = geolocator.geocode(cleaned, timeout=10)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        logger.warning(f"Geokódolás hiba az 1. lépésben ({cleaned}): {e}")

    # --- 2. LÉPÉS: Irányítószám nélkül ---
    # Ha pl. "4031 Debrecen, Derék u. 76", megpróbáljuk irányítószám nélkül
    no_zip = re.sub(r'^\d{4}\s+', '', cleaned)
    if no_zip != cleaned:
        try:
            time.sleep(1.3)
            location = geolocator.geocode(no_zip, timeout=10)
            if location:
                return location.latitude, location.longitude
        except Exception as e:
            logger.warning(f"Geokódolás hiba a 2. lépésben ({no_zip}): {e}")

    # --- 3. LÉPÉS: Csak utca szint (házszám lecsípése) ---
    # Ha pl. "Debrecen, Derék u. 76", levágjuk a számot a végéről -> "Debrecen, Derék u."
    only_street = re.sub(r'\s+\d+\.?\s*$', '', no_zip)
    if only_street != no_zip:
        try:
            time.sleep(1.3)
            location = geolocator.geocode(only_street, timeout=10)
            if location:
                return location.latitude, location.longitude
        except Exception as e:
            logger.warning(f"Geokódolás hiba a 3. lépésben ({only_street}): {e}")

    return None, None
