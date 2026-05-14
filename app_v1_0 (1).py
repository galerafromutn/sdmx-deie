"""
Conversor SDMX — DEIE Mendoza  v1.0
Agrega una capa semántica con Claude para detectar automáticamente
la estructura de cualquier tabla de la DEIE.

Streamlit Cloud: agregar ANTHROPIC_API_KEY en Settings > Secrets
"""

import streamlit as st
import pandas as pd
import re
import json
import requests

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
    'fuente','nota','dato igual','- dato','datos igual','(*)','elaboracion',
    'elaboración','ver ','véase','aclaracion','aclaración',
    'los valores','los datos','en el ano','en el año','promedio'
]
IGNORAR_CONTIENE = ['grafico','gráfico','cuadro','figura']
IGNORAR_EXACTOS  = {
    'rubros','rubro','descripcion','descripción','concepto',
    'item','ítem','detalle','categoria','categoría'
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
    n_puntos    = s.count('.')
    n_comas     = s.count(',')
    if tiene_coma and tiene_punto:
        s = s.replace('.','').replace(',','.') if s.rfind(',') > s.rfind('.') else s.replace(',','')
    elif tiene_punto and n_puntos > 1:
        s = s.replace('.','')
    elif tiene_coma and n_comas == 1:
        s = s.replace(',','.')
    elif tiene_coma and n_comas > 1:
        s = s.replace(',','')
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
    if re.search(r'\bvar(iacion|iación)?\b', s_norm) or s_norm.strip('%').strip() == '':
        return ('VAR_PCT', None), 'VAR'
    if s_norm in MESES_ES:
        return ('MES', MESES_ES[s_norm]), 'M'
    if re.fullmatch(r'(19|20)\d{2}', s):
        return s, 'A'
    m = re.fullmatch(r'((19|20)\d{2})\s*[-–]\s*((19|20)\d{2})', s)
    if m:
        a1, a2 = m.group(1), m.group(3)
        diff = int(a2) - int(a1)
        return (a1 if diff <= 1 else f"{a1}/{a2}"), ('A' if diff <= 1 else 'P')
    m = re.search(r'(\d)[°º]?\s*(trim)', s_norm)
    if not m:
        m = re.search(r'\bt\s*(\d)', s_norm)
    if m:
        return ('TRIM', int(m.group(1))), 'Q'
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

def resolver_time_period(periodo_raw, freq, anio_ctx, num_col_var=None, cols_index_ref=None):
    if isinstance(periodo_raw, tuple):
        tipo, num = periodo_raw
        if tipo == 'MES':
            return (f"{anio_ctx}-{num:02d}", 'M') if anio_ctx else (None, freq)
        if tipo == 'TRIM':
            return (f"{anio_ctx}-Q{num}", 'Q') if anio_ctx else (None, freq)
        if tipo == 'SEM':
            return (f"{anio_ctx}-S{num}", 'S') if anio_ctx else (None, freq)
        if tipo == 'VAR_PCT':
            if cols_index_ref is not None and num_col_var is not None:
                if num_col_var < len(cols_index_ref):
                    ref_periodo, ref_freq = cols_index_ref[num_col_var][1], cols_index_ref[num_col_var][2]
                    return resolver_time_period(ref_periodo, ref_freq, anio_ctx)
            return (str(anio_ctx), 'A') if anio_ctx else (None, freq)
    return str(periodo_raw), freq

def clasificar_columnas(rows, fila_enc, enc_raw, mapeo_ia=None):
    """
    Clasifica columnas como INDEX o VAR_PCT.
    Si hay mapeo de IA disponible, lo usa como prioridad.
    """
    n = len(rows)
    filas_sup = [rows[fila_enc - k] for k in range(1, 4) if fila_enc - k >= 0]
    filas_inf = [rows[fila_enc + k] for k in range(1, 3) if fila_enc + k < n]
    todas_las_filas = filas_sup + [rows[fila_enc]] + filas_inf

    col_tipo     = {}
    encontro_pct = False

    for col_idx, periodo_raw, _ in enc_raw:
        # Si la IA detectó el tipo de esta columna, usarlo
        if mapeo_ia and str(col_idx) in mapeo_ia.get('col_tipos', {}):
            col_tipo[col_idx] = mapeo_ia['col_tipos'][str(col_idx)]
            if col_tipo[col_idx] == 'VAR_PCT':
                encontro_pct = True
            continue

        if isinstance(periodo_raw, tuple) and periodo_raw[0] == 'VAR_PCT':
            col_tipo[col_idx] = 'VAR_PCT'
            encontro_pct = True
            continue

        celdas      = [str(f[col_idx]) if col_idx < len(f) else '' for f in todas_las_filas]
        celdas_norm = [normalizar(c) for c in celdas]
        es_pct      = any('%' in c or 'var' in c for c in celdas_norm)
        if es_pct:
            col_tipo[col_idx] = 'VAR_PCT'
            encontro_pct = True
        else:
            col_tipo[col_idx] = 'INDEX'

    for col_idx, _, _ in enc_raw:
        if col_idx not in col_tipo:
            col_tipo[col_idx] = 'INDEX'

    return col_tipo

# ─── Capa semántica con Claude ────────────────────────────────────────────────

def preview_a_texto(rows, max_filas=40):
    """Convierte las primeras filas a texto plano para enviar a Claude."""
    lines = []
    for i, row in enumerate(rows[:max_filas]):
        vals = [v for v in row if v and v not in ('nan','')]
        if vals:
            lines.append(f"F{i+1}: {' | '.join(str(v)[:30] for v in vals[:12])}")
    return '\n'.join(lines)

def analizar_con_claude(rows, api_key):
    """
    Envía las primeras filas a Claude y obtiene un JSON con el mapeo semántico.
    Retorna un dict con la estructura detectada, o None si falla.
    """
    preview = preview_a_texto(rows, max_filas=50)

    prompt = f"""Analizá esta tabla de datos estadísticos de la DEIE (Dirección de Estadísticas de Mendoza, Argentina).

CONTENIDO DE LA HOJA (primeras filas, formato F[número_fila]: col1 | col2 | ...):
{preview}

Tu tarea es identificar la estructura para convertirla a formato SDMX.

Respondé ÚNICAMENTE con un JSON válido con esta estructura exacta:
{{
  "tipo_tabla": "indices_mensuales" | "indices_anuales" | "precios_multiples_medidas" | "tabla_anual_rubros" | "otro",
  "descripcion": "descripción breve de qué contiene la tabla",
  "fila_encabezado": número de fila (1-based) donde están los períodos (meses/años/trimestres),
  "col_rubros": número de columna (0-based) que contiene los nombres de indicadores/rubros,
  "freq": "M" | "A" | "Q" | "S",
  "unit_measure": "INDEX" | "ARS" | "KG" | "HL" | "TN" | "UNIDAD" | "otro",
  "base_year": "1988" u otro año base si se menciona, o null,
  "col_tipos": {{
    "N": "INDEX" | "VAR_PCT" | "PRECIO" | "KG" | "HL" | "TN" | "OPERACIONES" | "ATADO" | "UNIDAD"
  }},
  "notas": "observaciones importantes sobre la estructura"
}}

Donde col_tipos mapea el índice de columna (0-based, como string) al tipo de medida que contiene.
Solo incluí las columnas que claramente son datos numéricos (no la columna de rubros ni columnas vacías).
Si no podés determinarlo con certeza, usá "INDEX" como default.
NO incluyas texto fuera del JSON."""

    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        body = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}]
        }
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        texto = data['content'][0]['text'].strip()

        # Limpiar markdown si Claude lo envuelve en ```json
        texto = re.sub(r'^```json\s*', '', texto)
        texto = re.sub(r'^```\s*', '', texto)
        texto = re.sub(r'\s*```$', '', texto)

        return json.loads(texto), None

    except requests.exceptions.Timeout:
        return None, "Timeout al conectar con Claude. Intentá de nuevo."
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return None, "API key inválida. Verificá el secret ANTHROPIC_API_KEY en Streamlit."
        return None, f"Error HTTP {e.response.status_code}: {e.response.text[:200]}"
    except json.JSONDecodeError as e:
        return None, f"Claude no devolvió JSON válido: {e}"
    except Exception as e:
        return None, f"Error inesperado: {e}"

