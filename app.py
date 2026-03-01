import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

def extract_v11(pdf_file):
    all_customers = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            
            # 1. Keressük meg a sorszámok helyzetét (y koordináta)
            # Az Interfoodnál a sorszám a bal szélen van (x0 < 40)
            markers = []
            for w in words:
                if w['x0'] < 40 and re.match(r'^\d+$', w['text']):
                    markers.append({'num': w['text'], 'top': w['top']})
            
            # 2. Határozzuk meg a sávokat
            for i in range(len(markers)):
                top = markers[i]['top']
                # A sáv alja a következő sorszám teteje, vagy az oldal alja
                bottom = markers[i+1]['top'] if i+1 < len(markers) else page.height
                
                # 3. Szívjuk be az összes szót ebben a magasságban
                block_words = [w for w in words if top - 2 <= w['top'] < bottom - 2]
                
                # 4. Válogassunk (szöveg összerakása)
                full_text = " ".join([w['text'] for w in block_words])
                
                # Adat kinyerés a blokkból
                kod_match = re.search(r'([PZSC]-\d{6})', full_text)
                tel_match = re.search(r'(\d{2}/\d{6,10})', full_text.replace(" ", ""))
                # Cím: 4000-től Debrecenen át az első vesszőig vagy hosszabb részig
                addr_match = re.search(r'(\d{4}\s+Debrecen,[^,]+(?:,[^,]+)?)', full_text)
                
                # Név: A kód és a cím közötti rész, vagy a kód utáni rész
                kod = kod_match.group(1) if kod_match else ""
                cim = addr_match.group(1) if addr_match else ""
                
                # Tisztított név keresése
                name_text = full_text.replace(kod, "").replace(cim, "").strip()
                # Az ügyintézők nevei gyakran "Takács Ildikó" stb., ezeket próbáljuk leválasztani
                nev = name_text.split('/')[0].strip() if '/' in name_text else name_text.split(' ')[0:3]
                nev = " ".join(nev) if isinstance(nev, list) else nev

                # Rendelések (X-YYYY)
                rendelesek = re.findall(r'(\d+-[A-Z0-9]+)', full_text)

                all_customers.append({
                    "Sorszám": markers[i]['num'],
                    "Kód": kod,
                    "Név": nev[:30],
                    "Cím": cim,
                    "Telefon": tel_match.group(1) if tel_match else "",
                    "Rendelés": ", ".join(rendelesek),
                    "Db": len(rendelesek)
                })

    return pd.DataFrame(all_customers)

# --- Streamlit UI v11 ---
st.title("Interfood Porszívó v11")
file = st.file_uploader("Menetterv PDF", type="pdf")

if file:
    df = extract_v11(file)
    st.dataframe(df)
    
    # CSV letöltés teszteléshez
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("Export CSV", csv, "interfood_v11.csv", "text/csv")
