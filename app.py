import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_institutions_and_firms(text):
    # Brutális, mindent elsöprő lista az eddigi összes javításod alapján
    blacklist = [
        r"Harro\s*Höfliger\s*Hungary", r"Harro\s*Höfliger", r"Hungary",
        r"Pearl\s*Enterprises", r"Pearl",
        r"DEKK\s*Kenézy\s*Gyula\s*Kórház", r"DEKK",
        r"Zaza\s*Süteményes\s*bolt", r"Zaza\s*Süteményes", r"Zaza",
        r"Főnix\s*Gyógyszertár", r"Főnix",
        r"Fest-É-ker", r"Fest\s*É\s*ker",
        r"Medgyessy\s*Gimnázium", r"Medgyessy\s*Ferenc\s*Gimnázium",
        r"Általános\s*Iskola", r"Iskola",
        r"Triton\s*Services", r"Triton",
        r"Globiz\s*International", r"Globiz",
        r"Kormányhivatal", r"Mister\s*Minit", r"Richter\s*Gedeon",
        r"Javítsd\s*Magad", r"Matrackirály", r"Ifjúsági\s*Ház"
    ]
    cleaned = text
    for phrase in blacklist:
        cleaned = re.sub(phrase, "", cleaned, flags=re.IGNORECASE)
    return cleaned

def extract_v33(pdf_file):
    all_customers = []
    
    # Olyan szavak, amik SOHA nem részei egy névnek (kódok, megjegyzések)
    stop_words = [
        "csokimax", "kft", "zrt", "debrecen", "utca", "út", "tér", "fszt", "fsz",
        "dkm", "rzk", "vdk", "kcs", "otp", "cica", "harapós", "nem", "kér", "számlát"
    ]

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            markers = []
            for w in words:
                if w['x0'] < 40 and re.match(r'^\d+$', w['text']):
                    markers.append({'num': w['text'], 'top': w['top']})
            
            for i in range(len(markers)):
                top = markers[i]['top']
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                raw_text = " ".join([w['text'] for w in block_words if "Összesen" not in w['text']])
                
                # 1. TISZTÍTÁS: Kicsapjuk a cégneveket és intézményeket
                cleaned_text = clean_institutions_and_firms(raw_text)
                
                # Cím és kód kinyerése (ezek nem változtak)
                kod_m = re.search(r'([PZSC]-\d{6})', cleaned_text)
                kod = kod_m.group(1) if kod_m else ""
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*.*?\d+[\s/]*[A-Z-]*\.?)', cleaned_text)
                cim = cim_m.group(1).strip() if cim_m else "Cím nem található"
                
                # 2. NÉV KERESÉSE: A már "steril" szövegben
                search_area = cleaned_text.replace(kod, "").replace(cim, "")
                # Csak a nagybetűvel kezdődő szavakat gyűjtjük ki
                potential_names = re.findall(r'\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ-]*\b', search_area)
                
                name_parts = []
                for p in potential_names:
                    if p.lower() not in stop_words and len(p) > 2:
                        if p not in name_parts:
                            # Összetett nevek (Hajós-Szabó) duplikáció elleni védelme
                            is_sub = False
                            for idx, existing in enumerate(name_parts):
                                if p in existing: is_sub = True; break
                                if existing in p: name_parts[idx] = p; is_sub = True; break
                            if not is_sub:
                                name_parts.append(p)

                # Név összeállítása az első 2-3 megmaradt szóból
                ugyintezo = " ".join(name_parts[:3]) if len(name_parts) >= 3 else " ".join(name_parts[:2])
                if not name_parts: ugyintezo = "Név nem azonosítható"

                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', raw_text)
                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Rendelés": ", ".join(rendelesek)
                })
    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v33 - A „Tényleg utolsó” tisztító")
f = st.file_uploader("PDF feltöltése", type="pdf")
if f:
    df = extract_v33(f)
    st.write("### Ellenőrzés: Takács Ildikó, Kovács László, Medgyesi Zita")
    st.dataframe(df)
    st.download_button("v33 CSV Letöltése", df.to_csv(index=False).encode('utf-8-sig'), "interfood_v33.csv")
