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
    .tag-warn{ background:#fff3cd; color:#856404; padding:2px 8px; border-radius:4px; font-size:0.8rem; }
</style>
""", unsafe_allow_html=True)

# ─── Constantes ───────────────────────────────────────────────────────────────
MESES_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,
    'noviembre':11,'diciembre':12
}

FREQ_LABEL = {'M':'Mensual','A':'Anual','Q':'Trimestral','S':'Semestral','P':'Plurianual'}

# Palabras que indican que una fila NO es un dato real
IGNORAR_PREFIJOS = [
    'fuente','nota','dato','promedio','rubros','grafico','gráfico',
    'cuadro','figura','ver ','véase','elaboracion','elaboración',
    'nan','%','total general'
]

# Palabras en el nombre del rubro que indican que NO es un dato numérico
IGNORAR_EN_RUBRO = ['grafico','gráfico','cuadro','figura','ver grafico','nota']

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
    if v is None or str(v).strip() in ('','nan','None','-','—','...','..','(*)','*'):
        return None
    s = str(v).strip()
    # Quitar paréntesis (valores negativos a veces vienen así)
    s = s.strip('()')
    if ',' in s and '.' in s:
        s = s.replace('.','').replace(',','.') if s.rfind(',') > s.rfind('.') else s.replace(',','')
    elif ',' in s:
        s = s.replace(',','.')
    s = re.sub(r'[^\d.\-]', '', s)
    try:
        return float(s)
    except ValueError:
        return None

def es_rubro_valido(texto):
    """Filtra filas que no son datos reales: gráficos, cuadros, notas, etc."""
    if not texto or str(texto).strip().lower() in ('','nan','none'):
        return False
    norm = normalizar(texto)
    # Ignorar si empieza con palabras clave de metadatos
    if any(norm.startswith(p) for p in IGNORAR_PREFIJOS):
        return False
    # Ignorar si contiene palabras de gráficos/cuadros en cualquier parte
    if any(p in norm for p in IGNORAR_EN_RUBRO):
        return False
    # Ignorar si es un año solo
    if re.fullmatch(r'(19|20)\d{2}', texto.strip()):
        return False
    # Ignorar si es un número solo (sin texto)
    try:
        float(texto.replace(',','.').replace('.','',1))
        return False
    except:
        pass
    return True

# ─── Detección de períodos ────────────────────────────────────────────────────

def detectar_periodo(v):
    """
    Detecta si una celda es un período temporal.
    Devuelve (periodo_raw, freq) o (None, None).
    """
    s = str(v).strip()
    if not s or normalizar(s) in ('nan','none',''):
        return None, None

    s_norm = normalizar(s).rstrip('*').rstrip('.').strip()

    # Mes
    if s_norm in MESES_ES:
        return ('MES', MESES_ES[s_norm]), 'M'

    # Año simple: "2024"
    if re.fullmatch(r'(19|20)\d{2}', s):
        return s, 'A'

    # Rango de años "2022-2025"
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
        num = m.group(1)
        return ('TRIM', int(num)), 'Q'

    # Semestre
    m = re.search(r'(\d)[°º]?\s*sem', s_norm)
    if m:
        return ('SEM', int(m.group(1))), 'S'

    return None, None

def detectar_encabezado_en_fila(row):
    """Retorna lista de (col_idx, periodo_raw, freq) si hay >= 2 períodos."""
    res = []
    for idx, v in enumerate(row):
        p, f = detectar_periodo(v)
        if p is not None:
            res.append((idx, p, f))
    return res if len(res) >= 2 else []

def detectar_encabezado_automatico(rows):
    for i, row in enumerate(rows):
        if len(detectar_encabezado_en_fila(row)) >= 2:
            return i
    return None

def resolver_time_period(periodo_raw, freq, anio_ctx):
    if isinstance(periodo_raw, tuple):
        tipo, num = periodo_raw
        if tipo == 'MES':
            return (f"{anio_ctx}-{num:02d}", 'M') if anio_ctx else (None, freq)
        if tipo == 'TRIM':
            return (f"{anio_ctx}-Q{num}", 'Q') if anio_ctx else (None, freq)
        if tipo == 'SEM':
            return (f"{anio_ctx}-S{num}", 'S') if anio_ctx else (None, freq)
    return str(periodo_raw), freq

# ─── Clasificación INDEX vs VAR_PCT ───────────────────────────────────────────

def clasificar_columnas(rows, fila_encabezado, enc_raw):
    """
    Determina si cada columna es INDEX o VAR_PCT.
    Estrategia (en orden de prioridad):
    1. Busca '%' o 'var' en la celda de encabezado o en las 2 filas superiores
    2. Si el encabezado tiene pares (Índice, %) alternados → par=INDEX, impar=VAR_PCT
    3. Si todas son años/meses sin info adicional → todas INDEX (datos anuales sin variación)
    """
    fila_enc = rows[fila_encabezado]
    filas_sup = [rows[fila_encabezado - k] for k in range(1, 3) if fila_encabezado - k >= 0]

    col_tipo = {}
    encontro_pct_explicito = False

    for col_idx, periodo_raw, freq in enc_raw:
        celda_enc = normalizar(str(fila_enc[col_idx]) if col_idx < len(fila_enc) else '')
        celdas_sup = [normalizar(str(f[col_idx]) if col_idx < len(f) else '') for f in filas_sup]
        todas = [celda_enc] + celdas_sup

        es_pct = any('%' in c or 'var' in c or 'variacion' in c or 'variación' in c for c in todas)
        if es_pct:
            col_tipo[col_idx] = 'VAR_PCT'
            encontro_pct_explicito = True
        else:
            col_tipo[col_idx] = 'INDEX'

    # Si no encontró ningún % explícito, intentar patrón alternado
    # Solo si hay pares de columnas (típico de tablas DEIE con Índice + %)
    if not encontro_pct_explicito and len(enc_raw) >= 2:
        # Verificar si hay columnas pareadas mirando la fila anterior
        # En tablas DEIE el encabezado suele tener: [año] [año] [año]
        # y la fila anterior: [Índice] [%] [Índice] [%]
        fila_pre = rows[fila_encabezado - 1] if fila_encabezado > 0 else []
        tiene_pct_arriba = any('%' in normalizar(str(v)) for v in fila_pre)
        if tiene_pct_arriba:
            # Asignar alternado según la fila anterior
            for i, (col_idx, _, _) in enumerate(enc_raw):
                cel = normalizar(str(fila_pre[col_idx]) if col_idx < len(fila_pre) else '')
                col_tipo[col_idx] = 'VAR_PCT' if '%' in cel or 'var' in cel else 'INDEX'
        # else: todas quedan como INDEX (es tabla sin variación, ej. transporte anual)

    return col_tipo

# ─── Parser principal ─────────────────────────────────────────────────────────

def parsear_datos(rows, fila_encabezado, col_rubro, ref_area, unit_measure, base_year):
    registros = []
    anio_ctx = None

    enc_raw = detectar_encabezado_en_fila(rows[fila_encabezado])
    if not enc_raw:
        return [], "No se detectaron períodos temporales en la fila de encabezado."

    col_tipo = clasificar_columnas(rows, fila_encabezado, enc_raw)

    # Determinar FREQ dominante
    freqs = [f for _, _, f in enc_raw]
    freq_dom = max(set(freqs), key=freqs.count)

    cols_info = [(col_idx, periodo_raw, freq, col_tipo[col_idx]) for col_idx, periodo_raw, freq in enc_raw]

    # Detectar año de contexto inicial (para tablas de meses)
    # Buscar en las filas anteriores al encabezado
    for row in rows[:fila_encabezado]:
        for v in row:
            m = re.search(r'\b(19|20)\d{2}\b', str(v))
            if m:
                anio_ctx = int(m.group(0))

    for row in rows[fila_encabezado + 1:]:
        col0 = str(row[col_rubro]).strip() if col_rubro < len(row) else ''

        # Actualizar año de contexto si aparece en la fila
        for v in row:
            m = re.search(r'\b(19|20)\d{2}\b', str(v))
            if m:
                nuevo_anio = int(m.group(0))
                # Solo actualizar si es razonable (no viene de un valor de datos)
                if nuevo_anio >= 1980 and nuevo_anio <= 2030:
                    anio_ctx = nuevo_anio
                break

        # Filtrar rubros inválidos
        if not es_rubro_valido(col0):
            continue

        rubro_code  = a_code(col0)
        rubro_label = col0

        for col_idx, periodo_raw, freq, obs_msr in cols_info:
            v_raw = row[col_idx] if col_idx < len(row) else ''
            valor = limpiar_numero(v_raw)

            # No emitir registros con valor None Y que sean VAR_PCT
            # (evita ruido en tablas que no tienen variación)
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

    registros.sort(key=lambda x: (x['TIME_PERIOD'], x['INDICATOR'], x['OBS_MSR']))
    return registros, None

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
    xl = pd.ExcelFile(uploaded_file, engine='openpyxl' if uploaded_file.name.endswith('xlsx') else 'xlrd')
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
  <p class="step-desc">Elegí la hoja que tenga los datos en formato tabla (no gráficos ni contenido).</p>
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
  <p class="step-desc">La app detecta automáticamente meses, años, trimestres y quinquenios.</p>
</div>""", unsafe_allow_html=True)