# ─── Parser multi-bloque ──────────────────────────────────────────────────────

OBS_MSR_ORDEN = {'INDEX': 0, 'VAR_PCT': 1}

def parsear_datos(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year, mapeo_ia=None):
    registros = []

    bloques = []
    for i in range(fila_inicio, len(rows)):
        enc = detectar_encabezado_en_fila(rows[i])
        if enc:
            bloques.append((i, enc))

    if not bloques:
        return [], "No se detectaron períodos temporales en la hoja."

    def ultimo_bloque_index(b_idx, bloques_lista):
        for j in range(b_idx - 1, -1, -1):
            enc_ref = bloques_lista[j][1]
            tipos = [p[0] if isinstance(p, tuple) else 'ANIO' for _, p, _ in enc_ref]
            if 'VAR_PCT' not in tipos:
                return enc_ref
        return None

    for b_idx, (fila_enc, enc_raw) in enumerate(bloques):
        fila_fin = bloques[b_idx + 1][0] if b_idx + 1 < len(bloques) else len(rows)
        col_tipo  = clasificar_columnas(rows, fila_enc, enc_raw, mapeo_ia)
        cols_info = [(col_idx, periodo_raw, freq, col_tipo[col_idx])
                     for col_idx, periodo_raw, freq in enc_raw]

        es_bloque_var = all(col_tipo[ci] == 'VAR_PCT' for ci, _, _ in enc_raw)
        cols_index_ref = None
        if es_bloque_var:
            ref = ultimo_bloque_index(b_idx, bloques)
            if ref:
                cols_index_ref = ref

        anio_ctx = None
        buscar_desde = max(0, fila_enc - 10)
        for row in rows[buscar_desde:fila_enc]:
            for v in row:
                m = re.search(r'\b(19|20)\d{2}\b', str(v))
                if m:
                    anio_ctx = int(m.group(0))

        for row in rows[fila_enc + 1 : fila_fin]:
            col0 = str(row[col_rubro]).strip() if col_rubro < len(row) else ''

            for v in row:
                m = re.search(r'\b(19|20)\d{2}\b', str(v))
                if m:
                    nuevo = int(m.group(0))
                    if 1980 <= nuevo <= 2030:
                        anio_ctx = nuevo
                        break

            if not es_rubro_valido(col0):
                continue

            rubro_code  = a_code(col0)
            rubro_label = col0
            var_col_counter = 0

            for col_idx, periodo_raw, freq, obs_msr in cols_info:
                v_raw = row[col_idx] if col_idx < len(row) else ''
                valor = limpiar_numero(v_raw)

                if valor is None and obs_msr == 'VAR_PCT':
                    var_col_counter += 1
                    continue

                if obs_msr == 'VAR_PCT':
                    time_period, freq_final = resolver_time_period(
                        periodo_raw, freq, anio_ctx,
                        num_col_var=var_col_counter,
                        cols_index_ref=cols_index_ref
                    )
                    var_col_counter += 1
                else:
                    time_period, freq_final = resolver_time_period(periodo_raw, freq, anio_ctx)

                if time_period is None:
                    continue

                # unit_measure: si la IA detectó uno, usarlo; si no, el del formulario
                u_measure = unit_measure
                if mapeo_ia and mapeo_ia.get('unit_measure') and obs_msr == 'INDEX':
                    u_measure = mapeo_ia['unit_measure']

                registros.append({
                    'FREQ':            freq_final,
                    'REF_AREA':        ref_area,
                    'INDICATOR':       rubro_code,
                    'INDICATOR_LABEL': rubro_label,
                    'TIME_PERIOD':     time_period,
                    'OBS_MSR':         obs_msr,
                    'OBS_VALUE':       valor,
                    'OBS_STATUS':      'A' if valor is not None else 'M',
                    'UNIT_MEASURE':    u_measure if obs_msr != 'VAR_PCT' else 'PCT',
                    'BASE_YEAR':       base_year,
                })

    seen = {}
    for r in registros:
        key = (r['TIME_PERIOD'], r['INDICATOR'], r['OBS_MSR'])
        if key not in seen or (seen[key]['OBS_VALUE'] is None and r['OBS_VALUE'] is not None):
            seen[key] = r

    resultado = sorted(
        seen.values(),
        key=lambda x: (x['TIME_PERIOD'], x['INDICATOR'], OBS_MSR_ORDEN.get(x['OBS_MSR'], 99))
    )
    return resultado, None

