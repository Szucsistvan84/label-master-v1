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
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

# ==========================================
# 1. STÍLUSOK ÉS BETŰTÍPUSOK (DIZÁJN)
# ==========================================
def register_fonts():
    try:
        # Ha megvan a fájl, ezt használja. Ha nincs, alapértelmezett Helvetical-t.
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        return "DejaVu", "DejaVu-Bold"
    except:
        return "Helvetica", "Helvetica-Bold"

# ==========================================
# 2. ADATBÁNYÁSZAT (PDF ÉS EXCEL)
# ==========================================
def get_live_menu(year, week, day_name):
    """Letölti az aktuális heti étlapot az Interfood oldaláról."""
    excel_url = f"https://ia.interfood.hu/api/v3/excel-export?year={year}&week={week}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    menu_map = {}
    day_to_col = {'Hétfő': 1, 'Kedd': 2, 'Szerda': 3, 'Csütörtök': 4, 'Péntek': 5, 'Szombat': 6}
    target_col = day_to_col.get(day_name, 3) 

    try:
        response = requests.get(excel_url, headers=headers, timeout=15)
        if response.status_code == 200:
            df = pd.read_excel(BytesIO(response.content), engine='openpyxl')
            current_category = "Egyéb"
            for i in range(len(df)):
                row = df.iloc[i]
                col_a = str(row.iloc[0]).strip()
                if col_a and col_a != 'nan' and " - " in col_a:
                    parts = col_a.split(" - ")
                    code = parts[0].strip()
                    current_category = parts[1].strip()
                    name_on_day = str(row.iloc[target_col]).strip()
                    if name_on_day and name_on_day != 'nan' and len(name_on_day) > 2:
                        try:
                            next_row = df.iloc[i+1]
                            p_str = re.sub(r'[^\d]', '', str(next_row.iloc[target_col]))
                            if p_str:
                                # Itt tároljuk el az adatokat az Excelből
                                menu_map[code] = {'nev': name_on_day[:60], 'ar': int(p_str), 'kategoria': current_category, 'excel_order': i}
                        except: continue
    except: pass
    return menu_map

def parse_interfood_pdf(pdf_file):
    """Kinyeri a PDF-ből a címeket és a rendeléseket."""
    rows = []
    meta = {'year': None, 'week': None, 'day': None, 'jarat': "????"}
    with pdfplumber.open(pdf_file) as pdf:
        first_txt = pdf.pages[0].extract_text() or ""
        # Járatszám: az első számsor a pontig (pl: 4002.)
        jarat_m = re.search(r'^(\d+)\.', first_txt)
        if jarat_m: meta['jarat'] = jarat_m.group(1)
        
        y_m = re.search(r'Év:\s*(\d{4})', first_txt); w_m = re.search(r'Hét:\s*(\d{1,2})', first_txt); d_m = re.search(r'Nap:\s*([a-zA-Záéíóöőúüű]+)', first_txt)
        if y_m: meta['year'] = y_m.group(1); meta['week'] = w_m.group(1); meta['day'] = d_m.group(1)

        for page in pdf.pages:
            words = page.extract_words()
            lines = {}
            for w in words:
                y = round(w['top'], 1)
                for ey in lines:
                    if abs(y - ey) < 3: lines[ey].append(w); break
                else: lines[y] = [w]
            
            for y in sorted(lines.keys()):
                line_words = sorted(lines[y], key=lambda x: x['x0'])
                text_ws = " ".join([w['text'] for w in line_words])
                u_code_m = re.search(r'([HKSCPZ]-[0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                # Ügyfélkód kinyerése (ID)
                uid = str(u_code_m.group(0).split('-')[-1])
                b3 = " ".join([w['text'] for w in line_words if 150 <= w['x0'] < 355]) # Cím oszlop
                b4 = " ".join([w['text'] for w in line_words if 355 <= w['x0'] < 490]) # Név oszlop
                
                clean_name = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ \-]', '', b4).strip()
                tel_m = re.search(r'(\d{2}/\d{6,7})', text_ws.replace(" ", ""))
                addr_m = re.search(r'(\d{4})', b3)
                address = b3[addr_m.start():].strip() if addr_m else b3
                
                # Fizetendő összeg keresése
                money_val = "0 Ft"
                all_y = sorted(lines.keys())
                curr_idx = all_y.index(y)
                if curr_idx + 1 < len(all_y):
                    next_line_text = " ".join([w['text'] for w in sorted(lines[all_y[curr_idx+1]], key=lambda x: x['x0'])])
                    m_match = re.search(r'(-?\s?\d[\d\s]*\s*Ft)', next_line_text)
                    if m_match: money_val = m_match.group(1).strip()
                
                # Rendelések (pl. 1-R2*)
                raw_orders = re.findall(r'(\d+-[A-Z][A-Z0-9*+]*)', text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    try:
                        q = int(re.sub(r'\D', '', o.split('-')[0])[-1])
                        v_o.append(f"{q}-{o.split('-')[1]}"); sq += q
                    except: continue
                
# ... (itt van a v_o és sq kiszámítása)
                
                if v_o:
                    # Rövidítjük a napot (Péntek -> Pé, Csütörtök -> Csü)
                    nap_rovid = meta['day'][:3] if meta['day'] else ""
                    rendeles_szoveg = f"{nap_rovid}: {', '.join(v_o)}"
                    
                    rows.append({
                        "ID": uid, 
                        "Járat": meta['jarat'], 
                        "Ügyintéző": clean_name, 
                        "Cím": address, 
                        "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": rendeles_szoveg,
                        "Pénz": money_val, 
                        "Összesen": sq
                    })
    return rows, meta  # Ez a sor már a függvény legszélén van!

# ==========================================
# 3. PDF GENERÁLÁS (RAJZOLÁS)
# ==========================================
def create_label_pdf(df, futar_nev, futar_tel):
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.4*mm 
    inner_m = 5.5*mm
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9)
    
    for i in range(math.ceil(len(df) / 21) * 21):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
            # SORSZÁM (Kisebb: 8-as méret)
            p.setFont(f_bold, 8) 
            p.drawString(x + inner_m, top_y - 3*mm, f"#{r['Sorrend']}") 
            
            # ID (Jobb felső sarok)
            p.setFont(f_reg, 7)
            p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            
            # NÉV ÉS TELEFONSZÁM (Egy sorban)
            p.setFont(f_bold, 9)
            p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:22])
            
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            
            # CÍM (7.5-es méret)
            p.setFont(f_reg, 7.5)
            p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            # RENDELÉS (Bekezdés típusú szöveg)
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm)
            para.drawOn(p, x + inner_m, y + inner_m + 7*mm)
            
            # ALSÓ INFÓ SÁV (Járatszám + Futár adatok)
            p.setFont(f_bold, 6)
            p.drawCentredString(x + lw/2, y + inner_m - 1.5*mm, f"[{r['Járat']}] Futár: {futar_nev} | {futar_tel}")
            
            # FIZETENDŐ ÉS DB
            m_val = re.sub(r'[^\d-]', '', str(r['Pénz']))
            if m_val != "0":
                p.setFont(f_bold, 10)
                p.drawString(x + inner_m, y + inner_m + 3*mm, f"FIZET: {r['Pénz']}")
            
            p.setFont(f_bold, 9)
            p.drawRightString(x + lw - inner_m, y + inner_m + 3*mm, f"{r['Összesen']} db")
    p.save(); buf.seek(0); return buf

