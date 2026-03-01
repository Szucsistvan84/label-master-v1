import streamlit as st
import pdfplumber # Ez sokkal stabilabb ilyen kaotikus PDF-eknél
import pandas as pd
import re
from fpdf import FPDF
import os

def parse_v102(pdf_file):
    all_customers = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Kinyerjük az összes szót és azok pontos helyét (koordinátáit)
            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            
            # Keressük az ügyfélkódokat: P-123456 vagy Z-123456
            for i, w in enumerate(words):
                text = w['text']
                code_match = re.search(r'([PZ])\s?-\s?(\d{6})', text)
                
                if code_match:
                    prefix = code_match.group(1)
                    cid = code_match.group(2)
                    
                    # NÉV KERESÉSE: Megnézzük, mi van közvetlenül a kód FELETT (top koordináta kisebb)
                    # Tőkés István így meglesz, mert a kódja felett ott a neve, hiába van ott a fejléc is.
                    name_candidates = []
                    for w2 in words:
                        # Ha a szó a kód felett van max 15 egységgel és vízszintesen hasonló helyen
                        if 0 < (w['top'] - w2['bottom']) < 18 and abs(w['x0'] - w2['x0']) < 50:
                            # Kiszűrjük a technikai szavakat, de a nevet megtartjuk
                            if not any(x in w2['text'].upper() for x in ["KÓD", "SOR", "ÜGYFÉL"]):
                                name_candidates.append(w2['text'])
                    
                    name = " ".join(name_candidates).strip()
                    if not name or len(name) < 3: name = "Név hiányzik"

                    # ADATOK KERESÉSE a kód 40 egységnyi környezetében
                    context_words = [w2['text'] for w2 in words if abs(w2['top'] - w['top']) < 45]
                    context_str = " ".join(context_words)

                    tel = "NINCS"
                    tel_m = re.search(r'((?:\+36|06|20|30|70)[\s/]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4})', context_str)
                    if tel_m: tel = tel_m.group(1)

                    addr = "Cím hiányzik"
                    addr_m = re.search(r'(\d{4}\s+Debrecen,?\s+[^|]+)', context_str)
                    if addr_m: addr = addr_m.group(1).split("REND:")[0].strip()

                    money = 0
                    money_m = re.search(r'(\d+[\s\d]*)\s*Ft', context_str)
                    if money_m: money = int(re.sub(r'\s+', '', money_m.group(1)))

                    rends = re.findall(r'(\d+-[A-Z0-9]+)', context_str)

                    all_customers.append({
                        "cid": cid, "prefix": prefix, "name": name, "tel": tel, 
                        "addr": addr, "money": money, "rend": rends
                    })

    # Összevonás (Péntek + Szombat + Név javítás)
    final_dict = {}
    for item in all_customers:
        # A biztos kulcs az ügyfélkód és a cím eleje
        key = (item["cid"], item["addr"][:10])
        if key not in final_dict:
            final_dict[key] = {"id": item["cid"], "név": item["name"], "cím": item["addr"], 
                               "tel": item["tel"], "P": [], "Z": [], "pénz": 0}
        
        # Ha az egyik beolvasásnál (pl. P) "Név hiányzik", de a másiknál (pl. Z) megvan, javítsuk ki
        if final_dict[key]["név"] == "Név hiányzik" and item["name"] != "Név hiányzik":
            final_dict[key]["név"] = item["name"]
        
        if item["prefix"] == "Z": final_dict[key]["Z"].extend(item["rend"])
        else: final_dict[key]["P"].extend(item["rend"])
        final_dict[key]["pénz"] += item["money"]

    return pd.DataFrame([{
        "Sorszám": i+1, "Ügyfélkód": d["id"], "Ügyintéző": d["név"], "Telefon": d["tel"], "Cím": d["cím"],
        "Rendelés": f"P: {', '.join(set(d['P']))} | SZ: {', '.join(set(d['Z']))}".strip(" |"),
        "Pénz": f"{d['pénz']} Ft" if d['pénz'] > 0 else ""
    } for i, d in enumerate(final_dict.values())])

# A PDF generáló rész (FPDF) marad a régi, bevált formátumban...
# (A sorszámozás és az elrendezés 3x7-es marad)

st.title("Interfood v102 - Koordináta Alapú Elemző")
uploaded_file = st.file_uploader("Válaszd ki az etikett PDF-et", type="pdf")

if uploaded_file:
    # Mentés átmeneti fájlba a pdfplumbernek
    with open("temp_v102.pdf", "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    with st.spinner("Adatok kinyerése folyamatban..."):
        df_final = parse_v102("temp_v102.pdf")
        
    if not df_final.empty:
        st.success(f"Siker! {len(df_final)} ügyfelet találtam.")
        st.dataframe(df_final)
        # Itt jönne a PDF letöltés gomb...
    else:
        st.error("Nem találtam adatokat. Biztos jó PDF-et töltöttél fel?")
    
    os.remove("temp_v102.pdf")
