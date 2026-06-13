# -*- coding: utf-8 -*-
import re
import pdfplumber
import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# --- GLOBÁLIS REGEX MINTÁK (PDF FELDOLGOZÁSHOZ) ---
PHONE_PAT = r'(\d{2}/\d[\d\s,]*\d)'
# Frissített minta: felismeri a sima (-), az en-dash (–) és az em-dash (—) jeleket is
ORDER_PAT = r'(\d+)\s*[-\u2013\u2014\u2212]\s*([A-Z][A-Z0-9*+]*)'
# Frissített, "szóköz-toleráns" regex
MONEY_PAT = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

# --- 3. FŐ FÜGGVÉNY: PDF BEOLVASÁS ÉS BLOKKOSÍTÁS ---
def parse_interfood_pdf(pdf_file, napi_etlap_kodok):
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
            # 1. Kinyerjük az aktuális oldal szavait
            words = pg.extract_words(x_tolerance=3, y_tolerance=3)
            
            # --- FÜGGŐLEGES SOROMPÓ (Cutoff) BEÁLLÍTÁSA ---
            footer_elements = [
                w for w in words 
                if any(tag in w['text'] for tag in ["Összesítés", "Csilagozott", "Összesen"])
                and w['top'] > pg.height * 0.5
            ]
            
            page_cutoff = min([w['top'] for w in footer_elements]) - 2 if footer_elements else pg.height

            # 2. Horgonyok gyűjtése csak az aktuális oldalról
            anchors = [w for w in words if re.search(r'[HKSCPZ]-\d{5,7}', w['text'])]
            
            for i, anchor in enumerate(anchors):
                if anchor['top'] >= page_cutoff: continue

                # --- 1. ZÓNA ÉS SZÖVEG BEOLVASÁSA ---
                y_top = max(0, anchor['top'] - 12)
                
                if i + 1 < len(anchors):
                    y_bottom = anchors[i+1]['top'] + 5 
                else:
                    y_bottom = min(page_cutoff, anchor['top'] + 180)
                
                if y_bottom <= y_top: 
                    y_bottom = y_top + 60 

                # --- KRITIKUS JAVÍTÁS: page helyett pg-t használunk! ---
                full_row_box = pg.within_bbox((20, y_top, 585, y_bottom))
                raw_text = full_row_box.extract_text() or ""
                lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
                
                # --- 2. AZONOSÍTÁS ÉS NÉV KINYERÉSE (Szigorú kontrollal) ---
                current_id = anchor['text']
                local_customer_name = ""
                name_line_index = -1
                
                for idx, l in enumerate(lines):
                    if current_id in l:
                        # Kivágjuk az ID-t: "Dr. Vincze Ildikó belülre kérem" (vagy "Kovács Bt. / Kovács János")
                        raw_line = l.replace(current_id, "").strip()
                        
                        # Csak addig gyűjtjük a szavakat, amíg NEVET látunk (Nagybetű/Dr/stb)
                        name_parts = []
                        for word in raw_line.split():
                            if word[0].isupper() or word.startswith("Dr.") or word.lower() in ["id.", "ifj.", "özv."]:
                                name_parts.append(word)
                            else:
                                break
                        local_customer_name = " ".join(name_parts)
                        name_line_index = idx
                        break

                # --- 3. SZÉTVÁLOGATÁS (Részleg + Megjegyzés megtartásával) ---
                reszleg_ceg_lista = []
                hosszu_megj_lista = []

                for idx, l_strip in enumerate(lines):
                    # Alap szűrések
                    if any(x in l_strip for x in ["Debrecen", "Ebes", "Hajdú", "Sor", "Ügyfél", "Össz.", "Nyomtatva:"]): 
                        continue
                    if re.search(PHONE_PAT, l_strip) or re.search(MONEY_PAT, l_strip):
                        continue

                    if idx == name_line_index:
                        # Ez a név sora. Ami itt maradt az ID és a Név levágása után, az a Részleg!
                        # Pl: "S-123 ID. Kovács János Részleg" -> "Részleg" marad meg.
                        maradek = l_strip.replace(current_id, "").replace(local_customer_name, "").strip()
                        
                        if len(maradek) > 1:
                            # Ha a maradék kisbetűvel kezdődik (mint a "belülre kérem"), 
                            # akkor az inkább a hosszú megjegyzéshez tartozik, nem cég/részleg név.
                            if maradek[0].islower():
                                hosszu_megj_lista.append(maradek)
                            else:
                                reszleg_ceg_lista.append(maradek)
                    else:
                        # Minden más sor (ami nem a név sora) a hosszú megjegyzésbe megy
                        hosszu_megj_lista.append(l_strip)

                # --- 4. MENTÉS A VÁLTOZÓKBA ---
                megj_resz_1 = " | ".join(reszleg_ceg_lista)
                megj_resz_2 = " | ".join(hosszu_megj_lista)
                
                # Fontos: frissítsük a globális nevet is, ha a későbbi pontoknak kell
                customer_name = local_customer_name
            
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
                        
                        full_text_area = top_text + " " + bottom_text
                        
                        # Telefon felismerése
                        phone_match = re.search(r'(\d{1,2}/\d+)', full_text_area)
                        phone_val = phone_match.group(1).replace(" ", "") if phone_match else ""
                        
                        # --- JAVÍTOTT PÉNZ FELISMERÉS ---
                        # Engedélyezzük a szóközt a mínusz jel után: (-?\s*\d[\d\s]*)\s*Ft
                        # Használjuk a teljes területet, mert a pénz néha elcsúszhat
                        money_match = re.search(r'(-?\s*\d[\d\s]*)\s*Ft', bottom_text if bottom_text else top_text)
                        
                        if money_match:
                            # Kinyerjük a találatot, és töröljük a felesleges szóközöket, DE a mínuszt megtartjuk
                            raw_money = money_match.group(1).replace(" ", "")
                            money_val = f"{raw_money}Ft"
                        else:
                            # Tartalék megoldás: ha nincs Ft, de van szám a végén
                            last_num = re.search(r'(-?\s*\d+)$', (bottom_text.strip() if bottom_text else top_text.strip()))
                            if last_num:
                                money_val = f"{last_num.group(1).replace(' ', '')}Ft"
                            else:
                                money_val = "0Ft"

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

                    # --- 4. RENDELÉS ÉS MEGJEGYZÉS SZÉTVÁLASZTÁSA (DINAMIKUS SZŰRÉS) ---
                    
                    width = page.width 
                    # Visszaállunk a biztos 60%-ra (52.5 / 88), hogy a rendelések eleje ne vesszen el
                    x_start_limit = width * 0.596 
                    x_end_limit = width * 0.91    

                    # 1. KIVÁGÁS: A folyosó szavai (most már a 60%-tól)
                    folyoso_words = sorted([
                        w for w in line_words 
                        if (w['x0'] + w['x1'])/2 >= x_start_limit and (w['x0'] + w['x1'])/2 <= x_end_limit
                    ], key=lambda x: (x['top'], x['x0']))
                    
                    # 2. TISZTÍTÁS: CSAK a kódok kellenek, a telefonszámot és az összesítést kidobjuk!
                    tiszta_elemek = []
                    for w in folyoso_words:
                        txt = w['text'].strip()
                        
                        # --- ÚJ: CSAK ITT ÁLLÍTJUK MEG A RENDELÉSEK GYŰJTÉSÉT ---
                        if any(stop in txt for stop in ["Összesítés:", "Csilagozott", "Összesen:"]):
                            break # Itt megáll, de az ember megmarad!
                        
                        # Ha a szó telefonszám formátumú (pl. 30/1234567), akkor átugorjuk
                        if re.match(r'\d{2}/\d+', txt):
                            continue
                            
                        # Csak azt tartjuk meg, ami kód-szerű
                        if re.search(r'[\d\-\u2013\u2014\u2212A-Z\*]', txt):
                            tiszta_elemek.append(txt)

                    # 3. LEGO-RAGASZTÓ: Összehúzzuk a szétesett darabokat
                    raw_folyoso_text = " ".join(tiszta_elemek)
                    # Itt tüntetjük el a szóközöket: "1 - D14" -> "1-D14"
                    fixed_text = re.sub(r'(\d+)\s*([-\u2013\u2014\u2212])\s*', r'\1\2', raw_folyoso_text)

                    # 4. KERESÉS: "Mindent látó" Erika-biztos gyűjtő
                    # Először a biztonságos Legó-ragasztó
                    raw_orders = re.findall(ORDER_PAT, fixed_text)
                    
                    # Ha a Legó nem talált semmit, nézzük meg a dobozban lévő ÖSSZES szót
                    if not raw_orders:
                        # Az összes szót összefűzzük egy hosszú lánccá
                        box_content = " ".join([w['text'] for w in line_words])
                        # Ebben keressük meg az összes érvényes rendelést
                        potential_orders = re.findall(ORDER_PAT, box_content)
                        
                        # Szűrés: Csak azokat tartjuk meg, amik a sor végén (jobb oldalon) vannak
                        # A házszámokat (13-15) az ORDER_PAT (betűvel kezdődő kód) már eleve kiszűri!
                        raw_orders = potential_orders

                    rendeles_str = ", ".join([f"{q}-{c}" for q, c in raw_orders])
                    
                    # 5. MEGJEGYZÉS: A teljes sorból kivonjuk a már megtalált rendeléseket
                    # Így a megjegyzésben megmarad minden, ami a folyosón kívül volt (vagy amit kidobtunk)
                    full_line_text = " ".join([w['text'] for w in sorted(line_words, key=lambda x: x['x0'])])
                    clean_comment = full_line_text
                    
                    for q, c in raw_orders:
                        # Olyan mintát keresünk, ami rugalmas a szóközökre a törlésnél
                        p = rf'{q}\s*[-\u2013\u2014\u2212]\s*{re.escape(c)}'
                        clean_comment = re.sub(p, '', clean_comment, count=1)
                    
                    # Utolsó simítás: Telefonszám, pénz és ID eltávolítása a megjegyzésből
                    clean_comment = re.sub(PHONE_PAT, '', clean_comment)
                    clean_comment = re.sub(MONEY_PAT, '', clean_comment)
                    clean_comment = re.sub(r'^[S|C|P]-\d+\s+', '', clean_comment)
                    
                    megjegyzes = clean_comment.strip(", ").strip()
                    megjegyzes = re.sub(r'\s+', ' ', megjegyzes).strip()

                    # CÍM meghatározása (v_lines[2] és x40 között)
                    address = " ".join([w['text'] for w in sorted([w for w in row_words if v_lines[2] <= (w['x0']+w['x1'])/2 < x40], key=lambda x: x['x0'])]).strip()

                    # --- DINAMIKUS CÍMTISZTÍTÁS (Frissített verzió) ---
                    if admin_name and address:
                        # 1. Előkészítjük a neveket és a cím szavait
                        name_parts_to_erase = [n.strip(" ,.|/-").lower() for n in admin_name.split() if len(n.strip(" ,.|/-")) > 1]
                        # Hozzáadjuk a listához a tiltott titulusokat is, így a while ciklus ezeket is kitakarítja
                        name_parts_to_erase.extend(["dr", "dr.", "idősb", "ifj", "id", "ifj."])
                        
                        address_parts = address.split()
                        
                        # 2. Hátulról előre haladva levágjuk a névmaradványokat ÉS a titulusokat
                        # A ciklus addig fut, amíg a cím utolsó szava szerepel a "tiltólistán"
                        while address_parts:
                            last_word_clean = address_parts[-1].strip(" ,.|/-").lower()
                            if last_word_clean in name_parts_to_erase:
                                address_parts.pop()
                            else:
                                break # Ha olyan szót találunk, ami nem név/titulus, megállunk
                        
                        # 3. Cím visszaállítása
                        address = " ".join(address_parts).strip(" ,.|/-")

                    # --- 1. HORGONYOK ELŐKÉSZÍTÉSE ---
                    raw_line = line_text_full 
                    megj_resz_1 = "" 
                    megj_resz_2 = ""
                    parts = []  # <--- IDE KERÜLJÖN

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

                    # --- 8. ÖSSZEFŰZÉS ÉS TISZTÍTÁS (Végleges, Ildikó-biztos verzió) ---
                    all_notes = []
                    
                    # 1. Megjegyzés part 1 (Cégnév, részleg az ID mellől)
                    if megj_resz_1.strip():
                        all_notes.append(megj_resz_1.strip())
                    
                    # 2. Megjegyzés part 2 (Hosszú instrukciók új sorokból - EZ HIÁNYZOTT!)
                    if megj_resz_2.strip():
                        all_notes.append(megj_resz_2.strip())
                    
                    # 3. Egyéb gyűjtött részek (pl. Ügyintéző cellából vagy cím végéről)
                    all_notes.extend(parts)

                    # Duplikátumok szűrése az eredeti sorrend megtartásával
                    seen = set()
                    final_parts = []
                    for n in all_notes:
                        n_clean = n.strip()
                        if not n_clean:
                            continue
                        # Kis/nagybetű különbség ne okozzon duplázást
                        if n_clean.lower() not in seen:
                            final_parts.append(n_clean)
                            seen.add(n_clean.lower())

                    # Összefűzés elegáns elválasztóval
                    clean_customer = " | ".join(final_parts)

                    # Junk (felesleges) szavak és mondatok kitakarítása
                    junk_list = [
                        "Felnőtt", "Nyugdíjas", "Gyerek", "Vendég", "Dr.", "idősb", "ifj",
                        "Csilagozott betűnél kiegészítő is van!!!",
                        "Csilagozott betűnél kiegészítő is van"
                    ]
                    
                    for junk in junk_list:
                        # Csak akkor cseréljük, ha pontos egyezés van vagy határolt szó, 
                        # hogy ne rontson bele értelmes szavakba
                        clean_customer = clean_customer.replace(junk, "")

                    # Végső kozmetika: dupla szóközök és felesleges írásjelek eltávolítása a szélekről
                    clean_customer = re.sub(r'\s+', ' ', clean_customer)
                    # Tisztítjuk a maradék elválasztókat, amik a junk törlése után maradtak
                    clean_customer = clean_customer.strip(" -/|.,")
                    
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

                    # --- 5. INTELLIGENS ÖSSZEFŰZÉS ÉS ÉTLAP ALAPJÚ TAKARÍTÁS ---
                    final_note_parts = []
                    r_clean = reszleg.strip(" ,.-/|*")
                    e_clean = extra_instructions.strip(" ,.-/|*")
                    
                    # --- OKOS TAKARÍTÁS: Itt használjuk a kapott napi_etlap_kodok-at ---
                    # Sorba rendezzük hosszuk szerint csökkenőben (D14 előbb, mint D1)
                    for kod in sorted(napi_etlap_kodok, key=len, reverse=True):
                        if len(kod) > 1:
                            # HOSSZÚ KÓDOK (pl. D14, REPA, E2K):
                            # Töröljük, ha különálló egység (szóhatár: szóköz, kötőjel vagy sor vége)
                            # A minta felismeri: "1-D14", "1 - D14", vagy simán "D14"
                            minta = r'\d*\s*[-\u2013\u2014\u2212]?\s*\b' + re.escape(kod) + r'\b'
                            e_clean = re.sub(minta, '', e_clean)
                        else:
                            # RÖVID KÓDOK (pl. A, P, I, C):
                            # CSAK akkor töröljük, ha van előtte egy szám és egy kötőjel! (pl. 1-A)
                            # Így a nevekben (pl. Attila) lévő betűk biztonságban maradnak.
                            minta = r'\d+\s*[-\u2013\u2014\u2212]\s*\b' + re.escape(kod) + r'\b'
                            e_clean = re.sub(minta, '', e_clean)

                    # Utólagos szemétmentesítés a törlés után maradt jeleknek
                    e_clean = re.sub(r'[-\u2013\u2014\u2212]{2,}', '-', e_clean) # Dupla kötőjel -> sima
                    e_clean = e_clean.replace('  ', ' ').strip(" ,.-/|*")
                    # --- TAKARÍTÁS VÉGE ---

                    # Most már a megtisztított e_clean-t adjuk hozzá a megjegyzéshez
                    if r_clean and len(r_clean) > 1:
                        final_note_parts.append(r_clean)
                    if e_clean and len(e_clean) > 1:
                        # Ellenőrizzük, hogy az extra ne legyen ugyanaz, mint a részleg
                        if not final_note_parts or e_clean.lower() != final_note_parts[0].lower():
                            final_note_parts.append(e_clean)
                    
                    full_note = " | ".join(final_note_parts)
                    
                    # --- 6. UTOLSÓ FINOMHANGOLÁS (JAVÍTOTT, HIBAMENTES) ---
                    
                    # 1. OPTIPONT ÉS ÖSSZESÍTŐK AZONNALI TÖRLÉSE
                    full_note = re.sub(r'(Összesítés:|Csillagozott|Összesen:).*', '', full_note, flags=re.IGNORECASE)

                    # 2. MAGÁNYOS ELŐHÍVÓK IRTÁSA (Fix cserékkel a legbiztosabb)
                    # Előbb a fix elválasztós formák (Erzsébet-ügy megoldása)
                    for num in ["20", "30", "70", "06"]:
                        full_note = full_note.replace(f"| {num} |", "|")
                        full_note = full_note.replace(f"|{num}|", "|")
                        full_note = full_note.replace(f"| {num}", "|")
                        full_note = full_note.replace(f"{num} |", "|")
                    
                    # 3. MAGÁNYOS SZÁMOK TÖRLÉSE (Regex hiba nélkül)
                    # Olyan 20, 30, 70, 06 amiket szóköz vesz körül, de NEM telefonszámok (nincs / utánuk)
                    # A \b (szóhatár) használata biztonságosabb itt
                    full_note = re.sub(r'\b(20|30|70|06)\b(?!\s*/|\s*\d)', '', full_note)

                    # 4. NÉV-DUPLIKÁCIÓ (Globiz-effektus)
                    if "|" in full_note:
                        parts = [p.strip() for p in full_note.split("|")]
                        if len(parts) > 1 and parts[1].lower().startswith(parts[0].lower()):
                            parts[1] = parts[1][len(parts[0]):].strip()
                        # dict.fromkeys kiszűri a duplikált blokkokat
                        full_note = " | ".join(dict.fromkeys([p for p in parts if p]))

                    # 5. ÍRÁSJEL-HALMOZÓDÁS ÉS ÁRVA VESSZŐK
                    # Kenézy-féle vesszőtenger: több vessző/pont/szóköz -> egy szóköz
                    full_note = re.sub(r'([ ,.]*[,.][ ,.]*){2,}', ' ', full_note)
                    # Pipeline melletti szemét takarítása
                    full_note = re.sub(r'\|\s*[,. ]+', '| ', full_note)
                    full_note = re.sub(r'[,. ]+\s*\|', ' |', full_note)

                    # 6. PIPELINE POLÍROZÁS ÉS VÉGSŐ TISZTÍTÁS
                    # Több pipeline egymás után -> egy pipeline
                    full_note = re.sub(r'(\|[ \t]*)+', ' | ', full_note)
                    # Dupla szóközök ki
                    full_note = re.sub(r'\s+', ' ', full_note)
                    # Szélekről minden maradék le (vessző, pont, pipeline, perjel)
                    full_note = full_note.strip(" ,.-/|*")
                    
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

