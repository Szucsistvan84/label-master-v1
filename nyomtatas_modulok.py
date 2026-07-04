import re
import os
import math
import logging
from io import BytesIO
from datetime import datetime
import streamlit as st

# ReportLab alapvető importok
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Flowable, PageBreak
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# Globális minták és konstansok a rendelések feldolgozásához
ORDER_PAT = r'(\d+)-([A-Z0-9\*]+)'

def register_fonts():
    """Regisztrálja a szükséges TrueType betűtípusokat a ReportLab számára."""
    f_reg = "DejaVu"
    f_bold = "DejaVu-Bold"
    
    # Határozzuk meg a projekt alapmappáját (ahol ez a modul van)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    reg_path = os.path.join(base_dir, "DejaVuSans.ttf")
    bold_path = os.path.join(base_dir, "DejaVuSans-Bold.ttf")
    
    try:
        if f_reg not in pdfmetrics.getRegisteredFontNames():
            if os.path.exists(reg_path):
                pdfmetrics.registerFont(TTFont('DejaVu', reg_path))
            else:
                raise FileNotFoundError(f"Hiányzó fájl: {reg_path}")
                
        if f_bold not in pdfmetrics.getRegisteredFontNames():
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont('DejaVu-Bold', bold_path))
            else:
                raise FileNotFoundError(f"Hiányzó fájl: {bold_path}")
                
    except Exception as e:
        # Ha bármi hiba van, sima printet használunk, így nincs szükség logger modulra!
        print(f"⚠️ Betűtípus regisztrációs hiba, Helvetica használata: {e}")
        f_reg = "Helvetica"
        f_bold = "Helvetica-Bold"
        
    return f_reg, f_bold

def get_day_short(nap_neve):
    """Visszaadja a nap nevének 2 betűs rövidítését az etikett illesztéshez."""
    if not nap_neve: return ""
    nap_neve = str(nap_neve).strip().lower()
    if "hétfő" in nap_neve: return "Hé"
    if "kedd" in nap_neve: return "Ke"
    if "szerda" in nap_neve: return "Sze"
    if "csütörtök" in nap_neve: return "Csü"
    if "péntek" in nap_neve: return "Pé"
    if "szombat" in nap_neve: return "Szo"
    return ""

def clean_text(text):
    """Segédfüggvény a szövegek összehasonlításához (kisbetű, írásjelek nélkül)."""
    if not text: return ""
    import unicodedata
    text = str(text).strip().lower()
    text = "".join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', text)

# --- AKTÍV REPORTLAB FLOWABLE OSZTÁLYOK ---

class Checkbox(Flowable):
    """Klasszikus üres négyzet rajzolása a menetterv táblázatába."""
    def __init__(self, size=10):
        Flowable.__init__(self)
        self.width = size
        self.height = size

    def draw(self):
        self.canv.setLineWidth(0.8)
        self.canv.setStrokeColor(colors.black)
        self.canv.rect(0, 0, self.width, self.height, stroke=1, fill=0)

def get_checkbox_drawing():
    """Szép vektoros checkbox rajzolása a raklistához."""
    d = Drawing(10, 10)
    d.hAlign = 'CENTER'
    d.add(Rect(1, 1, 8, 8, fillColor=colors.white, strokeColor=colors.HexColor('#555555'), strokeWidth=0.6))
    return d

# =========================================================================
# 🔴 SEGÉDFÜGGVÉNYEK AZ ETIKETTHEZ (nyomtatas_modulok.py)
# =========================================================================

def get_gender_and_nevnap(full_name, nevnapok_df, keresztnevek_df, target_date):
    """Meghatározza, hogy az ügyfélnek névnapja van-e, és a neme alapján ikont rendel hozzá."""
    if nevnapok_df is None or nevnapok_df.empty or not target_date:
        return None
        
    # Biztosítjuk a dátum formátum egyezőségét (pl. 04-24)
    # Ha a táblázatban csak MM-DD van, vagy YYYY-MM-DD, ahhoz igazítjuk
    target_clean = str(target_date)[-5:].replace('.', '-') # pl: "04-24"
    
    # Megkeressük a mai napot a táblázatban (kezelve, ha a 'Datum' oszlop máshogy tartalmazza)
    mai_sor = nevnapok_df[nevnapok_df['Datum'].astype(str).str.contains(target_clean)]
    if mai_sor.empty: 
        return None
    
    mai_nevek = [n.strip().lower() for n in str(mai_sor.iloc[0]['Nevek']).split(',')]
    
    # Tisztítjuk az ügyfél nevét a megszólításoktól az összehasonlításhoz
    t_nev = str(full_name).strip()
    for t in ["Dr.", "dr.", "id.", "ifj.", "özv.", "Özv."]:
        t_nev = t_nev.replace(t, "")
        
    name_parts = [s.strip() for s in t_nev.split() if s.strip()]
    
    for part in name_parts:
        clean_part = part.lower()
        if clean_part in mai_nevek:
            # 💡 VISSZATÉRÉS A REJTETT DEJAVU GRAFIKÁKHOZ (A hétvégi hiba végleges javítása)
            ikon = "✦" # Gyönyörű négyágú csillag (Férfi/Általános) - garantáltan működik!
            
            if keresztnevek_df is not None and not keresztnevek_df.empty:
                gender_match = keresztnevek_df[keresztnevek_df['Keresztnév'].astype(str).str.lower() == clean_part]
                if not gender_match.empty:
                    nem = str(gender_match.iloc[0]['Nem']).lower()
                    if 'nő' in nem:
                        ikon = "❀" # Gyönyörű tiszta virág (Női) - garantáltan működik!
            
            return f"{ikon} Boldog Névnapot, {part}! {ikon}"
    return None

