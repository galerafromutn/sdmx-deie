"""
Conversor SDMX — DEIE Mendoza (versión local)
Corre en tu PC con: streamlit run app.py
Requiere: pip install pandas xlrd openpyxl pdfplumber streamlit
"""

import streamlit as st
import pandas as pd
import re
import io
import json
import urllib.request

# pdfplumber es opcional — solo para PDFs
try:
    import pdfplumber
    PDF_DISPONIBLE = True
except ImportError:
    PDF_DISPONIBLE = False

st.set_page_config(
    page_title="Conversor SDMX — DEIE Mendoza",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    .step-box {
        background: #f8f9fa;
        border-left: 4px solid #1f77b4;
        padding: 1rem 1.25rem;
        border-radius: 0 8px 8px 0;
        margin-bottom: 1rem;
    }
    .step-title { font-weight:600; font-size:1.05rem; color:#1f77b4; margin:0 0 .25rem 0; }
    .step-desc  { font-size:.9rem; color:#555; margin:0; }
    .tag-ok  { background:#d4edda; color:#155724; padding:2px 8px; border-radius:4px; font-size:.8rem; }
    .tag-err { background:#f8d7da; color:#721c24; padding:2px 8px; border-radius:4px; font-size:.8rem; }
    .tag-warn{ background:#fff3cd; color:#856404; padding:2px 8px; border-radius:4px; font-size:.8rem; }
</style>
""", unsafe_allow_html=True)

# ─── Constantes ───────────────────────────────────────────────────────────────
MESES_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,
    'noviembre':11,'diciembre':12
}
FREQ_LABEL = {'M':'Mensual','A':'Anual','Q':'Trimestral','S':'Semestral','P':'Plurianual'}

IGNORAR_PREFIJOS = [
    'fuente','nota','dato igual','- dato','datos igual','elaboracion','elaboración',
    'ver ','véase','aclaracion','aclaración','los valores','los datos',
    'en el ano','en el año','(1)','(2)','(3)','(*)','n/d','s/d',
    'promedio anual', 'promedio general', 'total general'
]
IGNORAR_CONTIENE = ['grafico','gráfico','cuadro','figura']
IGNORAR_EXACTOS  = {
    'rubros','rubro','descripcion','descripción','concepto','item','ítem',
    'detalle','categoria','categoría','producto','productos','indicador',
    'var.','var','variacion','variación','indice','índice','mes','año','anio'
}

# ─── Utilidades ───────────────────────────────────────────────────────────────

def normalizar(t):
    t = str(t).strip().lower()
    for a,b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        t = t.replace(a,b)
    return t

def a_code(texto):
    t = re.sub(r'\s+', ' ', str(texto).strip())
    for a,b in [('Á','A'),('É','E'),('Í','I'),('Ó','O'),('Ú','U'),('Ñ','N'),
                ('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        t = t.replace(a,b)
    return re.sub(r'[^A-Z0-9_]', '_', t.upper().replace(' ','_')).strip('_')

def limpiar_numero(v):
    if v is None or str(v).strip() in ('','nan','None','-','—','...','..','(*)','*','n/d','s/d','N/A','#N/A'):
        return None
    s = str(v).strip().strip('()').strip()
    s = re.sub(r'[*†‡°]', '', s).strip()
    if not s:
        return None
    tiene_coma  = ',' in s
    tiene_punto = '.' in s
    if tiene_coma and tiene_punto:
        s = s.replace('.','').replace(',','.') if s.rfind(',') > s.rfind('.') else s.replace(',','')
    elif tiene_punto and s.count('.') > 1:
        s = s.replace('.','')
    elif tiene_coma:
        s = s.replace(',','.')
    s = re.sub(r'[^\d.\-]', '', s)
    if not s or s in ('.', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def es_rubro_valido(texto):
    if not texto or str(texto).strip().lower() in ('','nan','none'):
        return False
    norm = normalizar(texto)
    if norm in IGNORAR_EXACTOS:
        return False
    if any(norm.startswith(p) for p in IGNORAR_PREFIJOS):
        return False
    if any(p in norm for p in IGNORAR_CONTIENE):
        return False
    if re.fullmatch(r'(19|20)\d{2}', texto.strip()):
        return False
    try:
        float(texto.replace(',','.').replace('.','',1))
        return False
    except:
        pass
    return True

# ─── Detección de períodos ────────────────────────────────────────────────────

def detectar_periodo(v):
    s = str(v).strip()
    if not s or normalizar(s) in ('nan','none',''):
        return None, None
    s_norm = normalizar(s).rstrip('*').rstrip('.').strip()

    # Variación %
    if re.search(r'\bvar(iacion|iación)?\b', s_norm) or s_norm in ('%','var.','var'):
        return ('VAR_PCT', None), 'VAR'

    # Mes
    if s_norm in MESES_ES:
        return ('MES', MESES_ES[s_norm]), 'M'

    # Año simple
    if re.fullmatch(r'(19|20)\d{2}', s):
        return s, 'A'

    # Rango de años
    m = re.fullmatch(r'((19|20)\d{2})\s*[-–]\s*((19|20)\d{2})', s)
    if m:
        a1, a2 = m.group(1), m.group(3)
        diff = int(a2) - int(a1)
        return (a1 if diff <= 1 else f"{a1}/{a2}"), ('A' if diff <= 1 else 'P')

    # Trimestre
    m = re.search(r'(\d)[°º]?\s*(trim)', s_norm)
    if not m:
        m = re.search(r'\bt\s*(\d)', s_norm)
    if m:
        return ('TRIM', int(m.group(1))), 'Q'

    # Semestre
    m = re.search(r'(\d)[°º]?\s*sem', s_norm)
    if m:
        return ('SEM', int(m.group(1))), 'S'

    return None, None

def detectar_encabezado_en_fila(row):
    res = []
    for idx, v in enumerate(row):
        p, f = detectar_periodo(v)
        if p is not None:
            res.append((idx, p, f))
    return res if len(res) >= 2 else []

def resolver_time_period(periodo_raw, freq, anio_ctx):
    if isinstance(periodo_raw, tuple):
        tipo, num = periodo_raw
        if tipo == 'MES':
            return (f"{anio_ctx}-{num:02d}", 'M') if anio_ctx else (None, freq)
        if tipo == 'TRIM':
            return (f"{anio_ctx}-Q{num}", 'Q') if anio_ctx else (None, freq)
        if tipo == 'SEM':
            return (f"{anio_ctx}-S{num}", 'S') if anio_ctx else (None, freq)
        if tipo == 'VAR_PCT':
            return (str(anio_ctx), 'A') if anio_ctx else (None, freq)
    return str(periodo_raw), freq

# ─── Detección de tipo de medida (OBS_MSR) ───────────────────────────────────

def detectar_obs_msr(col_header_text, filas_sup_texts):
    """
    Dado el texto del encabezado de una columna (y filas superiores),
    determina qué tipo de medida representa.
    Retorna un string que irá en OBS_MSR.
    """
    textos = [normalizar(str(t)) for t in [col_header_text] + filas_sup_texts if t]

    for t in textos:
        if '%' in t or 'var' in t:
            return 'VAR_PCT'
        if 'precio' in t or 'price' in t:
            return 'PRECIO'
        if 'kilo' in t or ' kg' in t or '/kg' in t:
            return 'KG'
        if 'atado' in t:
            return 'ATADO'
        if 'unidad' in t or ' un' in t:
            return 'UNIDAD'
        if 'litro' in t or ' lt' in t or ' hl' in t or 'hectolitro' in t:
            return 'HL'
        if 'operac' in t or 'oper.' in t:
            return 'OPERACIONES'
        if 'tonelada' in t or ' tn' in t:
            return 'TN'
        if 'indice' in t or 'índice' in t or 'index' in t:
            return 'INDEX'

    return 'INDEX'  # default

def clasificar_columnas(rows, fila_enc, enc_raw):
    """
    Para cada columna del encabezado determina su OBS_MSR
    mirando el texto de la propia celda y hasta 3 filas superiores.
    """
    fila_row = rows[fila_enc]
    filas_sup = [rows[fila_enc - k] for k in range(1, 4) if fila_enc - k >= 0]

    col_tipo = {}
    for col_idx, _, _ in enc_raw:
        celda = str(fila_row[col_idx]) if col_idx < len(fila_row) else ''
        sup_celdas = [str(f[col_idx]) if col_idx < len(f) else '' for f in filas_sup]
        col_tipo[col_idx] = detectar_obs_msr(celda, sup_celdas)

    # Si todas quedaron INDEX y hay pares → aplicar alternado INDEX/VAR_PCT
    if all(t == 'INDEX' for t in col_tipo.values()) and len(enc_raw) >= 2:
        for fi in filas_sup:
            if any('%' in normalizar(str(v)) or 'var' in normalizar(str(v)) for v in fi):
                for i, (col_idx, _, _) in enumerate(enc_raw):
                    cel = normalizar(str(fi[col_idx]) if col_idx < len(fi) else '')
                    col_tipo[col_idx] = 'VAR_PCT' if ('%' in cel or 'var' in cel) else 'INDEX'
                break

    return col_tipo

# ─── Parser multi-bloque ──────────────────────────────────────────────────────

OBS_MSR_ORDEN = {'INDEX': 0, 'PRECIO': 1, 'KG': 2, 'ATADO': 3,
                 'UNIDAD': 4, 'HL': 5, 'TN': 6, 'OPERACIONES': 7, 'VAR_PCT': 8}

def parsear_hoja(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year):
    registros = []

    # Encontrar todos los bloques desde fila_inicio
    bloques = []
    for i in range(fila_inicio, len(rows)):
        enc = detectar_encabezado_en_fila(rows[i])
        if enc:
            bloques.append((i, enc))

    if not bloques:
        return [], "No se detectaron períodos temporales en la hoja."

    for b_idx, (fila_enc, enc_raw) in enumerate(bloques):
        fila_fin = bloques[b_idx + 1][0] if b_idx + 1 < len(bloques) else len(rows)
        col_tipo = clasificar_columnas(rows, fila_enc, enc_raw)
        cols_info = [(col_idx, periodo_raw, freq, col_tipo[col_idx])
                     for col_idx, periodo_raw, freq in enc_raw]

        # Año de contexto: buscar en las 10 filas anteriores al bloque
        anio_ctx = None
        for row in rows[max(0, fila_enc - 10): fila_enc]:
            for v in row:
                m = re.search(r'\b(19|20)\d{2}\b', str(v))
                if m:
                    anio_ctx = int(m.group(0))

        for row in rows[fila_enc + 1: fila_fin]:
            col0 = str(row[col_rubro]).strip() if col_rubro < len(row) else ''

            # Actualizar año de contexto
            for v in row:
                m = re.search(r'\b(19|20)\d{2}\b', str(v))
                if m:
                    nuevo = int(m.group(0))
                    if 1970 <= nuevo <= 2035:
                        anio_ctx = nuevo
                        break

            if not es_rubro_valido(col0):
                continue

            rubro_code  = a_code(col0)
            rubro_label = col0

            for col_idx, periodo_raw, freq, obs_msr in cols_info:
                v_raw = row[col_idx] if col_idx < len(row) else ''
                valor = limpiar_numero(v_raw)

                if valor is None and obs_msr == 'VAR_PCT':
                    continue

                time_period, freq_final = resolver_time_period(periodo_raw, freq, anio_ctx)
                if time_period is None:
                    continue

                registros.append({
                    'FREQ':            freq_final,
                    'REF_AREA':        ref_area,
                    'INDICATOR':       rubro_code,
                    'INDICATOR_LABEL': rubro_label,
                    'TIME_PERIOD':     time_period,
                    'OBS_MSR':         obs_msr,
                    'OBS_VALUE':       valor,
                    'OBS_STATUS':      'A' if valor is not None else 'M',
                    'UNIT_MEASURE':    unit_measure,
                    'BASE_YEAR':       base_year,
                })

    # Deduplicar: mismo (TIME_PERIOD, INDICATOR, OBS_MSR) → quedarse con el que tiene valor
    seen = {}
    for r in registros:
        key = (r['TIME_PERIOD'], r['INDICATOR'], r['OBS_MSR'])
        if key not in seen or (seen[key]['OBS_VALUE'] is None and r['OBS_VALUE'] is not None):
            seen[key] = r

    resultado = sorted(seen.values(),
        key=lambda x: (x['TIME_PERIOD'], x['INDICATOR'], OBS_MSR_ORDEN.get(x['OBS_MSR'], 99)))
    return resultado, None

# ─── Lectura de archivos ──────────────────────────────────────────────────────

def leer_excel(uploaded_file):
    """Lee XLS o XLSX y devuelve un ExcelFile de pandas."""
    nombre = uploaded_file.name.lower()
    contenido = uploaded_file.read()
    buf = io.BytesIO(contenido)

    # Intentar con xlrd primero (soporta XLS antiguo y algunos XLS disfrazados de XLSX)
    try:
        import xlrd
        xl = pd.ExcelFile(buf, engine='xlrd')
        return xl, None
    except Exception:
        pass

    # Intentar con openpyxl (XLSX real)
    buf.seek(0)
    try:
        xl = pd.ExcelFile(buf, engine='openpyxl')
        return xl, None
    except Exception as e:
        return None, str(e)

def leer_pdf(uploaded_file):
    """Extrae tablas de un PDF con pdfplumber."""
    if not PDF_DISPONIBLE:
        return None, "pdfplumber no está instalado. Ejecutá: pip install pdfplumber"

    contenido = uploaded_file.read()
    buf = io.BytesIO(contenido)
    todas_las_filas = []

    with pdfplumber.open(buf) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    cleaned = [str(c).strip() if c else '' for c in row]
                    todas_las_filas.append(cleaned)
                todas_las_filas.append([''] * 5)  # separador entre tablas

    return todas_las_filas, None

# ─── SQL ──────────────────────────────────────────────────────────────────────

def generar_sql(nombre_tabla, nombre_csv, ref_area):
    return f"""-- Tabla SDMX — generada automáticamente
CREATE TABLE IF NOT EXISTS public.{nombre_tabla} (
    id_registro       SERIAL PRIMARY KEY,
    "FREQ"            VARCHAR(2)    NOT NULL,           -- M=Mensual A=Anual Q=Trimestral S=Semestral P=Plurianual
    "REF_AREA"        VARCHAR(10)   DEFAULT '{ref_area}',
    "INDICATOR"       VARCHAR(255)  NOT NULL,           -- Código del rubro
    "INDICATOR_LABEL" TEXT,                             -- Nombre original del rubro
    "TIME_PERIOD"     VARCHAR(10)   NOT NULL,           -- YYYY-MM / YYYY / YYYY-QN / YYYY/YYYY
    "OBS_MSR"         VARCHAR(20)   NOT NULL,           -- INDEX / VAR_PCT / PRECIO / KG / ATADO / etc.
    "OBS_VALUE"       NUMERIC(18,6),
    "OBS_STATUS"      CHAR(1)       DEFAULT 'A',        -- A=disponible M=faltante
    "UNIT_MEASURE"    VARCHAR(20),
    "BASE_YEAR"       CHAR(4)
);

-- Importar datos (ajustá la ruta)
COPY public.{nombre_tabla} (
    "FREQ","REF_AREA","INDICATOR","INDICATOR_LABEL",
    "TIME_PERIOD","OBS_MSR","OBS_VALUE","OBS_STATUS","UNIT_MEASURE","BASE_YEAR"
)
FROM 'C:/ruta/a/tu/carpeta/{nombre_csv}'
DELIMITER ','
CSV HEADER
NULL '';
"""

# ─── Análisis de esquema con Claude API ──────────────────────────────────────

PROMPT_ESQUEMA = """Sos un experto en estadísticas de Argentina. Analizá esta tabla de datos del DEIE Mendoza y respondé SOLO con un JSON válido, sin texto adicional, sin markdown, sin backticks.

El JSON debe tener exactamente esta estructura:
{
  "col_articulo": <número de columna (0-based) que tiene el nombre del artículo/rubro/indicador>,
  "col_unidad": <número de columna que tiene la unidad de medida por fila, o null si no existe>,
  "col_categoria": <número de columna que tiene categorías/grupos padre (ej: HORTALIZAS, FRUTAS), o null si no existe>,
  "columnas_periodo": [
    {"col": <índice>, "tipo": "MES|AÑO|TRIMESTRE|SEMESTRE|VAR_PCT|OTRO", "valor": <número de mes 1-12, año YYYY, número de trimestre 1-4, o null>, "etiqueta": "<texto original>"}
  ],
  "fila_encabezado": <número de fila (0-based) donde están los encabezados de período>,
  "fila_datos_inicio": <número de fila (0-based) donde comienzan los datos reales>,
  "tiene_grupos": <true si hay filas que son categorías padre como HORTALIZAS/FRUTAS/HUEVOS>,
  "tiene_promedio": <true si hay una columna o fila de promedio/total>,
  "col_promedio": <índice de columna promedio o null>,
  "anio_contexto": <año que aplica a los datos, o null>,
  "notas": "<observaciones relevantes sobre la estructura de la tabla>"
}

Reglas:
- col_unidad: es la columna donde cada FILA tiene su propia unidad (Kilo, Atado, Bulbo, etc.), no el encabezado.
- col_categoria: es cuando hay filas que son títulos de grupo (en mayúsculas, sin datos) como "HORTALIZAS", "FRUTAS".
- columnas_periodo: incluí SOLO las columnas con períodos reales (meses, años, trimestres) o variaciones %. NO incluyas col_articulo, col_unidad ni col_categoria.
- Para meses abreviados (Ene., Feb., etc.) usá tipo MES y valor 1-12.
- Para columnas "Var." o "Var. %" usá tipo VAR_PCT.
- Para columnas "Prom." o "Promedio" marcalas como tipo OTRO y también ponelas en col_promedio.

Tabla (primeras filas, formato CSV):
{tabla_csv}
"""

def filas_a_csv_preview(rows, max_filas=25):
    """Convierte las primeras filas a texto CSV simple para el prompt."""
    lineas = []
    for i, row in enumerate(rows[:max_filas]):
        lineas.append(f"fila{i}," + ",".join(f'"{v}"' if v else '' for v in row[:20]))
    return "\n".join(lineas)

@st.cache_data(show_spinner=False)
def analizar_esquema_con_claude(rows_tuple, anio_hint=None):
    """
    Llama a Claude API para que analice el esquema de la tabla.
    Usa caché de Streamlit para no llamar dos veces con los mismos datos.
    """
    rows = list(rows_tuple)
    tabla_csv = filas_a_csv_preview(rows)
    prompt = PROMPT_ESQUEMA.replace("{tabla_csv}", tabla_csv)
    if anio_hint:
        prompt += f"\n\nNota adicional: el año de contexto probable es {anio_hint}."

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        texto = "".join(b.get("text","") for b in data.get("content",[]) if b.get("type")=="text")
        # Limpiar por si acaso viene con backticks
        texto = re.sub(r'^```[a-z]*\n?', '', texto.strip())
        texto = re.sub(r'\n?```$', '', texto.strip())
        esquema = json.loads(texto)
        return esquema, None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return None, f"Error API {e.code}: {body[:200]}"
    except Exception as e:
        return None, str(e)

# ─── Parser basado en esquema ─────────────────────────────────────────────────

MESES_ABR = {
    'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,
    'jul':7,'ago':8,'sep':9,'set':9,'oct':10,'nov':11,'dic':12
}

def mes_de_etiqueta(etiqueta):
    """Convierte 'Ene.', 'Enero', 'feb', etc. a número de mes."""
    n = normalizar(etiqueta).rstrip('.').strip()
    if n in MESES_ES:
        return MESES_ES[n]
    if n[:3] in MESES_ABR:
        return MESES_ABR[n[:3]]
    return None

def parsear_con_esquema(rows, esquema, ref_area, unit_measure, base_year):
    """
    Parser flexible que usa el esquema devuelto por Claude para extraer datos.
    Soporta: col_unidad por fila, grupos/categorías, promedios, VAR_PCT, meses abreviados.
    """
    registros = []

    col_art  = esquema.get("col_articulo", 0)
    col_uni  = esquema.get("col_unidad")
    col_cat  = esquema.get("col_categoria")
    col_prom = esquema.get("col_promedio")
    fila_ini = esquema.get("fila_datos_inicio", 0)
    anio_ctx = esquema.get("anio_contexto")
    tiene_grupos = esquema.get("tiene_grupos", False)

    # Construir lista de columnas de período con su TIME_PERIOD ya resuelto (excepto meses)
    cols_periodo = []
    for cp in esquema.get("columnas_periodo", []):
        col  = cp["col"]
        tipo = cp.get("tipo","").upper()
        val  = cp.get("valor")
        etiq = cp.get("etiqueta","")
        if col == col_prom:
            continue  # Ignorar columna de promedio
        cols_periodo.append({
            "col": col, "tipo": tipo, "valor": val, "etiqueta": etiq
        })

    if not cols_periodo:
        return [], "El esquema no contiene columnas de período válidas."

    categoria_actual = None

    for i, row in enumerate(rows):
        if i < fila_ini:
            continue

        art = str(row[col_art]).strip() if col_art < len(row) else ''

        # Actualizar año de contexto si aparece en la fila
        for v in row:
            m = re.search(r'\b(19|20)\d{2}\b', str(v))
            if m:
                nuevo = int(m.group(0))
                if 1970 <= nuevo <= 2035:
                    anio_ctx = nuevo
                    break

        # Detectar fila de categoría/grupo (ej: HORTALIZAS)
        if tiene_grupos and art and art == art.upper() and len(art) > 2:
            if limpiar_numero(art) is None and not any(c.isdigit() for c in art):
                norm_art = normalizar(art)
                if not any(norm_art.startswith(p) for p in IGNORAR_PREFIJOS):
                    categoria_actual = art
                    continue

        # Validar artículo
        if not es_rubro_valido(art):
            continue

        # Unidad de medida por fila (Kilo, Atado, etc.)
        unidad_fila = ''
        if col_uni is not None and col_uni < len(row):
            unidad_fila = str(row[col_uni]).strip()

        rubro_label = art
        # Prefijamos con categoría si existe
        rubro_code = a_code((categoria_actual + "_" + art) if categoria_actual else art)

        for cp in cols_periodo:
            col  = cp["col"]
            tipo = cp["tipo"]
            val  = cp["valor"]
            etiq = cp["etiqueta"]

            v_raw = row[col] if col < len(row) else ''
            valor = limpiar_numero(v_raw)

            # No emitir VAR_PCT sin valor
            if valor is None and tipo == "VAR_PCT":
                continue

            # Resolver TIME_PERIOD
            if tipo == "MES":
                mes = val if val else mes_de_etiqueta(etiq)
                if mes and anio_ctx:
                    time_period = f"{anio_ctx}-{int(mes):02d}"
                    freq = "M"
                else:
                    continue
            elif tipo in ("AÑO", "ANIO", "A"):
                time_period = str(val or anio_ctx or "")
                freq = "A"
                if not time_period:
                    continue
            elif tipo == "TRIMESTRE":
                time_period = f"{anio_ctx}-Q{val}" if anio_ctx and val else ""
                freq = "Q"
                if not time_period:
                    continue
            elif tipo == "SEMESTRE":
                time_period = f"{anio_ctx}-S{val}" if anio_ctx and val else ""
                freq = "S"
                if not time_period:
                    continue
            elif tipo == "VAR_PCT":
                time_period = str(anio_ctx) if anio_ctx else ""
                freq = "A"
                if not time_period:
                    continue
            else:
                continue  # OTRO u desconocido → saltar

            # OBS_MSR: VAR_PCT o la unidad de fila o INDEX
            if tipo == "VAR_PCT":
                obs_msr    = "VAR_PCT"
                unit_final = "PCT"
            elif unidad_fila:
                obs_msr    = a_code(unidad_fila)   # KILO, ATADO, BULBO, etc.
                unit_final = unit_measure
            else:
                obs_msr    = "INDEX"
                unit_final = unit_measure

            registros.append({
                "FREQ":            freq,
                "REF_AREA":        ref_area,
                "INDICATOR":       rubro_code,
                "INDICATOR_LABEL": rubro_label,
                "CATEGORIA":       categoria_actual or "",
                "UNIDAD_FILA":     unidad_fila,
                "TIME_PERIOD":     time_period,
                "OBS_MSR":         obs_msr,
                "OBS_VALUE":       valor,
                "OBS_STATUS":      "A" if valor is not None else "M",
                "UNIT_MEASURE":    unit_final,
                "BASE_YEAR":       base_year,
            })

    # Deduplicar
    seen = {}
    for r in registros:
        key = (r["TIME_PERIOD"], r["INDICATOR"], r["OBS_MSR"])
        if key not in seen or (seen[key]["OBS_VALUE"] is None and r["OBS_VALUE"] is not None):
            seen[key] = r

    resultado = sorted(seen.values(),
        key=lambda x: (x["TIME_PERIOD"], x.get("CATEGORIA",""), x["INDICATOR"], x["OBS_MSR"]))
    return resultado, None



st.title("📊 Conversor SDMX — DEIE Mendoza")
st.markdown("Versión local — soporta XLS, XLSX y PDF.")

# ── Paso 1: Subir archivo ─────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 1 — Subí el archivo</p>
  <p class="step-desc">XLS, XLSX o PDF de la DEIE.</p>
</div>""", unsafe_allow_html=True)

tipos = ["xlsx","xls"]
if PDF_DISPONIBLE:
    tipos.append("pdf")

uploaded_file = st.file_uploader("Archivo", type=tipos, label_visibility="collapsed")
if not uploaded_file:
    if not PDF_DISPONIBLE:
        st.info("💡 Para habilitar PDFs: pip install pdfplumber")
    st.stop()

es_pdf = uploaded_file.name.lower().endswith('.pdf')

# ── Leer archivo ──────────────────────────────────────────────────────────────
if es_pdf:
    rows_pdf, err = leer_pdf(uploaded_file)
    if err:
        st.error(f"❌ {err}")
        st.stop()
    st.success(f"✅ PDF cargado: {uploaded_file.name} — {len(rows_pdf)} filas extraídas")
    hojas = ['PDF (tabla extraída)']
    hoja_elegida = hojas[0]
    rows_activas = rows_pdf
    es_excel = False
else:
    xl, err = leer_excel(uploaded_file)
    if err:
        st.error(f"❌ No se pudo leer el archivo: {err}")
        st.stop()
    hojas = xl.sheet_names
    st.success(f"✅ {uploaded_file.name} — {len(hojas)} hoja(s)")
    es_excel = True

# ── Paso 2: Elegir hoja ───────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 2 — Elegí la hoja</p>
  <p class="step-desc">Elegí la hoja con todos los datos en formato tabla.</p>
</div>""", unsafe_allow_html=True)

if es_excel:
    hoja_elegida = st.selectbox("Hoja", hojas)
    df_raw = xl.parse(hoja_elegida, header=None)
    rows_activas = [[str(v).strip() if pd.notna(v) else '' for v in row]
                    for _, row in df_raw.iterrows()]

with st.expander("👁️ Vista previa — primeras 40 filas", expanded=True):
    if es_excel:
        df_prev = df_raw.head(40).fillna('').astype(str)
    else:
        df_prev = pd.DataFrame(rows_activas[:40])
    df_prev.index = range(1, len(df_prev)+1)
    st.dataframe(df_prev, use_container_width=True)

# ── Paso 3: Configuración ─────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 3 — Configuración</p>
  <p class="step-desc">La app detecta todos los bloques automáticamente desde la fila indicada.</p>
</div>""", unsafe_allow_html=True)

# Detectar primer bloque automáticamente
primer_bloque = next(
    (i for i, row in enumerate(rows_activas)
     if len(detectar_encabezado_en_fila(row)) >= 2),
    None
)
auto_msg = f"(auto: fila {primer_bloque+1})" if primer_bloque is not None else "(no detectada)"

col_a, col_b = st.columns(2)

with col_a:
    fila_inicio_input = st.number_input(
        f"Fila desde donde empezar {auto_msg}",
        min_value=1, max_value=max(len(rows_activas),1),
        value=(primer_bloque+1) if primer_bloque is not None else 1,
        step=1,
        help="La app procesa todos los bloques de esta fila hacia abajo."
    )
    fila_inicio = int(fila_inicio_input) - 1

    n_bloques = sum(1 for i in range(fila_inicio, len(rows_activas))
                    if len(detectar_encabezado_en_fila(rows_activas[i])) >= 2)
    if n_bloques > 0:
        st.markdown(f'<span class="tag-ok">✓ {n_bloques} bloque(s) detectado(s)</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="tag-err">✗ No se detectaron bloques</span>',
                    unsafe_allow_html=True)

with col_b:
    fila_ref = primer_bloque if primer_bloque is not None else 0
    opciones_col = {}
    fila_muestra = rows_activas[fila_ref] if fila_ref < len(rows_activas) else []
    fila_sig     = rows_activas[fila_ref+1] if fila_ref+1 < len(rows_activas) else []
    for i in range(min(len(fila_muestra), 20)):
        contenido = fila_muestra[i] or fila_sig[i] if i < len(fila_sig) else ''
        etiqueta  = f"Col {i+1}"
        if contenido and contenido not in ('','nan'):
            etiqueta += f" — {contenido[:30]}"
        opciones_col[etiqueta] = i

    col_rubro_label = st.selectbox(
        "Columna con los rubros / indicadores",
        list(opciones_col.keys()),
        help="Columna que tiene los nombres de los indicadores/rubros."
    )
    col_rubro = opciones_col[col_rubro_label]

col_c, col_d, col_e, col_f = st.columns(4)
with col_c:
    nombre_tabla = st.text_input(
        "Nombre tabla PostgreSQL",
        value=normalizar(hoja_elegida if es_excel else uploaded_file.name.rsplit('.',1)[0]).replace(' ','_')[:50]
    )
with col_d:
    ref_area = st.text_input("REF_AREA", value="AR-MZA")
with col_e:
    unit_measure = st.text_input("UNIT_MEASURE", value="INDEX")
with col_f:
    base_year = st.text_input("BASE_YEAR", value="1988")

# ── Paso 4: Convertir ─────────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 4 — Convertir y descargar</p>
  <p class="step-desc">Revisá la vista previa antes de guardar.</p>
</div>""", unsafe_allow_html=True)

if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
    with st.spinner("Procesando..."):
        registros, error = parsear_hoja(
            rows_activas, fila_inicio, col_rubro, ref_area, unit_measure, base_year
        )

    if error:
        st.error(f"❌ {error}")
    elif not registros:
        st.error("❌ No se encontraron datos.")
        with st.expander("🔍 Diagnóstico"):
            for i in range(fila_inicio, min(fila_inicio+30, len(rows_activas))):
                enc = detectar_encabezado_en_fila(rows_activas[i])
                if enc:
                    st.write(f"Fila {i+1}:", rows_activas[i], "→", enc)
    else:
        df_out = pd.DataFrame(registros)
        anios      = sorted(df_out['TIME_PERIOD'].str[:4].unique())
        freqs_out  = df_out['FREQ'].unique()
        medidas    = df_out['OBS_MSR'].unique()
        nulos      = int(df_out['OBS_VALUE'].isna().sum())

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Registros",  f"{len(registros):,}")
        c2.metric("Rubros",     df_out['INDICATOR'].nunique())
        c3.metric("Período",    f"{anios[0]}–{anios[-1]}" if anios else "—")
        c4.metric("Medidas",    ", ".join(medidas))

        if nulos:
            st.warning(f"⚠️ {nulos} registros sin valor numérico (quedarán como NULL).")

        with st.expander("👁️ Vista previa SDMX (primeros 40 registros)"):
            st.dataframe(df_out.head(40), use_container_width=True)

        with st.expander("📋 Rubros detectados"):
            st.dataframe(
                df_out[['INDICATOR','INDICATOR_LABEL']].drop_duplicates().sort_values('INDICATOR'),
                use_container_width=True
            )

        with st.expander("📐 Medidas detectadas (OBS_MSR)"):
            resumen = df_out.groupby('OBS_MSR')['OBS_VALUE'].agg(
                registros='count', nulos=lambda x: x.isna().sum()
            ).reset_index()
            st.dataframe(resumen, use_container_width=True)

        nombre_csv = f"{nombre_tabla}_sdmx.csv"
        csv_bytes  = df_out.to_csv(index=False).encode('utf-8')
        sql        = generar_sql(nombre_tabla, nombre_csv, ref_area)

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button("⬇️ Descargar CSV SDMX", csv_bytes,
                file_name=nombre_csv, mime="text/csv", use_container_width=True)
        with dl2:
            st.download_button("⬇️ Descargar SQL", sql.encode('utf-8'),
                file_name=f"{nombre_tabla}.sql", mime="text/plain", use_container_width=True)

        with st.expander("📄 SQL para DBeaver"):
            st.code(sql, language='sql')

st.markdown("---")
st.caption("Conversor SDMX v1.0.0 — DEIE Mendoza | Versión local")