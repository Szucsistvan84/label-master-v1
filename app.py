import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import requests
import PIL.ImageDraw
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Frame, KeepInFrame, Flowable

# --- ALAPBEÁLLÍTÁSOK ---
PHONE_PAT = r'(\d{2}/\d[\d\s,]*\d)'
# Frissített minta: felismeri a sima (-), az en-dash (–) és az em-dash (—) jeleket is
ORDER_PAT = r'(\d+)\s*[-\u2013\u2014\u2212]\s*([A-Z][A-Z0-9*+]*)'
# Frissített, "szóköz-toleráns" regex
MONEY_PAT = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

# --- EZT A SEGÉDFÜGGVÉNYT TEDD A KÓD ELEJÉRE ---
def get_day_short(day_str):
    if not day_str: return ""
    primary_day = day_str.split(',')[0].strip() # "Csütörtök, Péntek" -> "Csütörtök"
    day_map = {
        "Hétfő": "Hé", "Kedd": "Ke", "Szerda": "Sze",
        "Csütörtök": "Csü", "Péntek": "Pé", "Szombat": "Szo"
    }
    return day_map.get(primary_day, primary_day[:2])

def extract_all_meta(pdf_files):
    all_meta = {'jaratok': [], 'ev': '', 'het': '', 'nap': ''}
    
    # Járatszám minta: 4 számjegy + pont + járat VAGY Nyomtatta: 4 számjegy
    jarat_re = re.compile(r'(\d{4})\.\s*járat|Nyomtatta:\s*(\d{4})')
    
    for uploaded_file in pdf_files:
        uploaded_file.seek(0) 
        with pdfplumber.open(uploaded_file) as pdf:
            text = pdf.pages[0].extract_text() or ""
            
            # 1. Járatszámok gyűjtése
            for match in jarat_re.finditer(text):
                j_num = match.group(1) or match.group(2)
                if j_num and j_num not in all_meta['jaratok']:
                    all_meta['jaratok'].append(j_num)
            
            # 2. Dátum infók - Csak ha még üresek
            if not all_meta['ev']:
                ev_m = re.search(r'Év:\s*(\d{4})', text)
                if ev_m: all_meta['ev'] = ev_m.group(1)

            if not all_meta['het']:
                het_m = re.search(r'Hét:\s*(\d{1,2})', text)
                if het_m: all_meta['het'] = het_m.group(1)

            # 3. A NAPOK kinyerése (Péntek, Szombat stb.)
            if not all_meta['nap']:
                # Keressük a 'Nap:' utáni részt az 'InterFood' szóig
                nap_m = re.search(r'Nap:\s*(.*?)(?=InterFood|$)', text, re.DOTALL)
                if nap_m:
                    # Tisztítjuk: leszedjük a felesleges vesszőket a végéről és a szóközöket
                    nap_raw = nap_m.group(1).strip()
                    all_meta['nap'] = nap_raw.rstrip(',')
    
    all_meta['jaratok'].sort()
    return all_meta

def register_fonts():
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        
        return 'DejaVu', 'DejaVu-Bold'
    except Exception as e:
        return 'Helvetica', 'Helvetica-Bold'


def get_etlap_dict(year, week, target_day=None):
    """
    Lekéri az Interfood Excel étlapot és kigyűjti a pénteki (5) és szombati (6) oszlopokat.
    A kulcsok prefixet kapnak (P_ vagy Z_), hogy megkülönböztessük a napokat.
    """
    if not year or not week: return {}

    url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    etlap_full = {}

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), header=None)

            # 5-ös oszlop: Péntek (F), 6-os oszlop: Szombat (G/Zárónap)
            # A PDF-ben a 'P' jelöli a pénteket, a 'Z' a szombatot
            for day_prefix, col_idx in [("P", 5), ("Z", 6)]:
                for i in range(len(df)):
                    val = str(df.iloc[i, 0])
                    if " - " in val:
                        cikkszam = val.split(" - ")[0].strip().upper()
                        try:
                            # Név kinyerése
                            nev = str(df.iloc[i, col_idx]).strip()
                            # Ár kinyerése a név alatti cellából
                            ar_val = df.iloc[i + 1, col_idx]

                            if nev != "nan" and nev != "" and "étlap" not in nev.lower():
                                ar = 0
                                if pd.notnull(ar_val):
                                    try:
                                        ar = int(re.sub(r'\D', '', str(ar_val)))
                                    except:
                                        ar = 0

                                # Egyedi kulcs: pl. "P_A" vagy "Z_A"
                                etlap_full[f"{day_prefix}_{cikkszam}"] = {'nev': nev, 'ar': ar}
                        except:
                            continue
            return etlap_full
    except Exception as e:
        st.error(f"Étlap letöltési hiba: {e}")
    return {}

