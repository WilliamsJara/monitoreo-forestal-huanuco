# Sistema inteligente de monitoreo satelital y alerta temprana de contaminación y amenazas forestales en el departamento de Huánuco

Monitorea las 11 provincias del departamento de Huánuco (Ambo, Dos de Mayo, Huacaybamba,
Huamalíes, Huánuco, Lauricocha, Leoncio Prado, Marañón, Pachitea, Puerto Inca y Yarowilca) y
genera alertas preventivas de:

| Amenaza | Fuente | Método |
|---|---|---|
| Incendios / focos de calor | NASA FIRMS — VIIRS S-NPP, NOAA-20, NOAA-21 (375 m) y MODIS (1 km) | Asignación por provincia y agrupación en **eventos de incendio con DBSCAN** (haversine, 1,5 km) con severidad por número de focos, FRP y persistencia |
| Deforestación / tala / quema | Sentinel-2 L2A (Copernicus Data Space) | Mediana de NDVI por píxel sin nubes (SCL) en dos periodos; pérdida = bosque (NDVI ≥ 0,6) que cae ≥ 0,25 y queda sin dosel (≤ 0,55) dentro del bosque oficial de MINAM, con ≥ 2 observaciones despejadas por periodo y descarte de píxeles aislados; zonas prioritarias en hectáreas |
| Recuperación de ecosistemas | Sentinel-2 L2A | Áreas degradadas con aumento sostenido de NDVI |
| Salud de la vegetación | Sentinel-2 L2A — Statistical API | NDVI mensual por provincia y caída frente a la mediana anual |
| Contaminación atmosférica | Sentinel-5P TROPOMI (NO₂, CO) | Serie semanal por provincia y **anomalía z** frente a su línea base |

Mejoras respecto de YACUMAMA IA (notebooks de Colab):

- Proyecto Python modular y reutilizable (`src/huanuco_monitor`), sin dependencia de Colab ni de Google Earth Engine.
- Credenciales en `.env`, fuera del código.
- Cuatro sensores FIRMS en lugar de uno, hasta 30 días de historial (consultas en ventanas de 5 días).
- Agrupación de focos en eventos de incendio (DBSCAN) con severidad.
- Detección de deforestación y recuperación **por píxel** comparando con el mismo periodo del año anterior (evita falsas alertas por estacionalidad), con enmascarado de nubes.
- Pérdida evaluada solo dentro del bosque oficial de MINAM (Geobosques) y validada contra sus alertas tempranas:
  95 % de las zonas detectadas coincide con alertas oficiales (azar: 11 %).
- Caché en disco con vencimiento: las consultas no se repiten innecesariamente.
- Tablero web Streamlit y script de actualización programable que exporta CSV/JSON.

Documentación completa (uso, descripción de cada archivo, fórmulas y reglas de cálculo):
[docs/MANUAL_TECNICO.md](docs/MANUAL_TECNICO.md) — también en Word/PDF en `docs/Manual_tecnico.*`.

## Instalación

```powershell
cd C:\Users\HP\PycharmProjects\monitoreo-forestal-huanuco
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # y completar las credenciales
```

Credenciales necesarias en `.env`:

- `SH_CLIENT_ID`, `SH_CLIENT_SECRET`: cliente OAuth de Copernicus Data Space
  (https://shapps.dataspace.copernicus.eu/dashboard/ → User settings → OAuth clients).
- `FIRMS_MAP_KEY`: https://firms.modaps.eosdis.nasa.gov/api/map_key/

## Uso

Tablero interactivo:

```powershell
.venv\Scripts\streamlit run app.py
```

Actualización por línea de comandos (precalienta la caché del tablero y exporta resultados a `salidas/`):

```powershell
.venv\Scripts\python scripts\actualizar.py --dias 7              # focos, NDVI y aire
.venv\Scripts\python scripts\actualizar.py --dias 7 --cobertura  # + deforestación/recuperación (≈ 5-10 min)
```

Para alertas diarias automáticas, programa el segundo comando en el Programador de tareas de Windows.

Validación e informe (después de una corrida con `--cobertura`):

```powershell
.venv\Scripts\python scripts\validar.py   # métricas, sensibilidad y láminas antes/después en salidas\validacion
.venv\Scripts\python scripts\informe.py   # informe Word en salidas\informe
.venv\Scripts\python scripts\comparar_mascara.py  # efecto de la máscara de nubes sobre la muestra ya interpretada
.venv\Scripts\python scripts\validar_minam.py     # validación independiente con alertas oficiales MINAM (Geobosques)
```

`validar.py` toma muestras aleatorias (semilla 42) de zonas detectadas. La interpretación de cada lámina
se registra a mano en `salidas\validacion\interpretacion_visual.csv`; si se cambia la muestra, ese archivo
debe rehacerse antes de generar el informe.

## Estructura

```
app.py                       Tablero Streamlit (mapa, alertas, gráficos)
scripts/actualizar.py        Actualización y exportación programable
data/provincias_huanuco.geojson   Límites provinciales (geoBoundaries, ADM2)
src/huanuco_monitor/
  config.py        credenciales, endpoints y umbrales de alerta
  copernicus.py    cliente OAuth2 + Statistical/Process API de Sentinel Hub
  firms.py         focos de calor y eventos DBSCAN
  indicadores.py   NDVI, cambio de cobertura, color real, NO₂ y CO
  alertas.py       reglas de alerta por provincia
  monitor.py       orquestación de todas las provincias
  geo.py, cache.py utilidades
```

Los umbrales (NDVI de bosque, caída mínima, hectáreas por nivel, puntaje z, etc.) están en
`config.py` y deben calibrarse con verificación de campo o con datos oficiales (Geobosques/MINAM).

## Limitaciones

- La nubosidad amazónica reduce las observaciones ópticas; el tablero informa el % de área observable.
- Una caída de NDVI indica *posible* pérdida (tala, quema, cosecha, desbroce): requiere verificación.
- Sentinel-5P mide columnas atmosféricas (no concentración a nivel del suelo) con ~5 km de resolución.
- Consumo de Copernicus: el análisis de cobertura de las 11 provincias usa unidades de procesamiento
  de la cuota mensual gratuita; la caché de 24 h evita repetirlo.