# ─── SQL ──────────────────────────────────────────────────────────────────────

def generar_sql(nombre_tabla, nombre_csv, ref_area):
    return f"""-- Tabla SDMX — generada automáticamente
CREATE TABLE IF NOT EXISTS public.{nombre_tabla} (
    id_registro       SERIAL PRIMARY KEY,
    "FREQ"            VARCHAR(2)    NOT NULL,
    "REF_AREA"        VARCHAR(10)   DEFAULT '{ref_area}',
    "INDICATOR"       VARCHAR(255)  NOT NULL,
    "INDICATOR_LABEL" TEXT,
    "TIME_PERIOD"     VARCHAR(10)   NOT NULL,
    "OBS_MSR"         VARCHAR(20)   NOT NULL,
    "OBS_VALUE"       NUMERIC(18,6),
    "OBS_STATUS"      CHAR(1)       DEFAULT 'A',
    "UNIT_MEASURE"    VARCHAR(20),
    "BASE_YEAR"       CHAR(4)
);

COPY public.{nombre_tabla} (
    "FREQ","REF_AREA","INDICATOR","INDICATOR_LABEL",
    "TIME_PERIOD","OBS_MSR","OBS_VALUE","OBS_STATUS","UNIT_MEASURE","BASE_YEAR"
)
FROM 'C:/ruta/a/tu/carpeta/{nombre_csv}'
DELIMITER ','
CSV HEADER
NULL '';
"""