def debug_pdf_layout(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        im = page.to_image(resolution=150)
        
        # Rajzoljunk egy rácsot 50 pontonként, és írjuk rá a számokat
        for x in range(0, int(page.width), 50):
            im.draw_vlines([x], stroke="lightgray", stroke_width=1)
            # Ez a rész vizuálisan segít beazonosítani a pontos helyet
        
        # A jelenlegi (még rossz) vonalaid pirossal
        current_v_lines = [0, 50, 140, 360, 510, 580, 780, 842]
        im.draw_vlines(current_v_lines, stroke="red", stroke_width=2)
        
        st.image(im.annotated, caption="Keresd meg, hol végződnek az oszlopok a szürke rács alapján!", use_container_width=True)

# --- 3. FŐ FÜGGVÉNY: PDF BEOLVASÁS ÉS BLOKKOSÍTÁS ---
def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jaratok': []}
    
    # Kibővített Stop Words lista a te meghatározásod alapján
    stop_words = [
        "Összesítés:", 
        "Csilagozott betűnél", # Eltéréssel is: Csillagozott/Csilagozott
        "Összesen:", 
        "Nyomtatta:", 
        "Oldal:", 
        "Menetlevél", 
        "Vége"
    ]

    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        W = page.width
        def c(kocka): return (kocka / 88) * W
        v_lines = [c(0), c(5.5), c(21.5), c(39.5), c(47), c(52), c(82.5), c(88)]

        for pg in pdf.pages:
            words = pg.extract_words(x_tolerance=3, y_tolerance=3)
            
            # --- FÜGGŐLEGES SOROMPÓ (Cutoff) BEÁLLÍTÁSA ---
            # Megkeressük a lap alját jelző szavak legmagasabb pontját
            footer_elements = [
                w for w in words 
                if any(tag in w['text'] for tag in ["Összesítés", "Csilagozott", "Összesen"])
                and w['top'] > pg.height * 0.5 # Csak a lap alsó felében keressük
            ]
            
            # Ha nincs ilyen szó, a lap alja a határ, ha van, akkor a szó teteje
            page_cutoff = min([w['top'] for w in footer_elements]) - 2 if footer_elements else pg.height

            anchors = [w for w in words if re.search(r'[HKSCPZ]-\d{5,7}', w['text'])]
            
            for i, anchor in enumerate(anchors):
                # Ha az ID eleve a cutoff alatt van (téves találat), kihagyjuk
                if anchor['top'] >= page_cutoff:
                    continue

                y_top = anchor['top'] - 5
                # A blokk vége: vagy a következő ID, vagy a lap alja (sorompó)
                next_anchor_top = anchors[i+1]['top'] - 5 if i+1 < len(anchors) else page_cutoff
                y_bottom = min(next_anchor_top, page_cutoff)
                
                line_words = [w for w in words if y_top <= w['top'] < y_bottom]
                
                def get_col_text(x_min, x_max):
                    sel = [w for w in line_words if x_min <= (w['x0'] + w['x1'])/2 < x_max]
                    sel.sort(key=lambda x: (x['top'], x['x0']))
                    return " ".join([w['text'] for w in sel])

                # Adatgyűjtés a sávokból
                full_id_area = get_col_text(v_lines[0], v_lines[2])
                id_match = re.search(r'([HKSCPZ]-\d{5,7})', full_id_area)
                
                # --- 0. FEJLÉC ÉS LÁBLÉC TELJES KIZÁRÁSA ---
                line_text_full = " ".join([w['text'] for w in line_words])
                tiltott_szavak = ["járat", "menetterve", "Év:", "Hét:", "Nap:", "InterFood", "oldal", "Nyomtatva", "Összesítés:", "Csilagozott", "Összesen:"]
                
                if any(stop in line_text_full for stop in tiltott_szavak):
                    if not re.search(r'[HKSCPZ]-\d{5,7}', line_text_full):
                        continue

                if id_match:
                    full_id = id_match.group(1)
                    prefix = full_id.split('-')[0]
                    
                    # --- 1. KOORDINÁTÁK ÉS ALAP-SOR MEGHATÁROZÁSA ---
                    W = page.width
                    x40 = (40 / 88) * W
                    x48 = (48 / 88) * W
                    x52_5 = (52.5 / 88) * W
                    
                    y_anchor = (anchor['top'] + anchor['bottom']) / 2
                    # Definiáljuk a row_words-öt az adott sorhoz
                    row_words = [w for w in line_words if abs(((w['top'] + w['bottom']) / 2) - y_anchor) < 8]

                    # --- 2. TELEFON ÉS PÉNZ ---
                    tel_money_words = sorted([w for w in row_words if x40 <= (w['x0'] + w['x1'])/2 < x52_5], key=lambda w: w['top'])
                    
                    phone_val, money_val = "", "0Ft"
                    if tel_money_words:
                        first_y = tel_money_words[0]['top']
                        top_row = [w for w in tel_money_words if abs(w['top'] - first_y) < 4]
                        bottom_row = [w for w in tel_money_words if w not in top_row]
                        top_text = " ".join([w['text'] for w in sorted(top_row, key=lambda w: w['x0'])])
                        bottom_text = " ".join([w['text'] for w in sorted(bottom_row, key=lambda w: w['x0'])])
                        
                        phone_match = re.search(r'(\d{1,2}/\d+)', top_text + " " + bottom_text)
                        phone_val = phone_match.group(1).replace(" ", "") if phone_match else ""
                        
                        money_match = re.search(r'(-?\d[\d\s]*)\s*Ft', bottom_text if bottom_text else top_text)
                        if money_match:
                            money_val = money_match.group(0).replace(" ", "")
                        else:
                            last_num = re.search(r'(\d+)$', bottom_text.strip() if bottom_text else top_text.strip())
                            money_val = f"{last_num.group(1)}Ft" if last_num else "0Ft"

                    # --- ÜGYINTÉZŐ KERESÉSE (V15 - A Szanyi-specialista) ---
                    x_start_admin = (38 / 88) * W
                    x_end_admin = (54 / 88) * W
                    
                    # Csak azokat a szavakat gyűjtjük, amik az admin sávban vannak
                    admin_candidates = [w for w in line_words if x_start_admin <= (w['x0'] + w['x1'])/2 < x_end_admin]
                    
                    y_start = (anchor['top'] + anchor['bottom']) / 2
                    raw_name_parts = []
                    
                    # STOP-szavak az összesítéshez
                    stop_keywords = ["Összesen", "Összesítés", "Össz"]
                    
                    # Rendezés: fentről le, balról jobbra
                    for w in sorted(admin_candidates, key=lambda x: (x['top'], x['x0'])):
                        t_clean = w['text'].strip()
                        
                        # 1. STOP: Ha elérjük az összesítőt
                        if any(stop.lower() in t_clean.lower() for stop in stop_keywords):
                            break
                            
                        # 2. FÜGGŐLEGES SZŰRÉS: Maradunk az ID magasságában (+/- 35 pixel)
                        if abs(w['top'] - y_start) < 35:
                            # 3. HORIZONTÁLIS VÉDELEM: Ha a szó x1-e túlnyúlik az admin sávon, 
                            # és a szöveg gyanúsan rövid/töredék, akkor az már a megjegyzés
                            if w['x1'] > x_end_admin * 1.02 and len(t_clean) < 6:
                                continue

                            # 4. TÍPUS SZŰRÉS: Pénz, telefon, kódok (pl. 4-SP3)
                            if "Ft" in t_clean: continue
                            if "/" in t_clean and any(c.isdigit() for c in t_clean): continue
                            if re.search(r'\d-[A-Z]', t_clean): continue
                            if t_clean.isdigit() and len(t_clean) < 4: continue
                                
                            raw_name_parts.append(w)

                    # --- ÖSSZEÁLLÍTÁS ÉS SEBÉSZI TISZTÍTÁS ---
                    full_raw_text = " ".join([p['text'] for p in sorted(raw_name_parts, key=lambda x: (x['top'], x['x0']))])
                    
                    # Számok, prefixek, csillagok törlése
                    clean_name = full_raw_text.replace("*", "")
                    clean_name = re.sub(r'\d+', '', clean_name)
                    clean_name = re.sub(r'-[A-Z0-9]{1,3}\b', '', clean_name)
                    
                    # SZÓTÁR ALAPÚ SZŰRÉS (Szanyi Norbert "közöt" és Gabriella "D" ellen)
                    junk_words = ["közöt", "között", "köz", "D", "S", "adag", "db"]
                    
                    final_parts = []
                    for part in clean_name.split():
                        p_stripped = part.strip(" ,.|/-")
                        # Ha a szó benne van a szemét-listában, vagy csak 1 karakter (és nem monogram)
                        if p_stripped.lower() in [j.lower() for j in junk_words]:
                            continue
                        if len(p_stripped) == 1 and not p_stripped.endswith('.'):
                            continue
                        final_parts.append(part)

                    admin_name = " ".join(final_parts).strip(" -/|.,*")
                    admin_name = " ".join(admin_name.split())

                    # --- 4. RENDELÉS ÉS MEGJEGYZÉS ---
                    order_words = [w for w in row_words if (w['x0'] + w['x1'])/2 >= x52_5]
                    order_text = " ".join([w['text'] for w in sorted(order_words, key=lambda x: x['x0'])])
                    raw_orders = re.findall(ORDER_PAT, order_text)
                    rendeles_str = ", ".join([f"{q}-{c}" for q, c in raw_orders])

                    # CÍM meghatározása (v_lines[2] és x40 között)
                    address = " ".join([w['text'] for w in sorted([w for w in row_words if v_lines[2] <= (w['x0']+w['x1'])/2 < x40], key=lambda x: x['x0'])]).strip()

                    # --- DINAMIKUS CÍMTISZTÍTÁS (Az Ügyintéző neve alapján) ---
                    if admin_name and address:
                        # Az ügyintéző nevét tiszta szavakra bontjuk, csak a 1 karakternél hosszabbakat tartjuk meg
                        name_parts_to_erase = [n.strip(" ,.|/-").lower() for n in admin_name.split() if len(n.strip(" ,.|/-")) > 1]
                        
                        address_parts = address.split()
                        
                        # Amíg a cím utolsó szava (tisztítva) egyezik valamelyik név-taggal, levágjuk
                        while address_parts and address_parts[-1].strip(" ,.|/-").lower() in name_parts_to_erase:
                            address_parts.pop()
                        
                        # Extra biztonsági kör: Dr. és egyéb maradékok
                        if address_parts and address_parts[-1].strip(" ,.|/-").lower() in ["dr", "dr.", "idősb", "ifj"]:
                            address_parts.pop()

                    # --- 1. HORGONYOK ELŐKÉSZÍTÉSE ---
                    raw_line = line_text_full 
                    megj_resz_1 = "" 
                    megj_resz_2 = "" 

                    # --- 2. LÉPÉS: SORSZÁM LEVÁGÁSA (AZ ID-IG) ---
                    id_pattern = r'[HKSCPZ]-\d{6}'
                    id_match = re.search(id_pattern, raw_line)
                    working_line = raw_line
                    if id_match:
                        working_line = raw_line[id_match.start():]

                    # --- 3. LÉPÉS: ADATOK KERESÉSE (Horgonyoknak) ---
                    # Telefon és Pénz horgonyok (ezek fixek)
                    phone_for_clean = ""
                    p_match = re.search(PHONE_PAT, working_line)
                    if p_match: phone_for_clean = p_match.group(1)

                    money_for_clean = ""
                    m_match = re.search(MONEY_PAT, working_line)
                    if m_match: money_for_clean = m_match.group(1)

                    # Cím horgony (Irányítószámtól a Telefonig/Pénzig tartó rész)
                    address_for_clean = ""
                    city_match = re.search(r'\b\d{4}\b', working_line)
                    if city_match:
                        # Megkeressük hol kezdődik a város és hol kezdődik a telefon/pénz
                        start_idx = city_match.start()
                        end_pat = f"{re.escape(phone_for_clean)}|{re.escape(money_for_clean)}|Ft|{ORDER_PAT}"
                        end_match = re.search(end_pat, working_line[start_idx:])
                        
                        if end_match:
                            address_for_clean = working_line[start_idx : start_idx + end_match.start()].strip()
                        else:
                            address_for_clean = working_line[start_idx:].strip()

                    # --- 4. LÉPÉS: KONTEXTUS BŐVÍTÉSE (PORSZÍVÓ) ---
                    # Toleranciát használunk a rendezésnél, hogy az egy sorban lévő szavak ne cserélődjenek fel
                    # A 'top' értéket 3 pixelre kerekítjük, így az egy vonalban lévők azonos 'top'-ot kapnak
                    line_words_sorted = sorted(line_words, key=lambda x: (round(x['top'] / 3) * 3, x['x0']))
                    full_block_text = " ".join([w['text'] for w in line_words_sorted])
                    
                    # Levágjuk az elejéről a sorszámot az ID-ig
                    id_match_context = re.search(id_pattern, full_block_text)
                    working_context = full_block_text[id_match_context.start():] if id_match_context else full_block_text

                    # --- 5. LÉPÉS: TISZTÍTOTT KONTEXTUS LÉTREHOZÁSA ---
                    # Csak itt inicializálunk, és rögtön takarítunk
                    megj_resz_1 = "" 
                    megj_resz_2 = "" 

                    # Kiszűrjük a rendelési kódokat és a pénzt, hogy ne zavarják a megjegyzés keresését
                    clean_context = re.sub(ORDER_PAT, '', working_context)
                    clean_context = re.sub(MONEY_PAT, '', clean_context)
                    # A telefonszámot is érdemes kivenni a clean_context-ből, hogy ne zavarjon be megjegyzésként
                    if 'phone_val' in locals() and phone_val:
                        clean_context = clean_context.replace(phone_val, "")

                    # --- 6. LÉPÉS: MEGJEGYZÉS 1. FELE (ID ÉS ZIP KÖZÖTT) ---
                    # Ez kezeli a nevet/részleget az irányítószám előtt
                    zip_match = re.search(r'\b\d{4}\b', clean_context)
                    if zip_match:
                        # Az ID utáni, de a ZIP előtti rész kinyerése
                        pre_zip = clean_context[:zip_match.start()].replace(full_id, "").strip()
                        if pre_zip:
                            if "/" in pre_zip:
                                megj_resz_1 = pre_zip.split("/")[0].strip()
                            else:
                                t_megj = pre_zip
                                if admin_name:
                                    for w in admin_name.split():
                                        if len(w) > 2:
                                            t_megj = re.sub(rf'\b{re.escape(w)}\b', '', t_megj, flags=re.IGNORECASE)
                                megj_resz_1 = t_megj.strip()

                    # --- 7. LÉPÉS: MEGJEGYZÉS 2. FELE (CÍM UTÁNI RÉSZ) ---
                    # Ez találja meg a "Sörfőzde", "Porta" stb. infókat a cím után
                    if address in clean_context:
                        anchor_pos = clean_context.find(address) + len(address)
                        after_address = clean_context[anchor_pos:].strip()
                        
                        # A végét a telefon vagy a sor vége jelzi (a pénzt/rendelést már töröltük)
                        end_m = re.search(re.escape(phone_val), after_address)
                        megj_resz_2 = after_address[:end_m.start()].strip() if end_m else after_address

                    # --- 8. ÖSSZEFŰZÉS ÉS RADÍROZÁS ---
                    parts = []
                    # Szanyi Norbi speciális esete
                    if address:
                        for keyword in ["legyenek", "perccel", "érkezés", "kapucsengő"]:
                            if keyword in address.lower() and keyword not in (megj_resz_1 + megj_resz_2).lower():
                                extra_s = re.search(rf'\b{keyword}\b.*', address, re.IGNORECASE)
                                if extra_s: parts.append(extra_s.group().strip())

                    if megj_resz_1 and len(megj_resz_1) > 1: parts.append(megj_resz_1)
                    if megj_resz_2 and len(megj_resz_2) > 1: parts.append(megj_resz_2)
                    
                    # Duplikátumok kiszűrése és tisztítás
                    raw_combined = " | ".join(dict.fromkeys(parts))
                    clean_customer = re.sub(r'\s+', ' ', raw_combined)
                    
                    # Junk szavak törlése (Felnőtt, Dr. stb)
                    for junk in ["Felnőtt", "Nyugdíjas", "Gyerek", "Vendég", "Dr.", "idősb", "ifj"]:
                        clean_customer = clean_customer.replace(junk, "")

                    # --- 9. RÉSZLEG ÉS INSTRUKCIÓ SZÉTVÁLASZTÁSA ---
                    reszleg = ""
                    if "/" in clean_customer:
                        c_parts = clean_customer.split("/")
                        potential_reszleg = c_parts[0].strip()
                        if admin_name and potential_reszleg.lower() != admin_name.lower():
                            reszleg = potential_reszleg
                    
                    # Ami maradt, az az extra instrukció
                    extra_instructions = clean_customer
                    if reszleg: extra_instructions = extra_instructions.replace(reszleg, "")
                    if admin_name:
                        for n_part in admin_name.split():
                            if len(n_part) > 2:
                                extra_instructions = re.sub(rf'\b{re.escape(n_part)}\b', '', extra_instructions, flags=re.IGNORECASE)

                    extra_instructions = extra_instructions.replace("/", "").strip(" -/|.,")

                    # --- TELEFONSZÁM- ÉS KAPUKÓD-BIZTOS TISZTÍTÁS ---
                    
                    # 1. CSAK a magányos előhívókat bántjuk (pl. "Név 30")
                    # Megnézzük, hogy a 20/30/70 után NINCS-E perjel vagy több számjegy
                    clean_customer = re.sub(r'\b(20|30|70)\b(?![/\d])', '', clean_customer)

                    # 2. Ügyintéző nevének radírozása (finomítva)
                    if admin_name:
                        # Teljes név törlése
                        clean_customer = re.sub(rf'\b{re.escape(admin_name)}\b', '', clean_customer, flags=re.IGNORECASE)
                        # Név részei (pl. Kiss, János), de csak ha önálló szavak
                        for name_part in admin_name.split():
                            if len(name_part) > 2:
                                clean_customer = re.sub(rf'\b{re.escape(name_part)}\b', '', clean_customer, flags=re.IGNORECASE)

                    # 3. Vesszőhegyek takarítása (a # és / jeleket békén hagyja!)
                    # Csak a halmozott vesszőt, pontot és szóközt cseréli egyetlen szóközre
                    clean_customer = re.sub(r'[,.;:|*]{2,}', ' ', clean_customer)

                    # 4. Részleg és Instrukció szétválasztása
                    reszleg = ""
                    extra_instructions = clean_customer
                    if "/" in clean_customer:
                        # Ha a perjel telefonszám része (szám van előtte és utána), nem vágjuk szét!
                        if not re.search(r'\d/\d', clean_customer):
                            c_parts = clean_customer.split("/")
                            reszleg = c_parts[0].strip()
                            extra_instructions = "/".join(c_parts[1:]).strip()

                    # 5. Intelligens összefűzés (Dupla pipeline ellen)
                    final_note_parts = []
                    r_clean = reszleg.strip(" ,.-/|*")
                    e_clean = extra_instructions.strip(" ,.-/|*")
                    
                    if r_clean and len(r_clean) > 1:
                        final_note_parts.append(r_clean)
                    if e_clean and len(e_clean) > 1:
                        if not final_note_parts or e_clean.lower() != final_note_parts[0].lower():
                            final_note_parts.append(e_clean)
                    
                    full_note = " | ".join(final_note_parts)
                    
                    # --- 6. UTOLSÓ FINOMHANGOLÁS ÉS KOZMETIKA ---
                    
                    # A) Magányos előhívók (30, 70, 06 stb.) eltávolítása, ha csak szóköz vagy pipeline van körülöttük
                    # 1. Ha a sor végén van egy pipeline és egy szám (pl. "Járási | 30")
                    full_note = re.sub(r'\|\s*(20|30|70|06|20|70)\s*$', '', full_note)
                    # 2. Ha a sor elején van egy szám és egy pipeline (pl. "30 | teherporta")
                    full_note = re.sub(r'^\s*(20|30|70|06)\s*\|', '', full_note)
                    # 3. Ha önállóan áll, és nem követi perjel vagy több számjegy (telefonvédelem)
                    full_note = re.sub(r'\b(20|30|70|06)\b(?!\s*/|\s*\d)', '', full_note)

                    # B) Vesszőhegyek és írásjel-halmozódások (Kenézy-effektus)
                    # Minden olyan részt, ahol vesszők és szóközök váltják egymást legalább 2-szer, egy szóközre cserélünk
                    full_note = re.sub(r'([ ,]*[,][ ,]*){2,}', ' ', full_note)

                    # C) Dupla pipeline-ok (||) és felesleges elválasztók takarítása
                    full_note = re.sub(r'\|\s*\|', '|', full_note)
                    
                    # D) Végső szóköz- és szélső karakter takarítás
                    full_note = re.sub(r'\s+', ' ', full_note).strip(" ,.-/|*")
                    
                    # Rendelés szöveges formázása a CSV-hez
                    mapping = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}
                    full_rendeles_text = f"{mapping.get(prefix, '')}: {rendeles_str}" if rendeles_str else ""

                    mapping = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}
                    full_rendeles_text = f"{mapping.get(prefix, '')}: {rendeles_str}" if rendeles_str else ""

                    rows.append({
                        "ID": full_id, "Ügyintéző": admin_name, "Cím": address, "Telefon": phone_val,
                        "Pénz": money_val, "Rendelés": rendeles_str, "Megjegyzés": full_note,
                        "Összesen": sum(int(q) for q, c in raw_orders) if raw_orders else 0,
                        "Rendelés_Full": full_rendeles_text, "temp_id": full_id.split('-')[-1],
                        "Prefix": prefix, "Csoport": current_group_id if 'current_group_id' in locals() else 0
                    })
    
    if not rows: return [], metadata
    df = pd.DataFrame(rows)
    df['Csoport'] = df.groupby('temp_id').ngroup() + 1
    return df.to_dict('records'), metadata
    
