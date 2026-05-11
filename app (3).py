import streamlit as st
import pandas as pd
import re
import io

st.set_page_config(
    page_title="Conversor SDMX — DEIE Mendoza",
    page_icon="📊",
    layout="wide"
)

# ─── Estilos ─────────────────────────────────────────────────────────────────
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
    .tag-ok   { background:#d4edda; color:#155724; padding:2px 8px; border-radius:4px; font-size:0.8rem; }
    .tag-warn { background:#fff3cd; color:#856404; padding:2px 8px; border-radius:4px; font-size:0.8rem; }
    .tag-err  { background:#f8d7da; color:#721c24; padding:2px 8px; border-radius:4px; font-size:0.8rem; }
</style>
""", unsafe_allow_html=True)

# ─── Constantes ───────────────────────────────────────────────────────────────
MESES_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,
    'noviembre':11,'diciembre':12
}

# ─── Utilidades ───────────────────────────────────────────────────────────────

def normalizar(texto):
    texto = str(texto).strip().lower()
    for a, b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        texto = texto.replace(a, b)
    return texto

def a_code(texto):
    texto = re.sub(r'\s+', ' ', str(texto).strip())
    for a, b in [('Á','A'),('É','E'),('Í','I'),('Ó','O'),('Ú','U'),('Ñ','N'),
                 ('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        texto = texto.replace(a, b)
    return re.sub(r'[^A-Z0-9_]', '_', texto.upper().replace(' ', '_'))

def limpiar_numero(v):
    """Convierte string a float tolerando formatos argentinos (punto miles, coma decimal)."""
    if v is None or str(v).strip() in ('', 'nan', 'None', '-', '—'):
        return None
    s = str(v).strip()
    # Detectar formato: si hay coma y punto, el que va último es el decimal
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    s = re.sub(r'[^\d.\-]', '', s)
    try:
        return float(s)
    except ValueError:
        return None

def detectar_anio_en_fila(row):
    """Busca un año (1900-2100) en cualquier celda de la fila."""
    for v in row:
        s = str(v)
        m = re.search(r'\b(19|20)\d{2}\b', s)
        if m:
            return int(m.group(0))
    return None

def detectar_meses_en_fila(row):
    """Retorna dict {col_idx: numero_mes} para columnas que contienen nombres de mes."""
    resultado = {}
    for idx, v in enumerate(row):
        norm = normalizar(str(v)).rstrip('*').rstrip('.').strip()
        if norm in MESES_ES:
            resultado[idx] = MESES_ES[norm]
    return resultado

def detectar_encabezado_automatico(rows):
    """
    Heurística: busca la primera fila que tenga >= 3 meses.
    Devuelve el índice de esa fila o None.
    """
    for i, row in enumerate(rows):
        meses = detectar_meses_en_fila(row)
        if len(meses) >= 3:
            return i
    return None

def parsear_datos(rows, fila_encabezado, col_rubro, ref_area, unit_measure, base_year):
    """
    Parsea las filas de datos a partir de fila_encabezado.
    col_rubro: índice de la columna que tiene el nombre del indicador.
    Devuelve lista de registros SDMX.
    """
    registros = []
    anio_actual = None
    meses_cols = {}   # {col_idx: numero_mes}

    # Obtener meses del encabezado
    meses_cols = detectar_meses_en_fila(rows[fila_encabezado])

    if not meses_cols:
        return [], "No se detectaron meses en la fila de encabezado seleccionada."

    # Iterar desde la fila siguiente al encabezado
    for row in rows[fila_encabezado + 1:]:
        # ¿Hay un año en esta fila?
        anio_det = detectar_anio_en_fila(row)
        if anio_det:
            anio_actual = anio_det
            # Refrescar meses si esta fila también tiene meses (puede ser nuevo bloque)
            meses_nuevos = detectar_meses_en_fila(row)
            if len(meses_nuevos) >= 3:
                meses_cols = meses_nuevos
            continue

        if not anio_actual:
            continue

        # Obtener nombre de rubro
        rubro_raw = str(row[col_rubro]).strip() if col_rubro < len(row) else ''
        if not rubro_raw or rubro_raw.lower() in ('', 'nan', 'none'):
            continue

        # Ignorar filas que son encabezados o notas
        norm_rubro = normalizar(rubro_raw)
        if any(norm_rubro.startswith(p) for p in ['fuente', 'nota', 'dato', 'promedio', 'rubros', 'nan', '%']):
            continue

        rubro_code = a_code(rubro_raw)

        for col_idx, mes in meses_cols.items():
            v_raw = row[col_idx] if col_idx < len(row) else ''
            valor = limpiar_numero(v_raw)

            registros.append({
                'FREQ': 'M',
                'REF_AREA': ref_area,
                'INDICATOR': rubro_code,
                'INDICATOR_LABEL': rubro_raw,
                'TIME_PERIOD': f"{anio_actual}-{mes:02d}",
                'OBS_VALUE': valor,
                'OBS_STATUS': 'A' if valor is not None else 'M',
                'UNIT_MEASURE': unit_measure,
                'BASE_YEAR': base_year,
            })

    registros.sort(key=lambda x: (x['TIME_PERIOD'], x['INDICATOR']))
    return registros, None

def generar_sql(nombre_tabla, nombre_csv, ref_area):
    return f"""-- Crear tabla
CREATE TABLE IF NOT EXISTS public.{nombre_tabla} (
    id_registro   SERIAL PRIMARY KEY,
    "FREQ"        CHAR(1)       DEFAULT 'M',
    "REF_AREA"    VARCHAR(10)   DEFAULT '{ref_area}',
    "INDICATOR"   VARCHAR(100)  NOT NULL,
    "INDICATOR_LABEL" TEXT,
    "TIME_PERIOD" CHAR(7)       NOT NULL,
    "OBS_VALUE"   NUMERIC(18,6),
    "OBS_STATUS"  CHAR(1)       DEFAULT 'A',
    "UNIT_MEASURE" VARCHAR(20),
    "BASE_YEAR"   CHAR(4)
);

-- Importar datos (ajustá la ruta del archivo)
COPY public.{nombre_tabla} (
    "FREQ","REF_AREA","INDICATOR","INDICATOR_LABEL",
    "TIME_PERIOD","OBS_VALUE","OBS_STATUS","UNIT_MEASURE","BASE_YEAR"
)
FROM '/ruta/a/tu/carpeta/{nombre_csv}'
DELIMITER ','
CSV HEADER
NULL '';
"""

# ─── UI Principal ─────────────────────────────────────────────────────────────

st.title("📊 Conversor SDMX — DEIE Mendoza")
st.markdown("Convertí cualquier Excel de la DEIE a CSV listo para DBeaver, sin importar el formato.")

# ══ PASO 1: Subir archivo ══════════════════════════════════════════════════════
st.markdown("""
<div class="step-box">
  <p class="step-title">Paso 1 — Subí el archivo Excel</p>
  <p class="step-desc">Cualquier versión .xlsx o .xls de la DEIE.</p>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Archivo Excel", type=["xlsx", "xls"], label_visibility="collapsed")

if not uploaded_file:
    st.stop()

try:
    xl = pd.ExcelFile(uploaded_file)
except Exception as e:
    st.error(f"No se pudo leer el archivo: {e}")
    st.stop()

hojas = xl.sheet_names
st.success(f"✅ {uploaded_file.name} — {len(hojas)} hoja(s) encontradas")

# ══ PASO 2: Elegir hoja ════════════════════════════════════════════════════════
st.markdown("""
<div class="step-box">
  <p class="step-title">Paso 2 — Elegí la hoja</p>
  <p class="step-desc">La app muestra las primeras filas para que puedas orientarte.</p>
</div>
""", unsafe_allow_html=True)

hoja_elegida = st.selectbox("Hoja", hojas)

df_raw = xl.parse(hoja_elegida, header=None)
rows = [[str(v).strip() if pd.notna(v) else '' for v in row] for _, row in df_raw.iterrows()]

with st.expander("👁️ Vista previa — primeras 40 filas", expanded=True):
    df_preview = df_raw.head(40).fillna('').astype(str)
    df_preview.index = range(1, len(df_preview) + 1)  # Mostrar desde fila 1
    st.dataframe(df_preview, use_container_width=True)

# ══ PASO 3: Configuración ═════════════════════════════════════════════════════
st.markdown("""
<div class="step-box">
  <p class="step-title">Paso 3 — Configuración</p>
  <p class="step-desc">Indicá dónde están los encabezados y qué columna tiene los nombres de los rubros.</p>
</div>
""", unsafe_allow_html=True)

auto_enc = detectar_encabezado_automatico(rows)
auto_msg = f"(detectada automáticamente: fila {auto_enc + 1})" if auto_enc is not None else "(no detectada, indicá manualmente)"

col_a, col_b = st.columns(2)

with col_a:
    fila_enc_input = st.number_input(
        f"Fila de encabezado de meses {auto_msg}",
        min_value=1,
        max_value=len(rows),
        value=(auto_enc + 1) if auto_enc is not None else 1,
        step=1,
        help="El número de fila (contando desde 1) donde están los nombres de los meses."
    )
    fila_encabezado = int(fila_enc_input) - 1  # Convertir a índice 0-based

    # Mostrar qué meses se detectaron en esa fila
    meses_det = detectar_meses_en_fila(rows[fila_encabezado])
    if meses_det:
        meses_nombres = sorted(meses_det.items(), key=lambda x: x[1])
        st.markdown(f'<span class="tag-ok">✓ Meses detectados: {", ".join(str(m) for _,m in meses_nombres)}</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="tag-err">✗ No se detectaron meses en esa fila</span>', unsafe_allow_html=True)

with col_b:
    # Mostrar opciones de columna: número + contenido de la primera celda con texto
    opciones_col = {}
    for i in range(min(len(rows[fila_encabezado]), 20)):
        contenido = rows[fila_encabezado][i] or (rows[fila_encabezado + 1][i] if fila_encabezado + 1 < len(rows) else '')
        etiqueta = f"Col {i+1}"
        if contenido and contenido not in ('', 'nan'):
            etiqueta += f" — {contenido[:30]}"
        opciones_col[etiqueta] = i

    col_rubro_label = st.selectbox(
        "Columna con los rubros / indicadores",
        list(opciones_col.keys()),
        help="La columna que contiene los nombres de cada rubro o indicador (ej: 'Alimentos', 'Indumentaria', etc.)"
    )
    col_rubro = opciones_col[col_rubro_label]

col_c, col_d, col_e, col_f = st.columns(4)

with col_c:
    nombre_tabla = st.text_input(
        "Nombre tabla PostgreSQL",
        value=normalizar(hoja_elegida).replace(' ', '_')[:50]
    )
with col_d:
    ref_area = st.text_input("REF_AREA", value="AR-MZA")
with col_e:
    unit_measure = st.text_input("UNIT_MEASURE", value="INDEX")
with col_f:
    base_year = st.text_input("BASE_YEAR", value="1988")

# ══ PASO 4: Convertir ═════════════════════════════════════════════════════════
st.markdown("""
<div class="step-box">
  <p class="step-title">Paso 4 — Convertir y descargar</p>
  <p class="step-desc">Revisá la vista previa antes de descargar.</p>
</div>
""", unsafe_allow_html=True)

if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
    with st.spinner("Procesando..."):
        registros, error = parsear_datos(
            rows, fila_encabezado, col_rubro, ref_area, unit_measure, base_year
        )

    if error:
        st.error(f"❌ {error}")
    elif not registros:
        st.error("❌ No se encontraron datos. Revisá que la fila de encabezado y la columna de rubros sean correctas.")
        with st.expander("🔍 Diagnóstico"):
            st.write(f"Fila encabezado (idx {fila_encabezado}):", rows[fila_encabezado])
            st.write(f"Meses detectados:", detectar_meses_en_fila(rows[fila_encabezado]))
            st.write(f"Fila siguiente:", rows[fila_encabezado + 1] if fila_encabezado + 1 < len(rows) else "N/A")
    else:
        df_out = pd.DataFrame(registros)

        anios = sorted(df_out['TIME_PERIOD'].str[:4].unique())
        rubros_unicos = df_out['INDICATOR'].nunique()
        nulos = df_out['OBS_VALUE'].isna().sum()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Registros", f"{len(registros):,}")
        col2.metric("Rubros", rubros_unicos)
        col3.metric("Período", f"{anios[0]}–{anios[-1]}" if anios else "—")
        col4.metric("Valores nulos", nulos)

        if nulos > 0:
            st.warning(f"⚠️ {nulos} registros sin valor numérico (quedarán como NULL en la base).")

        with st.expander("👁️ Vista previa del CSV (primeros 30 registros)"):
            st.dataframe(df_out.head(30), use_container_width=True)

        with st.expander("📋 Rubros detectados"):
            rubros_lista = df_out[['INDICATOR','INDICATOR_LABEL']].drop_duplicates().sort_values('INDICATOR')
            st.dataframe(rubros_lista, use_container_width=True)

        # ── Descargas ────────────────────────────────────────────────────────
        nombre_csv = f"{nombre_tabla}_sdmx.csv"

        # CSV sin INDICATOR_LABEL en la salida final (opcional: se puede dejar)
        csv_bytes = df_out.to_csv(index=False).encode('utf-8')

        sql = generar_sql(nombre_tabla, nombre_csv, ref_area)

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                label="⬇️ Descargar CSV",
                data=csv_bytes,
                file_name=nombre_csv,
                mime="text/csv",
                use_container_width=True
            )
        with dl2:
            st.download_button(
                label="⬇️ Descargar SQL",
                data=sql.encode('utf-8'),
                file_name=f"{nombre_tabla}.sql",
                mime="text/plain",
                use_container_width=True
            )

        with st.expander("📄 SQL para DBeaver"):
            st.code(sql, language='sql')

st.markdown("---")
st.caption("Conversor SDMX — DEIE Mendoza | Dirección de Estadísticas e Investigaciones Económicas")
