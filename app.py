import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_money_v145(text_block):
    """
    A Te szabályod: Csak akkor tartjuk meg a pénzt, ha nincs szóköz a 0 előtt,
    vagy ha egy értelmes ezres tagolású összeg.
    """
    if not text_block or "Ft" not in text_block:
        return "0 Ft"
    
    # Megkeressük az összes Ft-ot tartalmazó részt a blokkban
    matches = re.findall(r'(\d[\d\s]*)\s*Ft', text_block)
    if not matches:
        return "0 Ft"
    
    # Vegyük az utolsót (mert a pénz általában a blokk végén van)
    raw_val = matches[-1].strip()
    
    # Szóköz-nulla szabály: " 0" -> 0 Ft
    if raw_val == "0" or raw_val.endswith(" 0"):
        return "0 Ft"
    
    # Tisztítás az adagszámoktól (pl. "4 32 935" -> "32 935")
    parts = raw_val.split()
    if len(parts) >= 2 and len(parts[-1]) == 3: # Ha 32 935 formátum
        return f"{parts[-2]} {parts[-1]} Ft"
    
    return f"{parts[-1]} Ft"

def parse_pdf_v145(pdf_file):
    all_data = []
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                # Nem táblázatként, hanem soronként olvassuk a stabilitásért
                text = page.extract