def merge_data(all_rows):
    if not all_rows: 
        return pd.DataFrame()
    
    # --- HIBA JAVÍTÁSA ITT ---
    # Ha az all_rows nem DataFrame-ek listája, hanem soroké, 
    # akkor előbb csinálunk belőle egy nagy táblázatot.
    if isinstance(all_rows, list) and len(all_rows) > 0:
        if not isinstance(all_rows[0], pd.DataFrame):
            combined = pd.DataFrame(all_rows)
        else:
            combined = pd.concat(all_rows, ignore_index=True)
    else:
        combined = all_rows
    # -------------------------

    merged = []
    unique_ids = combined['temp_id'].unique()
    
    for tid in unique_ids:
        subset = combined[combined['temp_id'] == tid]
        base = subset.iloc[0].to_dict()
        
        if len(subset) > 1:
            # Rendelések összefűzése
            all_orders = []
            for _, r in subset.iterrows():
                o_str = str(r.get('Rendelés_Full', '')).strip()
                if o_str: all_orders.append(o_str)
            base['Rendelés_Full'] = " | ".join(all_orders)
            
            # DB összeadása
            try:
                base['Összesen'] = sum(pd.to_numeric(subset['Összesen'], errors='coerce').fillna(0))
            except: pass
            
            # PÉNZ: Az első érvényes összeget tartjuk meg (nem adunk össze)
            p_val = ""
            for _, r in subset.iterrows():
                val = str(r.get('Pénz', '')).strip()
                if val and val.lower() != 'nan' and any(c.isdigit() for c in val):
                    p_val = val
                    break
            base['Pénz'] = p_val

        merged.append(base)
    
    res = pd.DataFrame(merged)
    
    # Sorrend fixálása
    if 'Sorrend' in res.columns:
        res['Sorrend'] = pd.to_numeric(res['Sorrend'], errors='coerce')
        res = res.sort_values('Sorrend')

    # --- CSOPORTOSÍTÁS (Keretezéshez) ---
    res['Csoport'] = 0
    group_id = 1
    for i in range(1, len(res)):
        def clean_addr(s):
            return re.sub(r'\W+', '', str(s)).lower()
        
        addr_prev = clean_addr(res.iloc[i-1]['Cím'])
        addr_curr = clean_addr(res.iloc[i]['Cím'])
        
        if addr_prev == addr_curr and addr_curr != "":
            if res.iloc[i-1]['Csoport'] == 0:
                res.at[res.index[i-1], 'Csoport'] = group_id
                res.at[res.index[i], 'Csoport'] = group_id
                group_id += 1
            else:
                res.at[res.index[i], 'Csoport'] = res.iloc[i-1]['Csoport']
                
    return res

