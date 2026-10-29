# Manual de usuario y especificaciones técnicas

**Sistema inteligente de monitoreo satelital y alerta temprana de contaminación y amenazas forestales en el departamento de Huánuco**

Versión del software: 1.0.0 · Versión del manual: 1.0 · Octubre de 2026

---

## Contenido

- Parte I — Manual de usuario
  1. Qué hace el sistema
  2. Requisitos
  3. Instalación
  4. Configuración de credenciales
  5. Uso del tablero web
  6. Uso por línea de comandos
  7. Archivos de salida
  8. Solución de problemas
- Parte II — Especificaciones técnicas
  9. Arquitectura y flujo de datos
  10. Estructura de directorios
  11. Descripción de cada archivo
  12. Cómo calcula: algoritmos y fórmulas
  13. Reglas de alerta
  14. Parámetros configurables
  15. Servicios externos
  16. Caché
  17. Rendimiento
  18. Seguridad
  19. Fiabilidad y limitaciones conocidas
  20. Mantenimiento y extensión
- Anexo A — Glosario
- Anexo B — Referencia rápida de comandos

---

# Parte I — Manual de usuario

## 1. Qué hace el sistema

El sistema descarga datos de satélites, los procesa por provincia y genera alertas preventivas para las 11 provincias del departamento de Huánuco: Ambo, Dos de Mayo, Huacaybamba, Huamalíes, Huánuco, Lauricocha, Leoncio Prado, Marañón, Pachitea, Puerto Inca y Yarowilca.

| Amenaza o indicador | Satélite / fuente | Qué entrega el sistema |
|---|---|---|
| Incendios forestales | NASA FIRMS (VIIRS y MODIS) | Focos de calor, eventos de incendio agrupados y su severidad |
| Deforestación, tala o quema | Sentinel-2 | Hectáreas de posible pérdida de bosque y zonas prioritarias para verificar |
| Recuperación de vegetación | Sentinel-2 | Hectáreas con indicios de rebrote |
| Salud de la vegetación | Sentinel-2 | NDVI mensual por provincia |
| Contaminación atmosférica | Sentinel-5P | NO₂ y CO semanales por provincia y anomalías |

Tiene dos formas de uso:

- **Tablero web** (`app.py`): mapas, alertas, gráficos y descarga de datos en el navegador.
- **Línea de comandos** (`scripts/`): actualización automática, exportación de resultados, validación e informe.

> **Importante.** Las cifras de deforestación y recuperación son *posibles* cambios que requieren verificación. La validación del 20/10/2026 confirmó la detección de incendios, pero mostró que las hectáreas de pérdida están sobrestimadas (ver sección 19 y el informe técnico).

## 2. Requisitos

**Equipo**

- Windows 10/11, Linux o macOS.
- 4 GB de RAM como mínimo (recomendado 8 GB).
- 1 GB de disco para el entorno y la caché.
- Conexión a internet estable: el sistema consulta servicios en la nube.

**Software**

- Python 3.11 (probado con 3.11.9).
- Navegador web moderno (Edge, Chrome o Firefox).
- Microsoft Word, solo si se quiere convertir los documentos a PDF.

**Cuentas gratuitas**

| Servicio | Para qué | Dónde se obtiene |
|---|---|---|
| Copernicus Data Space Ecosystem | Imágenes Sentinel-2 y Sentinel-5P | https://dataspace.copernicus.eu → panel de Sentinel Hub → *User settings* → *OAuth clients* |
| NASA FIRMS | Focos de calor | https://firms.modaps.eosdis.nasa.gov/api/map_key/ |

**Librerías Python** (archivo `requirements.txt`; versiones con las que se probó)

| Librería | Versión probada | Uso |
|---|---|---|
| streamlit | 1.66.0 | Tablero web |
| streamlit-folium, folium | 0.20.0 (folium) | Mapas interactivos |
| plotly | 7.1.0 | Gráficos del tablero |
| pandas, numpy | 3.0.6 / 2.4.6 | Tablas y cálculo numérico |
| shapely | 2.2.0 | Geometría de provincias |
| scikit-learn | 1.9.1 | DBSCAN (agrupación de incendios) |
| requests | — | Llamadas HTTP a las API |
| python-dotenv | — | Lectura del archivo `.env` |
| Pillow | — | Lectura de imágenes PNG |
| matplotlib, python-docx | — | Solo para el informe y este manual en Word |

## 3. Instalación

Abrir PowerShell y ejecutar:

```powershell
cd C:\Users\HP\PycharmProjects\monitoreo-forestal-huanuco
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Luego editar `.env` con las credenciales (sección 4). Para comprobar la instalación:

```powershell
.venv\Scripts\python -c "import sys; sys.path.insert(0,'src'); from huanuco_monitor import geo; print(list(geo.provincias()))"
```

Debe imprimir los nombres de las 11 provincias.

## 4. Configuración de credenciales

El archivo `.env` (en la carpeta raíz del proyecto) contiene:

```text
SH_CLIENT_ID=sh-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SH_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FIRMS_MAP_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- `SH_CLIENT_ID` y `SH_CLIENT_SECRET`: cliente OAuth de Copernicus Data Space. El identificador empieza por `sh-`. Los clientes OAuth tienen **fecha de caducidad**: si el sistema deja de autenticarse, hay que crear uno nuevo en el panel.
- `FIRMS_MAP_KEY`: clave de 32 caracteres de NASA FIRMS.

Reglas de seguridad:

- `.env` está excluido de git (`.gitignore`); nunca se debe subir a un repositorio ni enviarse por correo o chat.
- Para compartir el proyecto se entrega `.env.example`, que solo contiene los nombres de las variables.
- Si una clave se expuso, hay que regenerarla en el panel del servicio.

## 5. Uso del tablero web

### 5.1 Iniciar y detener

```powershell
.venv\Scripts\streamlit run app.py
```

Se abre el navegador en `http://localhost:8501`. Para detenerlo: `Ctrl + C` en la terminal. Para otro puerto: `--server.port 8600`.

**Primera carga:** la primera vez puede tardar entre 3 y 5 minutos, porque descarga NDVI y datos de aire de las 11 provincias. Después, los datos quedan guardados 24 horas y la carga toma segundos. Para que el tablero abra rápido desde la primera vez, se puede ejecutar antes `scripts\actualizar.py` (sección 6).

### 5.2 Barra lateral

**Apertura rápida (desde el 25/10/2026):** al abrir, el tablero muestra la **última corrida programada** guardada en la base de datos (tarda segundos, no consulta satélites ni gasta cuota). Para consultar los satélites en ese momento, pulsar **Consultar satélites ahora**.

| Control | Función |
|---|---|
| **Sección** | Cambia entre las 5 pantallas del tablero |
| Datos de la corrida programada | Fecha de la corrida que se está mostrando (modo rápido) |
| **Consultar satélites ahora** / **Actualizar datos satelitales** | Pasa a consultar las fuentes en vivo / vuelve a consultarlas ignorando la caché |
| **Opciones avanzadas** | Días de focos de calor (1–30), sensores FIRMS, actualizar una sola fuente y volver a la última corrida guardada. Cambiar los días o los sensores pasa al modo en vivo |
| Actualización de cada fuente | Fecha de los datos de cada fuente; **⚠** = la última consulta falló y se muestran los últimos datos buenos (respaldo) |
| ⚠ consultas con error | Aparece solo si alguna consulta falló; lista provincia y motivo |

Cada fuente se consulta por separado: si una falla o demora, las demás siguen disponibles. Si una fuente falla por completo, se usan sus últimos datos buenos guardados en `.cache\respaldo_*.pkl` y se indica su fecha.

### 5.3 Sección «Panorama y alertas»

Ordenada para leerse de arriba abajo, también en celular (las tarjetas se acomodan de dos en dos):

1. **Indicadores:** focos de calor, eventos de incendio, provincias en alerta alta y NDVI regional del último mes.
2. **Resumen por provincia:** una tarjeta por provincia, de mayor a menor alerta, con su nivel y el número de alertas por tipo (incendio, deforestación, vegetación, aire).
3. **Alertas prioritarias:** hasta 6 alertas de nivel alto, cada una con su detalle, fecha, fuente y calidad de la observación.
4. **Mapa de alertas:** provincias coloreadas por nivel, focos de calor (el tamaño indica la potencia) y eventos de incendio. El selector de capas (arriba a la derecha, plegado) cambia el fondo entre imagen satelital y OpenStreetMap.
5. **Todas las alertas con su evidencia** (desplegable): fuente satelital, fecha o periodo, indicador y umbral que la activaron, calidad de la observación y coordenadas del punto más relevante. Se puede descargar en CSV.
6. **Historial de alertas** (desplegable): número de alertas por nivel en cada corrida programada.

> En modo rápido el panorama incluye las alertas de deforestación de la corrida programada (si se ejecutó con `--cobertura`). En modo en vivo, el detalle de deforestación se calcula bajo demanda en su propia sección.

### 5.4 Sección «Incendios y focos de calor»

- **Indicadores:** total de detecciones, cuántas tienen confianza alta, eventos agrupados y potencia radiativa total (FRP, en megavatios).
- **Mapa** de focos y eventos, con círculos coloreados por severidad.
- **Gráficos:** focos por provincia y focos por día.
- **Tabla de eventos:** provincia, número de focos, FRP total y máximo, ubicación, fechas, días activo y severidad.
- **Tabla de focos** desplegable, con botón **Descargar CSV**.