auto_enc = detectar_encabezado_automatico(rows)
auto_msg = f"(auto: fila {auto_enc+1})" if auto_enc is not None else "(no detectada)"

col_a, col_b = st.columns(2)

with col_a:
    fila_enc_input = st.number_input(
        f"Fila de encabezado {auto_msg}",
        min_value=1, max_value=len(rows),
        value=(auto_enc+1) if auto_enc is not None else 1,
        step=1,
        help="Fila donde están los períodos (meses, años, trimestres, etc.)"
    )
    fila_encabezado = int(fila_enc_input) - 1

    enc_det = detectar_encabezado_en_fila(rows[fila_encabezado])
    if enc_det:
        freqs_det = list(set(f for _,_,f in enc_det))
        desc = f"{len(enc_det)} columnas — {', '.join(FREQ_LABEL.get(f,f) for f in freqs_det)}"
        st.markdown(f'<span class="tag-ok">✓ {desc}</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="tag-err">✗ No se detectaron períodos en esa fila</span>', unsafe_allow_html=True)

with col_b:
    opciones_col = {}
    for i in range(min(len(rows[fila_encabezado]), 20)):
        contenido = rows[fila_encabezado][i] or (rows[fila_encabezado+1][i] if fila_encabezado+1 < len(rows) else '')
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
    with st.spinner("Procesando..."):
        registros, error = parsear_datos(rows, fila_encabezado, col_rubro, ref_area, unit_measure, base_year)

    if error:
        st.error(f"❌ {error}")
    elif not registros:
        st.error("❌ No se encontraron datos. Revisá la fila de encabezado y la columna de rubros.")
        with st.expander("🔍 Diagnóstico"):
            st.write("Fila encabezado:", rows[fila_encabezado])
            st.write("Períodos detectados:", detectar_encabezado_en_fila(rows[fila_encabezado]))
    else:
        df_out = pd.DataFrame(registros)
        anios = sorted(df_out['TIME_PERIOD'].str[:4].unique())
        nulos = df_out['OBS_VALUE'].isna().sum()
        freqs_out = df_out['FREQ'].unique()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Registros", f"{len(registros):,}")
        c2.metric("Rubros", df_out['INDICATOR'].nunique())
        c3.metric("Período", f"{anios[0]}–{anios[-1]}" if anios else "—")
        c4.metric("Frecuencia", ", ".join(FREQ_LABEL.get(f,f) for f in freqs_out))

        if nulos > 0:
            st.warning(f"⚠️ {nulos} registros sin valor (quedarán como NULL).")

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
st.caption("Conversor SDMX v0.3.1 — DEIE Mendoza | Dirección de Estadísticas e Investigaciones Económicas")
