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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# --- ALAPBEÁLLÍTÁSOK ---
PHONE_PAT = r'(\+?\d{1,2}[/\s-]?)?(\d{2}[/\s-]?)?\d{3}[/\s-]?\d{4}'
ORDER_PAT = r'\d+-[A-Z][A-Z0-9*+]*'


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
    MONEY_PAT = r'([-\u2013\u2014\u2212]?\s?\d[\d\s]*\s*Ft)'

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

                # Koordináták: B3 (Cím), B4 (Név)
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355])
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490])
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                
                tel_m = re.search(PHONE_PAT, text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3

                # Pénz keresése
                money_val = "0 Ft"
                raw_money_text = ""
                if i + 1 < len(sorted_y):
                    next_t = " ".join([w['text'] for w in sorted(lines[sorted_y[i + 1]], key=lambda x: x['x0'])])
                    m_match = re.search(MONEY_PAT, next_t)
                    if m_match: 
                        money_val = m_match.group(1).strip()
                        raw_money_text = m_match.group(0)

                # Rendelések
                raw_orders = re.findall(ORDER_PAT, text_ws)
                unique_orders, total_q = [], 0
                for o in raw_orders:
                    try:
                        q_part = o.split('-')[0]
                        q = int(re.sub(r'\D', '', q_part)[-1]) if re.sub(r'\D', '', q_part) else 1
                        unique_orders.append(f"{q}-{o.split('-')[1]}")
                        total_q += q
                    except: continue

                # --- A SZOBRÁSZ-LOGIKA (KIVONÁS) ---
                rem = text_ws
                rem = rem.replace(full_id_match, "")
                if clean_name: rem = rem.replace(clean_name, "")
                if address: rem = rem.replace(address, "")
                if tel_m: rem = rem.replace(tel_m.group(0), "")
                for o in raw_orders: rem = rem.replace(o, "")
                if raw_money_text: rem = rem.replace(raw_money_text, "")

                # Takarítás
                megj = re.sub(r'\s+', ' ', rem).strip()
                megj = re.sub(r'^\d+\s+', '', megj) # Sor eleji sorszám
                megj = re.sub(r'\s+\d+$', '', megj) # Sor végi összesítő
                megj = megj.strip(" ,.-")

                if unique_orders:
                    rows.append({
                        "Prefix": prefix, "ID": f"P-{u_id}", "Ügyintéző": clean_name,
                        "Cím": address, "Telefon": tel_m.group(0) if tel_m else "",
                        "Pénz": money_val, "Rendelés": ", ".join(unique_orders),
                        "Megjegyzés": megj, "Összesen": total_q, "temp_id": u_id,
                        "Raklista_Ertek": 0, "Rendelés_Full": f"{prefix}: {', '.join(unique_orders)}",
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

        # --- 1. PÉNZ KEZELÉSE (MAXIMUM SZABÁLY - CSAK PDF-BŐL) ---
        pdf_payment_val = 0
        has_negative = False
        
        for _, row in group.iterrows():
            m_str = str(row.get('Pénz', '0'))
            digits = "".join(re.findall(r'[-\d]', m_str))
            
            if "-" in digits:
                has_negative = True
                break
            else:
                pure_val = int(re.sub(r'\D', '', digits)) if re.sub(r'\D', '', digits) else 0
                if pure_val > pdf_payment_val:
                    pdf_payment_val = pure_val

        total_payment = 0 if has_negative else pdf_payment_val
        base['Pénz'] = f"{total_payment} Ft"

        # --- 2. RENDELÉSEK ÖSSZEVONÁSA (PDF + EXCEL) ---
        o_p, has_weekend = [], False
        for pfix in ['H', 'K', 'S', 'C', 'P']:
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

        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = pd.to_numeric(group['Összesen'], errors='coerce').sum()
        base['Hétvégi'] = has_weekend
        base['ID'] = f"P-{tid}"
        base['temp_id'] = tid
        
        # Sorrend visszatöltése (Fontos: a weights-ből a P-123456 formátumot keressük)
        base['Sorrend'] = st.session_state.get('weights', {}).get(f"P-{tid}", 999)
        
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
        """Etikett generálás biztonsági ellenőrzésekkel és hibajavítással"""
        # --- BIZTONSÁGI MENTÉS ÉS ELLENŐRZÉS ---
        if df is None or df.empty:
            return None
    
        # Ha nincs Sorrend oszlop (ami a KeyError-t okozta), pótoljuk
        if 'Sorrend' not in df.columns:
            df['Sorrend'] = range(1, len(df) + 1)
    
        # Sorrend szerinti rendezés biztonságosan
        df = df.sort_values('Sorrend')
    
        f_reg, f_bold = register_fonts()
        buf = BytesIO()
        p = canvas.Canvas(buf, pagesize=A4)
        lw, lh = 70 * mm, 42.42 * mm
        inner_m = 5.5 * mm
    
        order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9, encoding='utf-8')
        promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1, encoding='utf-8')
    
        total_slots = math.ceil(len(df) / 21) * 21
    
        for i in range(total_slots):
            idx = i % 21
            if idx == 0 and i > 0: p.showPage()
            col, row_i = idx % 3, 6 - (idx // 3)
            x, y = col * lw, row_i * lh
    
            if i < len(df):
                r = df.iloc[i]
                top_y = y + lh - inner_m
    
                # Hétvégi jelölés (szürke sáv az ügyintéző alatt)
                if r.get('Hétvégi'):
                    p.saveState()
                    p.setFillColor(colors.lightgrey)
                    p.rect(x + 1 * mm, top_y - 8.5 * mm, lw - 2 * mm, 4.5 * mm, fill=1, stroke=0)
                    p.restoreState()
    
                # 1. SOR: Sorszám és ID
                sorrend_val = int(r['Sorrend']) if pd.notnull(r['Sorrend']) else (i + 1)
                p.setFont(f_bold, 10);
                p.drawString(x + inner_m, top_y - 3 * mm, f"#{sorrend_val}")
                p.setFont(f_reg, 8);
                p.drawRightString(x + lw - inner_m, top_y - 3 * mm, f"ID: {r.get('ID', 'N/A')}")
    
                # 2. SOR: Ügyintéző és Telefon
                p.setFont(f_bold, 9);
                p.drawString(x + inner_m, top_y - 8 * mm, str(r.get('Ügyintéző', ''))[:28])
                p.setFont(f_reg, 8);
                p.drawRightString(x + lw - inner_m, top_y - 8 * mm, str(r.get('Telefon', '')))
    
                # 3. SOR: Cím
                p.setFont(f_reg, 7.5);
                p.drawString(x + inner_m, top_y - 12 * mm, str(r.get('Cím', ''))[:45])
    
                # 4. KÖZÉPSŐ RÉSZ: Rendelések összevonva
                rendeles_text = str(r.get('Rendelés_Full', r.get('Rendelés', '')))
                para = Paragraph(rendeles_text, order_s)
                para.wrap(lw - 2 * inner_m, 12 * mm)
                para.drawOn(p, x + inner_m, y + inner_m + 7 * mm)  # Kicsit feljebb toltam a pénznek
    
                # --- PÉNZ ÉS DARABSZÁM (Az etikett alja) ---
                # Megjelenítjük a pénzt, ha van "Ft" benne (PDF-ből jött), egyébként üresen hagyjuk
                penz_megjelenites = str(r.get('Pénz', ''))
                if "Ft" not in penz_megjelenites: penz_megjelenites = ""
    
                p.setFont(f_bold, 10);
                p.drawString(x + inner_m, y + inner_m + 1 * mm, penz_megjelenites)
                p.setFont(f_bold, 9);
                p.drawRightString(x + lw - inner_m, y + inner_m + 1 * mm, f"{int(r.get('Összesen', 0))} db")
    
                # Vonal és Futár adatok
                p.setDash(1, 0)
                p.setLineWidth(0.2)
                p.line(x + 5 * mm, y + 4.5 * mm, x + lw - 5 * mm, y + 4.5 * mm)
                p.setFont(f_reg, 6);
                p.drawCentredString(x + lw / 2, y + 2 * mm, f"Futár: {fn} | {ft}")
    
            else:
                # Marketing etikett változatlanul
                p.setDash(1, 0)
                m_text = (
                    f"<font size='10.5' name='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                    f"Új Ügyfeleink részére!<br/><br/>"
                    f"<b>Rendelés leadás:</b><br/>"
                    f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                    f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető<br/>területi képviselőnk által</b></font>"
                )
                para = Paragraph(m_text, promo_s)
                pw, ph = para.wrap(lw - 6 * mm, lh - 6 * mm)
                para.drawOn(p, x + (lw - pw) / 2, y + (lh - ph) / 2)
    
        p.save();
        buf.seek(0);
        return buf
    
    # --- 3. RÉSZ: PDF GENERÁLÓK ÉS ADATSZERKESZTŐ ---
    
    def create_manifest_pdf(df, fn, meta_list):
        """Menetterv készítése csoportosítással, oldalszámozással és DejaVu fontokkal"""
        df = df.sort_values('Sorrend')
        f_reg, f_bold = register_fonts()  # Itt már a DejaVu-t fogja adni
        buf = BytesIO()
    
        # Alsó margót kicsit megnöveljük az oldalszámnak (20mm)
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10 * mm, leftMargin=10 * mm, topMargin=20 * mm,
                                bottomMargin=20 * mm)
    
        # Címek kigyűjtése a csoportosítás ellenőrzéséhez
        all_addresses = df['Cím'].tolist()
    
        # --- ÚJ RÉSZ: Halmaz a már kiírt pénzösszegek követésére ---
        mar_kiirt_osszegek = set()
        # ---------------------------------------------------------
    
        jaratok = ", ".join(sorted(list(set([str(m.get('jarat', '')) for m in meta_list if m.get('jarat')]))))
        ev = meta_list[0].get('year', '') if meta_list else ""
        het = meta_list[0].get('week', '') if meta_list else ""
        nap = meta_list[0].get('day', '') if meta_list else ""
        fejlec_text = f"MENETTERV - Járat: {jaratok} | {ev}. év, {het}. hét | {nap}"
    
        elements = []
    
        # Stílusok definiálása ékezet-kezeléssel
        s_normal = ParagraphStyle('L', fontName=f_reg, fontSize=8, encoding='utf-8')
        s_bold_center = ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1, encoding='utf-8')
        s_order = ParagraphStyle('O', fontName=f_reg, fontSize=7, encoding='utf-8')
    
        data = [[
            Paragraph("<b>#</b>", s_bold_center),
            Paragraph("<b>NÉV / CÍM / INFÓ</b>", s_bold_center),
            Paragraph("<b>[ ]</b>", s_bold_center),
            Paragraph("<b>PÉNZ</b>", s_bold_center),
            Paragraph("<b>TEL</b>", s_bold_center),
            Paragraph("<b>RENDELÉS</b>", s_bold_center),
            Paragraph("<b>DB</b>", s_bold_center)
        ]]
    
        t_style = [
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (-1, 0), (-1, -1), 'CENTER'),
        ]
    
        for i, (_, r) in enumerate(df.iterrows()):
            # CSOPORTOSÍTÁS: Megnézzük, hányszor szerepel a cím
            is_group = all_addresses.count(r['Cím']) > 1
            group_tag = "<b><font color='blue'>▲ CSOPORT </font></b>" if is_group else ""
    
            note = str(r.get('Megjegyzés', ''))
            note_html = f"<br/><font color='red'><b>{note}</b></font>" if note and note.lower() != 'nan' and note.strip() != "" else ""
    
            # --- MÓDOSÍTOTT RÉSZ: Duplikált pénz kezelése ---
            nyers_penz = str(r['Pénz']).lower()
            ugyfel_kulcs = r['Ügyintéző']  # Az azonosításhoz az ügyintéző nevét használjuk (vagy ha van ID, az még jobb)
    
            if nyers_penz in ["0 ft", "0", "nan"] or ugyfel_kulcs in mar_kiirt_osszegek:
                penz = ""
            else:
                penz = str(r['Pénz'])
                mar_kiirt_osszegek.add(ugyfel_kulcs)  # Elmentjük, hogy ennél az ügyfélnél már kiírtuk a pénzt
            # -----------------------------------------------
    
            data.append([
                f"{int(r['Sorrend'])}",
                Paragraph(f"{group_tag}<b>{r['Ügyintéző']}</b><br/><font size='7'>{r['Cím']}</font>{note_html}", s_normal),
                "[ ]",
                Paragraph(f"<b>{penz}</b>", s_bold_center),
                str(r['Telefon']),
                Paragraph(str(r['Rendelés_Full']), s_order),
                f"{int(r['Összesen'])}"
            ])
    
            # Ha csoport, kap egy nagyon halvány háttérszínt a sor
            if is_group:
                t_style.append(('BACKGROUND', (0, i + 1), (-1, i + 1), colors.whitesmoke))
    
        t = Table(data, colWidths=[10 * mm, 60 * mm, 10 * mm, 20 * mm, 25 * mm, 55 * mm, 10 * mm], repeatRows=1)
        t.setStyle(TableStyle(t_style))
        elements.append(t)
    
        # OLDALSZÁMOZÁS ÉS FEJLÉC FUNKCIÓ
        def add_header_footer(canvas, doc):
            canvas.saveState()
            # Fejléc (minden oldalon)
            canvas.setFont(f_bold, 11)
            canvas.drawString(10 * mm, A4[1] - 12 * mm, fejlec_text)
            canvas.setFont(f_reg, 9)
            canvas.drawRightString(A4[0] - 10 * mm, A4[1] - 12 * mm, f"Futár: {fn}")
    
            # Oldalszám (minden oldalon alul középen)
            page_num = f"{canvas.getPageNumber()}. oldal"
            canvas.setFont(f_reg, 8)
            canvas.drawCentredString(A4[0] / 2, 10 * mm, page_num)
            canvas.restoreState()
    
        # Build indítása a fejléc/lábléc funkcióval
        doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
        buf.seek(0);
        return buf
    
    
    def create_raklista_pdf(df, jarat_info, meta_list):
        f_reg, f_bold = register_fonts()
        buf = BytesIO()
        # Margók minimalizálása az oldalszéleken is
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=7 * mm, bottomMargin=12 * mm, leftMargin=8 * mm,
                                rightMargin=8 * mm)
        etlap = st.session_state.get('etlap', {})
    
        # Napok és időszak kinyerése
        dates_str = ""
        if meta_list:
            m = meta_list[0]
            # Ha a 'days' kulcs létezik, azt írjuk be a zárójelbe
            napok = m.get('days', '')
            dates_str = f"{m.get('year', '')}. {m.get('week', '')}. hét ({napok})"
    
        # 1. Adatgyűjtés
        counts = {}
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
        st.subheader("📦 Adatok ellenőrzése és Sorrendezés")
    
        # 1. KULCS INICIALIZÁLÁSA (Ha még nem létezne)
        if 'editor_key' not in st.session_state:
            st.session_state.editor_key = 0
    
        # 2. ADATSZERKESZTŐ (Tizedesvessző barát konfigurációval)
        edited_df = st.data_editor(
            st.session_state.mdf,
            key=f"editor_v_{st.session_state.editor_key}", # Kényszerített frissítéshez
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "Sorrend": st.column_config.NumberColumn(
                    "Sorrend",
                    help="Tizedesekhez használj pontot! (pl. 1.5)",
                    min_value=0,
                    step=0.1,  # Ez engedi a tizedeseket
                    format="%.1f", # Így fog megjelenni
                ),
                "ID": st.column_config.TextColumn("Azonosító", disabled=True),
            }
        )

