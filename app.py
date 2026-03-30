import streamlit as st
import pdfplumber
import pandas as pd
import re
import math
import requests
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
PHONE_PAT = r'(\d{2}/\d{6,7})'
ORDER_PAT = r'\d+-[A-Z][A-Z0-9*+]*'
# Frissített, "szóköz-toleráns" regex
MONEY_PAT = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

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
   
# --- 3. FŐ FÜGGVÉNY: PDF BEOLVASÁS ÉS BLOKKOSÍTÁS ---
def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None}
    
    # Kiegészített regexek
    ORDER_PAT = r'(\d+-[A-Z][A-Z0-9*+]*)'
    PHONE_PAT = r'(\d{2}/\d{6,7})'
    # Ez a regex a pénzösszeghez kell a stop-feltételhez
    MONEY_PAT_LOCAL = r'([-\u2013\u2014\u2212]?\s*\d+[\d\s]*\s*Ft)'

    with pdfplumber.open(pdf_file) as pdf:
        if pdf.pages:
            first_page_text = pdf.pages[0].extract_text()
            if first_page_text:
                y_m = re.search(r'Év:\s*(\d{4})', first_page_text)
                w_m = re.search(r'Hét:\s*(\d{1,2})', first_page_text)
                d_m = re.search(r'Nap:\s*([a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ]+)', first_page_text)
                if y_m: metadata['year'] = y_m.group(1)
                if w_m: metadata['week'] = w_m.group(1)
                if d_m: metadata['day'] = d_m.group(1)

        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                found = False
                for ey in lines:
                    if abs(y - ey) < 3:
                        lines[ey].append(w)
                        found = True
                        break
                if not found:
                    lines[y] = [w]

            sorted_y = sorted(lines.keys())
            for i, y in enumerate(sorted_y):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue

                full_id_match = u_code_m.group(0)
                prefix = full_id_match.split('-')[0]
                u_id = full_id_match.split('-')[-1]

                # Koordináták finomhangolása
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 370])
                b4 = " ".join([w['text'] for w in line_words if 370 <= w['x0'] < 490])
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                clean_name = re.sub(r'\s*-[A-Z]$', '', clean_name)

                raw_tel_text = text_ws.replace(" ", "")
                tel_m = re.search(r'(52/\d{6}|[237]0/\d{7})', raw_tel_text)
                clean_tel = ""
                if tel_m:
                    clean_tel = tel_m.group(1)

                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3

                # --- ADATGYŰJTÉS ÉS PÉNZ KERESÉSE (STOP-LOGIKÁVAL) ---
                money_val = "0 Ft"
                raw_money_text = ""
                all_relevant_text_parts = [text_ws]
                
                # Kulcsszavak, amiknél MEG KELL ÁLLNI az adatgyűjtéssel (Harangi Csilla-fix)
                stop_keywords = ["Összesen:", "Étel kód", "InterFood", "Nyomtatta:", "Összesítés"]

                for offset in range(1, 6): # Megnövelve 6 sorra a biztonság kedvéért
                    if i + offset < len(sorted_y):
                        next_line_words = sorted(lines[sorted_y[i + offset]], key=lambda x: x['x0'])
                        next_t_ws = " ".join([w['text'] for w in next_line_words])
                        
                        # Ha jön a következő ügyfél, megállunk
                        if re.search(r'([HKSCPZ]-[0-9]{5,7})', next_t_ws):
                            break
                        
                        # --- ÚJ: Ha belefutunk a láblécbe, azonnal megszakítjuk az adatgyűjtést ---
                        if any(stop in next_t_ws for stop in stop_keywords):
                            break
                        
                        # --- ÚJ: Biztonsági fék (ha egy sorban túl sok ételkód van sorszám nélkül, az már az összesítő) ---
                        if len(re.findall(ORDER_PAT, next_t_ws)) > 10:
                            break

                        all_relevant_text_parts.append(next_t_ws)
                        
                        raw_next_line = "".join([w['text'] for w in next_line_words])
                        m_match = re.search(MONEY_PAT_LOCAL, raw_next_line) or re.search(MONEY_PAT_LOCAL, next_t_ws)
                        if m_match and money_val == "0 Ft":
                            money_val = m_match.group(1).strip()
                            raw_money_text = m_match.group(0)

                all_relevant_text = " | ".join(all_relevant_text_parts)

                # --- A SZOBRÁSZ-LOGIKA (VÁLTOZATLAN) ---
                raw_orders = re.findall(ORDER_PAT, all_relevant_text)
                unique_orders, total_q = [], 0
                for o in raw_orders:
                    try:
                        q_part = o.split('-')[0]
                        q = int(re.sub(r'\D', '', q_part)[-1]) if re.sub(r'\D', '', q_part) else 1
                        unique_orders.append(f"{q}-{o.split('-')[1]}")
                        total_q += q
                    except: continue

                rem = all_relevant_text
                # Itt a meglévő tisztítási lépéseid futnak tovább...
                stop_words = ["Csillagozott", "kiegészítő is van", "Összesítés", "Összesen:", "Nyomtatva:"]
                for sw in stop_words:
                    if sw in rem:
                        rem = rem.split(sw)[0]

                rem = re.sub(r'[A-Z]-\d+[-A-Z]*', '', rem)
                rem = rem.replace(full_id_match, "")
                rem = re.sub(r'(?i)\bdr\.?\s*', '', rem)
                
                name_targets = []
                if clean_name: 
                    clean_name_no_dr = re.sub(r'(?i)\bdr\.?\s*', '', str(clean_name)).strip()
                    name_targets.append(clean_name_no_dr)
                    name_parts = re.split(r'[\s\-]', clean_name_no_dr)
                    for part in name_parts:
                        if len(part.strip("., ")) > 2: 
                            name_targets.append(part.strip("., "))
                            
                for target in sorted(list(set(name_targets)), key=len, reverse=True):
                    rem = re.compile(re.escape(target), re.IGNORECASE).sub("", rem)

                if address: rem = rem.replace(address, "")
                if clean_tel: rem = rem.replace(clean_tel, "")
                rem = re.sub(r'52\s\d{6}', '', rem)
                for o in raw_orders: rem = rem.replace(o, "")
                if raw_money_text: rem = rem.replace(raw_money_text, "")
                rem = re.sub(MONEY_PAT_LOCAL, "", rem)

                if total_q:
                    tq_str = str(total_q)
                    rem = re.sub(rf'^\s*{tq_str}\s*\|?', '', rem)
                    rem = re.sub(rf'\|\s*{tq_str}(\s*\||\s+)', ' | ', rem)
                    rem = re.sub(rf'\s+{tq_str}\s*\|', ' |', rem)

                rem = re.sub(r'(?i)\bkcs[\s.:]*', '', rem)
                rem = re.sub(r'(?i)\bkapucsengő[\s.:]*', '', rem)
                rem = re.sub(r'\b[HKSCPZ]\b\s*[|:]*', '', rem)
                rem = re.sub(r'^\s*[\d\s]+\|?\s*', '', rem)

                rem = rem.replace(" - |", " | ")
                rem = rem.replace("/", " ").replace("*", " ")
                rem = re.sub(r'(\s*\|\s*)+', ' | ', rem)
                rem = re.sub(r'[,.\s]{2,}', ' ', rem) 
                
                megj = re.sub(r'\s+', ' ', rem).strip(" |,. /")
                
                if (re.match(r'^\d+$', megj) and "#" not in megj) or megj in ["-", "|"]:
                    megj = ""
                
                if unique_orders:
                    # A prefixet (Hé, Pé, Szo) használjuk, nem egy beégetett P-t
                    full_id = f"{prefix}-{u_id}" 
                    
                    rows.append({
                        "Prefix": prefix, 
                        "ID": full_id,  # Így a háttérben megmarad a nap szerinti elkülönítés
                        "Ügyintéző": clean_name,
                        "Cím": address, 
                        "Telefon": tel_m.group(0) if tel_m else "",
                        "Pénz": money_val, 
                        "Rendelés": ", ".join(unique_orders),
                        "Megjegyzés": megj, 
                        "Összesen": total_q, 
                        "temp_id": u_id,
                        "Raklista_Ertek": 0, 
                        "Rendelés_Full": f"{prefix}: {', '.join(unique_orders)}",
                        "Hétvégi": False,
                        "Sorrend": st.session_state.weights.get(str(u_id), 999)
                    })
    return rows, metadata
    
