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
from reportlab.platypus import SimpleDocTemplate, Spacer, Paragraph, Table, TableStyle

# --- ALAPBEÁLLÍTÁSOK ---
PHONE_PAT = r'(\+?\d{1,2}[/\s-]?)?(\d{2}[/\s-]?)?\d{3}[/\s-]?\d{4}'
ORDER_PAT = r'\d+-[A-Z][A-Z0-9*+]*'

def register_fonts():
    """Regisztrálja a GitHub-ra feltöltött DejaVu betűtípusokat"""
    try:
        # Bold (Félkövér) változat regisztrálása
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', 'DejaVuSans-Bold.ttf'))
        # Regular (Normál) változat regisztrálása
        pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
        return 'DejaVu', 'DejaVu-Bold'
    except Exception as e:
        # Ha valamiért nem találná a fájlt, visszaugrik alapértelmezettre, hogy ne álljon le az app
        st.warning(f"Nem sikerült betölteni a DejaVu betűtípust: {e}. Helvetica-t használok.")
        return 'Helvetica', 'Helvetica-Bold'

def clean_name_field(text):
    """
    SZIGORÚ SZŰRÉS: Eltávolítja a nevekből a telefonszámokat, 
    cikkszámokat és minden szemetet. Csak betűket hagy meg.
    """
    if not text: return ""
    # 1. Telefonszámok törlése
    text = re.sub(r'\d{2,}/?\d{3,}-?\d{3,}', '', text)
    # 2. Rendeléskódok (pl. 2-L3K) törlése
    text = re.sub(r'\d+-[A-Z0-9*+]+', '', text)
    # 3. CSAK betűk, magyar ékezetek és szóközök megtartása
    text = re.sub(r'[^a-zA-ZáéíóöőúüűÁÉÍÓÖŐÚÜŰ\s\-]', '', text)
    # 4. Tisztítás
    return " ".join(text.split()).strip()

def parse_interfood_pdf(pdf_file):
    rows = []
    metadata = {'year': None, 'week': None, 'day': None, 'jarat': None}
    with pdfplumber.open(pdf_file) as pdf:
        # Fejléc adatok kinyerése az első oldalról
        header_text = pdf.pages[0].extract_text()
        if header_text:
            j_m = re.search(r'(\d{4})\.\s*járat', header_text)
            y_m = re.search(r'Év:\s*(\d{4})', header_text)
            w_m = re.search(r'Hét:\s*(\d{1,2})', header_text)
            d_m = re.search(r'Nap:\s*([^I\n]+)', header_text)
            if j_m: metadata['jarat'] = j_m.group(1)
            if y_m: metadata['year'] = y_m.group(1)
            if w_m: metadata['week'] = w_m.group(1)
            if d_m: metadata['day'] = d_m.group(1).strip()

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
                u_code_m = re.search(r'([HKSCPZ][.-][0-9]{5,7})', text_ws)
                if not u_code_m: continue
                
                uid = re.sub(r'\D', '', u_code_m.group(0))
                prefix = u_code_m.group(0)[0]
                
                # Név kinyerése a jobb oldali sávból (360-520 koordináta)
                b4_words = [w['text'] for w in line_words if 360 <= w['x0'] < 520]
                clean_name = clean_name_field(" ".join(b4_words))
                
                # Cím kinyerése a középső sávból
                b3_words = [w['text'] for w in line_words if 140 <= w['x0'] < 360]
                b3_full = " ".join(b3_words)
                addr_m = re.search(r'(\d{4})', b3_full)
                address = b3_full[addr_m.start():].strip() if addr_m else b3_full
                
                tel_m = re.search(PHONE_PAT, text_ws.replace(" ", ""))
                raw_orders = re.findall(ORDER_PAT, text_ws)
                v_o, sq = [], 0
                for o in raw_orders:
                    if any(c.isalpha() for c in o.split('-')[-1]):
                        v_o.append(o)
                        try: sq += int(re.sub(r'\D', '', o.split('-')[0]))
                        except: pass
                
                if v_o:
                    rows.append({
                        "Prefix": prefix, "ID": uid, "Ügyintéző": clean_name, 
                        "Cím": address, "Telefon": tel_m.group(0) if tel_m else "", 
                        "Rendelés": ", ".join(v_o), "Pénz": "0 Ft", "Összesen": sq
                    })
    return rows, metadata