# ─── UI ───────────────────────────────────────────────────────────────────────

st.title("📊 Conversor SDMX — DEIE Mendoza")
st.markdown("Convierte cualquier Excel de la DEIE a formato SDMX usando IA para detectar la estructura.")

# ── API Key ───────────────────────────────────────────────────────────────────
api_key = st.secrets.get("ANTHROPIC_API_KEY", "") if hasattr(st, 'secrets') else ""
usar_ia  = bool(api_key)

if not usar_ia:
    st.warning("⚠️ No se encontró ANTHROPIC_API_KEY en los secrets de Streamlit. "
               "La app funciona sin IA pero con detección básica. "
               "Agregá el secret en Settings > Secrets para habilitar el análisis semántico.")

# ── Paso 1 ────────────────────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 1 — Subí el archivo Excel</p>
  <p class="step-desc">XLS o XLSX de la DEIE — mensual, anual, trimestral, etc.</p>
</div>""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Archivo Excel", type=["xlsx","xls"], label_visibility="collapsed")
if not uploaded_file:
    st.stop()

try:
    xl = pd.ExcelFile(uploaded_file,
        engine='openpyxl' if uploaded_file.name.endswith('xlsx') else 'xlrd')
except Exception:
    try:
        xl = pd.ExcelFile(uploaded_file)
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        st.stop()

hojas = xl.sheet_names
st.success(f"✅ {uploaded_file.name} — {len(hojas)} hoja(s)")

