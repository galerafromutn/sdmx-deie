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

def detectar_indicador(titulo):
    """Extrae el nombre del indicador del título del archivo/hoja."""
    titulo = titulo.strip()
    match = re.search(r'Índice de (.+?)\s*[\(\,]', titulo, re.IGNORECASE)
    if match:
        return match.group(1).strip().upper().replace(' ', '_').replace('Í','I').replace('É','E').replace('Ó','O').replace('Ú','U').replace('Á','A')
    return "INDICADOR"

def procesar_hoja(df_raw):
    """Procesa una hoja con formato DEIE y devuelve lista de registros SDMX."""
    
    # Convertir todo a string para procesar
    rows = []
    for _, row in df_raw.iterrows():
        rows.append([str(v).strip() if pd.notna(v) else '' for v in row])

    registros = []
    anio_actual = None
    meses_actuales = []
    modo = None
    rubros_detectados = set()

    for i, row in enumerate(rows):
        col0 = row[0].strip() if row else ''

        # Detectar año
        match_anio = re.search(r'[Aa]ño\s+(\d{4})', col0)
        if match_anio:
            anio_actual = int(match_anio.group(1))
            meses_actuales = []
            modo = None
            continue

        # Detectar fila de meses
        meses_fila = []
        for v in row:
            v_clean = v.strip().lower().rstrip('*').strip()
            if v_clean in MESES_MAP:
                meses_fila.append(MESES_MAP[v_clean])

        if meses_fila and anio_actual:
            # Mirar hacia adelante para determinar modo
            modo_sig = None
            for j in range(i+1, min(i+6, len(rows))):
                r2 = rows[j]
                c0 = r2[0].strip()
                if any('Var' in str(x) for x in r2):
                    modo_sig = 'variacion'
                    break
                # Si la primera columna no está vacía y no es encabezado, es valor
                if c0 and c0 not in ['', 'nan'] and not any(x in c0 for x in ['Fuente', 'Dato', 'Nota', 'Promedio']):
                    modo_sig = 'valor'
                    break
            if modo_sig == 'valor':
                meses_actuales = meses_fila
                modo = 'valor'
            elif modo_sig == 'variacion':
                modo = 'variacion'
            continue

        # Detectar si la fila tiene "Var" → modo variación
        if row and any('Var' in str(v) for v in row[:3]):
            modo = 'variacion'
            continue

        # Ignorar filas vacías, de fuente, promedio, etc.
        if not col0 or col0 in ['nan', ''] or any(x in col0 for x in ['Fuente', 'Dato', 'Nota', 'Promedio', '%', 'Rubros', 'rubros']):
            continue

        # Detectar rubro (cualquier texto no vacío que no sea encabezado)
        if anio_actual and meses_actuales and col0 and col0 not in ['nan', '']:
            rubro_nombre = col0.strip()
            # Limpiar caracteres extraños
            rubro_nombre = re.sub(r'\s+', ' ', rubro_nombre)
            rubro_code = rubro_nombre.upper().replace(' ', '_')
            # Reemplazar caracteres especiales
            for a, b in [('Á','A'),('É','E'),('Í','I'),('Ó','O'),('Ú','U'),('Ñ','N'),('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u')]:
                rubro_code = rubro_code.replace(a, b)

            data_vals = [v for v in row[1:] if v != '']

            if modo == 'valor':
                rubros_detectados.add(rubro_nombre)
                for idx, mes in enumerate(meses_actuales):
                    if idx < len(data_vals):
                        v = data_vals[idx].replace('.', '').replace(',', '.').strip()
                        try:
                            valor = float(v)
                        except:
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
                for idx, mes in enumerate(meses_actuales):
                    if idx < len(data_vals):
                        v = data_vals[idx].replace(',', '.').strip()
                        try:
                            var = float(v)
                        except:
                            var = None
                        for rec in reversed(registros):
                            if rec['TIME_PERIOD'] == f"{anio_actual}-{mes:02d}" and rec['INDICATOR'] == rubro_code:
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
            value=hoja_elegida.lower().replace(' ', '_').replace('í','i').replace('é','e').replace('ó','o').replace('á','a').replace('ú','u')
        )

        ref_area = st.text_input("📍 Código de área (REF_AREA)", value="AR-MZA")

        if st.button("⚙️ Convertir a SDMX", type="primary"):
            with st.spinner("Procesando..."):
                df_raw = xl.parse(hoja_elegida, header=None)
                registros, rubros = procesar_hoja(df_raw)

            if not registros:
                st.error("❌ No se encontraron datos. Verificá que la hoja tenga el formato DEIE estándar.")
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

st.markdown("---")
st.caption("Conversor SDMX — DEIE Mendoza | Datos: Dirección de Estadísticas e Investigaciones Económicas de Mendoza")
