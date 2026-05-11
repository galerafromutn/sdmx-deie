import streamlit as st
import pandas as pd
import re
import io

st.set_page_config(page_title="Conversor SDMX - DEIE Mendoza", page_icon="📊", layout="centered")

st.title("📊 Conversor SDMX — DEIE Mendoza")
st.markdown("Subí un archivo Excel de la DEIE, elegí la hoja correcta y descargá el CSV listo para importar en DBeaver.")

MESES_MAP = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12
}

IGNORAR_PREFIJOS = ['fuente', 'dato', 'nota', 'promedio', 'rubros', '%', 'nan', '']

def normalizar(texto):
    """Normaliza texto: minúsculas, sin tildes, sin espacios extra."""
    texto = texto.strip().lower()
    for a, b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        texto = texto.replace(a, b)
    return texto

def a_code(texto):
    """Convierte texto a código INDICATOR (mayúsculas, sin tildes, guiones bajos)."""
    texto = re.sub(r'\s+', ' ', texto.strip())
    for a, b in [('Á','A'),('É','E'),('Í','I'),('Ó','O'),('Ú','U'),('Ñ','N'),
                 ('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        texto = texto.replace(a, b)
    return texto.upper().replace(' ', '_')

def detectar_anio(row):
    """
    Intenta extraer un año (4 dígitos entre 1900-2100) de cualquier celda de la fila.
    Acepta: 'Año 2024', 'AÑO: 2024', 'año2024', o simplemente '2024' en celda sola.
    """
    for v in row:
        if not v:
            continue
        # Buscar patrón explícito "año XXXX"
        match = re.search(r'a[ñn]o\s*:?\s*(\d{4})', v, re.IGNORECASE)
        if match:
            anio = int(match.group(1))
            if 1900 <= anio <= 2100:
                return anio
        # Celda que solo contiene un año numérico
        match2 = re.fullmatch(r'\s*(\d{4})\s*', v)
        if match2:
            anio = int(match2.group(1))
            if 1900 <= anio <= 2100:
                return anio
    return None

def detectar_meses(row):
    """
    Devuelve lista de (columna_idx, numero_mes) para cada mes encontrado en la fila.
    Tolera asteriscos, puntos y espacios extra.
    """
    resultado = []
    for idx, v in enumerate(row):
        if not v:
            continue
        v_clean = normalizar(v).rstrip('*').rstrip('.').strip()
        if v_clean in MESES_MAP:
            resultado.append((idx, MESES_MAP[v_clean]))
    return resultado

def es_fila_ignorable(col0):
    """True si la fila debe saltarse (encabezados, fuentes, etc.)."""
    c = normalizar(col0)
    return any(c.startswith(p) for p in IGNORAR_PREFIJOS)

def procesar_hoja(df_raw):
    """Procesa una hoja con formato DEIE y devuelve lista de registros SDMX."""

    # Convertir todo a string para procesar (NaN → '')
    rows = []
    for _, row in df_raw.iterrows():
        rows.append([str(v).strip() if pd.notna(v) else '' for v in row])

    registros = []
    anio_actual = None
    # meses_cols: lista de (col_idx, numero_mes) para el bloque actual
    meses_cols = []
    modo = None  # 'valor' | 'variacion'
    rubros_detectados = set()

    for i, row in enumerate(rows):
        col0 = row[0] if row else ''

        # ── 1. Detectar año ──────────────────────────────────────────────────
        anio_det = detectar_anio(row)
        if anio_det:
            anio_actual = anio_det
            meses_cols = []
            modo = None
            continue

        # ── 2. Detectar fila de meses ────────────────────────────────────────
        meses_det = detectar_meses(row)
        if len(meses_det) >= 2:  # al menos 2 meses para considerar fila de encabezado
            meses_cols = meses_det

            # Determinar modo mirando filas siguientes (más tolerante)
            modo_sig = 'valor'  # default: asumir valores directos
            for j in range(i + 1, min(i + 8, len(rows))):
                r2 = rows[j]
                c0 = r2[0].strip()
                # Si encontramos "Var" en cualquier celda → modo variación
                if any(re.search(r'\bvar\b', str(x), re.IGNORECASE) for x in r2):
                    modo_sig = 'variacion'
                    break
                # Si primera col tiene texto útil → modo valor
                if c0 and not es_fila_ignorable(c0):
                    modo_sig = 'valor'
                    break

            modo = modo_sig
            continue

        # ── 3. Detectar cambio a modo variación por fila "Var..." ────────────
        if any(re.search(r'\bvar\b', str(v), re.IGNORECASE) for v in row[:3]):
            modo = 'variacion'
            continue

        # ── 4. Ignorar filas no útiles ───────────────────────────────────────
        if es_fila_ignorable(col0):
            continue

        # ── 5. Procesar fila de datos ────────────────────────────────────────
        if not (anio_actual and meses_cols and col0):
            continue

        rubro_nombre = re.sub(r'\s+', ' ', col0).strip()
        rubro_code = a_code(rubro_nombre)

        if modo == 'valor':
            rubros_detectados.add(rubro_nombre)
            for col_idx, mes in meses_cols:
                # Buscar valor en la columna exacta (col_idx)
                v_raw = row[col_idx] if col_idx < len(row) else ''
                if not v_raw:
                    # Fallback: buscar en columnas adyacentes ±1
                    for offset in [1, -1, 2, -2]:
                        alt = col_idx + offset
                        if 0 <= alt < len(row) and row[alt]:
                            v_raw = row[alt]
                            break
                v_str = v_raw.replace('.', '').replace(',', '.').strip()
                try:
                    valor = float(v_str)
                except (ValueError, AttributeError):
                    valor = None
                registros.append({
                    'FREQ': 'M',
                    'REF_AREA': 'AR-MZA',
                    'INDICATOR': rubro_code,
                    'TIME_PERIOD': f"{anio_actual}-{mes:02d}",
                    'OBS_VALUE': valor,
                    'OBS_STATUS': 'A',
                    'UNIT_MEASURE': 'INDEX',
                    'BASE_YEAR': '1988',
                    'VARIACION_PCT': None
                })

        elif modo == 'variacion':
            for col_idx, mes in meses_cols:
                v_raw = row[col_idx] if col_idx < len(row) else ''
                v_str = v_raw.replace(',', '.').strip()
                try:
                    var = float(v_str)
                except (ValueError, AttributeError):
                    var = None
                # Asociar variación al registro ya creado
                periodo = f"{anio_actual}-{mes:02d}"
                for rec in reversed(registros):
                    if rec['TIME_PERIOD'] == periodo and rec['INDICATOR'] == rubro_code:
                        rec['VARIACION_PCT'] = var
                        break

    registros.sort(key=lambda x: (x['TIME_PERIOD'], x['INDICATOR']))
    return registros, rubros_detectados


# ─── UI ───────────────────────────────────────────────────────────────────────

uploaded_file = st.file_uploader("📁 Subí el archivo Excel (.xlsx)", type=["xlsx", "xls"])

if uploaded_file:
    try:
        xl = pd.ExcelFile(uploaded_file)
        hojas = xl.sheet_names
        st.success(f"✅ Archivo cargado: **{uploaded_file.name}** — {len(hojas)} hojas encontradas")

        hoja_elegida = st.selectbox("📋 Elegí la hoja a procesar", hojas)

        nombre_tabla = st.text_input(
            "🏷️ Nombre de la tabla en PostgreSQL",
            value=normalizar(hoja_elegida).replace(' ', '_')
        )

        ref_area = st.text_input("📍 Código de área (REF_AREA)", value="AR-MZA")

        if st.button("⚙️ Convertir a SDMX", type="primary"):
            with st.spinner("Procesando..."):
                df_raw = xl.parse(hoja_elegida, header=None)
                registros, rubros = procesar_hoja(df_raw)

            if not registros:
                st.error("❌ No se encontraron datos. Verificá que la hoja tenga el formato DEIE estándar.")

                # ── Modo diagnóstico: mostrar primeras filas para ayudar a depurar ──
                with st.expander("🔍 Diagnóstico — primeras 30 filas de la hoja"):
                    df_diag = xl.parse(hoja_elegida, header=None).fillna('').astype(str)
                    st.dataframe(df_diag.head(30), use_container_width=True)
            else:
                # Aplicar REF_AREA personalizado
                for r in registros:
                    r['REF_AREA'] = ref_area

                df_out = pd.DataFrame(registros)
                anios = sorted(df_out['TIME_PERIOD'].str[:4].unique())

                st.success(f"✅ Conversión exitosa: **{len(registros)} registros**")

                col1, col2, col3 = st.columns(3)
                col1.metric("Registros", len(registros))
                col2.metric("Años", f"{anios[0]} – {anios[-1]}")
                col3.metric("Rubros", len(rubros))

                with st.expander("👁️ Vista previa (primeros 20 registros)"):
                    st.dataframe(df_out.head(20), use_container_width=True)

                with st.expander("📋 Rubros detectados"):
                    for r in sorted(rubros):
                        st.write(f"• {r}")

                # CSV para descargar
                csv_bytes = df_out.to_csv(index=False).encode('utf-8')
                nombre_csv = f"{nombre_tabla}_sdmx.csv"
                st.download_button(
                    label="⬇️ Descargar CSV SDMX",
                    data=csv_bytes,
                    file_name=nombre_csv,
                    mime="text/csv"
                )

                # SQL listo para DBeaver
                sql = f"""-- Crear tabla
CREATE TABLE public.{nombre_tabla} (
    id_registro SERIAL PRIMARY KEY,
    "FREQ" CHAR(1) DEFAULT 'M',
    "REF_AREA" VARCHAR(10) DEFAULT '{ref_area}',
    "INDICATOR" VARCHAR(50) NOT NULL,
    "TIME_PERIOD" CHAR(7) NOT NULL,
    "OBS_VALUE" NUMERIC(15,6),
    "OBS_STATUS" CHAR(1) DEFAULT 'A',
    "UNIT_MEASURE" VARCHAR(10) DEFAULT 'INDEX',
    "BASE_YEAR" CHAR(4) DEFAULT '1988',
    "VARIACION_PCT" NUMERIC(8,2)
);

-- Importar datos (ajustá la ruta)
COPY public.{nombre_tabla} ("FREQ","REF_AREA","INDICATOR","TIME_PERIOD","OBS_VALUE","OBS_STATUS","UNIT_MEASURE","BASE_YEAR","VARIACION_PCT")
FROM 'C:/ruta/a/tu/carpeta/{nombre_csv}'
DELIMITER ','
CSV HEADER
NULL '';
"""
                with st.expander("📄 SQL listo para DBeaver"):
                    st.code(sql, language='sql')

                st.download_button(
                    label="⬇️ Descargar SQL",
                    data=sql.encode('utf-8'),
                    file_name=f"{nombre_tabla}.sql",
                    mime="text/plain"
                )

    except Exception as e:
        st.error(f"❌ Error al procesar el archivo: {e}")
        st.exception(e)  # Muestra el traceback completo para depuración

st.markdown("---")
st.caption("Conversor SDMX — DEIE Mendoza | Datos: Dirección de Estadísticas e Investigaciones Económicas de Mendoza")