# --- 2. RÉSZ: ÖSSZEFÉSÜLÉS ÉS CSV KEZELÉS ---

def merge_data(raw_rows):
    if not raw_rows: return None
    # Helyi szótár a napok nevéhez
    L_DAYS = {'H': 'Hé', 'K': 'Ke', 'S': 'Sze', 'C': 'Csü', 'P': 'Pé', 'Z': 'Szo'}
    df = pd.DataFrame(raw_rows)
    merged = []
    
    # ID alapján csoportosítunk (egy ügyfél minden napja egy sorba kerül)
    for uid, group in df.groupby("ID", sort=False):
        base = group.iloc[0].copy().to_dict()
        o_p, has_weekend = [], False
        
        for pfix in ['H', 'K', 'S', 'C', 'P', 'Z']:
            day_group = group[group['Prefix'] == pfix]
            items = day_group['Rendelés'].tolist()
            if items: 
                o_p.append(f"{L_DAYS.get(pfix, pfix)}: {', '.join(items)}")
                if pfix == 'Z': has_weekend = True
        
        base['Rendelés_Full'] = " | ".join(o_p)
        base['Összesen'] = group['Összesen'].sum()
        base['Hétvégi'] = has_weekend 
        base['Megjegyzés'] = ""
        merged.append(base)
    
    res = pd.DataFrame(merged)
    if 'Sorrend' not in res.columns:
        res['Sorrend'] = range(1, len(res) + 1)
        res['Sorrend'] = res['Sorrend'].astype(float)
    return res

# --- UI ÉS BEÁLLÍTÁSOK ---

st.set_page_config(page_title="Interfood Logisztika", layout="wide")

if 'mdf' not in st.session_state: st.session_state.mdf = None
if 'meta_data' not in st.session_state: st.session_state.meta_data = []

with st.sidebar:
    st.header("⚙️ Kezelés")
    c_n = st.text_input("Futár Neve", "Szűcs István")
    c_p = st.text_input("Telefonszám", "+36 20 886 8971")
    
    st.divider()
    st.subheader("1. PDF Feldolgozás")
    up_files = st.file_uploader("PDF fájlok feltöltése", accept_multiple_files=True, type=['pdf'])
    if up_files and st.button("🚀 FELDOLGOZÁS"):
        all_rows, all_meta = [], []
        for f in up_files:
            rows, meta = parse_interfood_pdf(f)
            all_rows.extend(rows)
            all_meta.append(meta)
        st.session_state.mdf = merge_data(all_rows)
        st.session_state.meta_data = all_meta
        st.rerun()

    st.divider()
    st.subheader("2. CSV Visszatöltés")
    # Itt tudod visszatölteni a már elmentett sorrendet
    up_csv = st.file_uploader("Exportált CSV betöltése", type=['csv'])
    if up_csv and st.button("📥 BETÖLTÉS"):
        try:
            loaded_df = pd.read_csv(up_csv)
            # Biztosítjuk, hogy a Sorrend oszlop szám formátumú legyen
            if 'Sorrend' in loaded_df.columns:
                loaded_df['Sorrend'] = loaded_df['Sorrend'].astype(float)
            st.session_state.mdf = loaded_df
            st.success("CSV sikeresen betöltve!")
        except Exception as e:
            st.error(f"Hiba a CSV betöltésekor: {e}")

