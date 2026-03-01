import streamlit as st
from pypdf import PdfReader
import pandas as pd
import re
from fpdf import FPDF
import io

def parse_v104(pdf_file):
    reader = PdfReader(pdf_file)
    raw_text = ""
    for page in reader.pages:
        raw_text += page.extract_text() + "\n---PAGE---\n"

    # Tisztítás: a felesleges "Sor / Ügyfél" fejléceket kivesszük, hogy ne zavarjanak
    raw_text = re.sub(r'Sor\s+Ügyfél\s+Ügyfél\s+címe', '', raw_text)

    # Ügyfelek szétválasztása a "#szám | KÓD:" mintára
    # Ez a legstabilabb pont a PDF-edben
    chunks = re.split(r'#\d+\s*(?:\||)\s*KÓD:', raw_text)
    
    extracted_data = []
    for chunk in chunks:
        if not chunk.strip(): continue
        
        # 1. ÜGYFÉLKÓD (6 jegyű szám)
        cid_m = re.search(r'(\d{6})', chunk)
        if not cid_m: continue
        cid = cid_m.group(1)

        # 2. NÉV (A chunk elején keresünk nagybetűs neveket, amik nem telefonszámok)
        # Tőkés István itt fog megkerülni
        lines = [l.strip() for l in chunk.split('\n') if l.strip()]
        name = "Név hiányzik"
        for line in lines:
            if len(line.split()) >= 2 and not any(x in line for x in ["TEL:", "KÓD:", "REND:", "Ft", "tétel"]):
                if re.match(r'^[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+', line):
                    name = line
                    break

        # 3. TELEFON
        tel = "NINCS"
        tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', chunk)
        if tel_m: tel = tel_m.group(1)

        # 4. CÍM (Irányítószám + Debrecen)
        addr = "Cím hiányzik"
        addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^#\n]+)', chunk)
        if addr_m: addr = addr_m.group(1).strip()

        # 5. RENDELÉSEK ÉS PÉNZ
        money_m = re.search(r'(\d+[\s\d]*)\s*Ft', chunk)
        money = money_m.group(1).replace(" ", "") if money_m else "0"
        
        rends = re.findall(r'(\d+-[A-Z0-9]+)', chunk)

        extracted_data.append({
            "Ügyfélkód": cid, "Ügyintéző": name, "Telefon": tel,
            "Cím": addr, "Rendelés": ", ".join(set(rends)), "Pénz": money
        })

    return pd.DataFrame(extracted_data)

st.title("Interfood v104 - A Stabil Verzió")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    df = parse_v104(f)
    if not df.empty:
        st.write(f"Talált ügyfelek: {len(df)}")
        # Tőkés István ellenőrzése
        if any(df['Ügyintéző'].str.contains("Tőkés", na=False)):
            st.success("Tőkés István megtalálva!")
        st.dataframe(df)
        
        # PDF generálás itt...
    else:
        st.error("Nem sikerült adatot kinyerni. A PDF szerkezete túl egyedi.")