def main():
    # --- UI ---
    st.set_page_config(page_title="Interfood Logisztika", layout="wide")
    if 'mdf' not in st.session_state: st.session_state.mdf = None
    if 'meta_data' not in st.session_state: st.session_state.meta_data = []
    if 'etlap' not in st.session_state: st.session_state.etlap = {}
    
    with st.sidebar:
        st.header("⚙️ Kezelés")
        c_n = st.text_input("Futár Neve", "Szűcs István")
        c_p = st.text_input("Telefonszám", "+36 20 886 8971")
        st.divider()
        up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
    
        # ... (a kód eleje változatlan) ...
    
        if up_files and st.button("🚀 FELDOLGOZÁS"):
            all_rows = []    # <--- EZ A SOR HIÁNYZOTT! Ez hozza létre a listát.
            all_meta = []
            
            for uploaded_file in up_files:
                rows, meta = parse_interfood_pdf(uploaded_file)
                all_rows.extend(rows)  # Most már nem lesz NameError, mert létezik az all_rows
                all_meta.extend(meta)
    
            if all_rows:
                # Innen megy tovább a kódod...
                df = pd.DataFrame(all_rows)
                # Itt jöhet a táblázat megjelenítése...
                # Innen folytatódik a megjelenítés és a mentés...
            
            for f in up_files:
                rows, meta = parse_interfood_pdf(f)
                if rows:
                    all_rows.extend(rows)
                # Figyelem: extend-et használunk, és csak ha nem üres!
                if meta:
                    all_meta.extend(meta)
        
                # CSAK AKKOR LÉPÜNK TOVÁBB, HA VAN ADAT
                if all_rows and all_meta:
                    # Biztonsági mentés: ha az első elem valamiért mégis rossz lenne
                    try:
                        first_m = all_meta[0]
                        y = first_m.get('year', '2026')
                        w = first_m.get('week', '1')
                    except (IndexError, TypeError):
                        y, w = '2026', '1'
    
                st.session_state.meta_data = all_meta
                
                # Étlepadatok lekérése (Péntek=5, Szombat=6)
                p_map = get_etlap_dict(y, w, 5)
                sz_map = get_etlap_dict(y, w, 6)
                
                final_rows = merge_data(all_rows, p_map, sz_map)
                
                df = pd.DataFrame(final_rows)
                # Alapértelmezett sorrend: az eredeti PDF sorrendje
                df['Sorrend'] = range(1, len(df) + 1)
                
                st.session_state.mdf = df
                st.success(f"Sikeres feldolgozás: {len(df)} sor betöltve!")
                st.rerun()
            else:
                st.error("Nem sikerült adatokat kinyerni a PDF-ből. Ellenőrizd a fájlt!")
            mdf = merge_data(all_rows)
    
            # --- AUTOMATIKUS ÉTLAP KEZELÉS (Most már a gombon belül!) ---
            if all_meta and mdf is not None:
                y, w = all_meta[0]['year'], all_meta[0]['week']
                with st.spinner(f"Pénteki és Szombati étlapok betöltése..."):
                    # JAVÍTVA: get_etlap_dict-et hívunk, mert így nevezted el fent!
                    etlap = get_etlap_dict(y, w)
                    st.session_state.etlap = etlap
    
                    if etlap:
                        for idx, row in mdf.iterrows():
                            total_sum = 0
                            # Az ID-ból (pl. P-410511) kinyerjük az első betűt
                            row_id = str(row.get('ID', ''))
                            day_prefix = row_id[0] if row_id else "P"
    
                            # A rendelés sztringből kiszedjük a kódokat
                            order_string = str(row['Rendelés_Full'])
                            matches = re.findall(r'(\d+)-([A-Z0-9*+]+)', order_string)
    
                            for qty, code in matches:
                                clean_c = code.replace('*', '').strip().upper()
                                # Keresés: pl. "P_A" vagy "Z_AK"
                                lookup_key = f"{day_prefix}_{clean_c}"
    
                                if lookup_key in etlap:
                                    total_sum += int(qty) * etlap[lookup_key]['ar']
    
                            if total_sum > 0:
                                mdf.at[idx, 'Pénz'] = f"{total_sum} Ft"
    
                    st.session_state.mdf = mdf
                    st.session_state.meta_data = all_meta
                    st.rerun()
    
        # --- CSV Visszatöltés (Javított, típusbiztos verzió) ---
        st.divider()
        st.subheader("2. CSV Visszatöltés")
        up_csv = st.file_uploader("Exportált CSV betöltése", type=['csv'], key="csv_fixer")
    
        if up_csv and st.button("📥 SORREND FRISSÍTÉSE"):
            try:
                # 1. CSV beolvasása
                loaded_df = pd.read_csv(up_csv)
    
                if st.session_state.mdf is not None:
                    current_df = st.session_state.mdf.copy()
    
                    # 2. A PDF adatok ID-jéből csak a számokat tartjuk meg (P-410511 -> 410511)
                    current_df['match_id'] = current_df['ID'].astype(str).str.replace(r'\D', '', regex=True)
    
                    # 3. A CSV ID-jéből is biztosítjuk, hogy csak szám maradjon (stringként)
                    loaded_df['match_id'] = loaded_df['ID'].astype(str).str.replace(r'\D', '', regex=True)
    
                    # 4. Létrehozunk egy "szótárt" a párosításhoz: { '410511': 1.0, '489751': 2.0 ... }
                    sorrend_dict = loaded_df.set_index('match_id')['Sorrend'].to_dict()
    
                    # 5. Sorrend kiosztása az új táblázatban
                    if 'Sorrend' in current_df.columns:
                        current_df = current_df.drop(columns=['Sorrend'])
    
                    current_df['Sorrend'] = current_df['match_id'].map(sorrend_dict)
    
                    # 6. Tisztítás és mentés
                    current_df['Sorrend'] = pd.to_numeric(current_df['Sorrend'], errors='coerce').fillna(999).astype(float)
                    st.session_state.mdf = current_df.sort_values('Sorrend').drop(columns=['match_id'])
    
                    st.success("A sorrend sikeresen párosítva az ügyfélkódok alapján!")
                    st.rerun()
                else:
                    st.error("Előbb olvasd be a PDF-et!")
            except Exception as e:
                st.error(f"Hiba a beolvasáskor: {e}")
    
        # --- INFÓ PANEL ---
        if st.session_state.meta_data:
            st.divider()
            m = st.session_state.meta_data[0]
            st.info(f"📅 {m.get('year')}.{m.get('week')}. hét, {m.get('day')}")
            if not st.session_state.etlap:
                st.warning("⚠️ Az étlap üres!")
            else:
                st.success(f"✅ {len(st.session_state.etlap)} étel betöltve.")
        # ----------------------------------------------------------------
     
        # 3. MENTÉS ÉS ÚJRARENDEZÉS GOMB
        if st.button("💾 MÓDOSÍTÁSOK MENTÉSE ÉS ÚJRARENDEZÉS"):
            temp_df = edited_df.copy()
            
            # Tisztítjuk az ID-t
            temp_df['temp_id'] = temp_df['ID'].str.replace(r'[^\d]', '', regex=True).replace('', '0').astype(int)
            
            # --- EZT A SORT SZÚRD BE MOST: ---
            temp_df['Pénz'] = temp_df['Pénz'].str.replace(r'[^\d-]', '', regex=True).replace('', '0')
            # --------------------------------
            
            # Sorrend kényszerítése szám típusra
            temp_df['Sorrend'] = pd.to_numeric(temp_df['Sorrend'], errors='coerce').fillna(999).astype(float)
            
            # Fizikai sorrendezés az adatkeretben (hogy a PDF is jó legyen)
            temp_df = temp_df.sort_values(by='Sorrend').reset_index(drop=True)
            
            # Mentés a központi állapotba
            st.session_state.mdf = temp_df
            # Frissítjük a súlyokat is a merge_data függvény számára
            st.session_state.weights = dict(zip(temp_df['ID'].astype(str), temp_df['Sorrend']))
            
            # Kulcs növelése -> a táblázat ugrani fog az új sorrendbe
            st.session_state.editor_key += 1
            
            st.success("Sorrend elmentve és lista újrarendezve!")
            st.rerun()
    
        st.divider()
        
        # 4. LETÖLTÉSEK (Biztonságos j_info kinyeréssel)
        meta = st.session_state.meta_data
        j_info = ", ".join(list(set([str(m.get('jarat', '')) for m in meta if m.get('jarat')]))) if meta else "Nincs adat"
        
        c1, c2, c3, c4 = st.columns(4)
    
        c1.download_button("📄 ETIKETTEK (PDF)", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf", use_container_width=True)
        c2.download_button("📋 MENETTERV (PDF)", create_manifest_pdf(edited_df, c_n, meta), "menetterv.pdf", use_container_width=True)
        c3.download_button("📦 RAKLISTA (PDF)", create_raklista_pdf(edited_df, j_info, meta), f"raklista_{j_info}.pdf", use_container_width=True)
    
        csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
        c4.download_button("📊 CSV EXPORT", csv_data, "szallitasi_lista.csv", "text/csv", use_container_width=True)

if __name__ == "__main__":
    main()
