import streamlit as st
import pandas as pd
import re
import io

st.set_page_config(page_title="Conversor SDMX — DEIE Mendoza", page_icon="📊", layout="wide")

# ─── Estilos ──────────────────────────────────────────────────────────────────
st.markdown("""<style>.block-container { padding-top: 2rem; }.step-box { background: #f8f9fa; border-left: 4px solid #1f77b4; padding: 1rem 1.25rem; border-radius: 0 8px 8px 0; margin-bottom: 1rem; }.step-title { font-weight: 600; font-size: 1.05rem; color: #1f77b4; margin: 0; }</style>""", unsafe_allow_html=True)

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
    if valor is None or str(valor).strip() in ("", ".", "-", "nan", "None", "...", "/"): return None
    s = str(valor).strip().replace('.', '').replace(',', '.')
    s = re.sub(r'[^0-9.\-]', '', s) # Limpieza extra de caracteres no numéricos
    try: return float(s)
    except: return None

def es_rubro_valido(texto):
    s = normalizar(texto)
    if not s or len(s) < 2 or s == 'nan': return False
    ignorar = ['fuente', 'nota', 'cuadro', 'contacto', 'gobierno', 'mendoza', 'elaboracion']
    return not any(p in s for p in ignorar)

def generar_sql(tabla, archivo, area):
    return f"""-- SQL para DBeaver / PostgreSQL
CREATE TABLE IF NOT EXISTS public.{tabla} (
    freq char(1), ref_area varchar(50), indicator varchar(100), indicator_label text,
    time_period varchar(20), obs_msr varchar(20), obs_value numeric(18,6),
    obs_status char(1), unit_measure varchar(20), base_year varchar(20)
);

COPY public.{tabla} (freq, ref_area, indicator, indicator_label, time_period, obs_msr, obs_value, obs_status, unit_measure, base_year)
FROM 'C:/ruta/tu/archivo/{archivo}' WITH (FORMAT csv, HEADER true, DELIMITER ',');"""

# ─── Motor de Procesamiento ──────────────────────────────────────────────────
def parsear_datos_evolucionado(rows, fila_inicio, col_rubro, ref_area, unit_measure, base_year):
    def obtener_tiempo(v, anio_ctx):
        if not v or str(v).lower() == 'nan': return None, None
        s = normalizar(v)
        # 1. Búsqueda de Meses
        if s in MESES_ES:
            return f"{anio_ctx}-{MESES_ES[s]:02d}" if anio_ctx else None, 'M'
        # 2. Búsqueda de Años (Flexible: detecta 2010 incluso con asteriscos)
        m_a = re.search(r'\b(19|20)\d{2}\b', str(v))
        if m_a: return m_a.group(0), 'A'
        # 3. Búsqueda de Variación (Detecta "Var", "%", o celdas vacías estratégicas)
        if 'var' in s or '%' in s or s == '': 
            return 'VAR_MARKER', 'VAR'
        return None, None

    registros = []
    bloques = []
    
    # 1. Identificar encabezados (Filtro más permisivo)
    for i in range(int(fila_inicio), len(rows)):
        c_t = [idx for idx, c in enumerate(rows[i]) if obtener_tiempo(c, 2024)[1] is not None]
        if len(c_t) >= 1: # Bajamos a 1 para no perder tablas pequeñas
            bloques.append(i)

    if not bloques: return [], "No se detectaron encabezados temporales."

    anio_global = None

    for b_idx, f_enc_idx in enumerate(bloques):
        f_fin = bloques[b_idx + 1] if b_idx + 1 < len(bloques) else len(rows)
        
        # Búsqueda exhaustiva de año de contexto
        for r_off in range(-10, 2):
            idx_b = f_enc_idx + r_off
            if 0 <= idx_b < len(rows):
                for c in rows[idx_b]:
                    m = re.search(r'\b(19|20)\d{2}\b', str(c))
                    if m: anio_global = m.group(0); break

        mapa_cols = []
        u_t, u_f = None, 'M'
        fila_enc = rows[f_enc_idx]
        
        for c_idx, celda in enumerate(fila_enc):
            p, f = obtener_tiempo(celda, anio_global)
            if f == 'VAR':
                if u_t: # Si hay un índice previo, esta columna es su variación
                    mapa_cols.append({'idx': c_idx, 't': u_t, 'f': u_f, 'tipo': 'VAR_PCT'})
            elif p and p != 'VAR_MARKER':
                mapa_cols.append({'idx': c_idx, 't': p, 'f': f, 'tipo': 'INDEX'})
                u_t, u_f = p, f

        # Procesar datos
        for r_idx in range(f_enc_idx + 1, f_fin):
            fila = rows[r_idx]
            if len(fila) <= col_rubro: continue
            rubro_lbl = str(fila[col_rubro]).strip()
            if not es_rubro_valido(rubro_lbl): continue
            
            # Actualización de año en la misma fila (común en tablas largas)
            for c_f in fila:
                m_f = re.search(r'\b(19|20)\d{2}\b', str(c_f))
                if m_f: anio_global = m_f.group(0)

            for mc in mapa_cols:
                val = limpiar_numero(fila[mc['idx']] if mc['idx'] < len(fila) else None)
                if val is not None:
                    t_final = mc['t']
                    # Sincronizar mes con el año actual del bloque
                    if mc['f'] == 'M' and anio_global and "-" in str(t_final):
                        t_final = f"{anio_global}-{str(t_final).split('-')[1]}"
                    
                    registros.append({
                        'FREQ': mc['f'], 'REF_AREA': ref_area, 'INDICATOR': a_code(rubro_lbl),
                        'INDICATOR_LABEL': rubro_lbl, 'TIME_PERIOD': str(t_final),
                        'OBS_MSR': mc['tipo'], 'OBS_VALUE': val, 'OBS_STATUS': 'A',
                        'UNIT_MEASURE': unit_measure if mc['tipo'] == 'INDEX' else 'PCT',
                        'BASE_YEAR': base_year
                    })
    return registros, None