def create_label_pdf(df, fn, ft, meta):
    if df is None or df.empty: return None
    if 'Sorrend' not in df.columns: df['Sorrend'] = range(1, len(df) + 1)
    df = df.sort_values('Sorrend')
    
    # --- ÚJ: Bázis nap meghatározása ---
    bazis_nap_rovid = get_day_short(meta.get('nap', ''))
    nap_list = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo"]

    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70 * mm, 42.42 * mm
    inner_m = 5.5 * mm 
    usable_w = lw - (2 * inner_m)

    # Tömörített sorköz a rendeléseknek
    # Fontos: A Paragraph-nak meg kell adni, mi legyen a Bold párja
    order_s = ParagraphStyle('Order', 
                             fontName=f_reg, 
                             fontSize=7.5, 
                             leading=8.0)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1)

    total_slots = math.ceil(len(df) / 21) * 21

    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        lift = 4.5 * mm if row_i == 0 else 0
        y_eff = y + lift 

        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
# --- ÚJ: Precíziós nap-alapú formázás (JAVÍTOTT VÁLTOZÓKKAL) ---
            import re
            r_full = str(r.get('Rendelés_Full', r.get('Rendelés', '')))
            kulonleges = False
            
            # Szétvágjuk a szöveget ott, ahol új nap kezdődik, de megtartjuk az elválasztókat is
            # A regex figyeli a | jelet és a napok neveit is
            napi_blokkok = re.split(r'(\s*\|\s*|(?=Hé:|Ke:|Sze:|Csü:|Pé:|Szo:))', r_full)
            
            formazott_reszek = [] # Ezt kereste a hibaüzenet!
            
            for blokk in napi_blokkok:
                if not blokk or not blokk.strip(): 
                    if blokk: formazott_reszek.append(blokk)
                    continue
                
                szin_blokk = blokk
                # Megnézzük, hogy ez a blokk egy különleges nappal kezdődik-e
                for n in nap_list:
                    n_tag = f"{n}:"
                    if n_tag in blokk:
                        if n != bazis_nap_rovid:
                            kulonleges = True
                            # Vastagítás és méretnövelés a teljes blokkra
                            szin_blokk = f'<font name="{f_bold}" size="8.2">{blokk}</font>'
                        break
                
                formazott_reszek.append(szin_blokk)
            
            # Újra összefűzzük a darabokat
            formazott_rendeles = "".join(formazott_reszek)

            # 1. Név mögötti szürkítés (Csak ha különleges nap van a sorban)
            if kulonleges:
                p.saveState()
                p.setFillColor(colors.Color(0.88, 0.88, 0.88))
                # A téglalap pontosan a név alá pozicionálva
                p.rect(x + inner_m - 1*mm, top_y - 9.5 * mm, usable_w + 2*mm, 5.5 * mm, fill=1, stroke=0)
                p.restoreState()

            # 2. Fejléc adatok
            p.setFont(f_bold, 10)
            p.drawString(x + inner_m, top_y - 3 * mm, f"#{int(r['Sorrend'])}")
            
            display_id = str(r.get('temp_id', 'N/A'))
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, top_y - 3 * mm, f"ID: {display_id}")

            p.setFont(f_bold, 9)
            p.drawString(x + inner_m, top_y - 8.5 * mm, str(r.get('Ügyintéző', ''))[:25])
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, top_y - 8.5 * mm, str(r.get('Telefon', '')))

            p.setFont(f_reg, 7)
            p.drawString(x + inner_m, top_y - 12.5 * mm, str(r.get('Cím', ''))[:45])

            # 3. Rendelés (A formázott, szelektíven félkövérített szöveggel)
            para = Paragraph(formazott_rendeles, order_s)
            pw, ph = para.wrap(usable_w, 15 * mm)
            para.drawOn(p, x + inner_m, y_eff + inner_m + 6.8 * mm)

            # 4. Fizetendő és Darab
            penz = str(r.get('Pénz', '0 Ft')).replace(" ", "")
            if penz not in ["0Ft", "", "0"]:
                p.setFont(f_bold, 9)
                p.drawString(x + inner_m, y_eff + 5.5 * mm, f"Fizet: {str(r.get('Pénz', ''))}")
            
            p.setFont(f_bold, 8)
            p.drawRightString(x + lw - inner_m, y_eff + 5.5 * mm, f"{int(r.get('Összesen', 0))} db")

            # 5. Elválasztó vonal és Futár
            p.setDash(1, 0) 
            p.setStrokeColor(colors.black)
            p.setLineWidth(0.1)
            p.line(x + inner_m, y_eff + 5 * mm, x + lw - inner_m, y_eff + 5 * mm)
            
            p.setFont(f_reg, 6)
            p.drawCentredString(x + lw / 2, y_eff + 2.5 * mm, f"Futár: {fn} | {ft}")

        else:
            # --- MARKETING ETIKETT (Érintetlenül hagyva) ---
            m_text = (
                f"<font size='10' name='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető</b></font>"
            )
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(usable_w, lh - (2 * inner_m) - lift)
            para.drawOn(p, x + (lw - pw) / 2, y_eff + (lh - ph) / 2)

    p.save()
    buf.seek(0)
    return buf
    
