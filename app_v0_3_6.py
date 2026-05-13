import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="Conversor SDMX — DEIE Mendoza", layout="wide")

# --- Estilos ---
st.markdown("""<style>.block-container { padding-top: 2rem; }.step-box { background: #f8f9fa; border-left: 4px solid #1f77b4; padding: 1rem 1.25rem; border-radius: 8px; margin-bottom: 1rem; }</style>""", unsafe_allow_html=True)

# --- Constantes ---
MESES_ES = {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12,'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}

# --- Funciones Core ---
def normalizar(t):
    s = str(t).lower().strip()
    for a,b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]: s = s.replace(a,b)
    return s

def limpiar_num(v):
    s = str(v).strip().replace('.','').replace(',','.')
    s = re.sub(r'[^0-9.\-]', '', s)
    try: return float(s)
    except: return None

def es_valido(t):
    s = normalizar(t)
    return s and len(s) > 1 and not any(x in s for x in ['fuente','nota','cuadro','gobierno'])

# --- Interfaz Lateral ---
st.sidebar.title("Configuración")
uploaded_file = st.sidebar.file_uploader("Archivo Excel", type=["xlsx", "xls"])
ref_area = st.sidebar.text_input("REF_AREA", "AR-MZA")
unit_measure = st.sidebar.text_input("UNIT_MEASURE", "INDEX")
base_year = st.sidebar.text_input("BASE_YEAR", "2004")

if uploaded_file:
    xl = pd.ExcelFile(uploaded_file)
    sheet = st.sidebar.selectbox("Hoja", xl.sheet_names)
    rows = xl.parse(sheet, header=None).values.tolist()

    st.markdown('<div class="step-box"><b>Configuración de Tabla</b></div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    f_inicio = c1.number_input("Fila Encabezado (1...)", 1, len(rows), 1) - 1
    c_rubro = c2.number_input("Columna Rubros (A=0...)", 0, 20, 0)

    if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
        registros = []
        anio_ctx = None
        mapa_cols = {} # Guardará {col_idx: (periodo, freq, tipo)}

        # 1. Escaneo de Encabezado (Fila seleccionada)
        fila_enc = rows[f_inicio]
        
        # Buscar año de contexto arriba de la fila de inicio
        for r in range(max(0, f_inicio-10), f_inicio + 1):
            for celda in rows[r]:
                m = re.search(r'\b(19|20)\d{2}\b', str(celda))
                if m: anio_ctx = m.group(0)

        # Mapear columnas
        ult_t, ult_f = None, 'M'
        for i, celda in enumerate(fila_enc):
            s = normalizar(celda)
            # ¿Es mes?
            if s in MESES_ES:
                p = f"{anio_ctx}-{MESES_ES[s]:02d}" if anio_ctx else f"0000-{MESES_ES[s]:02d}"
                mapa_cols[i] = (p, 'M', 'INDEX')
                ult_t, ult_f = p, 'M'
            # ¿Es año?
            elif re.search(r'\b(19|20)\d{2}\b', str(celda)):
                p = re.search(r'\b(19|20)\d{2}\b', str(celda)).group(0)
                mapa_cols[i] = (p, 'A', 'INDEX')
                ult_t, ult_f = p, 'A'
                anio_ctx = p # Actualizamos contexto
            # ¿Es Variación? (Sigue a un índice)
            elif ('var' in s or '%' in s or s == '') and ult_t:
                mapa_cols[i] = (ult_t, ult_f, 'VAR_PCT')

        # 2. Escaneo de Datos
        for r in range(f_inicio + 1, len(rows)):
            fila = rows[r]
            if len(fila) <= c_rubro: continue
            
            rubro_lbl = str(fila[c_rubro]).strip()
            if not es_valido(rubro_lbl): continue
            
            # Si la fila tiene un año nuevo (cambio de bloque)
            for celda in fila:
                m = re.search(r'^(19|20)\d{2}$', str(celda).strip())
                if m: anio_ctx = m.group(0)

            for idx, (p, f, tipo) in mapa_cols.items():
                val = limpiar_num(fila[idx] if idx < len(fila) else None)
                if val is not None:
                    # Corregir año si cambió
                    t_final = p
                    if f == 'M' and anio_ctx and "0000" in p:
                        t_final = f"{anio_ctx}-{p.split('-')[1]}"
                    elif f == 'M' and anio_ctx and "-" in p:
                        t_final = f"{anio_ctx}-{p.split('-')[1]}"

                    registros.append({
                        'FREQ': f, 'REF_AREA': ref_area, 'INDICATOR': rubro_lbl.upper().replace(' ','_'),
                        'INDICATOR_LABEL': rubro_lbl, 'TIME_PERIOD': str(t_final),
                        'OBS_MSR': tipo, 'OBS_VALUE': val, 'OBS_STATUS': 'A',
                        'UNIT_MEASURE': unit_measure if tipo == 'INDEX' else 'PCT',
                        'BASE_YEAR': base_year
                    })

        if registros:
            df = pd.DataFrame(registros)
            df['prio'] = df['OBS_MSR'].map({'INDEX': 0, 'VAR_PCT': 1})
            df = df.sort_values(['TIME_PERIOD', 'INDICATOR', 'prio']).drop(columns=['prio'])
            
            st.success(f"✅ {len(df)} registros detectados.")
            st.dataframe(df, use_container_width=True)
            st.download_button("Descargar CSV", df.to_csv(index=False).encode('utf-8'), "data.csv", "text/csv")
        else:
            st.error("No se detectaron datos. Probá cambiando la 'Fila Encabezado'.")
else:
    st.info("Subí un Excel para comenzar.")