def create_label_pdf(df, fn, ft):
    """Etikett generálás DejaVu fontokkal és marketing szöveggel az üres helyeken"""
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70*mm, 42.42*mm 
    inner_m = 5.5*mm
    
    # Stílusok az ékezetekhez és a marketing szöveghez
    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=8, leading=9, encoding='utf-8')
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=8, leading=10, alignment=1, encoding='utf-8')
    
    # Kiszámoljuk, hány matricahely van összesen (21 matrica / oldal)
    total_slots = math.ceil(len(df) / 21) * 21
    
    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        
        # 1. HA VAN ÜGYFÉL ADAT (Normál etikett)
        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m
            
            if r.get('Hétvégi'):
                p.saveState()
                p.setFillColor(colors.lightgrey)
                p.rect(x + 1*mm, top_y - 8.5*mm, lw - 2*mm, 4.5*mm, fill=1, stroke=0)
                p.restoreState()
            
            p.setFont(f_bold, 10); p.drawString(x + inner_m, top_y - 3*mm, f"#{int(r['Sorrend'])}") 
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 3*mm, f"ID: {r['ID']}")
            p.setFont(f_bold, 9); p.drawString(x + inner_m, top_y - 8*mm, str(r['Ügyintéző'])[:28])
            p.setFont(f_reg, 8); p.drawRightString(x + lw - inner_m, top_y - 8*mm, str(r['Telefon']))
            p.setFont(f_reg, 7.5); p.drawString(x + inner_m, top_y - 12*mm, str(r['Cím'])[:45])
            
            para = Paragraph(str(r['Rendelés_Full']), order_s)
            para.wrap(lw - 2*inner_m, 12*mm)
            para.drawOn(p, x + inner_m, y + inner_m + 5*mm)
            
            p.setFont(f_bold, 9); p.drawRightString(x + lw - inner_m, y + inner_m + 1*mm, f"{int(r['Összesen'])} db")
            p.setFont(f_reg, 6); p.drawCentredString(x + lw/2, y + 2*mm, f"Futár: {fn} | {ft}")

        # 2. HA NINCS TÖBB ÜGYFÉL (Marketing etikett az üres helyekre)
        else:
            # p.setDash(1, 2) # Szaggatott vonal a marketing matrica szélének (opcionális)
            # p.rect(x + 2*mm, y + 2*mm, lw - 4*mm, lh - 4*mm, stroke=1, fill=0)
            p.setDash(1, 0) # Vissza sima vonalra
            
            m_text = (
                f"<font size='10.5' name='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető<br/>területi képviselőnk által</b></font>"
            )
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(lw - 6*mm, lh - 6*mm)
            # Középre igazítva rajzoljuk ki
            para.drawOn(p, x + (lw - pw) / 2, y + (lh - ph) / 2)
            
    p.save(); buf.seek(0); return buf

# --- 3. RÉSZ: PDF GENERÁLÓK ÉS ADATSZERKESZTŐ ---

def create_manifest_pdf(df, fn, meta_list):
    """Menetterv készítése csoportosítással, oldalszámozással és DejaVu fontokkal"""
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts() # Itt már a DejaVu-t fogja adni
    buf = BytesIO()
    
    # Alsó margót kicsit megnöveljük az oldalszámnak (20mm)
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=20*mm, bottomMargin=20*mm)
    
    # Címek kigyűjtése a csoportosítás ellenőrzéséhez
    all_addresses = df['Cím'].tolist()
    
    jaratok = ", ".join(sorted(list(set([str(m['jarat']) for m in meta_list if m['jarat']]))))
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
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
    ]

    for i, (_, r) in enumerate(df.iterrows()):
        # CSOPORTOSÍTÁS: Megnézzük, hányszor szerepel a cím
        is_group = all_addresses.count(r['Cím']) > 1
        group_tag = "<b><font color='blue'>▲ CSOPORT </font></b>" if is_group else ""
        
        note = str(r.get('Megjegyzés', ''))
        note_html = f"<br/><font color='red'><b>{note}</b></font>" if note and note.lower() != 'nan' and note.strip() != "" else ""
        penz = "" if str(r['Pénz']).lower() in ["0 ft", "0", "nan"] else str(r['Pénz'])
        
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
            t_style.append(('BACKGROUND', (0, i+1), (-1, i+1), colors.whitesmoke))

    t = Table(data, colWidths=[10*mm, 60*mm, 10*mm, 20*mm, 25*mm, 55*mm, 10*mm], repeatRows=1)
    t.setStyle(TableStyle(t_style))
    elements.append(t)

    # OLDALSZÁMOZÁS ÉS FEJLÉC FUNKCIÓ
    def add_header_footer(canvas, doc):
        canvas.saveState()
        # Fejléc (minden oldalon)
        canvas.setFont(f_bold, 11)
        canvas.drawString(10*mm, A4[1] - 12*mm, fejlec_text)
        canvas.setFont(f_reg, 9)
        canvas.drawRightString(A4[0] - 10*mm, A4[1] - 12*mm, f"Futár: {fn}")
        
        # Oldalszám (minden oldalon alul középen)
        page_num = f"{canvas.getPageNumber()}. oldal"
        canvas.setFont(f_reg, 8)
        canvas.drawCentredString(A4[0]/2, 10*mm, page_num)
        canvas.restoreState()

    # Build indítása a fejléc/lábléc funkcióval
    doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    buf.seek(0); return buf
    