def create_manifest_pdf(df, futar_nev):
    """Legyártja a rakodási lista PDF-et."""
    f_reg, f_bold = register_fonts()
    buf = BytesIO(); p = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cell_s = ParagraphStyle('Cell', fontName=f_reg, fontSize=9, leading=11)
    head_s = ParagraphStyle('Head', fontName=f_bold, fontSize=10, alignment=1)

    all_codes = []
    for r in df['Rendelés_Full']: 
        all_codes.extend(re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r)))
    
    counts = {}
    for c, code in all_codes: counts[code] = counts.get(code, 0) + int(c)
    
    menu = st.session_state.get('live_menu', {})
    sum_rows = []
    last_cat = None
    # ABC sorrendben megyünk végig a kódokon
    for code in sorted(counts.keys()):
        # CSILLAGOS FIX: Az Excelben csillag nélkül keressük (R2* -> R2)
        lookup_code = code.replace('*', '')
        info = menu.get(lookup_code, {'nev': 'Ismeretlen étel', 'kategoria': 'Egyéb'})
        
        if info['kategoria'] != last_cat:
            sum_rows.append([Paragraph(f"<b>--- {info['kategoria']} ---</b>", cell_s), ""])
            last_cat = info['kategoria']
        sum_rows.append([Paragraph(f"<b>{code}</b> - {info['nev']}", cell_s), Paragraph(str(counts[code]), head_s)])

    p.setFont(f_bold, 14); p.drawString(15*mm, h - 15*mm, f"RAKODÁSI LISTA - {futar_nev}")
    # Táblázat rajzolása
    t = Table([[Paragraph("Étel megnevezése", head_s), Paragraph("DB", head_s)]] + sum_rows, colWidths=[145*mm, 25*mm])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (1,0), colors.lightgrey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]))
    
    tw, th = t.wrap(w - 30*mm, h - 40*mm)
    t.drawOn(p, 15*mm, h - 25*mm - th)
    p.save(); buf.seek(0); return buf

# ==========================================
# 4. A PROGRAM VEZÉRLÉSE (UI)
# ==========================================
st.set_page_config(page_title="Interfood Logisztika", layout="wide")

