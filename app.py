import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(page_title="Interfood v200.0 - THE STABLE ONE", layout="wide")

def parse_interfood_v200(pdf_file):
    all_data = []
    # A jól bevált rendelés-minta
    order_pat = r'(\d+-[A-Z][A-Z0-9*+]*)'

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            for line in text.split('\n'):
                line = line.strip()
                
                # Csak azokat a sorokat nézzük, amik sorszámmal kezdődnek
                s_match = re.match(r'^(\d+)', line)
                if not s_match: continue
                s_id = int(s_match.group(1))

                # 1. Ügyfélkód keresése (H- vagy S- kezdetű)
                u_code_m = re.search(r'([HS]-\d{5,7})', line)
                u_code = u_code_m.group(0) if u_code_m else ""

                # 2. Telefonszám keresése
                tel_match = re.search(r'(\d{2}/\d{6,7})', line.replace(" ", ""))
                phone = tel_match.group(0) if tel_match else " - "

                # 3. Rendelések kinyerése
                # Tisztítjuk a kötőjelek környékét
                search_text = re.sub(r'(\d+)\s*-\s*([A-Z])', r'\1-\2', line)
                raw_orders = re.findall(order_pat, search_text)
                
                clean_orders = []
                total_qty = 0
                for o in raw_orders:
                    # Julianna-mentőöv: ha a sorszám beleolvadt (pl. 011-M), levágjuk
                    parts = o.split('-')
                    q_str = parts[0]
                    if len(q_str) > 2 or q_str.startswith('0'):
                        # Csak az utolsó számjegyeket tartjuk meg, amik reálisak
                        m = re.search(r'([1-9]\d?)$', q_str)
                        if m: q_str = m.group(1)
                    
                    try:
                        qty = int(q_str)
                        if 0 < qty < 25:
                            clean_orders.append(f"{qty}-{parts[1]}")
                            total_qty += qty
                    except: continue

                # 4. Név és Cím (egyszerűbb, de biztosabb darabolás)
                # Kiszűrjük a sorszámot és a kódot, a maradékból próbáljuk meg a nevet
                name_addr_part = line.replace(str(s_id), "", 1).replace(u_code, "").strip()
                # A nevek általában nagybetűvel kezdődnek és a cím előtt vannak (Debrecen...)
                name_match = re.search(r'([A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+)+)', name_addr_part)
                u_nev = name_match.group(0) if name_match else "Név nem azonosítható"
                
                # A cím pedig onnan indul, ahol 4 számjegyet látunk (irányítószám)
                addr_match = re.search(r'(\d{4}\s+Debrecen.*)', line)
                u_cim = addr_match.group(1).split(phone)[0].strip() if addr_match else "Cím nem azonosítható"

                all_data.append({
                    "Sorszám": s_id,
                    "Ügyfélkód": u_code,
                    "Ügyintéző": u_nev,
                    "Cím": u_cim,
                    "Telefon": phone,
                    "Rendelés": ", ".join(clean_orders),
                    "Összesen": f"{total_qty} db"
                })

    df = pd.DataFrame(all_data)
    return df.drop_duplicates(subset=['Sorszám']).sort_values("Sorszám")

st.title("🛡️ Interfood v200.0 - A stabil visszatérés")
f = st.file_uploader("Töltsd fel a PDF-et", type="pdf")
if f:
    result_df = parse_interfood_v200(f)
    st.dataframe(result_df, use_container_width=True)
    st.download_button("💾 CSV Letöltése", result_df.to_csv(index=False).encode('utf-8-sig'), "interfood_v200_fix.csv")