def merge_data(raw_rows, p_map, sz_map):
    if not raw_rows: return pd.DataFrame()
    
    import pandas as pd
    import re

    L_DAYS = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}
    df = pd.DataFrame(raw_rows)
    
    # Biztonságos temp_id: csak a számokat tartjuk meg az ID-ból (pl. P-468296 -> 468296)
    df['temp_id'] = df['ID'].astype(str).str.replace(r'\D', '', regex=True)

    merged = []
    # Ügyfélkód (tid) szerint csoportosítunk
    for tid, group in df.groupby("temp_id", sort=False):
        # Alapadatokat az első sorból vesszük
        base = group.iloc[0].copy().to_dict()
        u_id = str(tid)

        # --- 1. PÉNZ KEZELÉSE (JAVÍTVA: MEGTARTJA A NEGATÍVOKAT) ---
        pdf_payment_val = 0
        
        for _, row in group.iterrows():
            m_str = str(row.get('Pénz', '0'))
            
            # 1. Kivesszük az összes szóközt és betűt, csak a számok és a kötőjelek maradnak
            clean_str = re.sub(r'[^\d\-\u2013\u2014\u2212]', '', m_str)
            # 2. A speciális PDF-es gondolatjeleket sima mínuszra cseréljük
            clean_str = re.sub(r'[\u2013\u2014\u2212]', '-', clean_str)
            
            if clean_str:
                try:
                    val = int(clean_str)
                    # Ha találunk egy nem nulla értéket (legyen az pozitív vagy negatív), azt kimentjük
                    if val != 0:
                        pdf_payment_val = val
                except ValueError:
                    pass

        base['Pénz'] = f"{pdf_payment_val} Ft"

        # --- 2. RENDELÉSEK ÖSSZEVONÁSA (PDF + EXCEL) ---
        o_p, has_weekend = [], False
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_rows = group[group['Prefix'] == pfix]
            if not day_rows.empty:
                items = day_rows['Rendelés'].astype(str).tolist()
                clean_items = [i for i in items if i != 'nan' and i.strip() != '']
                if clean_items:
                    o_p.append(f"{L_DAYS.get(pfix, pfix)}: {', '.join(clean_items)}")

        # Excel pótlások hozzáadása
        p_extra_order = p_map.get(u_id, {}).get('rendeles', "")
        sz_extra_order = sz_map.get(u_id, {}).get('rendeles', "")

        if p_extra_order:
            o_p.append(f"Pé(Ex): {p_extra_order}")
            has_weekend = True
        if sz_extra_order:
            o_p.append(f"Szo(Ex): {sz_extra_order}")
            has_weekend = True

        # Megkeressük az első érvényes prefixet a csoportban (Hé, Pé stb.)
        current_prefix = group['Prefix'].iloc[0] if 'Prefix' in group.columns else "P"

        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = pd.to_numeric(group['Összesen'], errors='coerce').sum()
        base['Hétvégi'] = has_weekend
        # A beégetett P- helyett a valódi prefixet használjuk:
        base['ID'] = f"{current_prefix}-{tid}"
        base['temp_id'] = tid
        
        # Sorrend visszatöltése: Megpróbáljuk az aktuális prefixszel, 
        # de ha nem találjuk, megnézzük a sima ID-t is.
        current_id = f"{current_prefix}-{tid}"
        weights = st.session_state.get('weights', {})
        
        # Először próbáljuk a teljes azonosítóval (pl. Hé-123456 vagy P-123456)
        # Ha nincs meg, marad a 999 (lista vége)
        base['Sorrend'] = weights.get(current_id, weights.get(f"P-{tid}", 999))
        
        merged.append(base)

    # --- 3. VÉGLEGES TÁBLÁZAT LÉTREHOZÁSA ÉS RENDEZÉSE ---
    res = pd.DataFrame(merged)
    
    if not res.empty:
        if 'Sorrend' not in res.columns:
            res['Sorrend'] = range(1, len(res) + 1)
        
        res['Sorrend'] = pd.to_numeric(res['Sorrend'], errors='coerce').fillna(999)
        res = res.sort_values(by='Sorrend').reset_index(drop=True)

    return res