# =========================================================================
# 🔴 1. MODUL: ETIKETT GENERÁLÓ (create_label_pdf)
# =========================================================================
def create_label_pdf(df, fn, ft, meta, master_df, nevnapok_df, keresztnevek_df, etlap_api_df):
    if df is None or df.empty: return None
    if 'Sorrend' not in df.columns: df['Sorrend'] = range(1, len(df) + 1)
    df = df.sort_values('Sorrend')
    
    bazis_nap_rovid = get_day_short(meta.get('nap', ''))
    nap_list = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo"]

    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    lw, lh = 70 * mm, 42.42 * mm
    inner_m = 5.5 * mm 
    usable_w = lw - (2 * inner_m)

    order_s = ParagraphStyle('Order', fontName=f_reg, fontSize=7, leading=7.5)
    promo_s = ParagraphStyle('Promo', fontName=f_reg, fontSize=7.5, leading=10, alignment=1)

    # =========================================================================
    # 🛰️ CSOPORTOSÍTOTT REKESZCSOMAG (RACE PACK) ELŐ-INDEXELŐ MOTOR
    # =========================================================================
    csoport_osszesen = {}  # Tárolja: { 'csoport_id': összes_címke_száma }
    csoport_aktualis = {}  # Tárolja: { 'csoport_id': épp_hányadiknál_tartunk }

    # Megszámoljuk, melyik csoportban hány darab címke van összesen mára
    if 'Csoport' in df.columns:
        for _, row in df.iterrows():
            c_val = str(row.get('Csoport', '')).strip().lower()
            if c_val and c_val not in ['0', '0.0', 'nan', 'none', '']:
                csoport_osszesen[c_val] = csoport_osszesen.get(c_val, 0) + 1
                if c_val not in csoport_aktualis:
                    csoport_aktualis[c_val] = 0
    # =========================================================================

    total_slots = math.ceil(len(df) / 21) * 21
    
    # --- JAVÍTOTT DÁTUM KEZELÉS (Kigyomlált datetime.now() és meta alapú illesztés) ---
    kulcs_api_datum = meta.get('api_datum_kulcs', '')
    pdf_datum = meta.get('datum_iso', '')
    
    if not kulcs_api_datum and pdf_datum:
        kulcs_api_datum = str(pdf_datum).replace('-', '.')
        if not kulcs_api_datum.endswith('.'):
            kulcs_api_datum += "."
            
    if not kulcs_api_datum:
        kulcs_api_datum = "NINCS"
        
    kulcs_nevnap = str(pdf_datum)[-5:].replace('.', '-') if pdf_datum else "NINCS"
    # --------------------------------------------------------------------------------

    for i in range(total_slots):
        idx = i % 21
        if idx == 0 and i > 0: p.showPage()
        
        col, row_i = idx % 3, 6 - (idx // 3)
        x, y = col * lw, row_i * lh
        lift = 4.5 * mm if row_i == 0 else 0
        y_eff = y + lift 

        if i < len(df):
            r = df.iloc[i]
            top_y = y + lh - inner_m + lift
            
            r_full = str(r.get('Rendelés_Full', r.get('Rendelés', '')))
            kulonleges = False
            napi_blokkok = re.split(r'(\s*\|\s*|(?=Hé:|Ke:|Sze:|Csü:|Pé:|Szo:))', r_full)
            formazott_reszek = []
            
            for blokk in napi_blokkok:
                if not blokk or not blokk.strip(): 
                    if blokk: formazott_reszek.append(blokk)
                    continue
                szin_blokk = blokk
                for n in nap_list:
                    n_tag = f"{n}:"
                    if n_tag in blokk:
                        if n != bazis_nap_rovid:
                            kulonleges = True
                            szin_blokk = f'<font name="{f_bold}" size="8">{blokk}</font>'
                        break
                formazott_reszek.append(szin_blokk)
            
            formazott_rendeles = "".join(formazott_reszek)

            # --- NÉVNAP ELLENŐRZÉS (Az új, áthelyezett függvénnyel) ---
            nevnap_uzenet = get_gender_and_nevnap(
                full_name=r.get('Ügyintéző', ''),
                nevnapok_df=nevnapok_df,
                keresztnevek_df=keresztnevek_df,
                target_date=pdf_datum
            ) or ""

            # --- INTELLIGENS SORFOLYTONOS KELLÉK MOTOR ---
            rendeles_szoveg = str(r.get('Rendelés_Full', '')).strip()
            
            if kulcs_api_datum != "NINCS" and etlap_api_df is not None and not etlap_api_df.empty:
                var_nap_szamokkal = "".join(filter(str.isdigit, kulcs_api_datum))
                napi_oszlop = next((col for col in etlap_api_df.columns if var_nap_szamokkal in "".join(filter(str.isdigit, str(col)))), None)
                
                if napi_oszlop:
                    napi_blokkok = rendeles_szoveg.split('|')
                    uj_blokkok = []
                    
                    for blokk in napi_blokkok:
                        found_orders = re.findall(ORDER_PAT, blokk.upper())
                        modositott_blokk = blokk
                        
                        for qty, code in found_orders:
                            nyers_kod = code.strip()          
                            
                            # Csak a csillagos kódokkal foglalkozunk
                            if '*' in str(nyers_kod):
                                tiszta_kod = nyers_kod.replace('*', '').strip()  
                                
                                # API Étlap keresés startswith-el
                                etel_sor = etlap_api_df[etlap_api_df.iloc[:, 0].astype(str).str.strip().str.startswith(tiszta_kod, na=False)]
                                
                                if not etel_sor.empty:
                                    etel_nev = str(etel_sor.iloc[0][napi_oszlop]).strip()
                                    tisztitott_etel_nev = clean_text(etel_nev)
                                    
                                    # Master Adatbázis keresés a kellékért
                                    match_row = master_df[master_df['Tisztított Név'] == tisztitott_etel_nev] if master_df is not None else None
                                    
                                    if match_row is not None and not match_row.empty:
                                        master_kellek_nyers = str(match_row.iloc[0]['Kellék']).strip()
                                        
                                        if master_kellek_nyers and master_kellek_nyers.lower() != 'nan':
                                            # Megtartjuk a Master Adatbázis eredeti írásmódját (pl. "Zsemlekockák")
                                            kellek_szep = master_kellek_nyers.replace('*', '').strip()
                                            
                                            # Intelligens in-line csere a szövegben
                                            regi_resz = f"{qty}-{code}"
                                            uj_resz = f"{qty}-{code} (⚠️+ {kellek_szep})"
                                            modositott_blokk = modositott_blokk.replace(regi_resz, uj_resz)
                        
                        uj_blokkok.append(modositott_blokk)
                    
                    rendeles_szoveg = "|".join(uj_blokkok)

            # Sortörések formázása a ReportLab számára
            rendeles_szoveg = rendeles_szoveg.replace('|', '<br/>').strip()
            
            # --- SZOMBATI RENDELÉSEK FÉLKÖVÉRRÉ TÉTELE ---
            if "Szo:" in rendeles_szoveg:
                uj_sorok = []
                for sor in rendeles_szoveg.split('<br/>'):
                    sor_strip = sor.strip()
                    # A startswith helyett az 'in'-nel biztosítjuk, hogy akkor is megtalálja, ha van előtte szóköz
                    if "Szo:" in sor_strip:
                        # A sima <b> helyett a ReportLab-nek dedikáltan átadjuk a f_bold (DejaVu-Bold) fontot tagként
                        uj_sorok.append(f'<font name="{f_bold}">{sor_strip}</font>')
                    else:
                        uj_sorok.append(sor)
                rendeles_szoveg = "<br/>".join(uj_sorok)

            # --- DINAMIKUS RENDELÉS BETŰMÉRET ÉS IN-LINE KELLÉK MEGJELENÍTÉS ---
            # Most már a frissített, sorfolytonos 'rendeles_szoveg' változót használjuk!
            nyers_rendeles_szoveg = str(rendeles_szoveg)
            karakterszam = len(nyers_rendeles_szoveg)
            
            # Készítünk egy egyedi stílust a rendelésnek a hossztól függően (egy picivel kisebbre véve, ahogy kérted)
            egyedi_order_s = ParagraphStyle('DinamikusOrderS', parent=order_s)
            
            if karakterszam > 150:     # Brutális gigarendelés
                egyedi_order_s.fontSize = 5.5
                egyedi_order_s.leading = 6.5
            elif karakterszam > 80:    # Hosszabb rendelés vagy sok kellékes kiegészítés
                egyedi_order_s.fontSize = 7.0
                egyedi_order_s.leading = 8.5
            else:                      # Normál rendelés (picit kisebb az eredeti 9-esnél az esztétika miatt)
                egyedi_order_s.fontSize = 8.0
                egyedi_order_s.leading = 10.0

            # --- 1. VEZETŐ ADATOK (FEJLÉC ÉS NÉV BLOKK) RAJZOLÁSA ---
            biztonsagi_emeles = -0.5 * mm if row_i == 0 else 0

            p.setFont(f_bold, 8)
            p.drawString(x + inner_m, top_y - (3 * mm) + biztonsagi_emeles, f"#{int(r['Sorrend'])}")
            p.setFont(f_reg, 7)
            p.drawRightString(x + lw - inner_m, top_y - (3 * mm) + biztonsagi_emeles, f"ID: {str(r.get('temp_id', 'N/A'))}")

            nev_y_pozicio = top_y - 7.0 * mm + biztonsagi_emeles
            if kulonleges:
                p.saveState()
                p.setFillColor(colors.lightgrey, alpha=0.3)
                p.rect(x + 0.5*mm, nev_y_pozicio - 1.5*mm, lw - 1*mm, 5 * mm, fill=1, stroke=0)
                p.restoreState()
            
            p.setFont(f_bold, 8.5)
            p.drawString(x + inner_m, nev_y_pozicio, str(r.get('Ügyintéző', ''))[:25])
            p.setFont(f_reg, 8)
            p.drawRightString(x + lw - inner_m, nev_y_pozicio, str(r.get('Telefon', '')))
            
            p.setFont(f_reg, 7)
            p.drawString(x + inner_m, top_y - 10.5 * mm + biztonsagi_emeles, str(r.get('Cím', ''))[:45])

            # --- 2. RENDELÉSEK ESZTÉTIKUS KERETEZETT MEGJELENÍTÉSE ---
            # Kiszámoljuk a rendelkezésre álló fix szélességet a keretnek
            keret_szelesseg = lw - (2 * inner_m)
            
            # Létrehozzuk a rendelési beágyazott szöveget az új stílussal
            para = Paragraph(rendeles_szoveg, egyedi_order_s)
            
            # Egycellás táblázattal elegáns keretet és halvány hátteret adunk neki
            rendeles_tabla = Table([[para]], colWidths=[keret_szelesseg])
            rendeles_tabla.setStyle(TableStyle([
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#BCBCBC")),      # Elegáns szürke keretvonal
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FAFAFA")),   # Nagyon halvány, tiszta háttérszín
                ('TOPPADDING', (0,0), (-1,-1), 3),                            # Belső margók a kereten belül
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ]))
            
            # Kiszámoljuk a méreteket és elhelyezzük a kártyán
            tw, th = rendeles_tabla.wrap(keret_szelesseg, 15 * mm)
            rendeles_y = top_y - 11.5 * mm - th
            rendeles_tabla.drawOn(p, x + inner_m, rendeles_y) 

            # --- 3. LÁBLÉC FIX ELEMEI (Fizetés, darabszám, futár) ---
            p.setLineWidth(0.1)
            p.line(x + inner_m, y_eff + 6 * mm, x + lw - inner_m, y_eff + 6 * mm)

            penz_nyers = str(r.get('Pénz', '0 Ft'))
            penz_tisztitott = penz_nyers.replace(" ", "")
            if penz_tisztitott not in ["0Ft", "", "0", "0ft"]:
                p.setFont(f_bold, 9)
                p.drawString(x + inner_m, y_eff + 7 * mm, f"Fizet: {penz_nyers}")

            p.setFont(f_bold, 7.5)
            try:
                osszesen_db = int(float(str(r.get('Összesen', 0)).replace("'", "").strip() or 0))
            except ValueError:
                osszesen_db = 0
            p.drawRightString(x + lw - inner_m, y_eff + 7 * mm, f"Össz: {osszesen_db} db")

            if nevnap_uzenet:
                p.setFont(f_reg, 8) 
                p.drawCentredString(x + lw / 2, y_eff + 2.5 * mm, nevnap_uzenet)
            else:
                p.setFont(f_reg, 6.5)
                p.drawCentredString(x + lw / 2, y_eff + 2.5 * mm, f"Futár: {fn} | {ft}")

            # --- 4. RÉGI TÖBBSOROS KELLÉK PANEL TÖRÖLVE (Beolvadt a fenti keretes rendelésbe!) ---

        else:
            m_text = (
                f"<font size='10' name='{f_bold}'>15% kedvezmény* 3 hétig</font><br/>"
                f"Új Ügyfeleink részére!<br/><br/>"
                f"<b>Rendelés leadás:</b><br/>"
                f"<b>{fn}</b>, tel: <b>{ft}</b><br/><br/>"
                f"<font size='5.5'><b>* a kedvezmény telefonon leadott rendelésekre érvényesíthető!</b></font>"
            )
            para = Paragraph(m_text, promo_s)
            pw, ph = para.wrap(usable_w, lh - (2 * inner_m) - lift)
            para.drawOn(p, x + (lw - pw) / 2, y_eff + (lh - ph) / 2)

    p.save()
    buf.seek(0)
    return buf


# =========================================================================
# 📂 2. MODUL: PAPÍR ALAPÚ MENETTERV GENERÁLÓ (create_manifest_pdf)
# =========================================================================
def create_manifest_pdf(df, c_n, meta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=5*mm, leftMargin=5*mm, topMargin=8*mm, bottomMargin=12*mm)
    f_reg, f_bold = register_fonts()

    styles = {
        'Normal': ParagraphStyle('Normal', fontName=f_reg, fontSize=8, leading=8.5),
        'Small': ParagraphStyle('Small', fontName=f_reg, fontSize=7, leading=8),
        'Header': ParagraphStyle('Header', fontName=f_bold, fontSize=10, leading=11, alignment=1),
        'NameBold': ParagraphStyle('NameBold', fontName=f_bold, fontSize=8.5, leading=9),
        'IDStyle': ParagraphStyle('IDStyle', fontName=f_reg, fontSize=7.5, leading=9, alignment=2, textColor=colors.gray),
        'QRTitle': ParagraphStyle('QRTitle', fontName=f_bold, fontSize=14, leading=16, alignment=1, spaceAfter=15),
        'QRText': ParagraphStyle('QRText', fontName=f_reg, fontSize=10, leading=14, alignment=1)
    }

    bazis_nap_rovid = get_day_short(meta.get('nap', ''))
    nap_list = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo"]

    elements = []
    j_str = ", ".join(meta.get('jaratok', []))
    header_str = f"MENETTERV - Járat(ok): {j_str} | {meta.get('ev', '')}. év, {meta.get('het', '')}. hét | {meta.get('nap', '')}"
    elements.append(Paragraph(header_str, styles['Header']))
    elements.append(Spacer(1, 2*mm))

    table_data = [["#", "NÉV / CÍM / INFÓ", "RENDELÉS", "☐", "PÉNZ", "TEL", "DB"]]
    col_widths = [8*mm, 95*mm, 32*mm, 10*mm, 18*mm, 24*mm, 8*mm]

    table_styles = [
        ('FONTNAME', (0,0), (-1,0), f_bold),
        ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (4,0), (4,-1), 'RIGHT'),  
        ('ALIGN', (3,0), (3,-1), 'CENTER'), 
        ('ALIGN', (6,0), (6,-1), 'CENTER'), 
        ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
    ]

    if 'Csoport' in df.columns:
        groups = df['Csoport'].astype(str).values
        start_idx = None
        for i in range(len(groups)):
            curr_val = str(groups[i]).strip().lower()
            is_valid_group = curr_val and curr_val not in ['0', '0.0', 'nan', 'none', '']
            
            if is_valid_group:
                if start_idx is None: start_idx = i
                next_val = ""
                if i + 1 < len(groups):
                    next_val = str(groups[i+1]).strip().lower()

                if i == len(groups) - 1 or next_val != curr_val:
                    r_s, r_e = start_idx + 1, i + 1
                    table_styles.append(('BOX', (0, r_s), (-1, r_e), 1.3, colors.black))
                    table_styles.append(('BACKGROUND', (0, r_s), (-1, r_e), colors.Color(0.96, 0.96, 0.96)))
                    start_idx = None

    for i, row in df.iterrows():
        r_full = str(row.get('Rendelés_Full', ''))
        kulonleges = False
        formazott_rendeles = r_full
        
        for n in nap_list:
            n_tag = f"{n}:"
            if n_tag in r_full:
                if n != bazis_nap_rovid:
                    kulonleges = True
                    formazott_rendeles = formazott_rendeles.replace(n_tag, f"<b>{n_tag}</b>")

        if kulonleges:
            special_bg = colors.Color(0.85, 0.85, 0.85)
            table_styles.append(('BACKGROUND', (2, i+1), (2, i+1), special_bg))
            table_styles.append(('BOX', (2, i+1), (2, i+1), 1.5, colors.black, None, (2, 2)))

        curr_grp = str(row.get('Csoport', '')).strip().lower()
        prev_grp = str(df.iloc[i-1].get('Csoport', '')).strip().lower() if i > 0 else ""
        is_valid = curr_grp and curr_grp not in ['0', '0.0', 'nan', 'none', '']

        prefix = "▲ " if (is_valid and i > 0 and curr_grp == prev_grp) else ""
        u_name = str(row.get('Ügyintéző', ''))[:45]
        u_id = str(row.get('temp_id', ''))
        
        t_inner = Table([[Paragraph(f"{prefix}{u_name}", styles['NameBold']), Paragraph(f"ID: {u_id}", styles['IDStyle'])]], 
                        colWidths=[70*mm, 22*mm], style=[('LEFTPADDING', (0,0), (-1,-1), 0), ('TOPPADDING', (0,0), (-1,-1), 0)])

        info_flow = [t_inner, Paragraph(str(row.get('Cím', '')), styles['Normal'])]
        
        megj = str(row.get('Megjegyzés', '')).strip()
        if megj and megj.lower() != 'nan':
            info_flow.append(Paragraph(megj, styles['Small']))

        p_raw = str(row.get('Pénz', '')).strip()
        digits_only = "".join(re.findall(r'\d+', p_raw))
        penz_val = p_raw if (digits_only and int(digits_only) > 0) else "" 
        
        sorszam_nyers = row.get('Sorrend', i+1)
        try:
            sorszam_vegleges = str(int(float(sorszam_nyers)))
        except:
            sorszam_vegleges = str(i+1)

        table_data.append([
            sorszam_vegleges,                                    
            info_flow,                                           
            Paragraph(formazott_rendeles, styles['Small']),      
            Checkbox(10),                                        
            Paragraph(f"<b>{penz_val}</b>", styles['Normal']),   
            Paragraph(str(row.get('Telefon', '')), styles['Small']), 
            str(row.get('Összesen', ''))                         
        ])

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(table_styles))
    elements.append(t)
    
    # --- UTOLSÓ OLDAL: QR-KÓD GENERÁLÁS MOBIL NÉZETHEZ ---
    elements.append(PageBreak()) 
    elements.append(Spacer(1, 40*mm)) 
    elements.append(Paragraph("📱 DIGITÁLIS FUTÁR TERMINÁL INDÍTÁSA", styles['QRTitle']))
    
    alap_url = "https://interfood-menetterv-etikett-generator.streamlit.app"
    jarat_id = meta.get('jarat', '')
    mobil_link = f"{alap_url}/?view=mobile&jarat={jarat_id}"
    
    qr_code = QrCodeWidget(mobil_link)
    qr_code.barWidth = 140
    qr_code.barHeight = 140
    qr_code.qrVersion = 1
    
    d = Drawing(140, 140)
    d.add(qr_code)
    d.hAlign = 'CENTER'
    
    elements.append(d)
    elements.append(Spacer(1, 10*mm))
    
    magyarazat = f"""
    Szkenneld be a fenti QR-kódot a telefonoddal a mobilra optimalizált nézet megnyitásához!<br/><br/>
    <b>Aktuális járat:</b> {jarat_id if jarat_id else j_str}<br/>
    <i>A rendszer automatikusan bejelentkeztet és betölti a hozzá tartozó adatokat.</i>
    """
    elements.append(Paragraph(magyarazat, styles['QRText']))
    
    class FinalCanvas(canvas.Canvas):
        """Ez az osztály végzi el dinamikusan az X / Y alapú oldalszámozást és láblécet."""
        def __init__(self, *args, **kwargs):
            canvas.Canvas.__init__(self, *args, **kwargs)
            self.pages = []

        def showPage(self):
            self.pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            page_count = len(self.pages)
            for state in self.pages:
                self.__dict__.update(state)
                self.draw_footer(page_count)
                canvas.Canvas.showPage(self)
            canvas.Canvas.save(self)

        def draw_footer(self, page_count):
            self.saveState()
            self.setFont(f_reg, 7)
            
            j_str = ", ".join(meta.get('jaratok', []))
            footer_left = f"{j_str}. járat menetterve | {meta.get('ev', '')}. év, {meta.get('het', '')}. hét | {meta.get('nap', '')}"
            self.drawString(15*mm, 10*mm, footer_left)
            
            footer_right = f"{self._pageNumber} / {page_count}. oldal"
            self.drawRightString(A4[0] - 15*mm, 10*mm, footer_right)
            self.restoreState()

    doc.build(elements, canvasmaker=FinalCanvas)
    buffer.seek(0)
    return buffer