Cómo interpretar: un *foco de calor* es un píxel del satélite más caliente que su entorno; un mismo fuego puede aparecer en varios satélites y varias pasadas. Un *evento* reúne focos a menos de 1,5 km entre sí.

### 5.5 Sección «Deforestación y recuperación»

1. Elegir la **provincia**.
2. Elegir la **duración de cada periodo** (30 a 180 días; 90 por defecto). Debajo se muestran las fechas exactas de los periodos «antes» (año anterior) y «después» (reciente).
3. Pulsar **Analizar**. La primera vez tarda aproximadamente 1 minuto por provincia.

Resultados:

- **Posible pérdida forestal (ha)**, **Indicios de recuperación (ha)**, **Área observable sin nubes (%)** y **Resolución de análisis (m)**.
- Si el área observable es menor al 40 %, aparece un aviso: conviene ampliar la duración de los periodos.
- Debajo de las cifras se indica la **máscara de bosque** aplicada (MINAM). Si el servicio de Geobosques no responde, aparece un aviso y el resultado se muestra sin máscara (puede incluir cambios agrícolas).
- **Mapa:** imagen Sentinel-2 reciente en color real, píxeles de posible pérdida en rojo, recuperación en verde y las 25 zonas de pérdida más grandes marcadas con círculos. En el control de capas se pueden activar las capas oficiales **MINAM: bosque al 2024** y **MINAM: alertas tempranas 2026** para contrastar.
- **Tablas** de zonas de pérdida y de recuperación con coordenadas y hectáreas, útiles para planificar verificaciones de campo.
- **Evidencia de una zona:** al elegir una de las 25 zonas de pérdida más grandes se muestran tres imágenes Sentinel-2 sin nubes de ~1,3 km de lado: antes, después y después en falso color (bosque verde oscuro; suelo desnudo o quema en rosado o marrón). La tabla de pérdida incluye la columna **alerta MINAM** (sí/no): si en la celda de la zona hay alerta temprana 2026 o pérdida 2025 oficial.

### 5.6 Sección «Cobertura vegetal (NDVI)»

- Gráfico del NDVI mensual de la provincia elegida (14 meses: el último año más el margen para compararlo con el año anterior). Los meses con menos del 5 % de la provincia sin nubes se omiten y aparecen como huecos en la línea.
- Tabla resumen por provincia: NDVI del último mes, mediana, mínimo y máximo anual, y la diferencia del último mes respecto de la mediana.

Referencia de lectura del NDVI: menos de 0,2 corresponde a suelo desnudo, roca o agua; entre 0,2 y 0,5, a pastos o cultivos; más de 0,6, a vegetación densa o bosque.

### 5.7 Sección «Calidad del aire»

- Elegir el contaminante (NO₂ o CO) y la provincia.
- Gráfico de la serie semanal de los últimos 120 días.
- Tabla de anomalías: puntaje z de la última semana válida de cada provincia (z ≥ 2 indica un valor inusualmente alto).

Cómo interpretar: Sentinel-5P mide la cantidad del gas en toda la columna de aire, no la concentración a nivel del suelo. El CO es mayor en la selva baja porque a menor altitud la columna de aire es más larga. **No se deben comparar provincias entre sí**, sino cada provincia con su propia historia.

## 6. Uso por línea de comandos

Todos los comandos se ejecutan desde la carpeta del proyecto.

### 6.1 Actualizar datos y generar alertas

```powershell
.venv\Scripts\python scripts\actualizar.py --dias 7               # focos, NDVI y aire (~3-5 min la 1.ª vez)
.venv\Scripts\python scripts\actualizar.py --dias 7 --cobertura   # + deforestación/recuperación (~13 min)
.venv\Scripts\python scripts\actualizar.py --forzar               # ignora la caché
```

| Opción | Significado |
|---|---|
| `--dias N` | Días de focos de calor (1–30). Por defecto, 7 |
| `--cobertura` | Incluye el análisis de pérdida y recuperación de las 11 provincias |
| `--forzar` | Vuelve a consultar todo aunque haya datos en caché |

Muestra en pantalla el nivel de alerta de cada provincia y la lista de alertas, y guarda los archivos en `salidas\AAAAMMDD_HHMM\` (sección 7).

### 6.2 Programar la actualización diaria (Windows)

```powershell
schtasks /Create /SC DAILY /ST 06:00 /TN "MonitoreoForestalHuanuco" /TR "C:\Users\HP\PycharmProjects\monitoreo-forestal-huanuco\.venv\Scripts\python.exe C:\Users\HP\PycharmProjects\monitoreo-forestal-huanuco\scripts\actualizar.py --dias 7 --cobertura"
```

El programa encuentra sus carpetas por sí mismo, así que no importa el directorio desde el que se lance. Para eliminar la tarea: `schtasks /Delete /TN "MonitoreoForestalHuanuco"`.

Cada corrida se guarda además en la base de datos `salidas\monitoreo.sqlite` (historial de alertas).

### 6.2.1 Copias de seguridad

```powershell
.venv\Scripts\python scripts\respaldo.py                        # crea y verifica un respaldo
.venv\Scripts\python scripts\respaldo.py --destino D:\Respaldos   # además lo copia a otro disco o USB
.venv\Scripts\python scripts\respaldo.py --verificar            # solo comprueba el último respaldo
```

Crea `respaldos\respaldo_AAAAMMDD_HHMM.zip` con la base de datos (copia consistente aunque el tablero esté abierto), toda la carpeta `salidas\` (incluidas las interpretaciones hechas a mano), `data\` y `.env.example`. Después **verifica la restauración**: extrae el ZIP en una carpeta temporal, comprueba la integridad de la base (`PRAGMA integrity_check`), cuenta corridas y alertas y lee cada CSV. Conserva los últimos 14 respaldos (`--conservar N` para cambiarlo). Para proteger los datos ante la pérdida del equipo, usar `--destino` con un disco externo o una carpeta sincronizada en la nube.

Respaldo diario automático, 30 minutos después de la actualización:

```powershell
schtasks /Create /SC DAILY /ST 06:30 /TN "MonitoreoForestalHuanucoRespaldo" /TR "C:\Users\HP\PycharmProjects\monitoreo-forestal-huanuco\.venv\Scripts\python.exe C:\Users\HP\PycharmProjects\monitoreo-forestal-huanuco\scripts\respaldo.py"
```

**Restaurar:** descomprimir el ZIP dentro de la carpeta del proyecto (sobrescribe `salidas\` y `data\`).

### 6.3 Validar los resultados

```powershell
.venv\Scripts\python scripts\validar.py
```

Requiere una corrida previa con `--cobertura` del mismo día, porque reutiliza esas imágenes. Genera métricas, pruebas de sensibilidad y láminas de imágenes antes/después de zonas tomadas al azar en `salidas\validacion\`. La interpretación de las láminas es manual y se anota en `salidas\validacion\interpretacion_visual.csv` (sección 11.13).

### 6.4 Generar el informe técnico

```powershell
.venv\Scripts\python scripts\informe.py
```

Crea `salidas\informe\Informe_monitoreo_forestal_Huanuco_AAAAMMDD.docx` con los resultados de la última corrida y de la validación.

### 6.4.1 Instalar en otro servidor (Linux, sin Docker)

1. En la computadora actual: `.venv\Scripts\python scripts\empaquetar_servidor.py`. Crea en Descargas un ZIP (~160 MB) con código, datos, resultados, base de datos, caché y `.env` (contiene credenciales: no compartirlo).
2. Copiar el ZIP al servidor: `scp "$env:USERPROFILE\Downloads\monitoreo-huanuco-servidor_*.zip" usuario@SERVIDOR:/tmp/`
3. En el servidor: `cd /tmp && unzip -q monitoreo-huanuco-servidor_*.zip -d monitoreo && cd monitoreo && sudo bash deploy/instalar.sh`
4. El instalador copia todo a `/opt/monitoreo-huanuco`, crea el entorno de Python con las versiones exactas (`requirements-lock.txt`), registra el servicio `monitoreo-huanuco` (Streamlit en `127.0.0.1:8501`, ruta `/carpeta`), programa en cron la actualización (06:00) y el respaldo (06:30) y deja el bloque de nginx en `/etc/nginx/snippets/monitoreo-huanuco.conf`.
5. Agregar `include snippets/monitoreo-huanuco.conf;` dentro del bloque `server { ... }` del sitio y ejecutar `sudo nginx -t && sudo systemctl reload nginx`. El tablero queda en `http://SERVIDOR/carpeta/`.

Comandos útiles en el servidor: `systemctl status monitoreo-huanuco`, `journalctl -u monitoreo-huanuco -n 50`, `tail -n 50 /opt/monitoreo-huanuco/logs/actualizar.log`. Las rutas de las corridas guardadas en la base de datos se resuelven por nombre dentro de `salidas/`, así que el historial funciona aunque venga de Windows. Si el servidor usa Apache en lugar de nginx: `ProxyPass /carpeta/ http://127.0.0.1:8501/carpeta/` más las reglas de WebSocket (`mod_proxy_wstunnel`).

### 6.5 Regenerar este manual en Word

```powershell
.venv\Scripts\python docs\generar_docx.py
```

## 7. Archivos de salida

