import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="Conversor SDMX", layout="wide")

# --- Funciones de Procesamiento ---
def normalizar(t):
    if not t: return ""
    s = str(t).lower().strip()
    for a,b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ñ','n')]: s = s.replace(a,b)
    return s

def limpiar_num(v):
    if v is None or str(v).strip() in ["", "nan", "-", "..."]: return None
    s = str(v).strip().replace('.','').replace(',','.')
    s = re.sub(r'[^0-9.\-]', '', s)
    try: return float(s)
    except: return None

# --- Interfaz ---
uploaded_file = st.sidebar.file_uploader("Subir Excel", type=["xlsx", "xls"])
ref_area = st.sidebar.text_input("REF_AREA", "AR-MZA")
unit_measure = st.sidebar.text_input("UNIT_MEASURE", "INDEX")
base_year = st.sidebar.text_input("BASE_YEAR", "2004")

if uploaded_file:
    xl = pd.ExcelFile(uploaded_file)
    sheet = st.sidebar.selectbox("Hoja", xl.sheet_names)
    df_raw = xl.parse(sheet, header=None)
    rows = df_raw.values.tolist()

    c1, c2 = st.columns(2)
    f_enc = c1.number_input("Fila Encabezado (1...)", 1, len(rows), 1) - 1
    c_rubro = c2.number_input("Columna Rubros (A=0...)", 0, 20, 0)

    if st.button("⚙️ Convertir a SDMX", type="primary", use_container_width=True):
        registros = []
        anio_ctx = None
        mapa_cols = [] # Lista de dicts con la estructura de la tabla

        # 1. Identificar contexto de año (buscar en filas superiores)
        for r in range(max(0, f_enc - 15), f_enc + 1):
            for celda in rows[r]:
                m = re.search(r'\b(19|20)\d{2}\b', str(celda))
                if m: anio_ctx = m.group(0)

        # 2. Mapear columnas de la fila de encabezado
        meses_dict = {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,'noviembre':11,'diciembre':12,'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}
        
        ult_t, ult_f = None, 'M'
        fila_header = rows[f_enc]
        
        for i, celda in enumerate(fila_header):
            s = normalizar(celda)
            
            # Caso Mes
            if s in meses_dict:
                p = f"{anio_ctx}-{meses_dict[s]:02d}" if anio_ctx else f"0000-{meses_dict[s]:02d}"
                mapa_cols.append({'idx': i, 't': p, 'f': 'M', 'tipo': 'INDEX'})
                ult_t, ult_f = p, 'M'
            # Caso Año
            elif re.search(r'^(19|20)\d{2}$', str(celda).strip()):
                p = str(celda).strip()
                mapa_cols.append({'idx': i, 't': p, 'f': 'A', 'tipo': 'INDEX'})
                ult_t, ult_f = p, 'A'
                anio_ctx = p
            # Caso Variación (Columna vacía o con texto de variación a la derecha de un índice)
            elif i > 0 and i > c_rubro and ult_t:
                # Si la celda es de variación o está vacía/es la siguiente al índice
                if 'var' in s or '%' in s or s == "":
                    mapa_cols.append({'idx': i, 't': ult_t, 'f': ult_f, 'tipo': 'VAR_PCT'})
                    ult_t = None # Reset para no asignar VAR a todo lo que sigue

        # 3. Extraer Datos
        for r in range(f_enc + 1, len(rows)):
            fila = rows[r]
            if len(fila) <= c_rubro: continue
            
            rubro_lbl = str(fila[c_rubro]).strip()
            if not rubro_lbl or rubro_lbl.lower() in ['nan', 'none'] or len(rubro_lbl) < 2: continue
            if any(x in rubro_lbl.lower() for x in ['fuente', 'nota', 'cuadro']): continue

            # Actualizar año si la fila actual lo contiene (cambio de bloque)
            for celda in fila:
                m = re.search(r'^(19|20)\d{2}$', str(celda).strip())
                if m: anio_ctx = m.group(0)

            for col in mapa_cols:
                val = limpiar_num(fila[col['idx']] if col['idx'] < len(fila) else None)
                if val is not None:
                    t_final = col['t']
                    # Corregir año si se detectó uno nuevo
                    if col['f'] == 'M' and anio_ctx:
                        mes_ext = t_final.split('-')[1] if '-' in t_final else "01"
                        t_final = f"{anio_ctx}-{mes_ext}"

                    registros.append({
                        'FREQ': col['f'],
                        'REF_AREA': ref_area,
                        'INDICATOR': rubro_lbl.upper().replace(' ','_'),
                        'INDICATOR_LABEL': rubro_lbl,
                        'TIME_PERIOD': str(t_final),
                        'OBS_MSR': col['tipo'],
                        'OBS_VALUE': val,
                        'UNIT_MEASURE': unit_measure if col['tipo'] == 'INDEX' else 'PCT',
                        'BASE_YEAR': base_year
                    })

        if registros:
            df = pd.DataFrame(registros)
            # Orden cronológico estricto
            df['prio'] = df['OBS_MSR'].map({'INDEX': 0, 'VAR_PCT': 1})
            df = df.sort_values(['TIME_PERIOD', 'INDICATOR', 'prio']).drop(columns=['prio'])
            
            st.success(f"Se procesaron {len(df)} registros.")
            st.dataframe(df, use_container_width=True)
            st.download_button("Descargar CSV", df.to_csv(index=False).encode('utf-8'), "data_sdmx.csv")
        else:
            st.error("No se detectaron datos. Verificá la fila de encabezado y columna de rubros.")
