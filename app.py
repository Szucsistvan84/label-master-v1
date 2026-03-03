import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_money_v145(context_text):
    # Keressük a Ft-ot és az előtte lévő számokat
    match = re.search(r'(\d[\d\s]*)\s*Ft', context_text.replace('\n', ' '))
    if not match: return "0 Ft"
    
    raw_num = match.group(1).strip()
    parts = raw_num.split()
    
    if len(parts) >= 2:
        # Ha az utolsó rész 3 számjegy (pl. 935), akkor az előtte lévővel együtt alkotja a pénzt
        if len(parts[-1]) == 3:
            return f"{parts[-2]} {parts[-1]} Ft"
        # Ha csak egy blokk van (pl. 850 Ft)
        return f"{parts[-1]} Ft"
    return f"{raw_num} Ft"

def parse_menetterv_v145(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split('\n')
            for i, line in enumerate(lines):
                # Sorszám és Kód keresése
                m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                if m:
                    # Kontextus: a sor és a következő sor (hogy a 32 935 Ft is beleférjen)
                    context = line + " " + (lines[i+1] if i+1 < len(lines) else "")
                    
                    # Cím és név (a kód után és a telefon előtt)
                    # A 61-es sor példájára szabva:
                    tel_match = re.search(r'\d{2}/\d{7}', context)
                    phone = tel_match.group(0) if tel_match else ""
                    
                    all_rows.append({
                        "Sorszám": int(m.group(1)),
                        "Kód": m.group(2),
                        "Ügyintéző": "Ellenőrizd: " + m.group(2), # Itt a v131 táblázatát kéne visszahozni
                        "Összeg": clean_money_v145(context),
                        "Nyers": context[:50] # Csak hogy lásd, mit olvasott be
                    })
    return pd.DataFrame(all_rows)

# UI rész...
