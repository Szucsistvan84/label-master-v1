# -*- coding: utf-8 -*-
import re
import pdfplumber
import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# --- GLOBÁLIS REGEX MINTÁK (PDF FELDOLGOZÁSHOZ - FRISSÍTVE A HIBÁS PONTOZÁS ELLEN) ---
PHONE_PAT = r'(\d{2}/[\.\s]*\d[\d\s,\.]*\d)'
ORDER_PAT = r'(\d+)\s*[-\u2013\u2014\u2212]\s*([A-Z][A-Z0-9*+]*)'
MONEY_PAT = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

# --- FŐ FÜGGVÉNY: PDF BEOLVASÁS ÉS BLOKKOSÍTÁS ---
def parse_interfood_pdf(pdf_file, napi_etlap_kodok):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jaratok': []}
    
    stop_words = [
        "Összesítés:", 
        "Csilagozott betűnél", 
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

        # Kinyerjük a napot az első oldalról gyorsan, hogy a sorszám-ragadásos horgonyoknál tudjuk a napot
        first_page_text = pdf.pages[0].extract_text() or ""
        nap_m = re.search(r'Nap:\s*([a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]+)', first_page_text)
        detect_day = nap_m.group(1).strip().lower() if nap_m else ""

        for pg in pdf.pages:
            words = pg.extract_words(x_tolerance=3, y_tolerance=3)
            
            # Horgonyok gyűjtése (Sorszám-ragadás elleni védelemmel)
            anchors = [w for w in words if re.search(r'\b[A-Za-z0-9]{1,3}-\d{5,7}\b', w['text'])]
            
            # --- JAVÍTOTT, DINAMIKUS LÁBLÉC-SOROMPÓ (MINDEN LAP ALÁN MEGBÍZHATÓAN LEZÁR) ---
            # Csak az utolsó érvényes horgony alatt keresünk lábléc elemeket, így a rövid lapokon is tökéletes
            last_anchor_top = max([a['top'] for a in anchors]) if anchors else 120
            
            footer_elements = []
            for w in words:
                txt = w['text']
                # Ékezet- és kódolás-immunis részstring alapú lábléc szűrő
                if any(tag.lower() in txt.lower() for tag in ["Összesítés", "osszesites", "Csilagozott", "csillagozott", "Összesen", "osszesen", "nyomtatta", "oldal", "menetlevél", "menetlevel"]) and w['top'] > last_anchor_top:
                    footer_elements.append(w)
            
            page_cutoff = min([w['top'] for w in footer_elements]) - 2 if footer_elements else pg.height

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

                full_row_box = pg.within_bbox((20, y_top, 585, y_bottom))
                raw_text = full_row_box.extract_text() or ""
                lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
                
                # --- 2. AZONOSÍTÁS ÉS NÉV KINYERÉSE ---
                current_id = anchor['text']
                local_customer_name = ""
                name_line_index = -1
                
                for idx, l in enumerate(lines):
                    if current_id in l:
                        raw_line = l.replace(current_id, "").strip()
                        
                        name_parts = []
                        for word in raw_line.split():
                            if word[0].isupper() or word.startswith("Dr.") or word.lower() in ["id.", "ifj.", "özv."]:
                                name_parts.append(word)
                            else:
                                break
                        local_customer_name = " ".join(name_parts)
                        name_line_index = idx
                        break

                # --- 3. SZÉTVÁLOGATÁS ---
                reszleg_ceg_lista = []
                hosszu_megj_lista = []

                for idx, l_strip in enumerate(lines):
                    if any(x in l_strip for x in ["Debrecen", "Ebes", "Hajdú", "Nyomtatva:"]): 
                        continue
                    if re.search(PHONE_PAT, l_strip) or re.search(MONEY_PAT, l_strip):
                        continue

                    if idx == name_line_index:
                        maradek = l_strip.replace(current_id, "").replace(local_customer_name, "").strip()
                        if len(maradek) > 1:
                            if maradek[0].islower():
                                hosszu_megj_lista.append(maradek)
                            else:
                                reszleg_ceg_lista.append(maradek)
                    else:
                        hosszu_megj_lista.append(l_strip)

                megj_resz_1 = " | ".join(reszleg_ceg_lista)
                megj_resz_2 = " | ".join(hosszu_megj_lista)
                customer_name = local_customer_name
            
                next_anchor_top = anchors[i+1]['top'] - 5 if i+1 < len(anchors) else page_cutoff
                y_bottom = min(next_anchor_top, page_cutoff)
                
                line_words = [w for w in words if y_top <= w['top'] < y_bottom]
                
                def get_col_text(x_min, x_max):
                    sel = [w for w in line_words if x_min <= (w['x0'] + w['x1'])/2 < x_max]
                    sel.sort(key=lambda x: (x['top'], x['x0']))
                    return " ".join([w['text'] for w in sel])

                full_id_area = get_col_text(v_lines[0], v_lines[2])
                id_match = re.search(r'([A-Za-z0-9]{1,3}-\d{5,7})', full_id_area)
                
                # --- 0. BIZTONSÁGOS, KONTEXTUS-ALAPÚ FEJLÉC ÉS LÁBLÉC SZŰRÉS ---
                line_text_full = " ".join([w['text'] for w in line_words])
                
                header_keywords = ["sor", "ügyfél", "ügyintéző", "telefon", "rendelése", "össz"]
                matched_header_words = sum(1 for kw in header_keywords if kw in line_text_full.lower())
                
                if matched_header_words >= 3:
                    continue 
                
                tiltott_szavak = ["járat", "menetterve", "Év:", "Hét:", "Nap:", "InterFood", "oldal", "Nyomtatva", "Összesítés:", "Csilagozott", "Összesen:"]
                if any(stop in line_text_full for stop in tiltott_szavak):
                    if not re.search(r'[A-Za-z0-9]{1,3}-\d{5,7}', line_text_full):
                        continue

                if id_match:
                    full_id = id_match.group(1)
                    prefix = full_id.split('-')[0]
                    
                    if prefix.isdigit():
                        nap_prefix_map = {
                            'hétfő': 'H', 'hetfo': 'H', 'kedd': 'K', 'szerda': 'S',
                            'csütörtök': 'C', 'csutortok': 'C', 'péntek': 'P', 'pentek': 'P', 'szombat': 'Z'
                        }
                        prefix = next((v for k, v in nap_prefix_map.items() if k in detect_day), "S")
                        full_id = f"{prefix}-{full_id.split('-')[-1]}"

                    W = page.width
                    x40 = (40 / 88) * W
                    x52_5 = (52.5 / 88) * W
                    
                    y_anchor = (anchor['top'] + anchor['bottom']) / 2
                    row_words = [w for w in line_words if abs(((w['top'] + w['bottom']) / 2) - y_anchor) < 8]

                    # --- 2. TELEFON ÉS PÉNZ (PONTOZÁST TISZTÍTÓ LOGIKÁVAL) ---
                    tel_money_words = sorted([w for w in row_words if x40 <= (w['x0'] + w['x1'])/2 < x52_5], key=lambda w: w['top'])
                    
                    phone_val, money_val = "", "0Ft"
                    if tel_money_words:
                        first_y = tel_money_words[0]['top']
                        top_row = [w for w in tel_money_words if abs(w['top'] - first_y) < 4]
                        bottom_row = [w for w in tel_money_words if w not in top_row]
                        top_text = " ".join([w['text'] for w in sorted(top_row, key=lambda w: w['x0'])])
                        bottom_text = " ".join([w['text'] for w in sorted(bottom_row, key=lambda w: w['x0'])])
                        
                        full_text_area = top_text + " " + bottom_text
                        phone_match = re.search(PHONE_PAT, full_text_area)
                        phone_val = phone_match.group(1).replace(" ", "").replace(".", "") if phone_match else ""
                        
                        money_match = re.search(r'(-?\s*\d[\d\s]*)\s*Ft', bottom_text if bottom_text else top_text)
                        if money_match:
                            raw_money = money_match.group(1).replace(" ", "")
                            money_val = f"{raw_money}Ft"
                        else:
                            last_num = re.search(r'(-?\s*\d+)$', (bottom_text.strip() if bottom_text else top_text.strip()))
                            if last_num:
                                money_val = f"{last_num.group(1).replace(' ', '')}Ft"
                            else:
                                money_val = "0Ft"

                    # --- ÜGYINTÉZŐ KERESÉSE (SZIGORÚ NÉV-SZŰRÉS) ---
                    x_start_admin = (38 / 88) * W
                    x_end_admin = (54 / 88) * W
                    
                    admin_candidates = [w for w in line_words if x_start_admin <= (w['x0'] + w['x1'])/2 < x_end_admin]
                    y_start = (anchor['top'] + anchor['bottom']) / 2
                    raw_name_parts = []
                    stop_keywords = ["Összesen", "Összesítés", "Össz"]
                    
                    for w in sorted(admin_candidates, key=lambda x: (x['top'], x['x0'])):
                        t_clean = w['text'].strip()
                        if any(stop.lower() in t_clean.lower() for stop in stop_keywords):
                            break
                        if abs(w['top'] - y_start) < 35:
                            if w['x1'] > x_end_admin * 1.02 and len(t_clean) < 6:
                                continue
                            if "Ft" in t_clean: continue
                            if "/" in t_clean and any(c.isdigit() for c in t_clean): continue
                            if re.search(r'\d-[A-Z]', t_clean): continue
                            if t_clean.isdigit() and len(t_clean) < 4: continue
                            
                            # SZIGORÚ JAVÍTOTT NÉV-SZŰRÉS (Csak nagybetűs szavak)
                            if not (t_clean[0].isupper() or t_clean.startswith("Dr.") or t_clean.lower() in ["id.", "ifj.", "özv."]):
                                continue
                                
                            raw_name_parts.append(w)

                    full_raw_text = " ".join([p['text'] for p in sorted(raw_name_parts, key=lambda x: (x['top'], x['x0']))])
                    clean_name = full_raw_text.replace("*", "")
                    clean_name = re.sub(r'\d+', '', clean_name)
                    clean_name = re.sub(r'-[A-Z0-9]{1,3}\b', '', clean_name)
                    
                    junk_words = ["közöt", "között", "köz", "D", "S", "adag", "db"]
                    final_parts = []
                    for part in clean_name.split():
                        p_stripped = part.strip(" ,.|/-")
                        if p_stripped.lower() in [j.lower() for j in junk_words]:
                            continue
                        if len(p_stripped) == 1 and not p_stripped.endswith('.'):
                            continue
                        final_parts.append(part)

                    admin_name = " ".join(final_parts).strip(" -/|.,*")
                    admin_name = " ".join(admin_name.split())

                    # --- 4. RENDELÉS ÉS MEGJEGYZÉS SZÉTVÁLASZTÁSA ---
                    width = page.width 
                    x_start_limit = width * 0.596 
                    x_end_limit = width * 0.91    

                    folyoso_words = sorted([
                        w for w in line_words 
                        if (w['x0'] + w['x1'])/2 >= x_start_limit and (w['x0'] + w['x1'])/2 <= x_end_limit
                    ], key=lambda x: (x['top'], x['x0']))
                    
                    tiszta_elemek = []
                    for w in folyoso_words:
                        txt = w['text'].strip()
                        if any(stop in txt for stop in ["Összesítés:", "Csilagozott", "Összesen:"]):
                            break
                        if re.match(r'\d{2}/\d+', txt):
                            continue
                        if re.search(r'/[\d\-\u2013\u2014\u2212A-Z\*]', txt):
                            tiszta_elemek.append(txt)

                    raw_folyoso_text = " ".join(tiszta_elemek)
                    fixed_text = re.sub(r'(\d+)\s*([-\u2013\u2014\u2212])\s*', r'\1\2', raw_folyoso_text)

                    raw_orders = re.findall(ORDER_PAT, fixed_text)
                    if not raw_orders:
                        box_content = " ".join([w['text'] for w in line_words])
                        potential_orders = re.findall(ORDER_PAT, box_content)
                        raw_orders = potential_orders

                    rendeles_str = ", ".join([f"{q}-{c}" for q, c in raw_orders])
                    
                    full_line_text = " ".join([w['text'] for w in sorted(line_words, key=lambda x: x['x0'])])
                    clean_comment = full_line_text
                    
                    for q, c in raw_orders:
                        p = rf'{q}\s*[-\u2013\u2014\u2212]\s*{re.escape(c)}'
                        clean_comment = re.sub(p, '', clean_comment, count=1)
                    
                    clean_comment = re.sub(PHONE_PAT, '', clean_comment)
                    clean_comment = re.sub(MONEY_PAT, '', clean_comment)
                    clean_comment = re.sub(r'^[S|C|P]-\d+\s+', '', clean_comment)
                    
                    megjegyzes = clean_comment.strip(", ").strip()
                    megjegyzes = re.sub(r'\s+', ' ', megjegyzes).strip()

                    # CÍM meghatározása (v_lines[2] és x40 között)
                    address = " ".join([w['text'] for w in sorted([w for w in row_words if v_lines[2] <= (w['x0']+w['x1'])/2 < x40], key=lambda x: x['x0'])]).strip()

                    if admin_name and address:
                        name_parts_to_erase = [n.strip(" ,.|/-").lower() for n in admin_name.split() if len(n.strip(" ,.|/-")) > 1]
                        name_parts_to_erase.extend(["dr", "dr.", "idősb", "ifj", "id", "ifj."])
                        address_parts = address.split()
                        
                        while address_parts:
                            last_word_clean = address_parts[-1].strip(" ,.|/-").lower()
                            if last_word_clean in name_parts_to_erase:
                                address_parts.pop()
                            else:
                                break
                        address = " ".join(address_parts).strip(" ,.|/-")

                    raw_line = line_text_full 
                    megj_resz_1 = "" 
                    megj_resz_2 = ""
                    parts = []  

                    id_pattern = r'[A-Za-z0-9]{1,3}-\d{6}'
                    id_match = re.search(id_pattern, raw_line)
                    working_line = raw_line
                    if id_match:
                        working_line = raw_line[id_match.start():]

                    phone_for_clean = ""
                    p_match = re.search(PHONE_PAT, working_line)
                    if p_match: phone_for_clean = p_match.group(1)

                    money_for_clean = ""
                    m_match = re.search(MONEY_PAT, working_line)
                    if m_match: money_for_clean = m_match.group(1)

                    address_for_clean = ""
                    city_match = re.search(r'\b\d{4}\b', working_line)
                    if city_match:
                        start_idx = city_match.start()
                        end_pat = f"{re.escape(phone_for_clean)}|{re.escape(money_for_clean)}|Ft|{ORDER_PAT}"
                        end_match = re.search(end_pat, working_line[start_idx:])
                        if end_match:
                            address_for_clean = working_line[start_idx : start_idx + end_match.start()].strip()
                        else:
                            address_for_clean = working_line[start_idx:].strip()

                    line_words_sorted = sorted(line_words, key=lambda x: (round(x['top'] / 3) * 3, x['x0']))
                    full_block_text = " ".join([w['text'] for w in line_words_sorted])
                    
                    id_match_context = re.search(id_pattern, full_block_text)
                    working_context = full_block_text[id_match_context.start():] if id_match_context else full_block_text

                    megj_resz_1 = "" 
                    megj_resz_2 = "" 

                    clean_context = re.sub(ORDER_PAT, '', working_context)
                    clean_context = re.sub(MONEY_PAT, '', clean_context)
                    if 'phone_val' in locals() and phone_val:
                        clean_context = clean_context.replace(phone_val, "")

                    # --- ZIP-CODE ANCHOR LOCK ---
                    addr_zip_match = re.search(r'\b\d{4}\b', address)
                    if addr_zip_match:
                        target_zip = addr_zip_match.group(0)
                        zip_match = re.search(rf'\b{target_zip}\b', clean_context)
                    else:
                        zip_match = re.search(r'\b\d{4}\b', clean_context)

                    if zip_match:
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

                    if address in clean_context:
                        anchor_pos = clean_context.find(address) + len(address)
                        after_address = clean_context[anchor_pos:].strip()
                        end_m = re.search(re.escape(phone_val), after_address)
                        megj_resz_2 = after_address[:end_m.start()].strip() if end_m else after_address

                    all_notes = []
                    if megj_resz_1.strip():
                        all_notes.append(megj_resz_1.strip())
                    if megj_resz_2.strip():
                        all_notes.append(megj_resz_2.strip())
                    all_notes.extend(parts)

                    seen = set()
                    final_parts = []
                    for n in all_notes:
                        n_clean = n.strip()
                        if not n_clean: continue
                        if n_clean.lower() not in seen:
                            final_parts.append(n_clean)
                            seen.add(n_clean.lower())

                    clean_customer = " | ".join(final_parts)

                    # --- JUNK LIST CUSTOMER ---
                    junk_list = [
                        "Felnőtt", "Nyugdíjas", "Gyerek", "Vendég", "Dr.", "idősb", "ifj",
                        "Csilagozott betűnél kiegészítő is van!!!",
                        "Csilagozott betűnél kiegészítő is van"
                    ]
                    
                    for junk in junk_list:
                        clean_customer = clean_customer.replace(junk, "")

                    clean_customer = re.sub(r'\s+', ' ', clean_customer)
                    clean_customer = clean_customer.strip(" -/|.,")
                    
                    reszleg = ""
                    extra_instructions = clean_customer
                    if "/" in clean_customer:
                        c_parts = clean_customer.split("/")
                        potential_reszleg = c_parts[0].strip()
                        if admin_name and potential_reszleg.lower() != admin_name.lower():
                            reszleg = potential_reszleg
                    
                    if reszleg: extra_instructions = extra_instructions.replace(reszleg, "")
                    if admin_name:
                        for n_part in admin_name.split():
                            if len(n_part) > 2:
                                extra_instructions = re.sub(rf'\b{re.escape(n_part)}\b', '', extra_instructions, flags=re.IGNORECASE)

                    extra_instructions = extra_instructions.replace("/", "").strip(" -/|.,")

                    clean_customer = re.sub(r'\b(20|30|70)\b(?![/\d])', '', clean_customer)

                    if admin_name:
                        clean_customer = re.sub(rf'\b{re.escape(admin_name)}\b', '', clean_customer, flags=re.IGNORECASE)
                        for name_part in admin_name.split():
                            if len(name_part) > 2:
                                clean_customer = re.sub(rf'\b{re.escape(name_part)}\b', '', clean_customer, flags=re.IGNORECASE)

                    clean_customer = re.sub(r'[,.;:|*]{2,}', ' ', clean_customer)

                    reszleg = ""
                    extra_instructions = clean_customer
                    if "/" in clean_customer:
                        if not re.search(r'\d/\d', clean_customer):
                            c_parts = clean_customer.split("/")
                            reszleg = c_parts[0].strip()
                            extra_instructions = "/".join(c_parts[1:]).strip()

                    final_note_parts = []
                    r_clean = reszleg.strip(" ,.-/|*")
                    e_clean = extra_instructions.strip(" ,.-/|*")
                    
                    for kod in sorted(napi_etlap_kodok, key=len, reverse=True):
                        if len(kod) > 1:
                            minta = r'\d*\s*[-\u2013\u2014\u2212]?\s*\b' + re.escape(kod) + r'\b'
                            e_clean = re.sub(minta, '', e_clean)
                        else:
                            minta = r'\d+\s*[-\u2013\u2014\u2212]\s*\b' + re.escape(kod) + r'\b'
                            e_clean = re.sub(minta, '', e_clean)

                    e_clean = re.sub(r'[-\u2013\u2014\u2212]{2,}', '-', e_clean)
                    e_clean = e_clean.replace('  ', ' ').strip(" ,.-/|*")

                    if r_clean and len(r_clean) > 1:
                        final_note_parts.append(r_clean)
                    if e_clean and len(e_clean) > 1:
                        if not final_note_parts or e_clean.lower() != final_note_parts[0].lower():
                            final_note_parts.append(e_clean)
                    
                    full_note = " | ".join(final_note_parts)
                    
                    # --- GOLYÓÁLLÓ AUTODETECT / FALLBACK SAFETY NET (EMESE KÓDJÁNAK MENTÉSE) ---
                    if not full_note or len(full_note.strip()) < 3:
                        raw_comment_parts = []
                        kk_match = re.search(r'\b(kcs|kk|kapukód|kapukod|kulcs)\b.*?(\d+[a-zA-Z0-9]*)', working_context, flags=re.IGNORECASE)
                        if kk_match:
                            start_pos = max(0, kk_match.start() - 5)
                            raw_comment_parts.append(working_context[start_pos : kk_match.end() + 15].strip(" ,.-/|*"))
                        
                        if raw_comment_parts:
                            full_note = " | ".join(raw_comment_parts)
                            if admin_name:
                                full_note = re.sub(rf'\b{re.escape(admin_name)}\b', '', full_note, flags=re.IGNORECASE)
                                for name_part in admin_name.split():
                                    if len(name_part) > 2:
                                        full_note = re.sub(rf'\b{re.escape(name_part)}\b', '', full_note, flags=re.IGNORECASE)
                            full_note = re.sub(ORDER_PAT, '', full_note)
                            full_note = re.sub(MONEY_PAT, '', full_note)
                            full_note = re.sub(r'\s+', ' ', full_note).strip(" ,.-/|*")

                    full_note = re.sub(r'(Összesítés:|Csillagozott|Összesen:).*', '', full_note, flags=re.IGNORECASE)

                    for num in ["20", "30", "70", "06"]:
                        full_note = full_note.replace(f"| {num} |", "|")
                        full_note = full_note.replace(f"|{num}|", "|")
                        full_note = full_note.replace(f"| {num}", "|")
                        full_note = full_note.replace(f"{num} |", "|")
                    
                    full_note = re.sub(r'\b(20|30|70|06)\b(?!\s*/|\s*\d)', '', full_note)

                    if "|" in full_note:
                        parts = [p.strip() for p in full_note.split("|")]
                        if len(parts) > 1 and parts[1].lower().startswith(parts[0].lower()):
                            parts[1] = parts[1][len(parts[0]):].strip()
                        full_note = " | ".join(dict.fromkeys([p for p in parts if p]))

                    full_note = re.sub(r'([ ,.]*[,.][ ,.]*){2,}', ' ', full_note)
                    full_note = re.sub(r'\|\s*[,. ]+', '| ', full_note)
                    full_note = re.sub(r'[,. ]+\s*\|', ' |', full_note)
                    full_note = re.sub(r'(\|[ \t]*)+', ' | ', full_note)
                    full_note = re.sub(r'\s+', ' ', full_note)
                    full_note = full_note.strip(" ,.-/|*")
                    
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
            
            for match in jarat_re.finditer(text):
                j_num = match.group(1) or match.group(2)
                if j_num and j_num not in all_meta['jaratok']:
                    all_meta['jaratok'].append(j_num)
            
            if not all_meta['ev']:
                ev_m = re.search(r'Év:\s*(\d{4})', text)
                if ev_m: all_meta['ev'] = ev_m.group(1)

            if not all_meta['het']:
                het_m = re.search(r'Hét:\s*(\d{1,2})', text)
                if het_m: all_meta['het'] = het_m.group(1)

            if not all_meta['nap']:
                nap_m = re.search(r'Nap:\s*(.*?)(?=InterFood|$)', text, re.DOTALL)
                if nap_m:
                    nap_raw = nap_m.group(1).strip()
                    all_meta['nap'] = nap_raw.rstrip(',')
    
    all_meta['jaratok'].sort()
    
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
                kalkulalt_datum = datetime.strptime(f"{target_year}-{target_week}-{nap_szama}", "%G-%V-%u")
                all_meta['datum_iso'] = kalkulalt_datum.strftime("%Y-%m-%d")
                all_meta['api_datum_kulcs'] = kalkulalt_datum.strftime("%Y.%m.%d.")
        except Exception as e:
            pass

    return all_meta

def load_all_names(sheet_df):
    all_names = set()
    titulusok = {"Dr.", "id.", "ifj.", "özv.", "dr.", "vitéz"}
    all_names.update(titulusok)
    
    if sheet_df is not None:
        if 'Családnév' in sheet_df.columns:
            csalad_nevek = sheet_df['Családnév'].dropna().unique()
            all_names.update([str(n).strip() for n in csalad_nevek if str(n).strip()])
            
        if 'Keresztnév' in sheet_df.columns:
            kereszt_nevek = sheet_df['Keresztnév'].dropna().unique()
            for n in kereszt_nevek:
                nev = str(n).strip()
                if nev:
                    all_names.add(nev)
                    all_names.add(nev + "né")
    return all_names

def split_name_logic(raw_text, name_db):
    if not raw_text: return "", ""
    words = raw_text.split()
    name_parts = []
    comment_parts = []
    is_name_part = True
    
    for word in words:
        if not word: continue
        clean = word.strip(",./-")
        if is_name_part and (clean in name_db or (word[0].isupper() if len(word) > 0 else False)):
            name_parts.append(word)
        else:
            is_name_part = False
            comment_parts.append(word)
            
    return " ".join(name_parts), " ".join(comment_parts)

def merge_data(all_rows):
    import pandas as pd
    import re

    if not all_rows: 
        return pd.DataFrame()
    
    if isinstance(all_rows, list) and len(all_rows) > 0:
        if not isinstance(all_rows[0], pd.DataFrame):
            combined = pd.DataFrame(all_rows)
        else:
            combined = pd.concat(all_rows, ignore_index=True)
    else:
        combined = all_rows

    if 'Rendelés_Full' in combined.columns:
        combined = combined[combined['Rendelés_Full'].astype(str).str.strip() != ""]
        combined = combined[combined['Rendelés_Full'].notna() & (combined['Rendelés_Full'].astype(str).str.lower() != 'nan')]
    if 'Rendelés' in combined.columns:
        combined = combined[combined['Rendelés'].astype(str).str.strip() != ""]
        combined = combined[combined['Rendelés'].notna() & (combined['Rendelés'].astype(str).str.lower() != 'nan')]

    if combined.empty: return pd.DataFrame()

    merged = []
    unique_ids = combined['temp_id'].unique()
    
    for tid in unique_ids:
        subset = combined[combined['temp_id'] == tid]
        base = subset.iloc[0].to_dict()
        
        if 'pdf_jarat' in subset.columns:
            nem_ures_jarat = subset['pdf_jarat'].dropna().astype(str).str.strip()
            nem_ures_jarat = nem_ures_jarat[nem_ures_jarat != ""]
            if not nem_ures_jarat.empty:
                base['pdf_jarat'] = nem_ures_jarat.iloc[0]
        
        if len(subset) > 1:
            all_orders = []
            for _, r in subset.iterrows():
                o_str = str(r.get('Rendelés_Full', '')).strip()
                if o_str and o_str.lower() != 'nan': 
                    all_orders.append(o_str)
            base['Rendelés_Full'] = " | ".join(all_orders)
            
            try:
                base['Összesen'] = sum(pd.to_numeric(subset['Összesen'], errors='coerce').fillna(0))
            except: 
                pass
            
            p_val = ""
            for _, r in subset.iterrows():
                val = str(r.get('Pénz', '')).strip()
                if val and val.lower() != 'nan' and any(c.isdigit() for c in val):
                    p_val = val
                    break
            base['Pénz'] = p_val

        merged.append(base)
    
    res = pd.DataFrame(merged)
    if 'Rendelés_Full' in res.columns:
        res = res[res['Rendelés_Full'].astype(str).str.strip() != ""]
        res = res[res['Rendelés_Full'].notna() & (res['Rendelés_Full'].astype(str).str.lower() != 'nan')]
    
    if res.empty: return pd.DataFrame()
    if 'pdf_jarat' in res.columns:
        res['Járat'] = res['pdf_jarat'].astype(str).str.strip()
    
    res.columns = [c.strip() for c in res.columns]
    res['Sorrend'] = range(1, len(res) + 1)
    if 'Csoport' in res.columns:
        res['Csoport'] = res['Csoport'].astype(str).replace(['nan', 'None', '0', '0.0'], '')

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