def create_label_pdf(df, fn, ft):
    if df is None or df.empty: return None
    if 'Sorrend' not in df.columns: df['Sorrend'] = range(1, len(df) + 1)
    df = df.sort_values('Sorrend')
    
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70 * mm, 42.42 * mm
    inner_m = 5.5 * mm 
    usable_w = lw - (2 * inner_m)

    # Tömörített sorköz a rendeléseknek
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=7.5, leading=8.0)
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

            # 1. Hétvégi kiemelés
            is_weekend = r.get('Hétvégi') == True or "Szo:" in str(r.get('Rendelés_Full', ''))
            if is_weekend:
                p.saveState()
                p.setFillColor(colors.lightgrey)
                p.rect(x + inner_m - 1*mm, top_y - 9.5 * mm, usable_w + 2*mm, 5.5 * mm, fill=1, stroke=0)
                p.restoreState()

            # 2. Fejléc adatok
            p.setFont(f_bold, 10)
            p.drawString(x + inner_m, top_y - 3 * mm, f"#{int(r['Sorrend'])}")
            
            # A prefix-es ID helyett a tiszta temp_id-t használjuk
            # Biztosítjuk, hogy szöveg legyen, ha esetleg számként jönne
            display_id = str(r.get('temp_id', 'N/A'))

            p.setFont(f_reg, 8)
            # Jobbra igazítva kiírjuk a tiszta kódot
            p.drawRightString(x + lw - inner_m, top_y - 3 * mm, f"ID: {display_id}")

            p.setFont(f_bold, 9)
            p.drawString(x + inner_m, top_y - 8.5 * mm, str(r.get('Ügyintéző', ''))[:25])
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, top_y - 8.5 * mm, str(r.get('Telefon', '')))

            p.setFont(f_reg, 7)
            p.drawString(x + inner_m, top_y - 12.5 * mm, str(r.get('Cím', ''))[:45])

            # 3. Rendelés (Lentebb tolva az ügyfél nevétől, hogy ne érjenek össze)
            rendeles_text = str(r.get('Rendelés_Full', r.get('Rendelés', '')))
            para = Paragraph(f"<b>{rendeles_text}</b>", order_s)
            
            # Maximális magasság, hogy ne lógjon rá az alsó adatokra
            pw, ph = para.wrap(usable_w, 15 * mm)
            para.drawOn(p, x + inner_m, y_eff + inner_m + 6.8 * mm)

            # 4. Fizetendő és Darab (Kisebb betű, közvetlenül a vonalra tolva)
            penz = str(r.get('Pénz', '0 Ft')).replace(" ", "")
            if penz not in ["0Ft", "", "0"]:
                p.setFont(f_bold, 9)
                # Itt a kért kiegészítés: "Fizet: "
                p.drawString(x + inner_m, y_eff + 5.5 * mm, f"Fizet: {str(r.get('Pénz', ''))}")
            
            p.setFont(f_bold, 8)
            p.drawRightString(x + lw - inner_m, y_eff + 5.5 * mm, f"{int(r.get('Összesen', 0))} db")

            # 5. Folytonos elválasztó vonal
            p.setDash(1, 0) 
            p.setStrokeColor(colors.black)
            p.setLineWidth(0.1)
            p.line(x + inner_m, y_eff + 5 * mm, x + lw - inner_m, y_eff + 5 * mm)
            
            # Futár adatok
            p.setFont(f_reg, 6)
            p.drawCentredString(x + lw / 2, y_eff + 2.5 * mm, f"Futár: {fn} | {ft}")

        else:
            # Marketing etikett
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
    
