# -*- coding: utf-8 -*-
import re
import pdfplumber
import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# --- GLOBÁLIS REGEX MINTÁK ---
PHONE_PAT = r'(\d{2}/[\.\s]*\d(?:[\s\.,-]*\d){5,6})'
ORDER_PAT = r'(\d+)\s*[-\u2013\u2014\u2212]\s*([A-Z0-9*+]+)'
MONEY_PAT = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

# --- FŐ FÜGGVÉNY: PDF BEOLVASÁS ÉS BLOKKOSÍTÁS ---
def parse_interfood_pdf(pdf_file, napi_etlap_kodok):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jaratok': []}
    
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        W = page.width
        def c(kocka): return (kocka / 88) * W
        v_lines = [c(0), c(5.5), c(21.5), c(39.5), c(47), c(52), c(82.5), c(88)]

        first_page_text = pdf.pages[0].extract_text() or ""
        nap_m = re.search(r'Nap:\s*([a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]+)', first_page_text)
        detect_day = nap_m.group(1).strip().lower() if nap_m else ""

        for pg in pdf.pages:
            words = pg.extract_words(x_tolerance=3, y_tolerance=3)
            anchors = [w for w in words if re.search(r'\b[A-Za-z0-9]{1,3}-\d{5,7}\b', w['text'])]
            
            last_anchor_top = max([a['top'] for a in anchors]) if anchors else 120
            
            footer_elements = []
            for w in words:
                txt = w['text']
                if any(tag.lower() in txt.lower() for tag in ["Összesítés", "osszesites", "Csilagozott", "csillagozott", "Összesen", "osszesen", "nyomtatta", "oldal", "menetlevél", "menetlevel"]) and w['top'] > last_anchor_top:
                    footer_elements.append(w)
            
            page_cutoff = min([w['top'] for w in footer_elements]) - 2 if footer_elements else pg.height

            for i, anchor in enumerate(anchors):
                if anchor['top'] >= page_cutoff: continue

                # --- 1. ZÓNA ÉS SZÖVEG BEOLVASÁSA ---
                y_top = max(0, anchor['top'] - 12)
                next_anchor_top = anchors[i+1]['top'] - 5 if i+1 < len(anchors) else page_cutoff
                y_bottom = min(next_anchor_top, page_cutoff)
                
                line_words = [w for w in words if y_top <= w['top'] < y_bottom]
                
                def get_col_text(x_min, x_max):
                    sel = [w for w in line_words if x_min <= (w['x0'] + w['x1'])/2 < x_max]
                    sel.sort(key=lambda x: (x['top'], x['x0']))
                    return " ".join([w['text'] for w in sel])

                full_id_area = get_col_text(v_lines[0], v_lines[2])
                id_match = re.search(r'([A-Za-z0-9]{1,3}-\d{5,7})', full_id_area)
                
                line_text_full = " ".join([w['text'] for w in line_words])
                header_keywords = ["sor", "ügyfél", "ügyintéző", "telefon", "rendelése", "össz"]
                matched_header_words = sum(1 for kw in header_keywords if kw in line_text_full.lower())
                if matched_header_words >= 3: continue 
                
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

                    # --- 2. TELEFON ÉS PÉNZ KINYERÉSE ---
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

                    # --- 3. ÜGYINTÉZŐ KERESÉSE ---
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

                    # --- 4. RENDELÉS FOLYOSÓ ÉS ÉTLAPKÓD-VALIDÁLÁS ---
                    width = page.width 
                    x_start_limit = width * 0.585
                    x_end_limit = width * 0.94    

                    folyoso_words = sorted([
                        w for w in line_words 
                        if (w['x0'] + w['x1'])/2 >= x_start_limit and (w['x0'] + w['x1'])/2 <= x_end_limit
                    ], key=lambda x: (x['top'], x['x0']))
                    
                    tiszta_elemek = []
                    for w in folyoso_words:
                        txt = w['text'].strip()
                        if any(stop in txt for stop in ["Összesítés:", "Csilagozott", "Összesen:"]):
                            break
                        if re.match(r'^\d{2}/\d+', txt):
                            continue
                        if "Ft" in txt:
                            continue
                        tiszta_elemek.append(txt)

                    raw_folyoso_text = " ".join(tiszta_elemek)
                    fixed_text = re.sub(r'(\d+)\s*([-\u2013\u2014\u2212])\s*', r'\1\2', raw_folyoso_text)
                    fixed_text = re.sub(r'(\d+[-\u2013\u2014\u2212])\s+([A-Z0-9*+]+)', r'\1\2', fixed_text)

                    potential_orders = re.findall(ORDER_PAT, fixed_text)
                    ervenyes_orders = []
                    tiszta_etlap_set = {str(k).strip().upper().replace('*', '') for k in napi_etlap_kodok if str(k).strip()}

                    for qty, code in potential_orders:
                        c_clean = code.strip().upper().replace('*', '')
                        if not tiszta_etlap_set or c_clean in tiszta_etlap_set:
                            ervenyes_orders.append((qty, code.strip()))

                    rendeles_str = ", ".join([f"{q}-{c}" for q, c in ervenyes_orders])
                    raw_orders = ervenyes_orders
                    
                    # --- 5. CÍM MEGHATÁROZÁSA ---
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

                    # --- 6. MEGJEGYZÉS 1 (CÉG/RÉSZLEG) ÉS MEGJEGYZÉS 2 (KAPUKÓD/INSTRUKCIÓ) ---
                    left_words = [w for w in line_words if (w['x0'] + w['x1'])/2 < x_start_limit]
                    line_words_sorted = sorted(left_words, key=lambda x: (round(x['top'] / 3) * 3, x['x0']))
                    full_block_text = " ".join([w['text'] for w in line_words_sorted])
                    
                    id_pattern = r'[A-Za-z0-9]{1,3}-\d{5,7}'
                    id_match_context = re.search(id_pattern, full_block_text)
                    working_context = full_block_text[id_match_context.start():] if id_match_context else full_block_text

                    # 💡 FIX: NEM futtatunk ORDER_PAT-ot working_context-en, mert megenné a "2-26", "1-11" házszámokat!
                    clean_context = re.sub(MONEY_PAT, '', working_context)
                    if phone_val:
                        clean_context = clean_context.replace(phone_val, " ")

                    megj_resz_1 = "" 
                    megj_resz_2 = "" 

                    # MEGJEGYZÉS 1: Cím előtti cégnév / részleg
                    addr_zip_match = re.search(r'\b\d{4}\b', address)
                    target_zip = addr_zip_match.group(0) if addr_zip_match else ""
                    
                    zip_match = re.search(rf'\b{target_zip}\b', clean_context) if target_zip else re.search(r'\b\d{4}\b', clean_context)

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

                    # MEGJEGYZÉS 2: Cím utáni instrukciók és kapukódok
                    if address and address in clean_context:
                        anchor_pos = clean_context.find(address) + len(address)
                        after_address = clean_context[anchor_pos:].strip()
                        megj_resz_2 = after_address
                    else:
                        # Ha a cím apró eltéréssel nem talál egybe, az irányítószám + utca utáni részt vágjuk le
                        if zip_match:
                            megj_resz_2 = clean_context[zip_match.end():].strip()
                            # Bármilyen magyar településnév és utcanév levágása (irányítószám mögül)
                            megj_resz_2 = re.sub(r'^[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű\s-]+,\s*[^.]*\.\s*', '', megj_resz_2).strip()
                        else:
                            megj_resz_2 = clean_context

                    # 🛡️ TISZTÍTÁS: ID törlése
                    megj_resz_1 = re.sub(r'\b[A-Za-z0-9]{1,3}-\d{5,7}\b', '', megj_resz_1).strip()
                    megj_resz_2 = re.sub(r'\b[A-Za-z0-9]{1,3}-\d{5,7}\b', '', megj_resz_2).strip()

                    # 🛡️ TISZTÍTÁS: Ügyintéző levágása
                    if admin_name:
                        megj_resz_1 = re.sub(rf'\b{re.escape(admin_name)}\b', '', megj_resz_1, flags=re.IGNORECASE).strip()
                        megj_resz_2 = re.sub(rf'\b{re.escape(admin_name)}\b', '', megj_resz_2, flags=re.IGNORECASE).strip()
                        for w in admin_name.split():
                            if len(w) > 2:
                                megj_resz_1 = re.sub(rf'\b{re.escape(w)}\b', '', megj_resz_1, flags=re.IGNORECASE).strip()
                                megj_resz_2 = re.sub(rf'\b{re.escape(w)}\b', '', megj_resz_2, flags=re.IGNORECASE).strip()

                    # 🛡️ TISZTÍTÁS: Árva előhívók levágása PERJELLEL ÉS ANÉLKÜL IS (pl. "20/", "30/", "70/")
                    # Figyelem: a valódi kapukódokat (pl. 30k2480, kcs: 20) és a telefonszámokat VÉDI!
                    megj_resz_1 = re.sub(r'(?:^|[\s|])(?:20|30|70)\s*/?\s*(?=[^\d\w]|$)', ' ', megj_resz_1).strip(" -/|.,*")
                    megj_resz_2 = re.sub(r'(?:^|[\s|])(?:20|30|70)\s*/?\s*(?=[^\d\w]|$)', ' ', megj_resz_2).strip(" -/|.,*")

                    # Felesleges rendszerfeliratok törlése
                    junk_list = [
                        "Felnőtt", "Nyugdíjas", "Gyerek", "Vendég", "Dr.", "idősb", "ifj",
                        "Csilagozott betűnél kiegészítő is van!!!",
                        "Csilagozott betűnél kiegészítő is van",
                        "Összesítés:", "Összesen:"
                    ]
                    for junk in junk_list:
                        megj_resz_1 = megj_resz_1.replace(junk, "").strip()
                        megj_resz_2 = megj_resz_2.replace(junk, "").strip()

                    # VÉGLEGES ÖSSZEFŰZÉS: Megjegyzés 1 (Cég) | Megjegyzés 2 (Kapukód)
                    final_parts = []
                    r1 = megj_resz_1.strip(" -/|.,*")
                    r2 = megj_resz_2.strip(" -/|.,*")

                    if r1 and len(r1) > 1 and r1.lower() != admin_name.lower():
                        final_parts.append(r1)
                    if r2 and len(r2) > 1 and r2.lower() != admin_name.lower():
                        if not final_parts or r2.lower() != final_parts[0].lower():
                            final_parts.append(r2)

                    full_note = " | ".join(final_parts)
                    full_note = re.sub(r'(?:\s*\|\s*)+', ' | ', full_note)
                    full_note = re.sub(r'\s+', ' ', full_note)
                    full_note = full_note.strip(" ,.-/|*")
                    
                    mapping = {"H": "Hé", "K": "Ke", "S": "Sze", "C": "Csü", "P": "Pé", "Z": "Szo"}
                    full_rendeles_text = f"{mapping.get(prefix, '')}: {rendeles_str}" if rendeles_str else ""

                    rows.append({
                        "ID": full_id, "Ügyintéző": admin_name, "Cím": address, "Telefon": phone_val,
                        "Pénz": money_val, "Rendelés": rendeles_str, "Megjegyzés": full_note,
                        "Összesen": sum(int(q) for q, c in raw_orders) if raw_orders else 0,
                        "Rendelés_Full": full_rendeles_text, "temp_id": full_id.split('-')[-1],
                        "Prefix": prefix
                    })
    
    if not rows: return [], metadata
    df = pd.DataFrame(rows)
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
                'hetfo': 1, 'hétfő': 1, 'kedd': 2, 'szerda': 3,
                'csutortok': 4, 'csütörtök': 4, 'pente': 5, 'pénte': 5,
                'pentek': 5, 'péntek': 5, 'szombat': 6, 'vasarnap': 7, 'vasárnap': 7
            }
            nap_szoveg_kulcs = next((k for k in nap_szamok if k in nap_tisztitott), None)
            if nap_szoveg_kulcs:
                nap_szama = nap_szamok[nap_szoveg_kulcs]
                target_year = int(all_meta['ev'])
                target_week = int(all_meta['het'])
                kalkulalt_datum = datetime.strptime(f"{target_year}-{target_week}-{nap_szama}", "%G-%V-%u")
                all_meta['datum_iso'] = kalkulalt_datum.strftime("%Y-%m-%d")
                all_meta['api_datum_kulcs'] = kalkulalt_datum.strftime("%Y.%m.%d.")
        except Exception:
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
            text = str(s).lower().replace('utca', 'u').replace('út', 'u').replace('.', ' ').replace(',', ' ')
            text_no_zip = re.sub(r'^\s*\d{4}\s*', '', text)
            match = re.search(r'^[^0-9]+\d+(?:\s*/\s*[a-z0-9]+)?(?:\s*[a-z]\b)?', text_no_zip)
            if match:
                return re.sub(r'\W+', '', match.group(0))
            return re.sub(r'\W+', '', text_no_zip)
        
        addr_prev = clean_addr(res.iloc[i-1]['Cím'])
        addr_curr = clean_addr(res.iloc[i]['Cím'])
        
        if (addr_prev == addr_curr or (addr_prev in addr_curr and len(addr_prev) > 8) or (addr_curr in addr_prev and len(addr_curr) > 8)) and addr_curr != "":
            if res.iloc[i-1]['Csoport'] == 0:
                res.at[res.index[i-1], 'Csoport'] = group_id
                res.at[res.index[i], 'Csoport'] = group_id
                group_id += 1
            else:
                res.at[res.index[i], 'Csoport'] = res.iloc[i-1]['Csoport']
                
    return res
