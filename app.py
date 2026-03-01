import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_v10(pdf_file):
    extracted_data = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # FIX OSZLOP HATÁROK (Pixelben mérve az A4-es lapon)
            # 0-45: Sorszám | 45-250: Ügyfél+Cím | 250-380: Ügyintéző | 380-530: Rendelés | 530+: Összeg
            # Ezeket az értékeket az Interfood menetterv standard elrendezéséhez lőttem be.
            
            # Kinyerjük a szavakat koordinátákkal együtt
            words = page.extract_words()
            
            # Sorokba rendezzük a szavakat a függőleges (top) pozíciójuk alapján
            lines = {}
            for w in words:
                y = round(w['top'], 0) # Kerekítünk, hogy az egy sorban lévők egy csoportba kerüljenek
                if y not in lines: lines[y] = []
                lines[y].append(w)
            
            # Feldolgozzuk a sorokat
            for y in sorted(lines.keys()):
                line_words = lines[y]
                
                # Oszlopok szerinti szétosztás
                col_sor = " ".join([w['text'] for w in line_words if w['x0'] < 45])
                col_ugyfel = " ".join([w['text'] for w in line_words if 45 <= w['x0'] < 250])
                col_rendeles = " ".join([w['text'] for w in line_words if 380 <= w['x0'] < 530])
                
                # Ha van sorszám, új ügyfelet kezdünk
                s_match = re.match(r'^(\d+)$', col_sor.strip())
                if s_match:
                    sorszam = s_match.group(1)
                    extracted_data.append({
                        "Sorszám": sorszam,
                        "Név": col_ugyfel.strip(),
                        "Cím": "", # A következő sorokban fogjuk megtalálni
                        "Telefon": "",
                        "Rendelés": [],
                        "Megjegyzés": ""
                    })
                elif extracted_data:
                    # Ha nincs sorszám, az előző ügyfél adatait folytatjuk (Cím, Rendelés, Telefon)
                    curr = extracted_data[-1]
                    
                    # Cím keresése (Irányítószám vagy Debrecen kulcsszó)
                    if "Debrecen" in col_ugyfel or re.search(r'\d{4}', col_ugyfel):
                        curr["Cím"] = col_ugyfel.strip()
                    
                    # Telefonszám és Rendelés kódok a megfelelő oszlopból
                    if col_rendeles:
                        tel = re.search(r'(\d{2}/\d{6,})', col_rendeles.replace(" ", ""))
                        if tel: curr["Telefon"] = tel.group(1)
                        
                        rend_codes = re.findall(r'(\d+-[A-Z0-9]+)', col_rendeles)
                        curr["Rendelés"].extend(rend_codes)

    # Tisztítás: csak azokat tartjuk meg, ahol van név
    final_data = [d for d in extracted_data if len(d["Név"]) > 2]
    return pd.DataFrame(final_data)

# --- Streamlit UI ---
st.title("Interfood Profiler v10")
uploaded_file = st.file_uploader("Menetterv PDF (4002)", type="pdf")

if uploaded_file:
    df = extract_v10(uploaded_file)
    if not df.empty:
        # A listákat stringgé alakítjuk a megjelenítéshez
        df['Rendelés'] = df['Rendelés'].apply(lambda x: ", ".join(x))
        st.success(f"Beolvasva: {len(df)} ügyfél")
        st.dataframe(df)
    else:
        st.error("Próbáljuk meg más beállításokkal, nem találtam adatot.")