# --- ÚJ OSZTÁLY A RAJZOLT NÉGYZETHEZ ---
class MyCheckbox(Flowable):
    def __init__(self, size=10):
        Flowable.__init__(self)
        self.size = size
        # Megadjuk a szélességet és magasságot, hogy a táblázat tudja igazítani
        self.width = size
        self.height = size

    def draw(self):
        # Elmozdítjuk a rajzot, hogy a cella függőleges közepéhez is igazodjon
        self.canv.setLineWidth(0.5)
        self.canv.setStrokeColor(colors.black)
        # x=0, y=0-nál rajzolunk, a táblázat ALIGN 'CENTER' fogja vízszintesen helyre tenni
        self.canv.rect(0, 0, self.size, self.size, stroke=1, fill=0)

def create_manifest_pdf(df, fn, meta_dict):
    if df is None or df.empty: 
        return None

    # --- 1. OKOS CSOPORTOSÍTÁS ELŐKÉSZÍTÉSE ---
    # Tisztítjuk a címeket az összevetéshez (pontok nélkül, kisbetűvel)
    df['clean_address'] = df['Cím'].astype(str).str.replace('.', '', regex=False).str.strip().str.lower()
    
    def get_group_id(row):
        manual = str(row.get('Csoport', '')).strip()
        if manual and manual.lower() != 'nan' and manual != "":
            return f"manual_{manual}"
        return f"addr_{row['clean_address']}"

    df['group_id'] = df.apply(get_group_id, axis=1)
    df = df.sort_values('Sorrend')
    
    f_reg, f_bold = register_fonts()  
    buf = BytesIO()

    # --- 2. STÍLUSOK ---
    from reportlab.lib.styles import ParagraphStyle
    styles = {
        'Normal': ParagraphStyle('Normal', fontName=f_reg, fontSize=8, leading=10),
        'Small': ParagraphStyle('Small', fontName=f_reg, fontSize=7, leading=9),
        'Header': ParagraphStyle('Header', fontName=f_bold, fontSize=10, leading=12, alignment=1)
    }

    elements = []
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=5*mm, leftMargin=5*mm, topMargin=10*mm, bottomMargin=15*mm)

    # --- 3. OLDALSZÁMOZÁS ÉS FEJLÉC FÜGGVÉNY ---
    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_reg, 8)
        # Oldalszám középre alulra
        page_num = f"{doc.page}. oldal"
        canvas.drawCentredString(105*mm, 10*mm, page_num)
        canvas.restoreState()

    # Fejléc tartalom
    jaratok = ", ".join(meta_dict.get('jaratok', []))
    fejlec_szov = f"MENETTERV - Járat(ok): {jaratok} | {meta_dict.get('ev')}. év, {meta_dict.get('het')}. hét | {meta_dict.get('nap')}"
    elements.append(Paragraph(fejlec_szov, styles['Header']))
    elements.append(Spacer(1, 4 * mm))

    # --- 4. TÁBLÁZAT ADATOK ---
    # Új oszloprend: #, Név/Cím, ☐, Pénz, Tel, Rendelés, DB
    table_data = [["#", "NÉV / CÍM / INFÓ", "☐", "PÉNZ", "TEL", "RENDELÉS", "DB"]]
    table_styles = [
        ('FONTNAME', (0,0), (-1,0), f_bold),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (2,0), (2,-1), 'CENTER'), # Checkbox középre
        ('ALIGN', (6,0), (6,-1), 'CENTER'), # DB középre
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
    ]

    current_row_idx = 1
    grouped = df.groupby('group_id', sort=False)

    for gid, group in grouped:
        is_group = len(group) > 1
        start_idx = current_row_idx
        
        for i, (_, row) in enumerate(group.iterrows()):
            # PÉNZ JAVÍTÁS: Csak akkor tüntetjük el, ha pontosan "0 Ft"
            p_raw = str(row.get('Pénz', '')).strip()
            penz_disp = "" if p_raw in ["0 Ft", "0", "nan", ""] else f"<b>{p_raw}</b>"
            
            megj_raw = str(row.get('Megjegyzés', '')).strip()
            megj = f"<br/><font color='red'><i>{megj_raw}</i></font>" if megj_raw and megj_raw.lower() != 'nan' else ""
            
            group_tag = "<font color='blue'>▲ </font>" if is_group else ""
            
            table_data.append([
                f"{row['Sorrend']:.1f}" if row['Sorrend'] % 1 != 0 else f"{int(row['Sorrend'])}",
                Paragraph(f"{group_tag}<b>{row['Ügyintéző']}</b><br/>{row['Cím']}{megj}", styles['Normal']),
                MyCheckbox(10),
                Paragraph(penz_disp, styles['Small']),
                Paragraph(str(row.get('Telefon', '')), styles['Small']),
                Paragraph(str(row.get('Rendelés_Full', '')), styles['Small']),
                str(int(row.get('Összesen', 0)))
            ])
            current_row_idx += 1
            
        if is_group:
            end_idx = current_row_idx - 1
            table_styles.append(('BACKGROUND', (0, start_idx), (-1, end_idx), colors.Color(0.96, 0.96, 0.96)))
            table_styles.append(('OUTLINE', (0, start_idx), (-1, end_idx), 1.2, colors.black))

    col_widths = [10*mm, 80*mm, 8*mm, 20*mm, 25*mm, 45*mm, 8*mm]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(table_styles))
    elements.append(t)

    # Build oldalszámozással
    doc.build(elements, onFirstPage=draw_footer, onLaterPages=draw_footer)
    buf.seek(0)
    return buf.getvalue()
    
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

        # --- ÚJ PDF-EK FELDOLGOZÁSA ---
        st.subheader("📄 Új PDF-ek")
        up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])

        if up_files and st.button("🚀 FELDOLGOZÁS"):
            # 1. Kinyerjük az összes metaadatot
            meta_auto = extract_all_meta(up_files)
            # Elmentjük a session_state-be, hogy a gombok is lássák
            st.session_state.meta_data = meta_auto 

            all_rows = []
            with st.spinner("PDF-ek beolvasása..."):
                for f in up_files:
                    f.seek(0) # Visszatekerés az elejére!
                    rows, _ = parse_interfood_pdf(f) # A parse_interfood meta-ját most kihagyjuk
                    if rows:
                        all_rows.extend(rows)

            if all_rows:
                # Az étlaphoz kellenek a dátumok
                y = meta_auto.get('ev') or '2026'
                w = meta_auto.get('het') or '13'
                
                p_map = get_etlap_dict(y, w, 5)
                sz_map = get_etlap_dict(y, w, 6)
                
                # Összefésülés
                df_temp = merge_data(all_rows, p_map, sz_map)
                
                if not df_temp.empty:
                    df_temp['Sorrend'] = range(1, len(df_temp) + 1)
                
                st.session_state.mdf = df_temp
                st.success(f"Sikeresen feldolgozva: {len(st.session_state.mdf)} ügyfél.")
                st.rerun()

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
            create_label_pdf(edited_df, st.session_state.c_n, st.session_state.c_p), 
            "etikettek.pdf", use_container_width=True
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
