import streamlit as st
import pdfplumber
import pandas as pd
import re

def parse_menetterv_v129(pdf_file):
    all_rows = []
    # A leggyakoribb úttípusok, amik mentén vágni fogunk
    ut_tipusok = [' út ', ' utca ', ' útja ', ' tér ', ' körút ', ' krt ', ' u. ', ' sor ', ' dűlő ', ' köz ']

    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # Az utolsó oldalig a fix táblázatos módszer (ez stabil)
            if i < len(pdf.pages) - 1:
                table = page.extract_table({"vertical_strategy": "lines", "horizontal_strategy": "lines"})
                if table:
                    for row in table:
                        if not row or len(row) < 2: continue
                        s_raw = str(row[0]).strip().split('\n')[0]
                        if not s_raw.isdigit(): continue
                        all_rows.append({
                            "Sorszám": int(s_raw),
                            "Kód": re.search(r'([HKSC P Z]-\d{6})', str(row[1])).group(1) if re.search(r'([HKSC P Z]-\d{6})', str(row[1])) else "",
                            "Cím": str(row[2]).strip().replace('\n', ' '),
                            "Ügyintéző": str(row[3]).split('\n')[0] if row[3] else ""
                        })
            else:
                # UTOLSÓ OLDAL - Szigorúan lineáris, törésmentes feldolgozás
                text = page.extract_text()
                for line in text.split('\n'):
                    line = line.strip()
                    # Csak akkor foglalkozunk a sorral, ha sorszámmal és kóddal kezdődik
                    start_m = re.search(r'^(\d{1,3})\s+([HKSC P Z]-\d{6})', line)
                    if not start_m: continue
                    
                    s_num, kod = start_m.groups()
                    
                    # 1. Lépés: Keressük az irányítószámot és a telefonszámot (a két végpont)
                    irsz_m = re.search(r'\s(\d{4})\s', line)
                    tel_m = re.search(r'(\d{2}/\d{6,7})', line)
                    
                    if irsz_m and tel_m:
                        # Ez a "köztes" rész tartalmazza a címet és a nevet
                        koztes = line[irsz_m.start(1):tel_m.start()].strip()
                        
                        cim_resz = koztes
                        nev_resz = "Nincs név"
                        
                        # 2. Lépés: Keressük meg, hol van benne az "út", "utca" stb.
                        for tipus in ut_tipusok:
                            if tipus in koztes.lower():
                                parts = re.split(f'({tipus})', koztes, flags=re.IGNORECASE, maxsplit=1)
                                if len(parts) >= 3:
                                    # Az út típus utáni első "szó" a házszám (pl. 73/c)
                                    maradek = parts[2].strip().split(' ', 1)
                                    hazszam = maradek[0]
                                    
                                    # Ha van még valami a házszám után, az a név
                                    lehetseges_nev = maradek[1] if len(maradek) > 1 else ""
                                    
                                    # Kiss Tímea javítás: ha a név számmal/ponttal kezdődik, csapjuk a házszámhoz
                                    if lehetseges_nev and (lehetseges_nev[0].isdigit() or lehetseges_nev.startswith('-')):
                                        h_extra = lehetseges_nev.split(' ', 1)
                                        hazszam += " " + h_extra[0]
                                        lehetseges_nev = h_extra[1] if len(h_extra) > 1 else ""
                                    
                                    cim_resz = (parts[0] + parts[1] + hazszam).strip()
                                    nev_resz = lehetseges_nev.strip() if lehetseges_nev else "Nincs név"
                                    break # Ha megvan az úttípus, nem keressük a többit
                        
                        # Rendelés kinyerése a telefonszámtól a sor végéig (levágva az utolsó számot)
                        rendeles = line[tel_m.start():].strip()
                        rendeles = re.sub(r'\s\d+$', '', rendeles)

                        all_rows.append({
                            "Sorszám": int(s_num), "Kód": kod, "Cím": cim_resz, 
                            "Ügyintéző": nev_resz, "Rendelés": rendeles
                        })

    df = pd.DataFrame(all_rows).drop_duplicates(subset=['Sorszám'])
    return df.sort_values("Sorszám")

# --- Streamlit Indítás ---
st.set_page_config(page_title="Interfood Stabilizer", layout="wide")
st.title("🛡️ Interfood v129 - Fagyásmentes Verzió")

uploaded_file = st.file_uploader("Töltsd fel a PDF-et", type="pdf")

if uploaded_file:
    try:
        with st.spinner('Adatok kinyerése folyamatban... Ez a verzió nem fog lefagyni.'):
            result_df = parse_menetterv_v129(uploaded_file)
            st.success(f"Sikeresen beolvasva: {len(result_df)} sor.")
            st.dataframe(result_df, use_container_width=True)
            
            csv = result_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("💾 CSV Letöltése", csv, "interfood_export.csv", "text/csv")
    except Exception as e:
        st.error(f"Hiba történt: {e}")
