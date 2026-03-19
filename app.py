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
    """Alapértelmezett betűtípusok"""
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

# --- 3. RÉSZ: PDF GENERÁLÓK ÉS ADATSZERKESZTŐ ---

def create_manifest_pdf(df, fn, meta_list):
    """Menetterv készítése"""
    df = df.sort_values('Sorrend')
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=10*mm, leftMargin=10*mm, topMargin=20*mm, bottomMargin=15*mm)
    
    jaratok = ", ".join(sorted(list(set([str(m['jarat']) for m in meta_list if m['jarat']]))))
    ev = meta_list[0].get('year', '') if meta_list else ""
    het = meta_list[0].get('week', '') if meta_list else ""
    nap = meta_list[0].get('day', '') if meta_list else ""
    fejlec = f"MENETTERV - Járat: {jaratok} | {ev}. év, {het}. hét | {nap}"

    elements = []
    data = [[
        Paragraph("<b>#</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1)),
        Paragraph("<b>NÉV / CÍM / INFÓ</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1)),
        Paragraph("<b>[ ]</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1)),
        Paragraph("<b>PÉNZ</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1)),
        Paragraph("<b>TEL</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1)),
        Paragraph("<b>RENDELÉS</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1)),
        Paragraph("<b>DB</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1))
    ]]
    
    for i, (_, r) in enumerate(df.iterrows()):
        note = str(r.get('Megjegyzés', ''))
        note_html = f"<br/><font color='red'><b>{note}</b></font>" if note and note.lower() != 'nan' and note.strip() != "" else ""
        penz = "" if str(r['Pénz']).lower() in ["0 ft", "0", "nan"] else str(r['Pénz'])
        
        data.append([
            f"{int(r['Sorrend'])}",
            Paragraph(f"<b>{r['Ügyintéző']}</b><br/><font size='7'>{r['Cím']}</font>{note_html}", ParagraphStyle('L', fontName=f_reg, fontSize=8)),
            "[ ]",
            Paragraph(f"<b>{penz}</b>", ParagraphStyle('C', fontName=f_bold, fontSize=8, alignment=1)),
            str(r['Telefon']),
            Paragraph(str(r['Rendelés_Full']), ParagraphStyle('L', fontName=f_reg, fontSize=7)),
            f"{int(r['Összesen'])}"
        ])

    t = Table(data, colWidths=[10*mm, 60*mm, 10*mm, 20*mm, 25*mm, 55*mm, 10*mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('ALIGN', (-1,0), (-1,-1), 'CENTER'),
    ]))
    elements.append(t)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_bold, 11); canvas.drawString(10*mm, A4[1] - 12*mm, fejlec)
        canvas.setFont(f_reg, 9); canvas.drawRightString(A4[0] - 10*mm, A4[1] - 12*mm, f"Futár: {fn}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
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