def extract_all_meta(pdf_files):
    all_meta = {'jaratok': [], 'ev': '', 'het': '', 'nap': '', 'datum_iso': '', 'api_datum_kulcs': ''}
    
    jarat_re = re.compile(r'(\d{2,4})\.\s*járat|Nyomtatta:\s*(\d{2,4})')
    
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

            # 3. A NAPOK kinyerése
            if not all_meta['nap']:
                nap_m = re.search(r'Nap:\s*(.*?)(?=InterFood|$)', text, re.DOTALL)
                if nap_m:
                    nap_raw = nap_m.group(1).strip()
                    all_meta['nap'] = nap_raw.rstrip(',')
    
    all_meta['jaratok'].sort()
    
    # --- DÁTUM KISZÁMÍTÁSA FIXEN AZ ÉV, HÉT ÉS NAP ALAPJÁN ---
    if all_meta['ev'] and all_meta['het'] and all_meta['nap']:
        try:
            nap_tisztitott = all_meta['nap'].lower().strip()
            nap_szamok = {
                'hetfo': 1, 'hétfő': 1,
                'kedd': 2,
                'szerda': 3,
                'csutortok': 4, 'csütörtök': 4,
                'pente': 5, 'pénte': 5, 'pentek': 5, 'péntek': 5,
                'szombat': 6,
                'vasarnap': 7, 'vasárnap': 7
            }
            
            nap_szoveg_kulcs = next((k for k in nap_szamok if k in nap_tisztitott), None)
            
            if nap_szoveg_kulcs:
                nap_szama = nap_szamok[nap_szoveg_kulcs]
                target_year = int(all_meta['ev'])
                target_week = int(all_meta['het'])
                
                # Kiszámoljuk a pontos naptári napot az ISO év és hét alapján (%G-%V-%u)
                kalkulalt_datum = datetime.strptime(f"{target_year}-{target_week}-{nap_szama}", "%G-%V-%u")
                
                # Mentjük a megfelelő változókba a meta szótáron belül
                all_meta['datum_iso'] = kalkulalt_datum.strftime("%Y-%m-%d")
                all_meta['api_datum_kulcs'] = kalkulalt_datum.strftime("%Y.%m.%d.")
        except Exception as e:
            pass

    return all_meta