# --- ÚJ OSZTÁLY A RAJZOLT NÉGYZETHEZ (Marad, ahogy írtad) ---
class Checkbox(Flowable):
    def __init__(self, size=10):
        Flowable.__init__(self)
        self.width = size
        self.height = size

    def draw(self):
        self.canv.setLineWidth(0.8)
        self.canv.setStrokeColor(colors.black)
        self.canv.rect(0, 0, self.width, self.height, stroke=1, fill=0)

def create_manifest_pdf(df, c_n, meta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=5*mm, leftMargin=5*mm, topMargin=8*mm, bottomMargin=12*mm)
    f_reg, f_bold = register_fonts()

    styles = {
        'Normal': ParagraphStyle('Normal', fontName=f_reg, fontSize=8, leading=8.5),
        'Small': ParagraphStyle('Small', fontName=f_reg, fontSize=7, leading=8),
        'Header': ParagraphStyle('Header', fontName=f_bold, fontSize=10, leading=11, alignment=1),
        'NameBold': ParagraphStyle('NameBold', fontName=f_bold, fontSize=8.5, leading=9),
        'IDStyle': ParagraphStyle('IDStyle', fontName=f_reg, fontSize=7.5, leading=9, alignment=2, textColor=colors.gray)
    }

    # --- ÚJ: Bázis nap meghatározása ---
    bazis_nap_rovid = get_day_short(meta.get('nap', ''))
    nap_list = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo"]

    elements = []
    j_str = ", ".join(meta.get('jaratok', []))
    header_str = f"MENETTERV - Járat(ok): {j_str} | {meta.get('ev', '')}. év, {meta.get('het', '')}. hét | {meta.get('nap', '')}"
    elements.append(Paragraph(header_str, styles['Header']))
    elements.append(Spacer(1, 2*mm))

    # 1. FEJLÉC ÉS OSZLOPSZÉLESSÉGEK FRISSÍTÉSE
    # Sorrend: #, NÉV, RENDELÉS, ☐, PÉNZ, TEL, DB
    table_data = [["#", "NÉV / CÍM / INFÓ", "RENDELÉS", "☐", "PÉNZ", "TEL", "DB"]]
    col_widths = [8*mm, 95*mm, 32*mm, 10*mm, 18*mm, 24*mm, 8*mm]

    table_styles = [
        ('FONTNAME', (0,0), (-1,0), f_bold),
        ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (4,0), (4,-1), 'RIGHT'),  # Pénz most már a 4. index (0-tól számolva)
        ('ALIGN', (3,0), (3,-1), 'CENTER'), # Checkbox középre
        ('ALIGN', (6,0), (6,-1), 'CENTER'), # DB középre
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
    ]

    if 'Csoport' in df.columns:
        groups = df['Csoport'].values
        start_idx = None
        for i in range(len(groups)):
            if groups[i] > 0:
                if start_idx is None: start_idx = i
                if i == len(groups) - 1 or groups[i+1] != groups[i]:
                    r_s, r_e = start_idx + 1, i + 1
                    table_styles.append(('BOX', (0, r_s), (-1, r_e), 1.3, colors.black))
                    table_styles.append(('BACKGROUND', (0, r_s), (-1, r_e), colors.Color(0.96, 0.96, 0.96)))
                    start_idx = None

    for i, row in df.iterrows():
        r_full = str(row.get('Rendelés_Full', ''))
        
        # --- ÚJ: Dinamikus szürkítés és félkövérítés logikája ---
        kulonleges = False
        formazott_rendeles = r_full
        
        for n in nap_list:
            n_tag = f"{n}:"
            if n_tag in r_full:
                if n != bazis_nap_rovid:
                    kulonleges = True
                    # Félkövérré tesszük a nem bázis napot (pl. <b>Pé:</b> 1-A)
                    formazott_rendeles = formazott_rendeles.replace(n_tag, f"<b>{n_tag}</b>")

        # Név háttérszínének beállítása (ha különleges nap van a sorban)
        name_bg = colors.Color(0.88, 0.88, 0.88) if kulonleges else None
        if name_bg:
            table_styles.append(('BACKGROUND', (1, i+1), (1, i+1), name_bg))

        prefix = "↑ " if (row.get('Csoport', 0) > 0 and i > 0 and df.iloc[i-1].get('Csoport') == row.get('Csoport')) else ""
        u_name = str(row.get('Ügyintéző', ''))[:45]
        u_id = str(row.get('temp_id', ''))
        
        t_inner = Table([[Paragraph(f"{prefix}{u_name}", styles['NameBold']), Paragraph(f"ID: {u_id}", styles['IDStyle'])]], 
                        colWidths=[70*mm, 22*mm], style=[('LEFTPADDING', (0,0), (-1,-1), 0), ('TOPPADDING', (0,0), (-1,-1), 0)])

        info_flow = [t_inner, Paragraph(str(row.get('Cím', '')), styles['Normal'])]
        
        megj = str(row.get('Megjegyzés', '')).strip()
        if megj and megj.lower() != 'nan':
            info_flow.append(Paragraph(megj, styles['Small']))

        p_raw = str(row.get('Pénz', '')).strip()
        digits_only = "".join(re.findall(r'\d+', p_raw))
        penz_val = p_raw if (digits_only and int(digits_only) > 0) else "" 
        
        table_data.append([
            f"{int(row.get('Sorrend', i+1))}",                   # 0: #
            info_flow,                                           # 1: Név/Cím
            Paragraph(formazott_rendeles, styles['Small']),      # 2: Rendelés
            Checkbox(10),                                        # 3: ☐ (EZ AZ ÚJ HELYE)
            Paragraph(f"<b>{penz_val}</b>", styles['Normal']),   # 4: Pénz
            Paragraph(str(row.get('Telefon', '')), styles['Small']), # 5: Tel
            str(row.get('Összesen', ''))                         # 6: DB
        ])

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(table_styles))
    elements.append(t)
    
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_reg, 7)
        canvas.drawCentredString(A4[0]/2, 5*mm, f"{canvas.getPageNumber()}. oldal")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer
    
