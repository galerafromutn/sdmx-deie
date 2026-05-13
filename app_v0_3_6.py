import streamlit as st
import pandas as pd
import re
import io

st.set_page_config(
    page_title="Conversor SDMX — DEIE Mendoza",
    page_icon="📊",
    layout="wide"
)

# ─── Estilos ──────────────────────────────────────────────────────────────────
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
    .step-title { font-weight: 600; font-size: 1.05rem; color: #1f77b4; margin: 0; }
</style>
""", unsafe_allow_html=True)

# ─── Constantes ───────────────────────────────────────────────────────────────
MESES_ES = {
    'enero':1, 'febrero':2, 'marzo':3, 'abril':4, 'mayo':5, 'junio':6,
    'julio':7, 'agosto':8, 'septiembre':9, 'setiembre':9, 'octubre':10, 'noviembre':11, 'diciembre':12,
    'ene':1, 'feb':2, 'mar':3, 'abr':4, 'may':5, 'jun':6, 'jul':7, 'ago':8, 'sep':9, 'oct':10, 'nov':11, 'dic':12
}

# ─── Utilidades ───────────────────────────────────────────────────────────────
def normalizar(texto):
    if not texto or str(texto).lower() == 'nan': return ""
    s = str(texto).lower().strip()
    for a, b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]:
        s = s.replace(a, b)
    return s

def a_code(texto):
    s = normalizar(texto)
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_').upper()

def limpiar_numero(valor):
    if valor is None or str(valor).strip() in ("", ".", "-", "nan", "None"):
        return None
    s = str(valor).strip().replace('.', '').replace(',', '.')
    try:
        return float(s)
    except:
        return None

def es_rubro_valido(texto):
    s = normalizar(texto)
    if not s or len(s) < 3 or s == 'nan': return False
    ignorar = ['fuente', 'nota', 'cuadro', 'contacto', 'gobierno', 'mendoza']
    return not any(p in s for p in ignorar)

def generar_sql(tabla, archivo, area):
    return f"""-- SQL para DBeaver / PostgreSQL
CREATE TABLE IF NOT EXISTS public.{tabla} (
    freq char(1), 
    ref_area varchar(50), 
    indicator varchar(100), 
    indicator_label text,
    time_period varchar(20), 
    obs_msr varchar(20), 
    obs_value numeric(18,6),
    obs_status char(1), 
    unit_measure varchar(20), 
    base_year varchar(20)
);

COPY public.{tabla} (freq, ref_area, indicator, indicator_label, time_period, obs_msr, obs_value, obs_status, unit_measure, base_year)
FROM 'C:/ruta/tu/archivo/{archivo}' 
WITH (FORMAT csv, HEADER true, DELIMITER ',');
"""

# ─── Motor de Procesamiento ──────────────────────────────────────────────────
def parsear_datos_evolucionado(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year):
    def obtener_tiempo(v, anio_ctx):
        if not v or str(v).lower() == 'nan': return None, None
        s = normalizar(v)
        if s in MESES_ES:
            return f"{anio_ctx}-{MESES_ES[s]:02d}" if anio_ctx else None, 'M'
        m_a = re.fullmatch(r'(19|20)\d{2}', str(v).strip())
        if m_a: return m_a.group(0), 'A'
        if 'var' in s or '%' in s or s == '': return 'VAR_MARKER', 'VAR'
        return None, None

    registros = []
    bloques = []
    
    for i in range(int(fila_inicio), len(rows)):
        c_t = [idx for idx, c in enumerate(rows[i]) if obtener_tiempo(c, 2000)[1] is not None]
        if len(c_t) >= 2: bloques.append(i)

    if not bloques: return [], "No se detectaron encabezados con meses o años."

    for b_idx, f_enc_idx in enumerate(bloques):
        f_fin = bloques[b_idx + 1] if b_idx + 1 < len(bloques) else len(rows)
        
        anio_bloque = None
        for r_off in range(-6, 2):
            idx_b = f_enc_idx + r_off
            if 0 <= idx_b < len(rows):
                for c in rows[idx_b]:
                    m = re.search(r'\b(19|20)\d{2}\b', str(c))
                    if m: anio_bloque = m.group(0); break

        mapa_cols = []
        u_t, u_f = None, 'M'
        for c_idx, celda in enumerate(rows[f_enc_idx]):
            p, f = obtener_tiempo(celda, anio_bloque)
            if f == 'VAR' and u_t:
                mapa_cols.append({'idx': c_idx, 't': u_t, 'f': u_f, 'tipo': 'VAR_PCT'})
            elif p and p != 'VAR_MARKER':
                mapa_cols.append({'idx': c_idx, 't': p, 'f': f, 'tipo': 'INDEX'})
                u_t, u_f = p, f

        for r_idx in range(f_enc_idx + 1, f_fin):
            fila = rows[r_idx]
            if len(fila) <= col_rubro: continue
            rubro_lbl = str(fila[col_rubro]).strip()
            if not es_rubro_valido(rubro_lbl): continue
            
            for c_f in fila:
                m_f = re.fullmatch(r'(19|20)\d{2}', str(c_f).strip())
                if m_f: anio_bloque = m_f.group(0)

            for mc in mapa_cols:
                val = limpiar_numero(fila[mc['idx']] if mc['idx'] < len(fila) else None)
                if val is not None:
                    t_final = mc['t']
                    if mc['f'] == 'M' and anio_bloque and "-" in str(t_final):
                        t_final = f"{anio_bloque}-{str(t_final).split('-')[1]}"
                    
                    registros.append({
                        'FREQ': mc['f'], 'REF_AREA': ref_area, 'INDICATOR': a_code(rubro_lbl),
                        'INDICATOR_LABEL': rubro_lbl, 'TIME_PERIOD': str(t_final),
                        'OBS_MSR': mc['tipo'], 'OBS_VALUE': val, 'OBS_STATUS': 'A',
                        'UNIT_MEASURE': unit_measure if mc['tipo'] == 'INDEX' else 'PCT',
                        'BASE_YEAR': base_year
                    })
    return registros, None

# ─── Interfaz Streamlit ──────────────────────────────────────────────────────
uploaded_file = st.sidebar.file_uploader("Subir Excel (.xlsx, .xls)", type=["xlsx", "xls"])

if uploaded_file:
    xl = pd.ExcelFile(uploaded_file)
    sheet = st.sidebar.selectbox("Hoja de Datos", xl.sheet_names)
    df_raw = xl.parse(sheet, header=None)
    rows = df_raw.values.tolist()

    st.sidebar.divider()
    ref_area = st.sidebar.text_input("REF_AREA", "AR-MZA")
    unit_measure = st.sidebar.text_input("UNIT_MEASURE (Index)", "INDEX")
    base_year = st.sidebar.text_input("BASE_YEAR", "2004")
    nombre_tabla = a_code(sheet)

    c_ui_1, c_ui_2 = st.columns(2)
    with c_ui_1:
        st.markdown('<div class="step-box"><p class="step-title">1. Fila de Inicio</p></div>', unsafe_allow_html=True)
        fila_inicio = st.number_input("Fila del primer encabezado", 1, len(rows), 1)
    with c_ui_2:
        st.markdown('<div class="step-box"><p class="step-title">2. Columna de Rubros</p></div>', unsafe_allow_html=True)
        col_rubro = st.number_input("Columna de indicadores (A=0, B=1...)", 0, 20, 0)

    if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
        registros, error = parsear_datos_evolucionado(rows, fila_inicio-1, col_rubro, ref_area, unit_measure, base_year)
        
        if error:
            st.error(f"❌ {error}")
        elif not registros:
            st.warning("⚠️ No se detectaron datos válidos.")
        else:
            df_out = pd.DataFrame(registros)
            df_out['msr_priority'] = df_out['OBS_MSR'].map({'INDEX': 0, 'VAR_PCT': 1})
            df_out = df_out.sort_values(by=['TIME_PERIOD', 'INDICATOR', 'msr_priority'])
            df_out = df_out.drop(columns=['msr_priority'])
            
            anios = sorted(df_out['TIME_PERIOD'].str[:4].unique())
            freqs = df_out['FREQ'].unique()

            st.success(f"✅ Se procesaron {len(df_out):,} registros.")
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Registros", f"{len(df_out):,}")
            m2.metric("Rubros", df_out['INDICATOR'].nunique())
            m3.metric("Período", f"{anios[0]}—{anios[-1]}" if anios else "—")
            m4.metric("Frecuencias", ", ".join(freqs))

            with st.expander("👁️ Vista Previa (Orden Cronológico)", expanded=True):
                st.dataframe(df_out.head(100), use_container_width=True)

            csv_data = df_out.to_csv(index=False).encode('utf-8')
            sql_data = generar_sql(nombre_tabla, f"{nombre_tabla}_sdmx.csv", ref_area)
            
            d_col1, d_col2 = st.columns(2)
            d_col1.download_button("⬇️ Descargar CSV", csv_data, f"{nombre_tabla}_sdmx.csv", "text/csv", use_container_width=True)
            d_col2.download_button("⬇️ Descargar SQL", sql_data.encode('utf-8'), f"{nombre_tabla}.sql", use_container_width=True)
            st.code(sql_data, language="sql")
else:
    st.info("👋 Subí un archivo Excel en la barra lateral para empezar.")
