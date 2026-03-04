def process_name_and_address(raw_name, raw_addr):
    to_move = ['lph', 'lp', 'porta', 'u', 'utca', 'út', 'útja', 'tér', 'ép', 'épület', 'fszt', 'em', 'LGM', 'kft', 'bt', 'zrt']
    allowed_prefixes = ['Dr.', 'Prof.', 'Ifj.', 'Id.', 'Özv.']
    
    # 1. SZUPER-KÖTŐJEL SZŰRŐ: Minden típusú kötőjelet (-, –, —) egységesítünk,
    # majd levadásszuk a kódokat (pl. -K, -SP, -DKM)
    normalized_name = raw_name.replace('–', '-').replace('—', '-')
    
    # Levágjuk a kódokat, amik kötőjellel kezdődnek és nagybetű/szám követi őket
    # Akkor is, ha a szó végén vannak vagy külön állnak
    normalized_name = re.sub(r'\s*-[A-Z0-9]+\b', '', normalized_name)
    
    words = normalized_name.split()
    clean_name_words = []
    moved_to_address = []

    for word in words:
        # 2. Egybetűs szűrő (Kertész Árpád "a" betűje itt bukik el)
        if len(word) == 1:
            if word == 'É':
                clean_name_words.append(word)
            else:
                moved_to_address.append(word)
            continue

        clean_word_comp = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]', '', word).lower()

        # 3. Vámház / LGM / Cégnevek
        if clean_word_comp in [x.lower() for x in to_move] or (word.isupper() and 2 <= len(word) <= 4):
            moved_to_address.append(word)
            continue

        # 4. Kisbetűs szemét
        if len(word) > 0 and word[0].islower():
            if (word.capitalize() + "." not in allowed_prefixes):
                moved_to_address.append(word)
                continue
            
        clean_name_words.append(word)

    # Név összeállítása
    final_name = " ".join(clean_name_words)
    # Csak betűk, kötőjel (neveken belüli!) és pont maradhat
    final_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-\.]', '', final_name)
    
    for pref in allowed_prefixes:
        final_name = final_name.replace(pref, pref.replace('.', '___'))
    final_name = final_name.replace('.', '').replace('___', '.')
    
    # Utolsó simítás a név elején maradt névelőkre
    final_name = re.sub(r'^[aA]\s+', '', final_name).strip()

    # Cím összeállítása
    zip_match = re.search(r'(\d{4})', raw_addr)
    base_addr = raw_addr[zip_match.start():].strip() if zip_match else raw_addr.strip()
    extra_info = " ".join(moved_to_address).strip()
    final_addr = f"{base_addr} {extra_info}".strip() if extra_info else base_addr

    return final_name, final_addr
