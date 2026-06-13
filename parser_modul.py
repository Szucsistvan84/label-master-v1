# -*- coding: utf-8 -*-
import re
import pdfplumber
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def parse_interfood_pdf(pdf_file):
    """
    A te éles, bevált PDF feldolgozó logikád a mentésből.
    Kinyeri az ügyfeleket, rendeléseket és megjegyzéseket.
    """
    logger.info("Interfood PDF feldolgozása elindult...")
    extracted_data = []
    
    current_customer = None
    
    # Napok azonosítására használt minták a kódodból
    nap_jelolők = ["H:", "K:", "Sze:", "Cs:", "Pé:", "Szo:", "V:"]
    
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if not text:
                continue
                
            lines = text.split('\n')
            for line in lines:
                # Ügyfél sor azonosítása (6 jegyű ID + Név + Telefon + Cím)
                customer_match = re.search(r'^(\d{6})\s+([^\d]+)\s+(\d{2}/\d{7})\s+(.*)$', line)
                
                if customer_match:
                    if current_customer:
                        extracted_data.append(current_customer)
                        
                    current_customer = {
                        'ID': customer_match.group(1),
                        'Név': customer_match.group(2).strip(),
                        'Telefon': customer_match.group(3),
                        'Cím': customer_match.group(4).strip(),
                        'Rendelés': '',
                        'Megjegyzés': ''
                    }
                    continue
                
                if current_customer:
                    # Megnézzük, hogy rendelési tétel-e (tartalmazza a napjelölőket)
                    is_order_line = any(nap in line for nap in nap_jelolők)
                    
                    if is_order_line:
                        if current_customer['Rendelés']:
                            current_customer['Rendelés'] += " | " + line.strip()
                        else:
                            current_customer['Rendelés'] = line.strip()
                    else:
                        # Minden más sor megjegyzés (kivéve az oldalszámot)
                        if line.strip() and not line.strip().startswith("Oldal"):
                            if current_customer['Megjegyzés']:
                                current_customer['Megjegyzés'] += " " + line.strip()
                            else:
                                current_customer['Megjegyzés'] = line.strip()
            
            if current_customer:
                extracted_data.append(current_customer)
                current_customer = None

    df = pd.DataFrame(extracted_data)
    logger.info(f"PDF sikeresen feldolgozva. Talált rekordok: {len(df)}")
    return df