# ─── Interfaz Streamlit ──────────────────────────────────────────────────────
uploaded_file = st.sidebar.file_uploader("Subir Excel", type=["xlsx", "xls"])

if uploaded_file:
    xl = pd.ExcelFile(uploaded_file)
    sheet = st.sidebar.selectbox("Hoja", xl.sheet_names)
    df_raw = xl.parse(sheet, header=None)
    rows = df_raw.values.tolist()

    st.sidebar.divider()
    ref_area = st.sidebar.text_input("REF_AREA", "AR-MZA")
    unit_measure = st.sidebar.text_input("UNIT_MEASURE", "INDEX")
    base_year = st.sidebar.text_input("BASE_YEAR", "2004")
    nombre_tabla = a_code(sheet)

    c1, c2 = st.columns(2)
    with c1: fila_inicio = st.number_input("Fila Inicio Encabezado", 1, len(rows), 1)
    with c2: col_rubro = st.number_input("Columna Rubros (A=0)", 0, 20, 0)

    if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
        registros, error = parsear_datos_evolucionado(rows, fila_inicio-1, col_rubro, ref_area, unit_measure, base_year)
        
        if error: st.error(f"❌ {error}")
        elif not registros: st.warning("⚠️ Sin datos.")
        else:
            df_out = pd.DataFrame(registros)
            df_out['prio'] = df_out['OBS_MSR'].map({'INDEX': 0, 'VAR_PCT': 1})
            df_out = df_out.sort_values(by=['TIME_PERIOD', 'INDICATOR', 'prio']).drop(columns=['prio'])
            
            anios = sorted(df_out['TIME_PERIOD'].str[:4].unique())
            st.success(f"✅ {len(df_out):,} registros procesados.")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Registros", f"{len(df_out):,}")
            m2.metric("Rubros", df_out['INDICATOR'].nunique())
            m3.metric("Período", f"{anios[0]}—{anios[-1]}" if anios else "—")

            st.dataframe(df_out, use_container_width=True)
            
            csv = df_out.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Descargar CSV", csv, f"{nombre_tabla}.csv", "text/csv", use_container_width=True)
            st.code(generar_sql(nombre_tabla, f"{nombre_tabla}.csv", ref_area), language="sql")
else:
    st.info("Subí el archivo para empezar.")