Cada corrida de `actualizar.py` crea una carpeta `salidas\AAAAMMDD_HHMM\` y registra la corrida en la base de datos `salidas\monitoreo.sqlite` (tablas `corridas`, `estado_fuentes`, `alertas` con su evidencia, `cobertura` y `zonas_perdida`). La carpeta contiene:

**`focos_calor.csv`** — un registro por detección de foco de calor

| Columna | Descripción | Unidad |
|---|---|---|
| latitud, longitud | Centro del píxel detectado | grados (WGS84) |
| fecha, hora | Fecha y hora de la pasada del satélite | UTC |
| fuente | Producto FIRMS (p. ej., `VIIRS_SNPP_NRT`) | — |
| satelite | Satélite según FIRMS (N, N20, N21, Terra, Aqua) | — |
| confianza | baja / nominal / alta (normalizada, ver 12.2) | — |
| frp | Potencia radiativa del fuego | MW |
| brillo_k | Temperatura de brillo (VIIRS I4 o MODIS canal 21) | K |
| dia_noche | día / noche | — |
| provincia | Provincia que contiene el foco | — |
| evento | Número de evento DBSCAN; −1 = foco aislado | — |

**`eventos_incendio.csv`** — un registro por evento de incendio

| Columna | Descripción |
|---|---|
| evento | Identificador del grupo |
| provincia | Provincia más frecuente entre sus focos |
| focos | Número de detecciones |
| frp_total_mw, frp_max_mw | FRP sumado y máximo (MW) |
| latitud, longitud | Centroide (promedio de los focos) |
| inicio, ultimo, dias_activo | Primera y última fecha, y días entre ambas (inclusive) |
| confianza_alta | Detecciones con confianza alta |
| severidad | alta / media / baja (ver 12.3) |

**`ndvi_mensual.csv`** — desde, hasta, media (NDVI medio), desv (desviación estándar), pct_valido (% de píxeles despejados), provincia.

**`aire_semanal.csv`** — las mismas columnas más `contaminante`. La media está en µmol/m² (NO₂) o mmol/m² (CO).

**`alertas.csv`** — provincia, tipo (incendio, deforestación, vegetación, aire), nivel (alta, media, baja), mensaje y valor numérico que originó la alerta.

**`cambio_cobertura.csv`** (solo con `--cobertura`) — provincia, perdida_ha, recuperacion_ha, cobertura_pct (área observable %), res_m (resolución aproximada).

**`resumen.json`** — fecha de generación, totales, nivel por provincia, lista de alertas y errores.

## 8. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| «Faltan credenciales en el archivo .env» | `.env` no existe o tiene variables vacías | Crear `.env` a partir de `.env.example` (sección 4) |
| «Autenticación fallida (401)» de Copernicus | Secreto incorrecto o cliente OAuth caducado | Crear un nuevo cliente OAuth y actualizar `.env` |
| «FIRMS … Invalid MAP_KEY» | Clave errónea | Revisar `FIRMS_MAP_KEY` |
| «FIRMS … Invalid day range» | La API cambió el máximo de días por consulta | Ajustar `MAX_DIAS_CONSULTA` en `firms.py` |
| Errores 429 o lentitud extrema | Límite de peticiones o cuota de Copernicus agotada | Esperar; el cliente reintenta solo. Revisar la cuota en el panel de Copernicus |
| Lista «⚠ consultas con error» en el tablero | Falló una provincia concreta; el resto sigue funcionando | Leer el mensaje; pulsar «Actualizar» más tarde |
| La primera carga tarda varios minutos | Sentinel-5P tarda de 15 a 50 s por consulta en el servidor | Ejecutar antes `actualizar.py`; los datos quedan en caché 24 h |
| Datos que parecen viejos | Caché vigente | Botón «Actualizar», opción `--forzar` o borrar la carpeta `.cache` |
| «Área observable» muy baja | Nubosidad persistente | Aumentar la duración de los periodos a 120 o 180 días |
| «Port 8501 is already in use» | Otro tablero abierto | Cerrar el otro o usar `--server.port 8600` |
| `validar.py` tarda mucho | La caché del análisis de cobertura no es del mismo día | Ejecutar antes `actualizar.py --cobertura` el mismo día |

---

# Parte II — Especificaciones técnicas

## 9. Arquitectura y flujo de datos

```text
                    ┌──────────────────────────── Servicios externos ────────────────────────────┐
                    │  NASA FIRMS (CSV)        Copernicus Data Space (Sentinel Hub)              │
                    │  /api/area/csv           OAuth2 token · Statistical API · Process API      │
                    └──────────┬──────────────────────────────┬──────────────────────────────────┘
                               │                              │
                        firms.py                       copernicus.py (cliente HTTP, token, reintentos)
                   (descarga, normaliza,                      │
                    DBSCAN → eventos)                  indicadores.py
                               │                 (NDVI mensual, cambio de cobertura,
                               │                  color real, NO₂/CO semanal, z-score)
                               │                              │
              geo.py (provincias, asignación, áreas) ── cache.py (disco, TTL) ── config.py (umbrales)
                               │                              │
                               └──────────────┬───────────────┘
                                          monitor.py
                              (orquesta 11 provincias en paralelo)
                                              │
                                          alertas.py
                                   (reglas → nivel por provincia)
                                              │
                 ┌────────────────────────────┼─────────────────────────────┐
              app.py                  scripts/actualizar.py        scripts/validar.py → scripts/informe.py
        (tablero Streamlit)          (CSV/JSON en salidas/)        (métricas, láminas)   (informe Word)
