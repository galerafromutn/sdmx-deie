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

def resolver_dimension_temporal(v, anio_ctx):
    s_norm = normalizar(v)
    
    # 1. Prioridad: Meses (Esto evita que "Ene" se confunda con otra cosa)
    if s_norm in MESES_ES:
        num_mes = MESES_ES[s_norm]
        return f"{anio_ctx}-{num_mes:02d}" if anio_ctx else None, 'M'
    
    # 2. Trimestres
    m_tri = re.search(r'(\d)[°º]?\s*(trim|t)', s_norm)
    if m_tri:
        num_tri = m_tri.group(1)
        return f"{anio_ctx}-Q{num_tri}" if anio_ctx else None, 'Q'
    
    # 3. Años puros (4 dígitos)
    m_anio = re.fullmatch(r'(19|20)\d{2}', str(v).strip())
    if m_anio:
        return m_anio.group(0), 'A'
    
    # 4. Detección de Variación
    # Si la celda contiene "var" o "%", es una columna de variación,
    # pero NO es el TIME_PERIOD.
    if 'var' in s_norm or '%' in s_norm:
        return 'ES_VAR', 'VAR'
        
    return None, None

def parsear_datos_evolucionado(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year):
    registros = []
    puntos_de_control = []
    
    for i in range(fila_inicio, len(rows)):
        enc_detectado = detectar_encabezado_en_fila(rows[i])
        if enc_detectado:
            puntos_de_control.append((i, enc_detectado))

    if not puntos_de_control:
        return [], "No se detectaron estructuras de datos válidas."

    for idx, (fila_enc, enc_raw) in enumerate(puntos_de_control):
        fila_fin = puntos_de_control[idx + 1][0] if idx + 1 < len(puntos_de_control) else len(rows)
        
        # --- Búsqueda de Año de Contexto ---
        anio_bloque = None
        for r_adj in rows[max(0, fila_enc-10):fila_enc+1]:
            for celda in r_adj:
                m = re.search(r'\b(19|20)\d{2}\b', str(celda))
                if m:
                    anio_bloque = m.group(0)
                    break
        
        mapa_columnas = []
        # Para emparejar VAR con su INDEX correspondiente
        ultimo_periodo_visto = None 
        ultima_freq_vista = 'M'

        for col_idx, val_raw, _ in enc_raw:
            periodo, freq = resolver_dimension_temporal(val_raw, anio_bloque)
            
            if freq == 'VAR':
                # Si es una columna de variación, hereda el tiempo de la columna anterior
                periodo_final = ultimo_periodo_visto
                freq_final = ultima_freq_vista
                tipo_final = 'VAR_PCT'
            else:
                periodo_final = periodo
                freq_final = freq
                tipo_final = 'INDEX'
                # Actualizamos para que la siguiente VAR sepa a qué periodo pertenece
                ultimo_periodo_visto = periodo
                ultima_freq_vista = freq

            if periodo_final:
                mapa_columnas.append({
                    'idx': col_idx,
                    'periodo': periodo_final,
                    'freq': freq_final,
                    'tipo': tipo_final
                })

        for r_idx in range(fila_enc + 1, fila_fin):
            fila_actual = rows[r_idx]
            nombre_rubro = str(fila_actual[col_rubro]).strip() if col_rubro < len(fila_actual) else ""
            if not es_rubro_valido(nombre_rubro): continue
            
            # Actualización dinámica de año si aparece en la fila
            for celda in fila_actual:
                m = re.search(r'^(19|20)\d{2}$', str(celda).strip())
                if m: anio_bloque = m.group(0)

            for col in mapa_columnas:
                valor_num = limpiar_numero(fila_actual[col['idx']] if col['idx'] < len(fila_actual) else None)
                
                # Solo agregamos si hay un valor numérico para evitar filas vacías
                if valor_num is not None:
                    registros.append({
                        'FREQ': col['freq'],
                        'REF_AREA': ref_area,
                        'INDICATOR': a_code(nombre_rubro),
                        'INDICATOR_LABEL': nombre_rubro,
                        'TIME_PERIOD': col['periodo'],
                        'OBS_MSR': col['tipo'],
                        'OBS_VALUE': valor_num,
                        'OBS_STATUS': 'A',
                        'UNIT_MEASURE': unit_measure if col['tipo'] == 'INDEX' else 'PCT',
                        'BASE_YEAR': base_year
                    })

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
        registros, error = parsear_datos_evolucionado(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year)

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
st.caption("Conversor SDMX v0.3.5 — DEIE Mendoza | Dirección de Estadísticas e Investigaciones Económicas")