# =========================================================================
# 📊 3. MODUL: PAPÍR ALAPÚ RAKLISTA GENERÁLÓ (create_raklista_pdf)
# =========================================================================
def create_raklista_pdf(df, jarat_info, meta_dict, sh):
    f_reg, f_bold = register_fonts()
    buf = BytesIO()
    
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=10 * mm, bottomMargin=12 * mm, leftMargin=10 * mm, rightMargin=10 * mm)
    
    etlap = st.session_state.get('etlap_adatok', {})
    kategoria_adatok = st.session_state.get('kategoria_adatok', {}) 

    ev = meta_dict.get('ev', '')
    het = meta_dict.get('het', '')
    napok = meta_dict.get('nap', '') 
    dates_str = f"{ev}. {het}. hét ({napok})"

    label_to_prefix = {"Hé": "H", "Ke": "K", "Sze": "S", "Csü": "C", "Pé": "P", "Szo": "Z"}
    prefix_to_nev = {"H": "Hétfő", "K": "Kedd", "S": "Szerda", "C": "Csütörtök", "P": "Péntek", "Z": "Szombat"}
    prefix_to_num = {"H": "1", "K": "2", "S": "3", "C": "4", "P": "5", "Z": "6"}

    counts = {}
    for _, r in df.iterrows():
        order_str = str(r.get('Rendelés_Full', ''))
        day_parts = order_str.split('|')
        for part in day_parts:
            part = part.strip()
            prefix = ""
            for label, pfx in label_to_prefix.items():
                if f"{label}:" in part:
                    prefix = pfx
                    break
            if not prefix: continue
            
            found = re.findall(ORDER_PAT, part)
            for qty, code in found:
                full_key = f"{prefix}_{code.strip().upper()}"
                counts[full_key] = counts.get(full_key, 0) + int(qty)

    title_style = ParagraphStyle('T', fontName=f_bold, fontSize=12, leading=14, spaceAfter=2)
    meta_style = ParagraphStyle('M', fontName=f_reg, fontSize=9, leading=11, spaceAfter=6)
    
    cat_header_style = ParagraphStyle('CH', fontName=f_bold, fontSize=8.5, leading=10, textColor=colors.HexColor('#1A1A1A'))
    th_style = ParagraphStyle('TH', fontName=f_bold, fontSize=7.5, leading=9, alignment=1, textColor=colors.HexColor('#444444'))
    
    row_reg_style = ParagraphStyle('RR', fontName=f_reg, fontSize=7, leading=8.5)
    row_bold_style = ParagraphStyle('RB', fontName=f_bold, fontSize=7, leading=8.5)
    center_style = ParagraphStyle('C', fontName=f_reg, fontSize=7, leading=8.5, alignment=1)
    center_bold_style = ParagraphStyle('CB', fontName=f_bold, fontSize=7.5, leading=8.5, alignment=1)
    right_style = ParagraphStyle('R', fontName=f_reg, fontSize=7, leading=8.5, alignment=2)
    right_bold_style = ParagraphStyle('R', fontName=f_bold, fontSize=7, leading=8.5, alignment=2)

    kategoria_csoportok = {}
    kategoria_sorrendek = {}
    
    total_qty = 0
    total_money = 0

    for full_key, db in counts.items():
        prefix = full_key.split('_')[0]
        code_label = full_key.split('_')[1]
        day_long = prefix_to_nev.get(prefix, prefix)
        
        keresett_kod = code_label.replace('*', '').strip()
        num_prefix = prefix_to_num.get(prefix, "1")
        sheets_key = f"{num_prefix}_{keresett_kod}"
        
        info = etlap.get(sheets_key, {})
        nev = info.get('nev', '---')
        
        nyers_ar = str(info.get('ar', '0')).replace('Ft', '').replace(' ', '').strip()
        ar = int(nyers_ar) if nyers_ar and nyers_ar.isdigit() else 0
        subtotal = db * ar
        
        total_qty += db
        total_money += subtotal

        keresett_kod = code_label.replace('*', '').strip().upper()
        kat_nev = 'Szezonális ételek'
        kat_sorszam = 99

        for sheets_cikkszam, adatok in kategoria_adatok.items():
            tiszta_sheets_kod = str(sheets_cikkszam).strip().upper()
            if keresett_kod == tiszta_sheets_kod:
                kat_nev = adatok['kategoria']
                kat_sorszam = adatok['sorrend']
                break

        kategoria_sorrendek[kat_nev] = kat_sorszam
        if kat_nev not in kategoria_csoportok:
            kategoria_csoportok[kat_nev] = []
            
        kategoria_csoportok[kat_nev].append({
            'day': day_long,
            'code': code_label,
            'db': db,
            'nev': nev,
            'ar': ar,
            'subtotal': subtotal,
            'starred': "*" in code_label
        })

    rendezett_kategoriak = sorted(kategoria_csoportok.keys(), key=lambda x: kategoria_sorrendek.get(x, 99))

    elements = [
        Paragraph("<b>RAKLISTA ÉS ELSZÁMOLÁS (KATEGORIZÁLT)</b>", title_style),
        Paragraph(f"Időszak: {dates_str} | Járat: {jarat_info}", meta_style),
        Spacer(1, 2 * mm)
    ]

    col_widths = [15 * mm, 16 * mm, 12 * mm, 10 * mm, 95 * mm, 18 * mm, 24 * mm]
    mobil_raklista_rows = []

    nap_sorrend = ["Hétfő", "Kedd", "Szerda", "Csütörtök", "Péntek", "Szombat"]
    elerheto_napok = set()
    for kat, tetelek in kategoria_csoportok.items():
        for tetel in tetelek:
            elerheto_napok.add(tetel['day'])
    rendezett_napok = sorted(list(elerheto_napok), key=lambda x: nap_sorrend.index(x) if x in nap_sorrend else 99)

    for aktualis_nap in rendezett_napok:
        for kat in rendezett_kategoriak:
            tetelek = [t for t in kategoria_csoportok[kat] if t['day'] == aktualis_nap]
            if not tetelek:
                continue
                
            kat_data = []
            kat_data.append([Paragraph(f"<b>📂 {aktualis_nap.upper()} - {kat.upper()}</b>", cat_header_style), "", "", "", "", "", ""])
            
            kat_data.append([
                Paragraph("<b>NAP</b>", th_style), Paragraph("<b>KÓD</b>", th_style), Paragraph("<b>DB</b>", th_style),
                Paragraph("<b>[ ]</b>", th_style), Paragraph("<b>MEGNEVEZÉS</b>", th_style), Paragraph("<b>ÁR</b>", th_style), Paragraph("<b>ÖSSZES</b>", th_style)
            ])
            
            tetelek_rendezve = sorted(tetelek, key=lambda x: x['code'])
            
            for tetel in tetelek_rendezve:
                p_style = row_bold_style if tetel['starred'] else row_reg_style
                c_style = center_bold_style if tetel['starred'] else center_style
                
                kat_data.append([
                    Paragraph(tetel['day'], center_style), Paragraph(tetel['code'], c_style), Paragraph(f"<b>{tetel['db']} db</b>", c_style),
                    get_checkbox_drawing(), Paragraph(tetel['nev'], p_style), Paragraph(f"{tetel['ar']} Ft", right_style),
                    Paragraph(f"{tetel['subtotal']} Ft", right_bold_style if tetel['starred'] else right_style)
                ])

                mobil_raklista_rows.append({
                    'Nap': str(tetel['day']).strip(),
                    'Cikkszam': str(tetel['code']).strip(),
                    'Terv_Darabszam': int(tetel['db']),
                    'Etel Neve': str(tetel['nev']).strip(),
                    'Teny_Darabszam': "",  
                    'Hiba_Tipusa': ""      
                })
               
            t = Table(kat_data, colWidths=col_widths, repeatRows=2)
            t_style = [
                ('SPAN', (0, 0), (-1, 0)), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAEAEA')),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 3), ('TOPPADDING', (0, 0), (-1, 0), 3), ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#222222')),
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#F5F5F5')), ('BOTTOMPADDING', (0, 1), (-1, 1), 2), ('TOPPADDING', (0, 1), (-1, 1), 2),
                ('LINEBELOW', (0, 1), (-1, 1), 0.6, colors.HexColor('#666666')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (3, 2), (3, -1), 'CENTER'),
                ('TOPPADDING', (0, 2), (-1, -1), 2), ('BOTTOMPADDING', (0, 2), (-1, -1), 2), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('ROWBACKGROUNDS', (0, 2), (-1, -1), [colors.white, colors.HexColor('#FAFAFA')]), ('LINEBELOW', (0, 2), (-1, -1), 0.3, colors.HexColor('#E0E0E0')),
                ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#222222')),
            ]
            t.setStyle(TableStyle(t_style))
            
            elements.append(t)
            elements.append(Spacer(1, 4 * mm)) 

    jutalek = int(total_money * 0.13)
    
    # =========================================================================
    # 📊 ITT MENTJÜK EL A HAJSZÁLPONTOS ADATOKAT A MOBIL MŰSZERFALNAK!
    # =========================================================================
    if isinstance(meta_dict, dict):
        meta_dict['osszes_etel'] = int(total_qty)
        meta_dict['total_ertek'] = int(total_money)
        meta_dict['futar_jutalek'] = int(jutalek)
        # A címeket a df-ből húzzuk ki egyedi számolással
        meta_dict['osszes_cim'] = int(df['Cím'].nunique()) if 'Cím' in df.columns else 0
    # =========================================================================

    summary_data = [
        ["", "", "", "", "ÖSSZESEN:", f"{total_qty} db", f"{total_money} Ft"],
        ["", "", "", "", "JUTALÉK (13%):", "", f"{jutalek} Ft"]
    ]
    st_table = Table(summary_data, colWidths=col_widths)
    st_table.setStyle(TableStyle([
        ('FONTNAME', (4, 0), (-1, -1), f_bold), ('FONTSIZE', (4, 0), (-1, -1), 9),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'), ('ALIGN', (5, 0), (6, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2), ('LINEABOVE', (4, 0), (-1, 0), 0.8, colors.black),
    ]))
    elements.append(st_table)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_reg, 7.5)
        canvas.drawRightString(200 * mm, 8 * mm, f"{doc.page}. oldal")
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    
    st.session_state['mobil_raklista_adatok'] = {
        'kategoriak': rendezett_kategoriak,
        'csoportok': kategoria_csoportok
    }

    try:
        if mobil_raklista_rows:
            import pandas as pd
            from gspread_dataframe import set_with_dataframe
            
            ws_mobil_raklista = sh.worksheet("Mobil_Raklista")
            existing_raklista = ws_mobil_raklista.get_all_records()
            if existing_raklista:
                df_ex_raklista = pd.DataFrame(existing_raklista)
                df_ex_raklista.columns = [c.strip() for c in df_ex_raklista.columns]
            else:
                df_ex_raklista = pd.DataFrame()
                
            df_uj_raklista = pd.DataFrame(mobil_raklista_rows)
            aktualis_futar_nev = st.session_state.get('user_nev', 'Ismeretlen_Futár')
            df_uj_raklista['Jarat_ID / Futar'] = aktualis_futar_nev
            
            raklista_cols = ['Nap', 'Cikkszam', 'Terv_Darabszam', 'Etel Neve', 'Teny_Darabszam', 'Hiba_Tipusa', 'Jarat_ID / Futar']
            df_uj_raklista = df_uj_raklista[raklista_cols]
            
            if not df_ex_raklista.empty and 'Jarat_ID / Futar' in df_ex_raklista.columns:
                df_masok_raklistaja = df_ex_raklista[df_ex_raklista['Jarat_ID / Futar'] != aktualis_futar_nev]
                df_sajat_mar_atvett = df_ex_raklista[
                    (df_ex_raklista['Jarat_ID / Futar'] == aktualis_futar_nev) & 
                    (df_ex_raklista['Teny_Darabszam'].astype(str).str.strip() != "")
                ]
                save_raklista_df = pd.concat([df_masok_raklistaja, df_sajat_mar_atvett, df_uj_raklista], ignore_index=True)
            else:
                save_raklista_df = df_uj_raklista
                
            for col in save_raklista_df.columns:
                save_raklista_df[col] = save_raklista_df[col].astype(object)
            save_raklista_df = save_raklista_df.fillna('')
            
            ws_mobil_raklista.clear()
            set_with_dataframe(ws_mobil_raklista, save_raklista_df, include_index=False, include_column_header=True)
            st.toast("🚀 Mobil Raklista sikeresen frissítve a Google Sheets-ben!")
            
    except Exception as e:
        st.warning(f"⚠️ A PDF kész, de a Mobil_Raklista fül frissítése megszakadt: {e}")
    
    return buf