if 'weights' not in st.session_state: st.session_state.weights = {}
if 'notes' not in st.session_state: st.session_state.notes = {}
if 'mdf' not in st.session_state: st.session_state.mdf = None

with st.sidebar:
    st.header("👤 Beállítások")
    f_name = st.text_input("Név", "Szűcs István")
    f_phone = st.text_input("Tel", "+36 20 886 8971")
    st.divider()
    
    csv_file = st.file_uploader("Tegnapi CSV betöltése", type="csv")
    if csv_file:
        try:
            imp = pd.read_csv(csv_file)
            # ID és Sorrend (Súly) összekötése
            st.session_state.weights = dict(zip(imp['ID'].astype(str), imp['Sorrend'].astype(float)))
            if 'Megjegyzés' in imp.columns:
                st.session_state.notes = dict(zip(imp['ID'].astype(str), imp['Megjegyzés'].fillna("")))
            st.success("✅ Sorrend betöltve!")
        except: st.error("Hiba a CSV-vel!")

    pdfs = st.file_uploader("Napi PDF-ek", accept_multiple_files=True)
    if pdfs and st.button("📊 FELDOLGOZÁS"):
        all_raw_data = []
        for f in pdfs:
            rows, meta = parse_interfood_pdf(f)
            all_raw_data.extend(rows)
            if meta['year']:
                st.session_state.live_menu = get_live_menu(meta['year'], meta['week'], meta['day'])
        
        if all_raw_data:
            df = pd.DataFrame(all_raw_data)
            merged_rows = []
            for uid, group in df.groupby("ID", sort=False):
                base = group.iloc[0].copy().to_dict()
                base['Rendelés_Full'] = ", ".join(group['Rendelés'].astype(str).tolist())
                base['Összesen'] = group['Összesen'].sum()
                # Pénz szummázása (ID-nként)
                m_list = [int(re.sub(r'[^\d-]', '', str(m)) or 0) for m in group['Pénz'].tolist()]
                base['Pénz'] = f"{sum(m_list)} Ft"
                # Súlyozás visszakeresése ID alapján
                uid_s = str(uid).strip()
                base['Sorrend'] = st.session_state.weights.get(uid_s, 999.0)
                base['Megjegyzés'] = st.session_state.notes.get(uid_s, "")
                merged_rows.append(base)
            
            # Eredmény elmentése: Súly, majd Járatszám szerinti sorrendben
            st.session_state.mdf = pd.DataFrame(merged_rows).sort_values(['Sorrend', 'Járat'])
            st.rerun()

# --- TÁBLÁZAT ÉS EXPORT ---
if st.session_state.mdf is not None:
    st.subheader("📍 Menetlevél és Sorrendezés")
    
    # Oszlopok sorrendje a kijelzőn
    disp_cols = ['Sorrend', 'ID', 'Járat', 'Ügyintéző', 'Cím', 'Rendelés_Full', 'Összesen', 'Pénz', 'Megjegyzés']
    
    # Itt tudod szerkeszteni a táblázatot
    edited_df = st.data_editor(
        st.session_state.mdf[disp_cols],
        hide_index=True,
        use_container_width=True,
        column_config={
            "Sorrend": st.column_config.NumberColumn("Súly", format="%.1f"),
            "ID": st.column_config.TextColumn("ID", disabled=True),
            "Járat": st.column_config.TextColumn("Járat", disabled=True),
            "Rendelés_Full": st.column_config.TextColumn("Rendelés", disabled=True),
        }
    )
    
    if st.button("✅ SORREND ÉS INFÓK MENTÉSE (ÚJRASORSZÁMOZÁS)"):
        # Sorba rakjuk a beírt súlyok szerint
        final_df = edited_df.sort_values(by='Sorrend').reset_index(drop=True)
        # Újrasorszámozzuk (1, 2, 3...)
        final_df['Sorrend'] = range(1, len(final_df) + 1)
        final_df['Sorrend'] = final_df['Sorrend'].astype(float)
        
        # Elmentjük a memóriába, hogy legközelebb is emlékezzen rá
        for _, r in final_df.iterrows():
            st.session_state.weights[str(r['ID'])] = r['Sorrend']
            st.session_state.notes[str(r['ID'])] = r['Megjegyzés']
        
        st.session_state.mdf = final_df
        st.success("Sorrend véglegesítve!")
        st.rerun()

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("📄 ETIKETTEK (PDF)", create_label_pdf(st.session_state.mdf, f_name, f_phone), "etikettek.pdf", use_container_width=True)
    with c2:
        st.download_button("📋 RAKLISTA (PDF)", create_manifest_pdf(st.session_state.mdf, f_name), "rakodasi_lista.pdf", use_container_width=True)
    with c3:
        # Ez az a CSV, amit holnap be kell töltened az importálóba!
        csv_data = st.session_state.mdf.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 EXPORT CSV (MENTÉS)", csv_data, "menetterv_mentes.csv", use_container_width=True)
