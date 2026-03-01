def process_v8(uploaded_file):
    reader = PdfReader(uploaded_file)
    customers = {}
    
    # Először gyűjtsük össze az összes sort az összes oldalról egy listába
    all_lines = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            all_lines.extend(text.split('\n'))

    for i, line in enumerate(all_lines):
        line = line.strip()
        # Ügyfélkód keresése: P-123456, Z-123456, S-123456, C-123456
        id_match = re.search(r'([PZSC])-(\d{6,})', line)
        
        if id_match:
            day_type = id_match.group(1)
            cust_id = id_match.group(2)
            full_code = id_match.group(0)

            # 1. SORSZÁM: Megnézzük a sor elejét vagy az előző sort
            sorszam = "?"
            s_match = re.match(r'^(\d{1,3})\s', line)
            if s_match:
                sorszam = s_match.group(1)
            elif i > 0:
                s_match_prev = re.match(r'^(\d{1,3})$', all_lines[i-1].strip())
                if s_match_prev:
                    sorszam = s_match_prev.group(1)

            # 2. ADATOK INICIALIZÁLÁSA
            if cust_id not in customers:
                customers[cust_id] = {
                    'kod': cust_id, 
                    'sorszamok': {sorszam} if sorszam != "?" else set(),
                    'nev': "Ügyfél", 
                    'cim': "", 
                    'P_rend': [], 'Z_rend': [], 'is_z': False
                }
            else:
                if sorszam != "?": customers[cust_id]['sorszamok'].add(sorszam)

            # 3. NÉV KERESÉSE (Kicsit okosabban: a kód környékén keressük a nagybetűs neveket)
            # Megpróbáljuk kivenni a sorból a sorszámot és a kódot, ami marad, az a név/cím lehet
            clean_line = line.replace(full_code, "").replace(sorszam, "", 1).strip()
            
            # Ha van benne Debrecen, akkor szétválasztjuk név és cím részre
            if "Debrecen" in clean_line:
                addr_match = re.search(r'(\d{4}\s+Debrecen.*)', clean_line)
                if addr_match:
                    customers[cust_id]['cim'] = addr_match.group(1)
                    customers[cust_id]['nev'] = clean_line.replace(addr_match.group(1), "").strip()
            
            # Ha még nincs neve, de a clean_line-ban maradt valami értelmes
            if customers[cust_id]['nev'] == "Ügyfél" and len(clean_line) > 4:
                # Csak akkor írjuk felül, ha nem csak számokból áll
                if not clean_line.replace(" ", "").isdigit():
                    customers[cust_id]['nev'] = clean_line[:30]

            # 4. ÉTELKÓDOK (Nézzük a környező sorokat is)
            # Az Interfood kódok formátuma: szám-betűkód (pl. 12-F4, 1-G)
            search_context = " ".join(all_lines[max(0, i-1) : i+4])
            codes = re.findall(r'\b\d{1,2}-[A-Z0-9]{1,4}\b', search_context)
            
            if day_type in ['Z', 'S']: # Szombat/Vasárnap
                customers[cust_id]['Z_rend'].extend(codes)
                customers[cust_id]['is_z'] = True
            else:
                customers[cust_id]['P_rend'].extend(codes)

    # Tisztítás: duplikált ételek kiszűrése
    for c_id in customers:
        customers[c_id]['P_rend'] = list(set(customers[c_id]['P_rend']))
        customers[c_id]['Z_rend'] = list(set(customers[c_id]['Z_rend']))

    return list(customers.values())