```

**Principios de diseño**

- **Procesamiento en la nube:** las imágenes no se descargan completas. Copernicus calcula NDVI, medianas y estadísticas en su servidor y devuelve solo el resultado (una tabla o una imagen pequeña).
- **Una provincia a la vez:** cada consulta usa la geometría exacta de la provincia, de modo que los píxeles de fuera no se cuentan.
- **Tolerancia a fallos:** si falla una provincia o un sensor, se registra el error y el resto continúa.
- **Caché en disco:** ninguna consulta se repite mientras su resultado esté vigente.
- **Configuración centralizada:** todos los umbrales están en `config.py`.

## 10. Estructura de directorios

```text
monitoreo-forestal-huanuco/
├── app.py                         Tablero web (Streamlit)
├── requirements.txt               Dependencias
├── README.md                      Guía rápida
├── .env / .env.example            Credenciales (real / plantilla)
├── .gitignore                     Excluye .env, .venv, .cache, salidas
├── data/
│   └── provincias_huanuco.geojson Límites de las 11 provincias
├── src/huanuco_monitor/           Paquete principal
│   ├── __init__.py                Versión
│   ├── config.py                  Credenciales, rutas, endpoints, umbrales
│   ├── cache.py                   Caché en disco con vencimiento
│   ├── geo.py                     Provincias y utilidades geográficas
│   ├── copernicus.py              Cliente de Copernicus Data Space
│   ├── firms.py                   Focos de calor y eventos de incendio
│   ├── indicadores.py             NDVI, cambio de cobertura, aire
│   ├── referencias.py             Capas oficiales MINAM (bosque, pérdida, alertas)
│   ├── alertas.py                 Reglas de alerta
│   ├── monitor.py                 Orquestador (fuentes independientes con respaldo)
│   └── almacen.py                 Base de datos SQLite: corridas, alertas, zonas
├── scripts/
│   ├── actualizar.py              Corrida completa y exportación
│   ├── validar.py                 Validación de resultados
│   ├── comparar_mascara.py        Compara máscaras de nubes sobre la misma muestra
│   ├── validar_minam.py           Validación independiente con datos oficiales MINAM
│   ├── informe.py                 Informe técnico en Word
│   ├── laminas_revision.py        Láminas sin nubes para la revisión humana
│   ├── material_innobest.py       Documento de resultados para INNOBEST 2026
│   └── respaldo.py                Copias de seguridad verificadas
├── docs/
│   ├── MANUAL_TECNICO.md          Este manual
│   └── generar_docx.py            Convierte este manual a Word
├── .cache/                        (generada) resultados de consultas
├── .venv/                         (generada) entorno de Python
└── salidas/                       (generada) corridas, validación, informe
```

## 11. Descripción de cada archivo

### 11.1 `src/huanuco_monitor/config.py` — configuración central

**Propósito:** reúne en un solo lugar todo lo que puede cambiar sin tocar la lógica.

- Carga `.env` con `python-dotenv` y expone `SH_CLIENT_ID`, `SH_CLIENT_SECRET` y `FIRMS_MAP_KEY`.
- Define las rutas `ROOT`, `DATA_DIR`, `CACHE_DIR`, `SALIDAS_DIR` y `PROVINCIAS_GEOJSON`, calculadas a partir de la ubicación del archivo; por eso el sistema funciona desde cualquier directorio.
- Define los endpoints de Copernicus (token, Statistical API, Process API) y de FIRMS, y el sistema de referencia `CRS84` (longitud/latitud WGS84).
- `FIRMS_FUENTES`: los cuatro productos de FIRMS y su nombre legible.
- Umbrales de análisis y de alerta (tabla completa en la sección 14) y tiempos de vida de la caché.
- `credenciales_faltantes()`: devuelve la lista de credenciales vacías; la usan el tablero y `actualizar.py` para detenerse con un mensaje claro.

### 11.2 `src/huanuco_monitor/cache.py` — caché en disco

**Función:** `memo(clave, ttl, calcular, forzar=False)`.

1. Convierte `clave` (cualquier estructura: tupla, fechas, texto) a JSON ordenado y calcula su hash SHA-256; los primeros 24 caracteres son el nombre del archivo `.cache/<hash>.pkl`.
2. Si el archivo existe, su antigüedad (fecha de modificación) es menor que `ttl` segundos y no se pide `forzar`, devuelve el contenido guardado.
3. Si no, ejecuta `calcular()`, guarda el resultado con `pickle` y lo devuelve.

Se guardan respuestas ya procesadas: tablas de pandas e imágenes PNG en bytes. La caché solo contiene datos generados por el propio sistema; no se debe copiar en ella contenido de terceros.

### 11.3 `src/huanuco_monitor/geo.py` — provincias y geografía

- **`Provincia`** (clase inmutable): `nombre`, `geometria` (Shapely), y las propiedades `bbox` (límites mín./máx.), `geojson` (para enviarlo a las API) y `area_km2`.
- **`provincias()`**: lee `data/provincias_huanuco.geojson`, repara geometrías inválidas con `make_valid` y devuelve un diccionario ordenado por nombre. Se carga una sola vez por proceso (`lru_cache`).
- **`region()`**: unión de las 11 provincias. **`bbox_region(margen)`**: su rectángulo envolvente con un margen de 0,02°; se usa para pedir los focos a FIRMS.
- **`asignar_provincia(lon, lat)`**: para cada punto devuelve la provincia que lo contiene (vectorizado con `shapely.contains_xy`) o `None` si cae fuera del departamento.
- **`area_km2(geom)`**: área aproximada (fórmula en 12.9).
- **`tamano_pixel_m(res_grados, lat)`**: convierte el tamaño de un píxel de grados a metros (12.6).

### 11.4 `src/huanuco_monitor/copernicus.py` — cliente de Copernicus Data Space

**Clase `ClienteCopernicus`**

- **Autenticación OAuth2** (*client credentials*): pide un token a `CDSE_TOKEN_URL` con el ID y el secreto. Lo guarda junto con su hora de expiración y lo renueva automáticamente 60 s antes de que venza. Un candado (`threading.Lock`) evita pedir varios tokens a la vez cuando se consultan provincias en paralelo.
- **`estadisticas(payload)`**: envía una petición a la *Statistical API* y devuelve JSON (medias, desviaciones y recuentos por intervalo de tiempo).
- **`procesar(payload, accept)`**: envía una petición a la *Process API* y devuelve la imagen (PNG) en bytes.
- **Reintentos:** ante un error 429 (demasiadas peticiones) o 5xx (error del servidor), espera lo que indique la cabecera `Retry-After` o 2, 4, 8 y 16 s, hasta 4 intentos. Otros errores lanzan `ErrorCopernicus` con el código y el mensaje del servidor.
- Tiempo máximo por petición: 180 s.

### 11.5 `src/huanuco_monitor/firms.py` — focos de calor e incendios

| Función | Qué hace |
|---|---|
| `_descargar(fuente, dias, inicio, bbox)` | Llama a `…/api/area/csv/{clave}/{fuente}/{O,S,E,N}/{dias}/{fecha_inicio}`. Si la respuesta no es un CSV, lanza un error con el mensaje de FIRMS. Renombra las columnas al español y normaliza la confianza y la hora |
| `_confianza(df)` | Unifica la confianza de VIIRS (letras) y MODIS (0–100) (12.2) |
| `_ventanas(dias, hoy)` | Divide el periodo pedido en tramos de 5 días como máximo, el límite de la API |
| `focos_de_calor(dias, fuentes, forzar)` | Descarga cada sensor y cada tramo (con caché), une los resultados, elimina duplicados exactos, asigna provincia y descarta los focos fuera de Huánuco |
| `agrupar_eventos(focos)` | Agrupa los focos en eventos con DBSCAN, resume cada evento y calcula su severidad (12.3) |

Caché: los tramos que terminan en los últimos 2 días se renuevan cada 3 horas (FIRMS sigue agregando datos casi en tiempo real); los tramos más antiguos se guardan 7 días.

### 11.6 `src/huanuco_monitor/indicadores.py` — indicadores satelitales

**Evalscripts** (programas en JavaScript que Copernicus ejecuta en cada píxel):

| Constante | Uso |
|---|---|
| `EVAL_NDVI_ESTADISTICA` | Calcula el NDVI por píxel y marca como válidos solo los píxeles despejados según la clasificación SCL |
| `EVAL_CAMBIO` | Para cada píxel junta todas las observaciones de los dos periodos, calcula la mediana del NDVI despejado de cada uno y cuántas observaciones válidas hubo; lo codifica en una imagen PNG de 3 bandas (12.5) |
| `EVAL_COLOR_REAL` | Imagen en color natural (rojo, verde y azul ×2,8) con transparencia fuera de la provincia |

**Funciones y clases**

| Elemento | Qué hace |
|---|---|
| `serie_ndvi(cliente, provincia, meses=NDVI_MESES)` | Statistical API: NDVI medio cada 30 días a ~220 m (0,002°). Anula los meses con menos del 5 % de píxeles válidos |
| `cambio_cobertura(cliente, provincia, antes, despues, max_px=1400)` | Process API: imagen del cambio; la decodifica y devuelve un objeto `CambioCobertura` |
| `CambioCobertura` | Guarda los NDVI de antes y después, la máscara de la provincia, el número de observaciones y el tamaño del píxel. Calcula las máscaras `perdida` y `recuperacion`, las hectáreas, el `%` observable, las zonas prioritarias (`focos_cambio`) y la capa de colores para el mapa (`imagen_rgba`) |
| `_sin_aislados(mascara)` | Elimina los píxeles marcados que tienen menos de 3 vecinos también marcados |
| `periodos_por_defecto(dias=90)` | Periodo reciente y el mismo periodo del año anterior |
| `imagen_color_real(…)` | Mosaico con la escena menos nublada de los últimos 60 días, para mostrar de fondo |
| `serie_aire(cliente, provincia, contaminante, dias=120)` | Statistical API sobre Sentinel-5P: media semanal a 0,05° (~5,5 km). Anula las semanas con menos del 20 % de píxeles válidos y convierte las unidades |
| `anomalia_z(serie)` | Puntaje z del último valor frente a los anteriores (12.8) |
| `CONTAMINANTES` | Nombre, unidad y factor de conversión de NO₂ y CO |

### 11.7 `src/huanuco_monitor/alertas.py` — reglas de alerta

- `Alerta` (clase): provincia, tipo, nivel, mensaje, valor.
- `alertas_incendio`, `alertas_deforestacion`, `alertas_vegetacion` y `alertas_aire` aplican las reglas de la sección 13.
- `nivel_por_provincia`: el nivel de una provincia es el más alto de sus alertas.
- `tabla`: convierte la lista de alertas en una tabla ordenada por gravedad y por provincia.

### 11.8 `src/huanuco_monitor/monitor.py` — orquestador

**`generar_reporte(dias_focos, fuentes_firms, con_cambio_cobertura, forzar, cliente)`** ejecuta en orden:

1. Focos FIRMS y agrupación en eventos.
2. NDVI mensual de las 11 provincias, en paralelo (6 hilos).
3. NO₂ y CO de las 11 provincias, en paralelo, y cálculo de su anomalía z.
4. Si se pide, cambio de cobertura de las 11 provincias, en paralelo.
5. Aplicación de todas las reglas de alerta.

Devuelve un objeto `Reporte` con todas las tablas, los cambios, las alertas y los errores. `_en_paralelo` captura el error de cada provincia y lo agrega a `errores` sin detener el resto.

### 11.9 `src/huanuco_monitor/__init__.py`

Declara el paquete y su versión (`__version__ = "1.0.0"`).

### 11.10 `app.py` — tablero web

- Verifica las credenciales al iniciar.
- **Caché de Streamlit** (en memoria, además de la caché en disco): `reporte()` dura 1 hora y depende de los días, los sensores y el contador del botón «Actualizar»; `cambio()` y `color_real()` duran 24 horas.
- **Mapas** (Folium/Leaflet): `mapa_base` (fondo Esri u OSM, pantalla completa, escala), `capa_provincias` (relleno por nivel de alerta y tooltip), `capa_focos` (focos y eventos), `leyenda`, `mostrar_mapa`.
- **Gráficos** (Plotly): `figura_linea` (series temporales con huecos donde no hay dato) y `figura_barras` (barras horizontales ordenadas).
- **Interfaz:** barra lateral y cinco secciones (sección 5). En la de deforestación, el análisis solo se ejecuta al pulsar «Analizar» y se recuerda la última combinación de provincia y periodo en `st.session_state`.
- **Paleta:** los colores de estado (rojo, naranja, amarillo, gris) se reservan para los niveles de alerta y siempre van acompañados de un símbolo (▲) y una etiqueta, de modo que el nivel no depende solo del color. Las series de datos usan un único azul.

### 11.11 `scripts/actualizar.py` — corrida completa

Lee las opciones `--dias`, `--cobertura` y `--forzar`, llama a `monitor.generar_reporte`, guarda los CSV y el JSON de la sección 7 en `salidas/AAAAMMDD_HHMM/` e imprime el resumen. Termina con error si faltan credenciales.

### 11.12 `scripts/validar.py` — validación

1. **Focos de calor:** totales por sensor, confianza y día/noche, y focos únicos (mismo día y misma celda de unos 400 m).
2. **Cambio de cobertura:** resumen por provincia, pérdida *extrapolada* (pérdida observada ÷ fracción observable) y **sensibilidad**: recalcula la pérdida total con 8 combinaciones de umbrales sobre las mismas imágenes en caché.
3. **Coincidencia con incendios:** distancia de cada zona de pérdida al foco VIIRS más cercano en los mismos 90 días, comparada con 3 000 puntos al azar dentro de las provincias (12.10).
4. **Láminas visuales:** 20 zonas de pérdida y 10 de recuperación elegidas al azar (semilla 42), más los 5 eventos de incendio de mayor FRP. Para cada una descarga recortes Sentinel-2 de unos 1,3 km (antes, después y después con la detección superpuesta) o, para incendios, en falso color SWIR, que resalta las quemas.
5. **NDVI y aire:** porcentaje de datos válidos, rangos, percentiles y valores negativos.

Salida en `salidas/validacion/`: `metricas.json`, `cambio_cobertura_resumen.csv`, `sensibilidad_umbrales.csv`, `zonas_perdida.csv`, `muestra_perdida.csv`, `muestra_recuperacion.csv` y las láminas `lamina_*.png`.

### 11.13 `salidas/validacion/interpretacion_visual.csv` — fotointerpretación

Se escribe a mano después de revisar las láminas. Columnas: `id` (P01…, R01…, E…), `tipo` (perdida, recuperacion, incendio), `categoria` (confirmada, falso_nube, falso_sombra, falso_rio, cambio_agricola, sin_cambio_visible, indeterminado) y `observacion`. Si cambian la semilla o los datos, la muestra cambia y este archivo debe rehacerse.

### 11.14 `scripts/informe.py` — informe técnico

Lee la última corrida y la validación; calcula la precisión con su intervalo de Wilson, la precisión ponderada por área, la estabilidad del orden de las provincias (correlación de Spearman) y la pérdida corregida; dibuja las figuras con Matplotlib y arma el documento Word con python-docx.

### 11.15 `data/provincias_huanuco.geojson`

FeatureCollection con 11 polígonos y la propiedad `provincia`. Origen: geoBoundaries, conjunto gbOpen, Perú, nivel ADM2, versión simplificada (versión 9469f09). Al extraerlo se corrigió una codificación defectuosa del nombre «Marañón» y se pusieron las tildes oficiales (Huamalíes, Huánuco, Marañón).

### 11.16 Otros archivos

| Archivo | Contenido |
|---|---|
| `requirements.txt` | Dependencias mínimas |
| `.env.example` | Plantilla de credenciales sin valores |
| `.gitignore` | Excluye `.env`, `.venv/`, `.cache/`, `salidas/` y `__pycache__/` |
| `README.md` | Guía rápida de instalación y uso |
| `docs/generar_docx.py` | Convierte este manual (Markdown) a Word |


### 11.17 `scripts/comparar_mascara.py` — comparación de máscaras de nubes

Recalcula el cambio de cobertura con la máscara anterior (v1: solo SCL, incluía agua y nieve) y con la actual (v2: SCL 4–5 + s2cloudless `CLM`/`CLP`) para **los mismos periodos y las mismas zonas** ya interpretadas en `interpretacion_visual.csv`; no sortea una muestra nueva. Una zona «sigue detectada» si la v2 marca ≥ 1 ha en su ventana de inspección (±0,006°). Salida en `salidas/validacion/comparacion_mascara/`: `muestra_v1_v2.csv`, `totales_por_provincia.csv`, `resumen.json` y láminas ANTES | DESPUÉS + v1 | DESPUÉS + v2.

Resultado del 24/10/2026 (periodos 22/07–20/10 de 2025 y de 2026):

| Indicador | v1 (SCL) | v2 (SCL + s2cloudless) |
|---|---|---|
| Zonas de pérdida de la muestra que siguen detectadas | 20 | 10 |
| Pérdidas confirmadas que se conservan | 7 de 7 | 7 de 7 |
| Falsos por nube o sombra que siguen | 9 de 9 | 0 de 9 |
| Cambios agrícolas que siguen | 3 de 3 | 3 de 3 |
| Precisión de pérdida en la muestra | 35 % | 70 % |
| Precisión de recuperación en la muestra | 20 % (2 de 10) | 33 % (2 de 6) |
| Pérdida total, 11 provincias | 9 719 ha | 5 241 ha |
| Recuperación total, 11 provincias | 20 442 ha | 10 371 ha |
| Área observable media | 44,2 % | 42,4 % |

Lectura: la máscara v2 elimina todos los falsos positivos por nubes de la muestra sin perder ninguna pérdida confirmada y casi sin reducir el área observable. Los falsos que quedan son **cambios agrícolas**, que requieren una máscara de bosque (Geobosques). Limitación: la precisión v2 se mide solo sobre zonas que ya detectaba la v1; para una estimación sin sesgo hay que interpretar una muestra nueva sorteada sobre los resultados v2.

### 11.18 `scripts/validar_minam.py` — validación independiente con datos oficiales

Compara tres versiones del detector sobre los mismos periodos (22/07–20/10 de 2025 y de 2026) con una referencia **independiente**: las alertas tempranas de MINAM/PNCB acumuladas en 2026 más la pérdida antrópica 2025 (Landsat, 30 m; otro sensor y otro método que los del sistema). v1 = máscara de nubes SCL; v2 = SCL + s2cloudless; v3 = v2 + máscara de bosque MINAM (sistema actual).

- **Precisión por zona:** % de zonas (celdas de 16 × 16 píxeles con ≥ 1 ha) donde algún píxel detectado toca, con tolerancia de ±1 píxel, una alerta o pérdida oficial.
- **Precisión por píxel** y **azar:** lo mismo por píxel; el azar es la proporción de píxeles de bosque observable que tocan la referencia (lo que coincidiría un detector aleatorio).
- **Sensibilidad ponderada:** % del área de alertas 2026 observables (sin nubes en ambos periodos) que el sistema detecta. También se informa solo para píxeles cubiertos ≥ 50 % por alertas, porque un claro de 30 m dentro de un píxel de ~110 m casi no cambia su NDVI.

Resultado del 24/10/2026:

| Versión | Pérdida (ha) | Zonas | Precisión por zona | Precisión por píxel | Azar | Sensibilidad ponderada | Sensibilidad (alertas ≥ 50 % del píxel) |
|---|---|---|---|---|---|---|---|
| v1 SCL | 9 719 | 1 355 | 40 % | 24 % | 11 % | 26 % | 37 % |
| v2 + s2cloudless | 5 241 | 779 | 60 % | 45 % | 11 % | 24 % | 34 % |
| v3 + bosque MINAM (umbral 0,45) | 1 678 | 245 | 97 % | 98 % | 11 % | 19 % | 28 % |
| **v3 + bosque MINAM, umbral 0,55 (actual)** | **2 858** | **400** | **95 %** | **96 %** | 11 % | 28 % | 40 % |

Área de alertas MINAM 2026 observable en el periodo: ~10 400 ha.

**Umbrales (v3, mismas imágenes):** el sistema está calibrado para la precisión. Relajar `NDVI_MAX_TRAS_PERDIDA` a 0,55 sube la sensibilidad ponderada a 28 % (40 % en alertas grandes) con precisión de 95 %; la combinación caída 0,20 + tras ≤ 0,55 + 2 vecinos llega a 35 % (50 %) con 87 % de precisión. Detalle en `umbrales_precision_sensibilidad.csv`. Elegir umbrales mirando la misma referencia con la que se evalúa sobreestima el resultado: cualquier cambio debe confirmarse con la muestra visual nueva.

**Cambio de umbral (24/10/2026):** se adoptó `NDVI_MAX_TRAS_PERDIDA = 0,55`. Con 0,45 se exigía suelo casi desnudo y se perdían los claros abiertos a inicios de 2026 que en julio–octubre ya tenían maleza o cultivo. Como el umbral se eligió mirando a MINAM, el cambio se verifica además con una muestra visual propia (muestra M, abajo).

**Muestra anterior (11.13) con v3:** se conservan 5 de 7 pérdidas confirmadas y se eliminan los 13 falsos (9 nubes, 3 agrícolas, 1 sin cambio): precisión 100 % en la muestra. Las 2 pérdidas reales eliminadas (P04, P09) están en el borde del bosque, en píxeles que MINAM ya no cuenta como bosque (P09 sobre pérdida anterior a 2024, posible bosque secundario); MINAM tiene alertas en esa misma ventana. Dar 1 píxel de tolerancia a la máscara recupera P04 pero también una parcela agrícola (P17) y baja la precisión a 91 %, por lo que no se adoptó.

**Muestras para fotointerpretación** (cada una se sortea una sola vez; si su CSV existe, el script la reutiliza y nunca sobrescribe la interpretación):

- **N** (`muestra_v3.csv`, semilla 2026): 30 zonas del sistema con el umbral 0,45. 29 de 30 coinciden con MINAM. Láminas `lamina_v3_*.png`; interpretación en `interpretacion_visual_v3.csv`.
- **M** (`muestra_umbral_055.csv`, semilla 2027): 30 zonas sorteadas entre las 298 que **solo aparecen al subir el umbral a 0,55**; en magenta se muestran solo los píxeles agregados. 30 de 30 coinciden con MINAM. Láminas `lamina_umbral_055_*.png`; interpretación en `interpretacion_visual_umbral_055.csv`.

Las dos juntas permiten estimar la precisión del sistema actual por fotointerpretación, independiente de MINAM.

**Resultado de la interpretación (24/10/2026) — asistida por IA, preliminar:** las dos muestras se interpretaron con una herramienta de inteligencia artificial sobre las láminas, sin revisión de un especialista ni verificación de campo.

| Muestra | Confirmadas | Indeterminadas | Falsos positivos | Precisión (indeterminadas = error) | Precisión (solo determinables) |
|---|---|---|---|---|---|
| N (umbral 0,45) | 8 | 22 | 0 | 27 % (IC 95 %: 14–44 %) | 8 de 8 (IC 95 %: 68–100 %) |
| M (agregadas por 0,55) | 13 | 17 | 0 | 43 % (IC 95 %: 27–61 %) | 13 de 13 (IC 95 %: 77–100 %) |

No se identificó ningún falso positivo en 60 zonas, pero la mayoría quedó indeterminada: 16 por nubes, sombras o artefactos en la lámina (que muestra una sola escena, mientras el sistema usa la mediana de todas las pasadas despejadas) y el resto por paisajes con claros previos donde no se distingue la fecha del cambio. Fuera de Puerto Inca ninguna zona pudo confirmarse (0 de 12). Por eso **la evidencia principal de precisión es la comparación con MINAM** (95 % de coincidencia); esta interpretación es complementaria y debe presentarse como preliminar.

**Limitaciones:** (a) MINAM mapea el bosque primario húmedo y el seco; la tala de bosque secundario (purmas) y de bosques andinos no mapeados queda fuera: Ambo, Lauricocha, Yarowilca y Dos de Mayo casi no tienen bosque MINAM y su pérdida pasa a 0. (b) La referencia no tiene fechas dentro de 2026; las pérdidas de las últimas semanas del periodo influyen poco en la mediana de 90 días. (c) Las alertas MINAM también tienen errores; la coincidencia mide acuerdo con la fuente oficial, no verdad de campo.

## 12. Cómo calcula: algoritmos y fórmulas

### 12.1 Asignación de focos a provincias

FIRMS se consulta con el rectángulo que envuelve todo el departamento. Cada foco (lon, lat) se prueba contra el polígono de cada provincia con `contains_xy` y se le asigna la primera que lo contiene; los que no caen en ninguna se descartan. Luego se eliminan los registros idénticos en latitud, longitud, fecha, hora y fuente.

### 12.2 Normalización de la confianza

| Sensor | Valor original | Valor normalizado |
|---|---|---|
| VIIRS | `l` / `n` / `h` | baja / nominal / alta |
| MODIS | 0–30 | baja |
| MODIS | 31–80 | nominal |
| MODIS | 81–100 | alta |

### 12.3 Eventos de incendio (DBSCAN) y severidad

DBSCAN es un algoritmo de agrupamiento no supervisado: forma grupos con los puntos que tienen suficientes vecinos cercanos y marca como aislados al resto.

- Distancia: **haversine** (distancia sobre la esfera terrestre). Las coordenadas se pasan a radianes y el radio de búsqueda es `eps = 1,5 km / 6 371 km` radianes.
- `min_samples = 3`: un foco es «núcleo» si tiene al menos 3 focos (contándose a sí mismo) a 1,5 km o menos. Los focos alcanzables desde un núcleo forman el mismo evento; los demás reciben `evento = −1`.
- La agrupación es **solo espacial**: focos de días distintos en el mismo lugar pertenecen al mismo evento (se interpreta como un incendio persistente).

Por evento se calculan: número de focos, FRP total y máximo, centroide (promedio de las coordenadas), primera y última fecha, días activo = (última − primera) + 1, y provincia (la más frecuente).

**Severidad del evento:**

| Severidad | Condición (la primera que se cumpla) |
|---|---|
| alta | focos ≥ 15 **o** FRP total ≥ 300 MW |
| media | focos ≥ 6 **o** días activo ≥ 3 |
| baja | resto |

### 12.4 NDVI y máscara de nubes

**NDVI** (índice de vegetación de diferencia normalizada), con las bandas de Sentinel-2 L2A (reflectancia de superficie):

```text
NDVI = (B08 − B04) / (B08 + B04 + 0,000001)
B08 = infrarrojo cercano (842 nm), B04 = rojo (665 nm)
```

El NDVI va de −1 a 1. La vegetación sana refleja mucho infrarrojo y absorbe el rojo, por eso tiene valores altos.

**Píxel válido** = `dataMask = 1`, clase SCL en {4 vegetación, 5 suelo desnudo}, máscara de nubes s2cloudless `CLM = 0` y probabilidad de nube `CLP < PROB_NUBE_MAX × 255` (0,20 → 51). Se excluyen: 0 sin dato, 1 saturado, 2 sombra oscura o topográfica, 3 sombra de nube, 6 agua (playas y barras de río que cambian con el caudal), 7 sin clasificar, 8 y 9 nube de probabilidad media y alta, 10 cirro y 11 nieve.

La máscara s2cloudless (`CLM`, `CLP`) es independiente de la clasificación SCL de Sen2Cor y `CLM` ya incluye un margen alrededor de cada nube, donde SCL suele dejar bordes y nubes finas sin marcar. Se incorporó el 24/10/2026 porque la validación visual mostró que 9 de 20 zonas de pérdida eran nubes, bordes de nube o sombras (sección 11.17).

**Serie mensual (`serie_ndvi`):** para cada intervalo de 30 días, el evalscript (mosaico `ORBIT`) calcula en cada píxel la **mediana del NDVI de todas las pasadas despejadas** del intervalo; la Statistical API devuelve la media y la desviación estándar de esas medianas en la provincia, a 0,002° (~220 m). Hasta el 24/10/2026 se usaba el mosaico simple, que toma solo la escena más reciente de cada píxel aunque esté nublada: en Puerto Inca el área observada era de 4–25 % por mes y pasó a 40–46 %; en el conjunto de provincias, los meses válidos subieron al 96,8 %. La API también devuelve `sampleCount` y `noDataCount`:

```text
pct_valido = 100 × (sampleCount − noDataCount) / sampleCount
si pct_valido < 5 % → media = sin dato
```

### 12.5 Cambio de cobertura (pérdida y recuperación)

**Periodos:** «después» = los últimos D días (90 por defecto); «antes» = las mismas fechas un año antes. Comparar la misma estación evita confundir la época seca con deforestación.

**Resolución:** `res = máx(ancho_bbox / 1400, alto_bbox / 1400, 0,0003°)`, para que la imagen no supere los 1 400 píxeles por lado. Resulta entre ~33 m (Yarowilca) y ~115 m (Puerto Inca).

**En el servidor (EVAL_CAMBIO), para cada píxel:**

1. Se toman todas las pasadas del satélite de cada periodo (mosaico `ORBIT`) con hasta 80 % de nubes por escena.
2. Se calcula el NDVI solo de las observaciones válidas (12.4).
3. Se toma la **mediana** de cada periodo (es resistente a valores extremos, como restos de nubes), y el número de observaciones válidas n_antes y n_después.
4. Se codifica en PNG de 8 bits:

```text
banda 1 = código(mediana_antes)     banda 2 = código(mediana_después)
código(x) = redondeo((recorte(x, −1, 1) + 1) × 100) + 1    → 1 … 201
código = 255 → sin observación válida;  código = 0 → fuera de la provincia
banda 3 = mín(n_antes, n_después, 254) + 1                → 0 = fuera de la provincia
```

**En Python (decodificación):** `NDVI = (código − 1) / 100 − 1`, con precisión de 0,01; `observaciones = banda3 − 1`.

**Píxel comparable:** dentro de la provincia, con NDVI en ambos periodos y `observaciones ≥ 2`.

**Pérdida (posible tala, quema o desbroce)**, todas las condiciones a la vez:

```text
NDVI_antes ≥ 0,60                      (era bosque o vegetación densa)
NDVI_después − NDVI_antes ≤ −0,25      (caída fuerte)
NDVI_después ≤ 0,55                    (quedó sin dosel: suelo, quema, pasto o rebrote incipiente)
y al menos 3 de sus 8 vecinos cumplen lo mismo (se descartan píxeles aislados)
```

**Máscara de bosque oficial (desde el 24/10/2026):** la pérdida solo se evalúa en píxeles que MINAM clasifica como bosque (bosque húmedo amazónico al 2024 o bosque estacionalmente seco al 2021, ≥ 50 % del píxel). Así se descartan cultivos y pastos que tienen NDVI alto parte del año. Las capas se leen de `gis.bosques.gob.pe` (módulo `referencias.py`) en la misma cuadrícula del análisis: se piden con submuestreo cercano a 30 m y se promedian a cada píxel.

**Recuperación:**

```text
NDVI_antes ≤ 0,45  y  NDVI_después − NDVI_antes ≥ 0,15  y  ≥ 3 vecinos
y el píxel fue bosque según MINAM (bosque actual o pérdida 2001-2024)
```

La última condición excluye cultivos, pastos y orillas de río que nunca fueron bosque.

**Área observable:** `cobertura_pct = 100 × píxeles comparables / píxeles de la provincia`.

### 12.6 Hectáreas por píxel

La imagen cubre exactamente el rectángulo de la provincia (x0, y0, x1, y1) repartido en «ancho × alto» píxeles:

```text
ancho_m = (x1 − x0) / ancho × 111 320 × cos(latitud_central)
alto_m  = (y1 − y0) / alto  × 110 574
ha_pixel = ancho_m × alto_m / 10 000
hectáreas = número de píxeles marcados × ha_pixel
```

111 320 m y 110 574 m son la longitud aproximada de un grado de longitud (en el ecuador) y de latitud. A la latitud de Huánuco (~9,5° S), el error es menor al 1 %.

### 12.7 Zonas prioritarias

`focos_cambio` divide la máscara en bloques de 16 × 16 píxeles. Por cada bloque con al menos 2 ha marcadas (1 ha en la validación), devuelve el centroide de sus píxeles marcados, convertido a latitud y longitud, y las hectáreas. Las zonas se ordenan de mayor a menor superficie.

### 12.8 Calidad del aire y anomalías

- **Datos:** Sentinel-5P TROPOMI L2, producto OFFL (procesamiento consolidado, con unos días de retraso). La banda `NO2` es la columna troposférica y la banda `CO`, la columna total, ambas en mol/m². El servicio aplica su propio filtro de calidad.
- **Agregación:** media semanal (intervalos de 7 días) sobre la provincia a 0,05°; las semanas con menos del 20 % de píxeles válidos se anulan.
- **Unidades:** NO₂ × 10⁶ → µmol/m²; CO × 10³ → mmol/m².
- **Anomalía z** del último valor válido, con al menos 7 semanas válidas:

```text
z = (último − media(anteriores)) / desviación_estándar(anteriores)
```

### 12.9 Área de cada provincia

Las coordenadas se convierten a kilómetros con una proyección equirectangular centrada en el centroide de la provincia (x × 111,320 × cos(latitud_centroide), y × 110,574), y se mide el área del polígono resultante. La diferencia con las áreas oficiales es menor al 5 %.

### 12.10 Cálculos de validación

- **Focos únicos:** focos con la misma fecha y la misma celda de 0,004° (~440 m), redondeando lon/0,004 y lat/0,004.
- **Pérdida extrapolada:** `pérdida_ha / (cobertura_pct / 100)`. Supone que la zona no observada se comporta igual que la observada, por lo que es solo orientativa.
- **Coincidencia con fuego:** para cada zona, distancia haversine al foco VIIRS más cercano de los mismos 90 días (`BallTree`). Se compara el % de zonas a ≤ 1 km y ≤ 2 km con el mismo % para 3 000 puntos aleatorios dentro de las provincias.
- **Precisión:** confirmadas / muestras, con **intervalo de confianza de Wilson** al 95 %:

```text
centro = (p + z²/2n) / (1 + z²/n);   margen = z·√(p(1−p)/n + z²/4n²) / (1 + z²/n);   z = 1,96
```

- **Precisión ponderada por área:** hectáreas confirmadas / hectáreas de la muestra.
- **Estabilidad del orden de provincias:** correlación de Spearman entre los rangos de pérdida por provincia con los umbrales por defecto y con cada variante.
- **Pérdida corregida:** pérdida observada × límites del intervalo de precisión.

## 13. Reglas de alerta

| Tipo | Alta | Media | Baja | Requisito |
|---|---|---|---|---|
| Incendio (por provincia) | ≥ 25 focos **o** FRP ≥ 500 MW **o** algún evento de severidad alta | ≥ 5 focos **o** al menos 1 evento | ≥ 1 foco | — |
| Deforestación | ≥ 50 ha de pérdida | ≥ 10 ha | > 0 ha | Solo con análisis de cobertura; se avisa si el área observable es < 40 % |
| Vegetación | caída ≥ 0,18 | caída ≥ 0,10 | — | caída = NDVI del mismo periodo del año anterior (mediana de los intervalos a ±45 días de esa fecha) − último mes válido; el último mes válido debe tener ≤ 60 días |
| Aire (NO₂ o CO) | z ≥ 3 | z ≥ 2 | — | ≥ 7 semanas válidas |

**Nivel de la provincia** = el más alto de sus alertas; «sin alerta» si no tiene ninguna.

## 14. Parámetros configurables (`config.py`)

| Parámetro | Valor | Efecto de aumentarlo |
|---|---|---|
| `NDVI_BOSQUE` | 0,60 | Solo se considera bosque la vegetación más densa: menos pérdida detectada |
| `CAIDA_NDVI_DEFORESTACION` | 0,25 | Se exigen caídas más fuertes: menos falsos positivos y más omisiones |
| `NDVI_MAX_TRAS_PERDIDA` | 0,55 (0,45 hasta el 24/10/2026) | Se aceptan como pérdida píxeles que conservan algo de vegetación |
| `NDVI_DEGRADADO` | 0,45 | Más áreas candidatas a recuperación |
| `GANANCIA_NDVI_RECUPERACION` | 0,15 | Se exigen rebrotes más fuertes |
| `MIN_OBSERVACIONES` | 2 | Más fiabilidad por píxel y menos área observable |
| `MIN_VECINOS` | 3 | Se eliminan más píxeles sueltos (con 5, la pérdida baja a menos de la mitad) |
| `PROB_NUBE_MAX` | 0,20 | Se aceptan observaciones con más probabilidad de nube: más área observable y más falsos positivos |
| `NDVI_MESES` | 14 | Serie NDVI más larga (más unidades de procesamiento) |
| `CAIDA_NDVI_MEDIO` / `_ALTO` | 0,10 / 0,18 | Menos alertas de vegetación |
| `DBSCAN_EPS_KM` | 1,5 | Eventos más grandes, que unen focos más separados |
| `DBSCAN_MIN_FOCOS` | 3 | Se necesitan más focos para formar un evento |
| `INCENDIO_FOCOS_MEDIO` / `_ALTO` | 5 / 25 | Menos provincias en alerta de incendio |
| `INCENDIO_FRP_ALTO_MW` | 500 | Ídem, según la potencia total |
| `EVENTO_FOCOS_ALTO` / `EVENTO_FRP_ALTO_MW` | 15 / 300 | Menos eventos de severidad alta |
| `DEFORESTACION_HA_MEDIO` / `_ALTO` | 10 / 50 | Menos alertas de deforestación |
| `AIRE_Z_MEDIO` / `_ALTO` | 2 / 3 | Menos alertas de aire |
| `TTL_FIRMS` | 3 h | Datos de incendios menos frescos y menos consultas |
| `TTL_ESTADISTICAS`, `TTL_IMAGENES` | 24 h | Ídem para Sentinel-2 y Sentinel-5P |

Otros parámetros dentro de los módulos: resolución del NDVI mensual (0,002°), resolución del aire (0,05°), máximo de píxeles de la imagen de cambio (1 400), umbral de mes válido (5 %) y de semana válida (20 %), y días por consulta a FIRMS (5).

> Cambiar el evalscript `EVAL_CAMBIO` invalida su caché automáticamente, porque el texto del script forma parte de la clave. Cambiar los umbrales de pérdida o recuperación no requiere volver a descargar nada: se aplican en Python sobre la imagen guardada.

## 15. Servicios externos

| Servicio | Endpoint | Autenticación | Notas |
|---|---|---|---|
| Token Copernicus | `identity.dataspace.copernicus.eu/…/openid-connect/token` | ID y secreto del cliente OAuth | Token de corta duración, renovado automáticamente |
| Statistical API | `sh.dataspace.copernicus.eu/api/v1/statistics` | Bearer token | NDVI mensual y aire semanal |
| Process API | `sh.dataspace.copernicus.eu/api/v1/process` | Bearer token | Imagen de cambio, color real, recortes de validación |
| NASA FIRMS | `firms.modaps.eosdis.nasa.gov/api/area/csv/…` | MAP_KEY en la URL | Máximo 5 días por consulta; límite de 5 000 transacciones cada 10 minutos |
| Geobosques (MINAM / PNCB) | `gis.bosques.gob.pe/server/rest/services/Interoperabilidad/…/MapServer/export` | Ninguna | Bosque 2024, bosque seco 2021, pérdida 2001-2024 y 2025, alertas tempranas 2026; imágenes de hasta 4 096 px por lado (se piden por bloques) |
| Mapa base | `server.arcgisonline.com` (Esri), OpenStreetMap | Ninguna | Solo en el navegador |

**Colecciones usadas:** `sentinel-2-l2a` (bandas B02, B03, B04, B08, SCL, dataMask) y `sentinel-5p-l2` (bandas NO2, CO, dataMask; `timeliness = OFFL`).

**Cuota mensual (importante):** la cuenta gratuita de Copernicus tiene una cuota mensual de *unidades de procesamiento*. Si se agota, Copernicus responde `403 ACCESS_INSUFFICIENT_PROCESSING_UNITS` y no se pueden hacer consultas nuevas hasta que se renueve. El saldo y la fecha de renovación se ven en el panel de la cuenta (https://shapps.dataspace.copernicus.eu/dashboard/). Mientras tanto el sistema sigue funcionando con la caché y con los respaldos de cada fuente (indicados con ⚠ en la barra lateral). NASA FIRMS (incendios) y Geobosques no dependen de esta cuota. El 24/10/2026 la cuota se agotó por el trabajo de desarrollo y validación (recalcular varias veces las 11 provincias); el uso diario normal consume mucho menos.

**Ahorro de cuota:** el NDVI y el cambio de cobertura, las consultas más costosas, terminan su periodo el lunes de la semana en curso (`inicio_semana`) y se guardan 7 días (`TTL_NDVI`, `TTL_IMAGENES`): se recalculan una vez por semana aunque la actualización sea diaria. El aire (consulta liviana) se renueva cada día. Antes de una demostración pública conviene abrir el tablero y analizar las provincias que se mostrarán, para que queden en caché.

**Si Copernicus está saturado o sin conexión:** el tablero espera como máximo 90 s con 2 intentos (las corridas programadas, 180 s con 4 intentos y esperas crecientes). Si no responde, la sección de deforestación muestra el último análisis guardado de esa provincia (hasta 8 semanas atrás) con un aviso de sus fechas; el panorama, los incendios, el NDVI y el aire usan la última corrida guardada o el último dato bueno de cada fuente. Para que los usuarios casi nunca esperen, la corrida programada de las 06:00 calcula cada lunes el análisis de la semana de las 11 provincias; el resto de la semana se sirve desde la caché, compartida entre todos los usuarios del tablero.

**Consumo:** cada consulta a Copernicus gasta *unidades de procesamiento* de la cuota mensual de la cuenta. La más costosa es el análisis de cambio de cobertura (multitemporal, 11 provincias); la caché de 24 h evita repetirlo. El saldo se revisa en el panel de Copernicus.

**Volumen por corrida completa:** FIRMS, 4 sensores × 2 tramos = 8 llamadas para 7 días; Statistical API, 11 (NDVI) + 22 (aire) = 33; Process API, 11 (cambio) más las imágenes de color real que se abran en el tablero.

## 16. Caché

| Dato | Clave (resumida) | Vigencia |
|---|---|---|
| Focos FIRMS | sensor, inicio, días, rectángulo | 3 h (tramos recientes) / 7 días |
| NDVI mensual | provincia, fechas | 24 h |
| Aire semanal | contaminante, provincia, fechas | 24 h |
| Cambio de cobertura | evalscript, provincia, periodos, tamaño | 24 h |
| Color real | provincia, fecha, tamaño | 24 h |
| Recortes de validación | evalscript, rectángulo, periodo | 30 días |

Como las claves incluyen la fecha de hoy, cada día se generan resultados nuevos. Borrar `.cache/` es seguro: solo obliga a volver a consultar.

## 17. Rendimiento (medido el 20/10/2026)

| Operación | Tiempo |
|---|---|
| FIRMS, 4 sensores, 7 días | ~9 s |
| NDVI mensual, 1 provincia | ~4 s |
| NO₂ o CO semanal, 1 provincia | 15–50 s (procesamiento en el servidor de Copernicus) |
| Cambio de cobertura, 1 provincia | 50–80 s |
| Corrida completa con cobertura | ~13 min la primera vez; segundos con caché |
| Tablero con caché vigente | < 5 s por sección |

## 18. Seguridad

- Las credenciales solo se leen de `.env`; no aparecen en el código, los registros ni las salidas.
- La clave de FIRMS viaja en la URL (así lo exige la API). Los errores de conexión se reescriben sin la URL, para que la clave no aparezca en el tablero ni en `resumen.json`.
- Todas las conexiones usan HTTPS.
- Por defecto, Streamlit acepta conexiones de **toda la red local** (muestra una «Network URL»). Para limitarlo al propio equipo: `streamlit run app.py --server.address 127.0.0.1`. Publicarlo en internet requiere autenticación y un servidor con HTTPS.
- La caché usa `pickle`: no se deben copiar en `.cache/` archivos de origen desconocido.

## 19. Fiabilidad y limitaciones conocidas

Resumen de la validación del 20/10/2026 (detalle en `salidas/informe/`):

| Resultado | Fiabilidad | Evidencia |
|---|---|---|
| Focos e incendios | Fiable | 4 de 5 eventos con cicatriz de quema nueva visible |
| Ubicación de posible tala | Parcial | 7 de 20 zonas confirmadas (IC 95 %: 18–57 %); 5 de 5 en Puerto Inca |
| Hectáreas de pérdida | No fiable | Sobrestimadas; muy sensibles a los umbrales (3 785–56 445 ha) |
| Recuperación | No fiable | 2 de 10 muestras correctas |
| NDVI mensual | Fiable con reservas | Valores coherentes; ~17 % de cada provincia observada por mes |
| NO₂ / CO | Fiable con reservas | Valores plausibles; sin estaciones en tierra para contrastar |

**Causas principales de error y mejoras previstas**

1. Nubes y sombras que la clasificación SCL no detecta (45 % de los falsos positivos) → **resuelto el 24/10/2026** con s2cloudless (11.17).
2. Parcelas agrícolas tratadas como bosque → **resuelto el 24/10/2026** con la máscara de bosque MINAM (11.18).
3. Selva alta casi siempre nublada → añadir radar Sentinel-1.
4. Umbrales: el sistema prioriza la precisión; con `NDVI_MAX_TRAS_PERDIDA = 0,55` detecta ~28 % del área de alertas oficiales observables (11.18).

**Actualización del 24/10/2026:** frente a las alertas oficiales de MINAM, el 95 % de las zonas de pérdida coincide (azar: 11 %) y se detecta el 28 % del área de alertas observables (40 % en claros grandes). Ver 11.18.

## 20. Mantenimiento y extensión

**Cambiar un umbral:** editar `config.py` y reiniciar el tablero, o pulsar «Actualizar».

**Agregar un sensor FIRMS:** añadir su código a `FIRMS_FUENTES` (por ejemplo `LANDSAT_NRT`). Si sus columnas son distintas, adaptar `_descargar`.

**Agregar un indicador de Sentinel-2** (por ejemplo, NBR para áreas quemadas):

1. Escribir un evalscript como `EVAL_NDVI_ESTADISTICA` con la nueva fórmula, por ejemplo NBR = (B08 − B12) / (B08 + B12).
2. Crear una función como `serie_ndvi` con su propia clave de caché.
3. Llamarla en `monitor.generar_reporte` y agregar el campo a `Reporte`.
4. Crear la regla en `alertas.py` y mostrarla en `app.py`.

**Agregar otro contaminante de Sentinel-5P:** añadirlo a `CONTAMINANTES` con su banda (por ejemplo `SO2`, `O3` o `HCHO`), unidad y factor; el resto del código lo recorre automáticamente.

**Cambiar el área de estudio:** reemplazar `data/provincias_huanuco.geojson` por otro con la propiedad `provincia`. Para áreas mucho más grandes, revisar `max_px` y la resolución.

**Actualizar dependencias:** `.venv\Scripts\pip install -U -r requirements.txt` y probar las cinco secciones del tablero.

**Comprobación rápida después de un cambio:**

```powershell
.venv\Scripts\python scripts\actualizar.py --dias 3
.venv\Scripts\streamlit run app.py
```

---

## Anexo A — Glosario

| Término | Significado |
|---|---|
| **NDVI** | Índice de vegetación de diferencia normalizada; mide el verdor y la densidad de la vegetación (−1 a 1) |
| **SCL** | *Scene Classification Layer*: clasificación de Sentinel-2 por píxel (nube, sombra, vegetación, agua…) |
| **L2A** | Producto de Sentinel-2 corregido atmosféricamente (reflectancia de superficie) |
| **FRP** | *Fire Radiative Power*: potencia radiativa del fuego, en megavatios; indica la intensidad |
| **Foco de calor** | Píxel con temperatura anómala detectado por satélite; no siempre es un incendio forestal |
| **VIIRS / MODIS** | Sensores de los satélites S-NPP, NOAA-20, NOAA-21 (VIIRS, 375 m) y Terra/Aqua (MODIS, 1 km) |
| **DBSCAN** | Algoritmo de agrupamiento por densidad que no necesita conocer de antemano el número de grupos |
| **Haversine** | Fórmula de distancia entre dos puntos sobre la superficie de la Tierra |
| **TROPOMI** | Instrumento de Sentinel-5P que mide gases atmosféricos |
| **Columna troposférica / total** | Cantidad del gas en toda la columna de aire sobre un punto (mol/m²) |
| **Puntaje z** | Número de desviaciones estándar que separan un valor de su promedio histórico |
| **Evalscript** | Programa en JavaScript que Copernicus ejecuta sobre cada píxel |
| **Mosaico ORBIT / leastCC** | Usar todas las pasadas del periodo / usar la escena con menos nubes |
| **TTL** | *Time to live*: tiempo de vigencia de un dato en caché |
| **IC de Wilson** | Intervalo de confianza para una proporción, adecuado para muestras pequeñas |
| **Spearman** | Correlación entre rangos (órdenes); mide si dos clasificaciones coinciden |
| **Precisión** | Fracción de detecciones que resultaron correctas |

## Anexo B — Referencia rápida de comandos

| Tarea | Comando |
|---|---|
| Instalar | `python -m venv .venv` y luego `.venv\Scripts\pip install -r requirements.txt` |
| Abrir el tablero | `.venv\Scripts\streamlit run app.py` |
| Actualizar (rápido) | `.venv\Scripts\python scripts\actualizar.py --dias 7` |
| Actualizar (completo) | `.venv\Scripts\python scripts\actualizar.py --dias 7 --cobertura` |
| Ignorar la caché | agregar `--forzar` |
| Validar | `.venv\Scripts\python scripts\validar.py` |
| Comparar máscaras de nubes | `.venv\Scripts\python scripts\comparar_mascara.py` |
| Validar con datos oficiales MINAM | `.venv\Scripts\python scripts\validar_minam.py` |
| Informe técnico | `.venv\Scripts\python scripts\informe.py` |
| Manual en Word | `.venv\Scripts\python docs\generar_docx.py` |
| Respaldo verificado | `.venv\Scripts\python scripts\respaldo.py` |
| Láminas para revisión humana | `.venv\Scripts\python scripts\laminas_revision.py` |
| Documento INNOBEST | `.venv\Scripts\python scripts\material_innobest.py` |
| Paquete para otro servidor | `.venv\Scripts\python scripts\empaquetar_servidor.py` |
| Presentación INNOBEST | `.venv\Scripts\python scripts\presentacion.py` |
| Vaciar la caché | borrar la carpeta `.cache` |