# ── Paso 2 ────────────────────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 2 — Elegí la hoja</p>
  <p class="step-desc">Elegí la hoja que tenga los datos en formato tabla.</p>
</div>""", unsafe_allow_html=True)

hoja_elegida = st.selectbox("Hoja", hojas)
df_raw = xl.parse(hoja_elegida, header=None)
rows   = [[str(v).strip() if pd.notna(v) else '' for v in row] for _, row in df_raw.iterrows()]

with st.expander("👁️ Vista previa — primeras 40 filas", expanded=True):
    df_prev = df_raw.head(40).fillna('').astype(str)
    df_prev.index = range(1, len(df_prev)+1)
    st.dataframe(df_prev, use_container_width=True)

# ── Paso 3: Análisis semántico ────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 3 — Análisis semántico</p>
  <p class="step-desc">Claude analiza la estructura de la tabla y sugiere la configuración óptima.</p>
</div>""", unsafe_allow_html=True)

mapeo_ia = None

if usar_ia:
    if st.button("🤖 Analizar con IA", use_container_width=True):
        with st.spinner("Claude está analizando la estructura de la tabla..."):
            mapeo_ia, err_ia = analizar_con_claude(rows, api_key)
        if err_ia:
            st.error(f"❌ Error en análisis IA: {err_ia}")
            mapeo_ia = None
        else:
            st.session_state['mapeo_ia']     = mapeo_ia
            st.session_state['hoja_analizada'] = hoja_elegida

    # Recuperar mapeo de session si ya fue analizado para esta hoja
    if mapeo_ia is None and st.session_state.get('hoja_analizada') == hoja_elegida:
        mapeo_ia = st.session_state.get('mapeo_ia')

    if mapeo_ia:
        st.success("✅ Análisis completado")
        c1, c2, c3 = st.columns(3)
        c1.info(f"**Tipo:** {mapeo_ia.get('tipo_tabla','—')}")
        c2.info(f"**Frecuencia:** {FREQ_LABEL.get(mapeo_ia.get('freq',''),'—')}")
        c3.info(f"**Medida:** {mapeo_ia.get('unit_measure','—')}")
        if mapeo_ia.get('descripcion'):
            st.caption(f"📝 {mapeo_ia['descripcion']}")
        if mapeo_ia.get('notas'):
            st.caption(f"⚠️ {mapeo_ia['notas']}")
        with st.expander("🔍 Ver mapeo completo (JSON)"):
            st.json(mapeo_ia)
else:
    st.info("ℹ️ Análisis IA no disponible — se usará detección automática básica.")

# ── Paso 4: Configuración ─────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 4 — Configuración</p>
  <p class="step-desc">Revisá y ajustá los parámetros sugeridos por la IA (o configurá manualmente).</p>
