import streamlit as st
import pdfplumber
import pandas as pd
import re

def process_cell_content(cell_text, expected_count):
    """
    Tisztítja a cellát és szétosztja az adatokat (Telefon, Étel, Pénz) 
    a benne lévő ügyfelek száma szerint.
    """
    if not cell_text:
        return [{"Telefon": "", "Étel": "", "Pénz": ""}] * expected_count

    # 1. TISZTÍTÁS a Te logikád szerint:
    t = cell_text.replace('\n\n\n', '\n').replace('\n ', '\n')
    lines = [l.strip() for l in t.split('\n') if l.strip()]
    
    # Adatgyűjtők az ügyfeleknek
    data_blocks = []
    for _ in range(expected_count):
        data_blocks.append({"Telefon": "Nincs", "Étel": "Nincs", "Pénz": "0 Ft"})
    
    # 2. SZÉTOSTÁS minták alapján
    current_user = 0
    for line in lines:
        if current_user >= expected_count: break
        
        if '/' in line: # Telefonszám minta
            data_blocks[current_user]["Telefon"] = line
        elif 'Ft' in line: # Pénz minta
            data_blocks[current_user]["Pénz"] = line
            # Ha megvan a pénz, jó eséllyel a következő adat már az új ügyfélé
            if data_blocks[current_user]["Étel"] != "Nincs":
                current_user += 1
        elif '-' in line: # Étel kód minta (pl. 1-DK)
            data_blocks[current_user]["Étel"] = line
            # Ha már van pénze és telefonja is, váltunk
            if data_blocks[current_user]["Pénz"] != "0 Ft" and data_blocks[current_user]["Telefon"] != "Nincs":
                current_user += 1
                
    return data_blocks

def parse_menetterv_v131_3(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            
            # TÁBLÁZATOS OLDALAK
            if i < total_pages - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if not table: continue
                
                for row in table:
                    if not row or len(row) < 5: continue
                    
                    # Sorszámok kinyerése (pl. "1\n2" -> [1, 2])
                    s_nums = [int(s) for s in str(row[0]).split('\n') if s.strip().isdigit()]
                    if not s_nums: continue
                    
                    # Adatok tisztítása és szétosztása
                    count = len(s_nums)
                    cell_4_data = process_cell_content(str(row[4]), count)
                    
                    # Nevek szétbontása (3. oszlop)
                    names = [n.strip() for n in str(row[3]).split('\n') if n.strip()]
                    
                    # Címek szétbontása (2. oszlop - itt maradt a v131 stabilitása)
                    # A címeket egyszerűen soronként próbáljuk hozzárendelni
                    addresses = str(row[2]).replace('\n\n\n', '\n').split('\n')
                    addresses = [a.strip() for a in addresses if a.strip() and '402' in a or '403' in a]

                    for idx, snum in enumerate(s_nums):
                        all_rows.append({
                            "Sorszám": snum,
                            "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                            "Ügyintéző": names[idx] if idx < len(names) else "Nincs név",
                            "Cím": addresses[idx] if idx < len(addresses) else "Lásd felette",
                            "Telefon": cell_4_data[idx]["Telefon"],
                            "Étel": cell_4_data[idx]["Étel"],
                            "Pénz": cell_4_data[idx]["Pénz"]
                        })

            # UTOLSÓ OLDAL (Vágó logika)
            else:
                # ... itt maradhat a v131-es utolsó oldali kódod, mert az jól működött ...
                pass

    return pd.DataFrame(all_rows).sort_values("Sorszám")

# UI rész...
