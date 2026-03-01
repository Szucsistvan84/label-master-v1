import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_v14(pdf_file):
    all_customers = []
    
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
                full_text = " ".join([w['text'] for w in block_words])
                
                # --- PRECIZIÓS BONTÁS ---
                
                # 1. Cím (A horgony)
                cim_m = re.search(r'(\d{4}\s+Debrecen,\s*[^,]+?[\d/A-Z\-]+\.?)', full_text)
                cim = cim_m.group(1) if cim_m else ""
                
                # 2. Telefonszám (A második horgony)
                tel_m = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                tel = tel_m.group(1) if tel_m else ""

                # 3. ÜGYINTÉZŐ TISZTÍTÁSA (A lényeg!)
                # Kivesszük a címet a szövegből, hogy ne zavarjon
                text_no_address = full_text.replace(cim, "")
                
                # Keressük a neveket: 2 vagy 3 egymást követő nagybetűs szó
                # Ami NEM tartalmaz számot és NEM a "Debrecen"
                name_m = re.findall(r'\b([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)?)\b', text_no_address)
                
                ugyintezo = ""
                if name_m:
                    # Az első talált név lesz az ügyintéző (kiszűrve a "Debrecen"-t ha véletlen benne maradt)
                    for n in name_m:
                        if "Debrecen" not in n:
                            ugyintezo = n
                            break

                # 4. Rendelések
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)
                
                # 5. Összeg
                osszeg_m = re.search(r'(\d[\d\s]*)\s*Ft', full_text)
                osszeg = osszeg_m.group(1).strip() if osszeg_m else "0"

                # 6. Megjegyzés (maradék keresés)
                megj = ""
                for keyword in ["kapukód", "porta", "kcs", "kulcs", "új épület", "hívni"]:
                    if keyword in full_text.lower():
                        m_m = re.search(f'({keyword}[^,]+)', full_text, re.IGNORECASE)
                        if m_m: megj = m_m.group(1)

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Ügyintéző": ugyintezo,
                    "Cím": cim,
                    "Telefon": tel,
                    "Rendelés": ", ".join(rendelesek),
                    "Összeg": osszeg + " Ft",
                    "Megjegyzés": megj
                })

    return pd.DataFrame(all_customers)

# --- UI ---
st.title("Interfood v14 - Névtisztító")
f = st.file_uploader("PDF feltöltése", type="pdf")

if f:
    df = extract_v14(f)
    # Csak a kért oszlopokat mutatjuk, tiszta névvel
    st.dataframe(df[["Sorszám", "Ügyintéző", "Cím", "Telefon", "Rendelés", "Összeg", "Megjegyzés"]])
    
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("Exportálás CSV-be", csv, "interfood_tisztitott.csv")