def create_raklista_pdf(df, jarat_info, meta_dict): # meta_list helyett meta_dict
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=7 * mm, bottomMargin=12 * mm, leftMargin=8 * mm, rightMargin=8 * mm)
    etlap = st.session_state.get('etlap', {})

    # --- JAVÍTOTT ADATLEKÉRÉS AZ ÚJ DICT-BŐL ---
    ev = meta_dict.get('ev', '')
    het = meta_dict.get('het', '')
    napok = meta_dict.get('nap', '') 
    
    dates_str = f"{ev}. {het}. hét ({napok})"
    # -----------------------------------------

    counts = {}
    # ... (a függvény többi része marad változatlanul)
    for _, r in df.iterrows():
        order_str = str(r.get('Rendelés_Full', ''))
        day_parts = order_str.split('|')
        for part in day_parts:
            prefix = "P" if "Pé:" in part else "Z" if "Szo:" in part else ""
            if not prefix: continue
            found = re.findall(r'(\d+)\s*-\s*([A-Z0-9*+]+)', part)
            for qty, code in found:
                full_key = f"{prefix}_{code.strip().upper()}"
                counts[full_key] = counts.get(full_key, 0) + int(qty)

    # 2. Stílusok finomhangolása
    header_style = ParagraphStyle('H', fontName=f_bold, fontSize=8, alignment=1)
    # Nagyon szűk sorköz (leading), hogy több férjen el
    normal_row_style = ParagraphStyle('NR', fontName=f_reg, fontSize=6.5, leading=7.5)
    star_row_style = ParagraphStyle('SR', fontName=f_bold, fontSize=6.5, leading=7.5)

    data = [[
        Paragraph("<b>NAP</b>", header_style),
        Paragraph("<b>KÓD</b>", header_style),
        Paragraph("<b>DB</b>", header_style),
        Paragraph("<b>[ ]</b>", header_style),
        Paragraph("<b>MEGNEVEZÉS</b>", header_style),
        Paragraph("<b>ÁR</b>", header_style),
        Paragraph("<b>ÖSSZES</b>", header_style)
    ]]

    total_qty = 0
    total_money = 0
    processed_full_keys = set()

    # 3. Táblázat feltöltése
    for etlap_key in etlap.keys():
        for suffix in ["", "*"]:
            current_lookup = f"{etlap_key}{suffix}"
            if current_lookup in counts:
                info = etlap[etlap_key]
                db = counts[current_lookup]
                ar = info.get('ar', 0)
                subtotal = db * ar
                is_starred = "*" in current_lookup

                current_font = f_bold if is_starred else f_reg
                current_p_style = star_row_style if is_starred else normal_row_style

                day_short = "Péntek" if current_lookup.startswith("P") else "Szombat"
                code_label = current_lookup.split('_')[1]

                data.append([
                    Paragraph(day_short, ParagraphStyle('D', fontName=current_font, fontSize=5.5, alignment=1)),
                    Paragraph(code_label, ParagraphStyle('K', fontName=current_font, fontSize=7.5, alignment=1)),
                    Paragraph(f"{db} db", ParagraphStyle('Q', fontName=current_font, fontSize=7.5, alignment=1)),
                    Paragraph("[  ]", ParagraphStyle('CB', fontName=f_reg, fontSize=8, alignment=1)),
                    # Középre zárt checkbox
                    Paragraph(info.get('nev', '---'), current_p_style),
                    Paragraph(f"{ar} Ft", ParagraphStyle('A', fontName=current_font, fontSize=7, alignment=2)),
                    Paragraph(f"{subtotal} Ft", ParagraphStyle('S', fontName=current_font, fontSize=7, alignment=2))
                ])
                total_qty += db
                total_money += subtotal
                processed_full_keys.add(current_lookup)

    # Oszlopszélességek (Összesen: 194mm)
    col_widths = [12 * mm, 15 * mm, 12 * mm, 8 * mm, 105 * mm, 18 * mm, 24 * mm]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # Minimális belső margók (Padding) a sűrűségért
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]))

    # 4. Összesítő rész (Kompakt)
    jutalek = int(total_money * 0.13)
    summary_data = [
        ["", "", "", "", "ÖSSZESEN:", f"{total_qty} db", f"{total_money} Ft"],
        ["", "", "", "", "JUTALÉK (13%):", "", f"{jutalek} Ft"]
    ]
    st_table = Table(summary_data, colWidths=col_widths)
    st_table.setStyle(TableStyle([
        ('FONTNAME', (4, 0), (-1, -1), f_bold),
        ('FONTSIZE', (4, 0), (-1, -1), 8.5),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('ALIGN', (5, 0), (6, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LINEABOVE', (4, 0), (-1, 0), 0.5, colors.black),
    ]))

    # Oldalszámozás
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_reg, 7)
        canvas.drawRightString(200 * mm, 8 * mm, f"{doc.page}. oldal")
        canvas.restoreState()

    elements = [
        Paragraph(f"<b>RAKLISTA ÉS ELSZÁMOLÁS</b>", ParagraphStyle('T', fontName=f_bold, fontSize=11)),
        Paragraph(f"Időszak: {dates_str} | Járat: {jarat_info}",
                  ParagraphStyle('S', fontName=f_reg, fontSize=8.5, spaceAfter=3)),
        t,
        Spacer(1, 3 * mm),
        st_table
    ]

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf
    
    # --- FŐ PROGRAMFUTÁS JAVÍTVA ---
    
    if st.session_state.mdf is not None:
        # Biztosítjuk, hogy legyen Csoport oszlop
        if 'Csoport' not in st.session_state.mdf.columns:
            st.session_state.mdf['Csoport'] = ""

        st.subheader("📦 Adatok ellenőrzése és Sorrendezés")
        
        edited_df = st.data_editor(
            st.session_state.mdf,
            key=f"editor_{st.session_state.get('editor_key', 0)}", 
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "Csoport": st.column_config.TextColumn(
                    "Csoport",
                    help="Azonos jel esetén (pl. '1') a PDF-ben egy keretbe kerülnek.",
                    width="small"
                ),
                "Sorrend": st.column_config.NumberColumn("Sor", format="%.1f", width="small"),
                "Ügyintéző": "Név",
                "Telefon": "Tel",
                "Pénz": "Összeg",
                "Megjegyzés": "Infó"
            }
        )