</div>""", unsafe_allow_html=True)

# Valores sugeridos por IA o autodetectados
primer_bloque = next(
    (i for i, row in enumerate(rows) if len(detectar_encabezado_en_fila(row)) >= 2),
    None
)
sugerido_fila = (mapeo_ia.get('fila_encabezado', primer_bloque + 1 if primer_bloque is not None else 1)
                 if mapeo_ia else (primer_bloque + 1 if primer_bloque is not None else 1))
sugerido_col  = (mapeo_ia.get('col_rubros', 0) if mapeo_ia else 0)
sugerido_freq = (mapeo_ia.get('freq', 'M')     if mapeo_ia else 'M')
sugerido_um   = (mapeo_ia.get('unit_measure','INDEX') if mapeo_ia else 'INDEX')
sugerido_by   = (mapeo_ia.get('base_year') or '1988') if mapeo_ia else '1988'

col_a, col_b = st.columns(2)

with col_a:
    auto_msg = f"(IA: fila {sugerido_fila})" if mapeo_ia else f"(auto: fila {primer_bloque+1})" if primer_bloque is not None else "(no detectada)"
    fila_enc_input = st.number_input(
        f"Fila desde donde empezar {auto_msg}",
        min_value=1, max_value=len(rows),
        value=int(sugerido_fila),
        step=1
    )
    fila_inicio = int(fila_enc_input) - 1

    n_bloques = sum(1 for i in range(fila_inicio, len(rows))
                    if len(detectar_encabezado_en_fila(rows[i])) >= 2)
    if n_bloques > 0:
        st.markdown(f'<span class="tag-ok">✓ {n_bloques} bloque(s) detectado(s)</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="tag-err">✗ No se detectaron bloques</span>', unsafe_allow_html=True)

with col_b:
    fila_ref = primer_bloque if primer_bloque is not None else 0
    opciones_col = {}
    for i in range(min(len(rows[fila_ref]), 20)):
        contenido = rows[fila_ref][i] or (rows[fila_ref+1][i] if fila_ref+1 < len(rows) else '')
        etiqueta  = f"Col {i+1}"
        if contenido and contenido not in ('','nan'):
            etiqueta += f" — {contenido[:30]}"
        opciones_col[etiqueta] = i

    idx_sugerido = min(sugerido_col, len(opciones_col) - 1)
    col_rubro_label = st.selectbox(
        "Columna con los rubros / indicadores",
        list(opciones_col.keys()),
        index=idx_sugerido
    )
    col_rubro = opciones_col[col_rubro_label]

col_c, col_d, col_e, col_f = st.columns(4)
with col_c:
    nombre_tabla = st.text_input("Nombre tabla PostgreSQL",
        value=normalizar(hoja_elegida).replace(' ','_')[:50])
with col_d:
    ref_area = st.text_input("REF_AREA", value="AR-MZA")
with col_e:
    unit_measure = st.text_input("UNIT_MEASURE", value=sugerido_um)
with col_f:
    base_year = st.text_input("BASE_YEAR", value=str(sugerido_by))

# ── Paso 5: Convertir ─────────────────────────────────────────────────────────
st.markdown("""<div class="step-box">
  <p class="step-title">Paso 5 — Convertir y descargar</p>
  <p class="step-desc">Revisá la vista previa antes de descargar.</p>
</div>""", unsafe_allow_html=True)

if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
    with st.spinner("Procesando..."):
        registros, error = parsear_datos(
            rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year, mapeo_ia
        )

    if error:
        st.error(f"❌ {error}")
    elif not registros:
        st.error("❌ No se encontraron datos.")
        with st.expander("🔍 Diagnóstico"):
            for i in range(fila_inicio, min(fila_inicio+30, len(rows))):
                enc = detectar_encabezado_en_fila(rows[i])
                if enc:
                    st.write(f"Fila {i+1}:", rows[i], "→", enc)
    else:
        df_out = pd.DataFrame(registros)
        anios  = sorted(df_out['TIME_PERIOD'].str[:4].unique())
        freqs  = df_out['FREQ'].unique()
        nulos  = int(df_out['OBS_VALUE'].isna().sum())

        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Registros",  f"{len(registros):,}")
        c2.metric("Rubros",     df_out['INDICATOR'].nunique())
        c3.metric("Período",    f"{anios[0]}–{anios[-1]}" if anios else "—")
        c4.metric("Frecuencia", ", ".join(FREQ_LABEL.get(f,f) for f in freqs))

        if nulos:
            st.warning(f"⚠️ {nulos} registros sin valor (quedarán como NULL).")

        with st.expander("👁️ Vista previa SDMX (primeros 30 registros)"):
            st.dataframe(df_out.head(30), use_container_width=True)

        with st.expander("📋 Rubros detectados"):
            st.dataframe(
                df_out[['INDICATOR','INDICATOR_LABEL']].drop_duplicates().sort_values('INDICATOR'),
                use_container_width=True
            )

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
st.caption("Conversor SDMX v1.0.0 — DEIE Mendoza | Dirección de Estadísticas e Investigaciones Económicas")
