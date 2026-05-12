import streamlit as st
import pandas as pd
import re

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
    .step-title { font-weight: 600; font-size: 1.05rem; color: #1f77b4; margin: 0 0 0.25rem 0; }
    .step-desc  { font-size: 0.9rem; color: #555; margin: 0; }
    .tag-ok  { background:#d4edda; color:#155724; padding:2px 8px; border-radius:4px; font-size:0.8rem; }
    .tag-err { background:#f8d7da; color:#721c24; padding:2px 8px; border-radius:4px; font-size:0.8rem; }
</style>
""", unsafe_allow_html=True)

# ─── Constantes ───────────────────────────────────────────────────────────────
MESES_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,
    'noviembre':11,'diciembre':12
}
FREQ_LABEL = {'M':'Mensual','A':'Anual','Q':'Trimestral','S':'Semestral','P':'Plurianual'}

# Prefijos que indican fila de metadatos (no datos)
IGNORAR_PREFIJOS = [
    'fuente','nota','dato igual','- dato','datos igual','(*)','elaboracion',
    'elaboración','ver ','véase','aclaracion','aclaración','(*)',
    'los valores','los datos','en el ano','en el año','promedio'
]
# Palabras en cualquier parte del rubro que lo descartan
IGNORAR_CONTIENE = ['grafico','gráfico','cuadro','figura']
# Textos exactos (normalizados) que son títulos de columna, no rubros reales
IGNORAR_EXACTOS = {'rubros', 'rubro', 'descripcion', 'descripción', 'concepto',
                   'item', 'ítem', 'detalle', 'categoria', 'categoría'}

# ─── Utilidades ───────────────────────────────────────────────────────────────

def normalizar(texto):
    t = str(texto).strip().lower()
    for a,b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        t = t.replace(a,b)
    return t

def a_code(texto):
    t = re.sub(r'\s+', ' ', str(texto).strip())
    for a,b in [('Á','A'),('É','E'),('Í','I'),('Ó','O'),('Ú','U'),('Ñ','N'),
                ('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        t = t.replace(a,b)
    return re.sub(r'[^A-Z0-9_]', '_', t.upper().replace(' ','_'))

def limpiar_numero(v):
    if v is None or str(v).strip() in ('','nan','None','-','—','...','..','(*)','*','n/d','s/d','N/A'):
        return None
    s = str(v).strip().strip('()').strip()
    # Quitar asteriscos y símbolos extra
    s = re.sub(r'[*†‡°%]', '', s).strip()
    if not s:
        return None

    tiene_coma  = ',' in s
    tiene_punto = '.' in s
    n_puntos    = s.count('.')
    n_comas     = s.count(',')

    if tiene_coma and tiene_punto:
        # Determinar cuál es el separador decimal por posición
        if s.rfind(',') > s.rfind('.'):
            # Coma es decimal → puntos son miles: 1.234.567,89
            s = s.replace('.', '').replace(',', '.')
        else:
            # Punto es decimal → comas son miles: 1,234,567.89
            s = s.replace(',', '')
    elif tiene_punto and n_puntos > 1:
        # Múltiples puntos = separador de miles argentino: 697.534.458
        s = s.replace('.', '')
    elif tiene_coma and n_comas == 1:
        # Una sola coma = decimal: 2,51
        s = s.replace(',', '.')
    elif tiene_coma and n_comas > 1:
        # Múltiples comas = separador de miles: 1,234,567
        s = s.replace(',', '')

    s = re.sub(r'[^\d.\-]', '', s)
    if not s or s in ('.', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def es_rubro_valido(texto):
    """True si el texto es un nombre de rubro real (no nota, gráfico, cuadro, título de columna, etc.)"""
    if not texto or str(texto).strip().lower() in ('','nan','none'):
        return False
    norm = normalizar(texto)
    # Ignorar textos exactos que son encabezados de columna, no rubros
    if norm in IGNORAR_EXACTOS:
        return False
    # Ignorar notas y metadatos
    if any(norm.startswith(p) for p in IGNORAR_PREFIJOS):
        return False
    if any(p in norm for p in IGNORAR_CONTIENE):
        return False
    # Ignorar si es un año solo
    if re.fullmatch(r'(19|20)\d{2}', texto.strip()):
        return False
    # Ignorar si es número puro
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

    # ── Variación porcentual explícita ──────────────────────────────────────────
    # Acepta: "Var.", "Var. %", "Var %", "Variación %", "Variacion", "%", etc.
    if re.search(r'\bvar(iacion|iación)?\b', s_norm) or s_norm.strip('%').strip() == '':
        return ('VAR_PCT', None), 'VAR'

    # ── Meses ───────────────────────────────────────────────────────────────────
    if s_norm in MESES_ES:
        return ('MES', MESES_ES[s_norm]), 'M'

    # ── Año simple ──────────────────────────────────────────────────────────────
    if re.fullmatch(r'(19|20)\d{2}', s):
        return s, 'A'

    # ── Rango de años ───────────────────────────────────────────────────────────
    m = re.fullmatch(r'((19|20)\d{2})\s*[-–]\s*((19|20)\d{2})', s)
    if m:
        a1, a2 = m.group(1), m.group(3)
        diff = int(a2) - int(a1)
        return (a1 if diff <= 1 else f"{a1}/{a2}"), ('A' if diff <= 1 else 'P')

    # ── Trimestres ──────────────────────────────────────────────────────────────
    m = re.search(r'(\d)[°º]?\s*(trim)', s_norm)
    if not m:
        m = re.search(r'\bt\s*(\d)', s_norm)
    if m:
        return ('TRIM', int(m.group(1))), 'Q'

    # ── Semestres ───────────────────────────────────────────────────────────────
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
    """
    Convierte un periodo_raw + contexto en (TIME_PERIOD string, FREQ).
    Para VAR_PCT: usa el número de orden de la columna para mapear al mismo período
    que le corresponde en el bloque de índices (mismo mes/trim/año, mismo año de contexto).
    """
    if isinstance(periodo_raw, tuple):
        tipo, num = periodo_raw
        if tipo == 'MES':
            return (f"{anio_ctx}-{num:02d}", 'M') if anio_ctx else (None, freq)
        if tipo == 'TRIM':
            return (f"{anio_ctx}-Q{num}", 'Q') if anio_ctx else (None, freq)
        if tipo == 'SEM':
            return (f"{anio_ctx}-S{num}", 'S') if anio_ctx else (None, freq)
        if tipo == 'VAR_PCT':
            # El VAR_PCT hereda el período del índice correspondiente por posición
            if cols_index_ref is not None and num_col_var is not None:
                # cols_index_ref: lista ordenada de (col_idx, periodo_raw, freq) del bloque índice
                if num_col_var < len(cols_index_ref):
                    ref_periodo, ref_freq = cols_index_ref[num_col_var][1], cols_index_ref[num_col_var][2]
                    return resolver_time_period(ref_periodo, ref_freq, anio_ctx)
            # Fallback: solo el año
            return (str(anio_ctx), 'A') if anio_ctx else (None, freq)
    return str(periodo_raw), freq

# ─── Clasificación INDEX vs VAR_PCT ───────────────────────────────────────────

def clasificar_columnas(rows, fila_enc, enc_raw):
    """
    Determina si cada columna es INDEX o VAR_PCT.
    Prioridad:
      1. Si el periodo detectado ya es ('VAR_PCT', None) → columna es VAR_PCT directamente.
      2. Si no, busca '%' o 'var' en ±3 filas alrededor del encabezado.
      3. Si no encuentra nada → INDEX.
    """
    n         = len(rows)
    filas_sup = [rows[fila_enc - k] for k in range(1, 4) if fila_enc - k >= 0]
    filas_inf = [rows[fila_enc + k] for k in range(1, 3) if fila_enc + k < n]
    todas_las_filas = filas_sup + [rows[fila_enc]] + filas_inf

    col_tipo     = {}
    encontro_pct = False

    for col_idx, periodo_raw, _ in enc_raw:
        # Si el propio periodo dice VAR_PCT, no hay que buscar más
        if isinstance(periodo_raw, tuple) and periodo_raw[0] == 'VAR_PCT':
            col_tipo[col_idx] = 'VAR_PCT'
            encontro_pct = True
            continue

        # Buscar señales de % en filas de contexto
        celdas      = [str(f[col_idx]) if col_idx < len(f) else '' for f in todas_las_filas]
        celdas_norm = [normalizar(c) for c in celdas]
        es_pct      = any('%' in c or 'var' in c for c in celdas_norm)
        if es_pct:
            col_tipo[col_idx] = 'VAR_PCT'
            encontro_pct = True
        else:
            col_tipo[col_idx] = 'INDEX'

    # Fallback: si aún hay columnas sin asignar
    for col_idx, _, _ in enc_raw:
        if col_idx not in col_tipo:
            col_tipo[col_idx] = 'INDEX'

    return col_tipo

# ─── Parser multi-bloque ──────────────────────────────────────────────────────

def parsear_datos(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year):
    """
    Procesa TODOS los bloques de la hoja.
    Un bloque = fila de encabezado + filas de datos hasta el próximo encabezado.
    Detecta bloques INDEX y bloques VAR_PCT por separado, y asocia las variaciones
    al período correcto usando el bloque de índices precedente como referencia.
    """
    registros = []

    # 1. Encontrar todas las filas que son encabezados de bloque
    bloques = []
    for i in range(fila_inicio, len(rows)):
        enc = detectar_encabezado_en_fila(rows[i])
        if enc:
            bloques.append((i, enc))

    if not bloques:
        return [], "No se detectaron períodos temporales en la hoja."

    # 2. Para cada bloque VAR_PCT, encontrar el bloque INDEX más cercano anterior
    #    para usar como referencia de períodos
    def ultimo_bloque_index(b_idx, bloques_lista):
        """Devuelve enc_raw del último bloque INDEX antes de b_idx."""
        for j in range(b_idx - 1, -1, -1):
            enc_ref = bloques_lista[j][1]
            tipos = [p[0] if isinstance(p, tuple) else 'ANIO'
                     for _, p, _ in enc_ref]
            if 'VAR_PCT' not in tipos:
                return enc_ref
        return None

    # 3. Procesar cada bloque
    for b_idx, (fila_enc, enc_raw) in enumerate(bloques):
        fila_fin = bloques[b_idx + 1][0] if b_idx + 1 < len(bloques) else len(rows)

        col_tipo  = clasificar_columnas(rows, fila_enc, enc_raw)
        cols_info = [(col_idx, periodo_raw, freq, col_tipo[col_idx])
                     for col_idx, periodo_raw, freq in enc_raw]

        # Determinar si este bloque es puramente VAR_PCT
        es_bloque_var = all(col_tipo[ci] == 'VAR_PCT' for ci, _, _ in enc_raw)

        # Referencia de índices para mapear períodos de variación
        cols_index_ref = None
        if es_bloque_var:
            ref = ultimo_bloque_index(b_idx, bloques)
            if ref:
                cols_index_ref = ref  # lista de (col_idx, periodo_raw, freq)

        # Buscar año de contexto en filas anteriores a este bloque
        anio_ctx = None
        buscar_desde = max(0, fila_enc - 10)
        for row in rows[buscar_desde:fila_enc]:
            for v in row:
                m = re.search(r'\b(19|20)\d{2}\b', str(v))
                if m:
                    anio_ctx = int(m.group(0))

        # Procesar filas de datos
        for row in rows[fila_enc + 1 : fila_fin]:
            col0 = str(row[col_rubro]).strip() if col_rubro < len(row) else ''

            # Actualizar año de contexto
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

            # Índice de posición dentro de las columnas VAR_PCT (para mapeo de período)
            var_col_counter = 0

            for col_idx, periodo_raw, freq, obs_msr in cols_info:
                v_raw = row[col_idx] if col_idx < len(row) else ''
                valor = limpiar_numero(v_raw)

                # No emitir VAR_PCT sin valor (evita ruido)
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

                registros.append({
                    'FREQ':            freq_final,
                    'REF_AREA':        ref_area,
                    'INDICATOR':       rubro_code,
                    'INDICATOR_LABEL': rubro_label,
                    'TIME_PERIOD':     time_period,
                    'OBS_MSR':         obs_msr,
                    'OBS_VALUE':       valor,
                    'OBS_STATUS':      'A' if valor is not None else 'M',
                    'UNIT_MEASURE':    unit_measure if obs_msr == 'INDEX' else 'PCT',
                    'BASE_YEAR':       base_year,
                })

    # Deduplicar: si el mismo (TIME_PERIOD, INDICATOR, OBS_MSR) aparece en varios bloques,
    # quedarse con el que tiene valor (el bloque más reciente suele ser más completo)
    seen = {}
    for r in registros:
        key = (r['TIME_PERIOD'], r['INDICATOR'], r['OBS_MSR'])
        if key not in seen or (seen[key]['OBS_VALUE'] is None and r['OBS_VALUE'] is not None):
            seen[key] = r

    resultado = sorted(seen.values(), key=lambda x: (x['TIME_PERIOD'], x['INDICATOR'], x['OBS_MSR']))
    return resultado, None

# ─── SQL ──────────────────────────────────────────────────────────────────────

def generar_sql(nombre_tabla, nombre_csv, ref_area):
    return f"""-- Tabla SDMX
CREATE TABLE IF NOT EXISTS public.{nombre_tabla} (
    id_registro       SERIAL PRIMARY KEY,
    "FREQ"            VARCHAR(2)    NOT NULL,
    "REF_AREA"        VARCHAR(10)   DEFAULT '{ref_area}',
    "INDICATOR"       VARCHAR(255)  NOT NULL,
    "INDICATOR_LABEL" TEXT,
    "TIME_PERIOD"     VARCHAR(10)   NOT NULL,
    "OBS_MSR"         VARCHAR(10)   NOT NULL,  -- INDEX o VAR_PCT
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
st.markdown("Convertí cualquier Excel de la DEIE a CSV en formato SDMX, listo para DBeaver.")

st.markdown("""<div class="step-box">
  <p class="step-title">Paso 1 — Subí el archivo Excel</p>
  <p class="step-desc">Cualquier .xlsx o .xls de la DEIE — mensual, anual, quinquenal, trimestral, etc.</p>
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
st.success(f"✅ {uploaded_file.name} — {len(hojas)} hoja(s) encontradas")

st.markdown("""<div class="step-box">
  <p class="step-title">Paso 2 — Elegí la hoja</p>
  <p class="step-desc">Elegí la hoja que tenga los datos en formato tabla.</p>
</div>""", unsafe_allow_html=True)

hoja_elegida = st.selectbox("Hoja", hojas)
df_raw = xl.parse(hoja_elegida, header=None)
rows = [[str(v).strip() if pd.notna(v) else '' for v in row] for _, row in df_raw.iterrows()]

with st.expander("👁️ Vista previa — primeras 40 filas", expanded=True):
    df_preview = df_raw.head(40).fillna('').astype(str)
    df_preview.index = range(1, len(df_preview)+1)
    st.dataframe(df_preview, use_container_width=True)

st.markdown("""<div class="step-box">
  <p class="step-title">Paso 3 — Configuración</p>
  <p class="step-desc">Indicá desde qué fila empezar. La app detecta todos los bloques automáticamente.</p>
</div>""", unsafe_allow_html=True)

col_a, col_b = st.columns(2)

with col_a:
    # Encontrar primer bloque automáticamente
    primer_bloque = None
    for i, row in enumerate(rows):
        if len(detectar_encabezado_en_fila(row)) >= 2:
            primer_bloque = i
            break
    auto_msg = f"(auto: fila {primer_bloque+1})" if primer_bloque is not None else "(no detectada)"

    fila_inicio_input = st.number_input(
        f"Fila desde donde empezar {auto_msg}",
        min_value=1, max_value=len(rows),
        value=(primer_bloque+1) if primer_bloque is not None else 1,
        step=1,
        help="La app procesará todos los bloques desde esta fila hacia abajo."
    )
    fila_inicio = int(fila_inicio_input) - 1

    # Contar bloques detectados
    n_bloques = sum(1 for i in range(fila_inicio, len(rows))
                    if len(detectar_encabezado_en_fila(rows[i])) >= 2)
    if n_bloques > 0:
        st.markdown(f'<span class="tag-ok">✓ {n_bloques} bloque(s) detectado(s) desde esa fila</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="tag-err">✗ No se detectaron bloques</span>', unsafe_allow_html=True)

with col_b:
    # Columna de rubros: usar primer bloque para mostrar opciones
    fila_ref = primer_bloque if primer_bloque is not None else 0
    opciones_col = {}
    for i in range(min(len(rows[fila_ref]), 20)):
        contenido = rows[fila_ref][i] or (rows[fila_ref+1][i] if fila_ref+1 < len(rows) else '')
        etiqueta = f"Col {i+1}"
        if contenido and contenido not in ('','nan'):
            etiqueta += f" — {contenido[:30]}"
        opciones_col[etiqueta] = i

    col_rubro_label = st.selectbox(
        "Columna con los rubros / indicadores",
        list(opciones_col.keys()),
        help="La columna con los nombres de cada indicador."
    )
    col_rubro = opciones_col[col_rubro_label]

col_c, col_d, col_e, col_f = st.columns(4)
with col_c:
    nombre_tabla = st.text_input("Nombre tabla PostgreSQL",
        value=normalizar(hoja_elegida).replace(' ','_')[:50])
with col_d:
    ref_area = st.text_input("REF_AREA", value="AR-MZA")
with col_e:
    unit_measure = st.text_input("UNIT_MEASURE", value="INDEX")
with col_f:
    base_year = st.text_input("BASE_YEAR", value="1988")

st.markdown("""<div class="step-box">
  <p class="step-title">Paso 4 — Convertir y descargar</p>
  <p class="step-desc">Revisá la vista previa antes de descargar.</p>
</div>""", unsafe_allow_html=True)

if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
    with st.spinner("Procesando todos los bloques..."):
        registros, error = parsear_datos(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year)

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
        anios = sorted(df_out['TIME_PERIOD'].str[:4].unique())
        freqs_out = df_out['FREQ'].unique()
        tiene_var = 'VAR_PCT' in df_out['OBS_MSR'].values

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Registros", f"{len(registros):,}")
        c2.metric("Rubros", df_out['INDICATOR'].nunique())
        c3.metric("Período", f"{anios[0]}–{anios[-1]}" if anios else "—")
        c4.metric("Frecuencia", ", ".join(FREQ_LABEL.get(f,f) for f in freqs_out))

        if tiene_var:
            st.info("ℹ️ Se detectaron columnas INDEX y VAR_PCT.")
        else:
            st.info("ℹ️ Solo se detectaron valores INDEX (sin columnas de variación %).")

        with st.expander("👁️ Vista previa SDMX (primeros 30 registros)"):
            st.dataframe(df_out.head(30), use_container_width=True)

        with st.expander("📋 Rubros detectados"):
            st.dataframe(
                df_out[['INDICATOR','INDICATOR_LABEL']].drop_duplicates().sort_values('INDICATOR'),
                use_container_width=True
            )

        nombre_csv = f"{nombre_tabla}_sdmx.csv"
        csv_bytes = df_out.to_csv(index=False).encode('utf-8')
        sql = generar_sql(nombre_tabla, nombre_csv, ref_area)

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
st.caption("Conversor SDMX v0.3.4 — DEIE Mendoza | Dirección de Estadísticas e Investigaciones Económicas")
