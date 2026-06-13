# -*- coding: utf-8 -*-
import re
import time
import logging
from geopy.geocoders import Nominatim

logger = logging.getLogger(__name__)

def tisztitott_cim_lekerese(nyers_szoveg):
    """A te eredeti, jól bevált címtisztító logikád"""
    if not nyers_szoveg:
        return ""
    
    # 1. Zárójeles részek eltávolítása (pl. név lecsípése a végéről)
    szoveg = re.sub(r'\(.*?\)', '', str(nyers_szoveg)).strip()
    szoveg = szoveg.replace('$', '').strip()
    
    # 2. OKOS LAKÁSSZÁM-ELTÁVOLÍTÁS (Pont és szóköz toleráns verzió)
    szoveg = re.sub(r'\.?\s+\d+/\d+.*$', '', szoveg)
    
    # Emelet, ajtó, lépcsőház kulcsszavak levágása
    szoveg = re.split(r'(?i)\s+(fszt|fsz|emelet|em|ajtó|ajto|lh|lph).*$', szoveg)[0]
    
    # Ha a legvégén maradt egy magányos pont vagy vessző a levágás miatt, azt lekapjuk
    szoveg = szoveg.strip().rstrip(',').rstrip('.')
    
    return szoveg

def geocode_with_retry(address_str, retries=2):
    """Biztonságos Nominatim hívás kötelező késleltetéssel és újrapróbálkozással"""
    geolocator = Nominatim(user_agent="interfood_label_master_v3")
    for i in range(retries):
        try:
            time.sleep(1.1)  # Kötelező Nominatim rate limit szünet
            location = geolocator.geocode(address_str, timeout=10)
            if location:
                return location
        except Exception as e:
            logger.warning(f"Nominatim hiba ({address_str}), próbálkozás {i+1}/{retries}: {e}")
            time.sleep(2)
    return None

def get_coordinates(address):
    """
    Lekéri a megadott cím koordinátáit - APOSZTRÓF NÉLKÜL, TISZTA STRINGSZÁMKÉNT!
    3 lépcsős biztonsági mentéssel.
    """
    try:
        tisztitott_cim = tisztitott_cim_lekerese(address)
        if not tisztitott_cim:
            return None, None
            
        # 1. Próbálkozás: Teljes tisztított cím
        location = geocode_with_retry(tisztitott_cim)
        
        # 2. Próbálkozás: Ha nem találja, megpróbáljuk irányítószám nélkül (lecsípjük az első 4 számjegyet)
        if not location:
            no_zip = re.sub(r'^\d{4}\s+', '', tisztitott_cim)
            if no_zip != tisztitott_cim:
                location = geocode_with_retry(no_zip)
                
        # 3. Próbálkozás: Ha még mindig nincs, csak az utca szint (házszám nélkül)
        if not location:
            only_street = re.sub(r'\s+\d+\.?\s*$', '', tisztitott_cim)
            if only_street != tisztitott_cim:
                location = geocode_with_retry(only_street)

        if location:
            # Szigorúan LEVÁGJUK az aposztrófot! Tiszta string formátum kell ponttal: "47.1234567"
            str_lat = f"{location.latitude:.7f}"
            str_lon = f"{location.longitude:.7f}"
            return str_lat, str_lon
        else:
            return None, None
            
    except Exception as e:
        logger.error(f"Váratlan hiba a geocoding során ({address}): {e}")
        return None, None
