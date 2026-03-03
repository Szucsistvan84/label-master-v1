import streamlit as st
import pdfplumber
import pandas as pd
import re

def clean_money_v145(text_block):
    """Szigorú pénzmosó: csak a valódi összegeket hagyja meg."""
    if not text_block or "Ft" not in text_block:
        return "0 Ft"
    
    # Sortörések eltüntetése a kereséshez
    clean_block = " ".join(text_block.split())
    
    # Kikeressük az utolsó számblokkot a Ft előtt
    matches = re.findall(r'(\d[\d\s]*)\s*Ft', clean_block)
    if not matches:
        return "0 Ft"
    
    raw_val = matches[-1].strip()
    
    # A TE SZABÁLYOD: Ha szóköz van a 0 előtt (" 0"), az nulla.
    if raw_val == "0" or raw_val.endswith(" 0"):
        return "0 Ft"
    
    # A 61-es sor javítása: levágjuk az elé ragadt adagszámot
    parts = raw_val.split()
    if len(parts) >= 2:
        # Ha az utolsó rész 3 számjegy (pl. 935), akkor ezres tagolású
        if len(parts[-1]) == 3:
            return f"{parts[-2]} {parts[-1]} Ft"
        return f"{parts[-1]} Ft"
    
    return f"{raw_val} Ft"

def parse_pdf_v145(pdf_file):
    all_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            lines = text.split('\n')
            for i, line in enumerate(lines):
                # Sorszám + Kód (pl. 61 P-437302)
                match = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line.strip())
                if match:
                    s_num = match.group(1)
                    kod = match.group(2)
                    
                    # Beolvassuk a környezetet a névhez, címhez és pénzhez (5 sor)
                    context_lines = lines[i:i+6]
                    full_context = " ".join(context_lines)
                    
                    # Telefonszám
                    tel = re.search(r'(\d{2}/\d{6,7})', full_context)
                    
                    # Név: a kód utáni rész az első sorban
                    name = line.split(kod)[-1].strip()
                    # Ha a névben benne van a cím eleje, megpróbáljuk tisztítani
                    name = name.split('402')[0].split('403')[0].strip() 

                    # Cím: általában a kód alatti sor
                    address = lines[i+1].strip() if i+1 < len(lines) else "Nincs"

                    all_data.append({
                        "Sorszám": int(s_num),
                        "Kód": kod,
                        "Ügyintéző": name,
                        "Cím": address,
                        "Telefon": tel.group(1) if tel else "Nincs",
                        "Összeg": clean_money_v145(full_context)
                    })
    
    return pd.DataFrame(all_data).drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

# --- UI ---
st.set_page_config(page_title="Interfood v145", layout="wide")
st.title("Interfood Menetterv Feldolgozó v145")
st.info("Stabilizált nevek, címek és a 'Puskás-Kiss' féle pénzjavítás.")

f = st.file_uploader("Válaszd ki a PDF fájlt", type="pdf")

if f:
    with st.spinner('Feldolgozás...'):
        df = parse_pdf_v145(f)
    
    if not df.empty:
        st.success(f"Sikeresen beolvasva {len(df)} sor.")
        st.dataframe(df, use_container_width=True)
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="💾 CSV fájl letöltése",
            data=csv,
            file_name=f"interfood_v145_{f.name.replace('.pdf','')}.csv",
            mime="text/csv",
        )