def create_raklista_pdf(df, jarat_info, meta_list):
    """Raklista készítése (Ételek összesítése)"""
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=25*mm)
    
    counts = {}
    for r in df['Rendelés_Full']:
        found = re.findall(r'(\d+)-([A-Z0-9*+]+)', str(r))
        for qty, code in found:
            # Csak ha a kód tartalmaz betűt (kiszűri a házszámokat a címből)
            if any(c.isalpha() for c in code):
                counts[code] = counts.get(code, 0) + int(qty)
    
    data = [[Paragraph("<b>KÓD</b>", ParagraphStyle('C', fontName=f_bold, fontSize=10, alignment=1)), 
             Paragraph("<b>MENNYISÉG</b>", ParagraphStyle('C', fontName=f_bold, fontSize=10, alignment=1))]]
    
    for code in sorted(counts.keys()):
        data.append([code, f"{counts[code]} db"])

    t = Table(data, colWidths=[40*mm, 40*mm])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    doc.build([t])
    buf.seek(0); return buf

# --- FŐ PROGRAMFUTÁS ---

if st.session_state.mdf is not None:
    st.subheader("📦 Adatok ellenőrzése és szerkesztése")
    
    # Adatszerkesztő megjelenítése
    # Itt tudod manuálisan átírni a nevet vagy címet ha mégis maradt benne valami
    edited_df = st.data_editor(st.session_state.mdf, hide_index=True, use_container_width=True,
                              column_config={"Sorrend": st.column_config.NumberColumn("Sorrend", format="%.1f")})
    
    if st.button("💾 MÓDOSÍTÁSOK VÉGLEGESÍTÉSE"):
        st.session_state.mdf = edited_df
        st.success("Módosítások mentve a memóriába!")

    st.divider()
    
    # Letöltések szekció
    c1, c2, c3, c4 = st.columns(4)
    
    j_info = ", ".join(list(set([str(m['jarat']) for m in st.session_state.meta_data if m['jarat']])))
    
    # ETIKETTEK LETÖLTÉSE (create_label_pdf függvényt az előző blokkból használja)
    c1.download_button("📄 ETIKETTEK (PDF)", create_label_pdf(edited_df, c_n, c_p), "etikettek.pdf")
    
    # MENETTERV LETÖLTÉSE
    c2.download_button("📋 MENETTERV (PDF)", create_manifest_pdf(edited_df, c_n, st.session_state.meta_data), "menetterv.pdf")
    
    # RAKLISTA LETÖLTÉSE
    c3.download_button("📦 RAKLISTA (PDF)", create_raklista_pdf(edited_df, j_info, st.session_state.meta_data), "raklista.pdf")
    
    # CSV EXPORT (hogy később visszatölthető legyen)
    csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
    c4.download_button("📊 CSV EXPORT", csv_data, "szallitasi_lista.csv", "text/csv")