def main():
    st.set_page_config(page_title="Interfood Label Master", layout="wide")
    register_fonts()

    # 1. SESSION STATE INICIALIZÁLÁSA (Itt tároljuk a futár adatait is)
    if 'mdf' not in st.session_state:
        st.session_state.mdf = None
    if 'meta_data' not in st.session_state:
        st.session_state.meta_data = []
    if 'weights' not in st.session_state:
        st.session_state.weights = {}
    if 'editor_key' not in st.session_state:
        st.session_state.editor_key = 0
    if 'c_n' not in st.session_state:
        st.session_state.c_n = "Szűcs István"
    if 'c_p' not in st.session_state:
        st.session_state.c_p = "+36 20 886 8971"

    # 2. OLDALSÁV (SIDEBAR)
    with st.sidebar:
        st.header("⚙️ Kezelés")
        st.session_state.c_n = st.text_input("Futár Neve", st.session_state.c_n)
        st.session_state.c_p = st.text_input("Telefonszám", st.session_state.c_p)
        st.divider()
        
        # --- KORÁBBI MENTÉS BETÖLTÉSE ---
        st.subheader("📂 Korábbi mentés")
        import_file = st.file_uploader("Exportált CSV visszatöltése", type=['csv'])
        
        if import_file is not None:
            if st.button("📥 CSV BETÖLTÉSE"):
                # Nyers betöltés, nem futtatunk rajta tisztító algoritmust!
                df_imported = pd.read_csv(import_file)
                
                # Biztosítjuk, hogy a Sorrend oszlop szám formátumú legyen
                if 'Sorrend' in df_imported.columns:
                    df_imported['Sorrend'] = pd.to_numeric(df_imported['Sorrend'], errors='coerce').fillna(999)
                
                st.session_state.mdf = df_imported
                st.success("Mentés sikeresen visszatöltve!")
                st.rerun()

        st.divider()

        # 1. A függvény elején (vagy a main elején) adjunk neki egy alapértéket, 
        # hogy ne legyen "Unbound" (ismeretlen)
        meta_auto = {} 
        
        st.subheader("📄 Új PDF-ek")
        up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
        
        if up_files:
            debug_pdf_layout(up_files[0]) 
        
            if st.button("🚀 FELDOLGOZÁS"):
                # MINDENT ide húzunk be a gomb alá:
                meta_auto = extract_all_meta(up_files)
                st.session_state.meta_data = meta_auto
                
                all_rows = []
                with st.spinner("PDF-ek beolvasása..."):
                    for f in up_files:
                        f.seek(0)
                        rows, _ = parse_interfood_pdf(f)
                        if rows:
                            all_rows.extend(rows)

                if all_rows:
                    # Metaadatok kinyerése a mentett állapotból vagy a frissből
                    current_meta = st.session_state.meta_data
                    y = current_meta.get('ev') or current_meta.get('year') or '2026'
                    w = current_meta.get('het') or current_meta.get('week') or '13'
                    
                    # Étlap és összefésülés
                    st.session_state.etlap = get_etlap_dict(y, w) # Elmentjük az étlapot is!
                    
                    df_temp = merge_data(all_rows)
                    
                    if not df_temp.empty:
                        df_temp['Sorrend'] = range(1, len(df_temp) + 1)
                    
                    st.session_state.mdf = df_temp
                    st.success(f"Sikeresen feldolgozva: {len(st.session_state.mdf)} ügyfél.")
                    st.rerun() # Ez most már csak egyszer fut le a végén

    # 3. FŐABLAK MEGJELENÍTÉSE
    if st.session_state.mdf is not None and not st.session_state.mdf.empty:
        df_to_edit = st.session_state.mdf.copy()
        
        # KRITIKUS: Kényszerítjük a 'float' (tizedes) típust, különben a 88.5-ből 88 lesz!
        df_to_edit['Sorrend'] = pd.to_numeric(df_to_edit['Sorrend'], errors='coerce').fillna(999).astype(float)
        
        # Rendezés a táblázat megjelenítése előtt
        df_to_edit = df_to_edit.sort_values(by='Sorrend').reset_index(drop=True)
    
        st.subheader("Szállítási lista")
        
        # Oszloprend beállítása
        all_cols = df_to_edit.columns.tolist()
        if 'Sorrend' in all_cols:
            all_cols.remove('Sorrend')
            new_column_order = ['Sorrend'] + all_cols
        else:
            new_column_order = all_cols
        
        edited_df = st.data_editor(
            df_to_edit,
            column_order=new_column_order,
            column_config={
                "Sorrend": st.column_config.NumberColumn(
                    "Sorrend",
                    help="Írj be tizedest (pl. 88.5), majd nyomj a lenti gombra!",
                    format="%.1f", # Ez mutatja a tizedest a táblázatban!
                    step=0.1,
                ),
                "Pénz": st.column_config.TextColumn("Pénz", disabled=False),
            },
            num_rows="dynamic",
            key=st.session_state.editor_key,
            use_container_width=True
        )
    
        # MENTÉS ÉS ÚJRARANKEZÉS GOMB
        if st.button("💾 SORREND VÉGLEGESÍTÉSE (Újraszámozás)"):
            # Itt már az edited_df-et használjuk, mert a fenti editor már létrehozta
            temp_df = edited_df.copy()
            
            # 1. Számmá alakítás (hogy a tizedesek alapján rendezni tudjunk)
            temp_df['Sorrend'] = pd.to_numeric(temp_df['Sorrend'], errors='coerce').fillna(999)
            
            # 2. Fizikai sorbarendezés
            temp_df.sort_values('Sorrend', inplace=True)
            
            # 3. Újrasorszámozás egész számokkal (1, 2, 3...)
            temp_df['Sorrend'] = range(1, len(temp_df) + 1)
            
            # 4. Mentés a session-be és frissítés
            st.session_state.mdf = temp_df
            st.session_state.editor_key += 1 
            st.success("Sorrend véglegesítve, a lista újra lett sorszámozva!")
            st.rerun()

        st.divider()

        # 3. PDF LETÖLTÉS - Végleges, stabil verzió
        
        # Biztosítjuk, hogy a meta egy szótár legyen
        meta = st.session_state.meta_data if isinstance(st.session_state.meta_data, dict) else {}
        
        # Kiszámoljuk a járatszámokat az új struktúrából
        jaratok_listaja = meta.get('jaratok', [])
        aktualis_jaratok = ", ".join(jaratok_listaja) if jaratok_listaja else "N/A"

        # KITEHETÜNK EGY VISSZAJELZÉST A GOMBOK FÖLÉ:
        st.info(f"Észlelt járatok a PDF-ekből: **{aktualis_jaratok}** | Időpont: **{meta.get('ev', '')}. {meta.get('het', '')}. hét**")

        c1, c2, c3 = st.columns(3)
        
        c1.download_button(
            "📄 ETIKETTEK", 
            create_label_pdf(edited_df, st.session_state.c_n, st.session_state.c_p, meta), # <--- Itt a 'meta' a végén!
            "etikettek.pdf", 
            use_container_width=True
        )
        c2.download_button(
            "📋 MENETTERV", 
            create_manifest_pdf(edited_df, st.session_state.c_n, meta), 
            "menetterv.pdf", use_container_width=True
        )
        c3.download_button(
            "📊 RAKLISTA", 
            create_raklista_pdf(edited_df, aktualis_jaratok, meta), 
            "raklista.pdf", use_container_width=True
        )

        st.divider()
        st.write("### 💾 Táblázat mentése és exportálása")
        
        # Új sor a mentési gomboknak
        save_col1, save_col2 = st.columns(2)

        with save_col1:
            # Fájlnév összeállítása a meta adatokból
            # Pl.: 4002_4003_jarat_2026_03_31.csv
            
            # Járatszámok összefűzése (ha több van, alulvonással)
            jarat_str = "_".join(meta.get('jaratok', ['Ismeretlen']))
            
            # Aktuális dátum formázása
            import datetime
            d_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # Az általad kért szintaktika: Sorrendezés mentés-járatszám-év-hó-nap
            beszedes_filenev = f"Sorrendezes_mentes-{jarat_str}-{d_str}.csv"
            
            csv_data = edited_df.to_csv(index=False, encoding='utf-8-sig')
            
            st.download_button(
                label="📥 KÉSZ TÁBLÁZAT MENTÉSE (CSV)",
                data=csv_data,
                file_name=beszedes_filenev,
                mime='text/csv',
                use_container_width=True
            )

        with save_col2:
            # Itt egy kis emlékeztető vagy állapotjelző
            st.info("A CSV mentése után ezt a fájlt használd a holnapi visszatöltéshez.")

if __name__ == "__main__":
    main()
