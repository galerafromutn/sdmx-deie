# Conversor SDMX — DEIE Mendoza

App web para convertir archivos Excel de la DEIE Mendoza al formato SDMX (CSV) listo para importar en DBeaver/PostgreSQL.

## ¿Cómo deployar en Streamlit Cloud? (gratis, sin instalar nada)

1. **Creá una cuenta** en https://github.com (si no tenés)
2. **Creá un repositorio nuevo** llamado `sdmx-deie` (público)
3. **Subí estos 2 archivos** al repositorio:
   - `app.py`
   - `requirements.txt`
4. **Andá a** https://share.streamlit.io
5. Iniciá sesión con tu cuenta de GitHub
6. Clic en **"New app"**
7. Elegí tu repositorio `sdmx-deie`, rama `main`, archivo `app.py`
8. Clic en **"Deploy"** — en 2 minutos tenés la URL lista

La URL va a ser algo como: `https://sdmx-deie.streamlit.app`
Esa URL la podés compartir con todo el equipo, funciona en cualquier dispositivo.

## ¿Cómo usar la app?

1. Abrí la URL en cualquier navegador
2. Subí el archivo Excel de la DEIE
3. Elegí la hoja que tiene todos los rubros juntos
4. Escribí el nombre de la tabla que querés crear en PostgreSQL
5. Clic en "Convertir a SDMX"
6. Descargá el CSV y el SQL generados
7. En DBeaver: ejecutá el SQL para crear la tabla, luego el COPY para importar

## Correr localmente (opcional)

```bash
pip install -r requirements.txt
streamlit run app.py
```
