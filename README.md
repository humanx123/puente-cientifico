# Puente Científico

App de escritorio para Windows, en español, que reúne tres proyectos de código abierto en una sola herramienta para investigar:

| Proyecto original | Qué aporta |
|---|---|
| [PageBridge](https://github.com/txp666/PageBridge) | Biblioteca PDF, traducción que conserva la maquetación, vista original/comparar/traducción, glosarios, asistente con citas de página, búsqueda de literatura en OpenAlex |
| [SciHubEVA](https://github.com/leovan/SciHubEVA) | Cliente de Sci-Hub: DOI, PMID, URL y rangos `{1-10}`, rotación de espejos, XPath configurables, CAPTCHA asistido, DDoS-Guard, proxy HTTP/SOCKS5, formato de nombre `{id}_{year}_{author}_{title}` |
| [libgen-api-enhanced](https://github.com/onurhanak/libgen-api-enhanced) | Búsqueda en Library Genesis por todo, título o autor; temas (libros, ficción, cómics, revistas, normas), filtros y enlace directo de descarga |
| [annas-archive](https://github.com/LilyLoops/annas-archive) | Código del sitio de Anna's Archive. La app consulta una instancia pública con su formato de tabla y usa su API de descarga rápida para miembros, o LibGen por md5 |
| [Tor](https://www.torproject.org/) | Túnel de privacidad opcional, solo para literatura y sin permisos de administrador; resuelve bloqueos de DNS o de dominio |
| [science-hub](https://github.com/goldruma/science-hub) | Agregador de noticias y convocatorias con fuentes RSS/HTML, etiquetas por nivel, área y categoría, y deduplicación. Adaptado a fuentes científicas en español y actualizado en segundo plano en vez de GitHub Actions |

## Funciones

- **Biblioteca:** importar PDF o carpetas, arrastrar y soltar, carpetas, favoritos, recientes, papelera, deduplicación por SHA-256, metadatos completados con OpenAlex y búsqueda de texto completo en originales y traducciones.
- **Lector:** páginas con carga diferida, texto seleccionable, miniaturas, índice, búsqueda, resaltados de colores, subrayados, notas y marcadores.
- **Traducción con maquetación:** se traduce cada párrafo en su sitio con Ollama (local) o cualquier API compatible con OpenAI. Se conservan columnas, figuras, fondos y tablas. Puedes traducir rangos de páginas (`1-5, 8`), reintentar o editar cada párrafo y retraducir solo los párrafos que contienen un término del glosario.
- **Exportación:** PDF traducido, bilingüe lado a lado, bilingüe intercalado, PDF anotado y notas en Markdown.
- **Asistente:** preguntas sobre el documento, la página, una selección o libres, con citas `[p. N]` que llevan a la página.
- **Glosarios:** ocho glosarios integrados de inglés a español (medicina, virología, estadística, IA, redacción académica, química, física e ingeniería). Puedes importar y exportar TXT o CSV y extraer términos candidatos de un documento.
- **Literatura:** búsqueda en OpenAlex con filtros, descarga de acceso abierto o Sci-Hub, colas por lote y registro en vivo.
- **Noticias:** 16 fuentes en español verificadas (El País, El Mundo, La Vanguardia, Europa Press, The Conversation, UNAM, Naukas y convocatorias de becas, SECIHTI y olimpiadas vía Google Noticias), más las fuentes que añadas tú.
- **Interfaz:** React con dos skins (brutalista y minimalista), temas claro y oscuro, y ventana nativa con WebView2. El menú se oculta con `Ctrl+B` y los paneles laterales se redimensionan arrastrando su borde o se ocultan con doble clic. Las tarjetas y las columnas tienen control de tamaño.
- **Búsqueda por autor:** OpenAlex por título, autor o ambos. Un clic en cualquier autor muestra todas sus obras usando su identificador de OpenAlex, sin confundir homónimos.
- **Libros:** LibGen y Anna's Archive. EPUB, MOBI, FB2, CBZ y XPS se convierten a PDF al importarlos.
- **Túnel:** directo, Tor integrado (con puentes Snowflake u obfs4 y país de salida) o el proxy SOCKS5/HTTP de tu VPN.

## Instalar

Ejecuta `PuenteCientifico-Setup-<versión>.exe`. No necesita permisos de administrador y se instala en `%LOCALAPPDATA%\Programs\PuenteCientifico`. El instalador puede instalar Ollama y un modelo de traducción de forma opcional.

Los datos del usuario se guardan en `%APPDATA%\PuenteCientifico` e incluyen la biblioteca, las traducciones, las notas y los ajustes. Desinstalar la app no los borra.

Si la app no abre, ejecuta **Diagnóstico de Puente Científico** desde el menú Inicio. Deja un informe en el Escritorio.

## Compilar desde el código

Requisitos: Windows 10/11 x64, Node 18+, Python 3.11 para desarrollo e Inno Setup 6.

```powershell
powershell -ExecutionPolicy Bypass -File build\build.ps1
```

El instalador queda en `build\dist\`.

## Desarrollo

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
.venv\Scripts\python backend\run.py --navegador     # API en http://127.0.0.1:8777
cd frontend; npm install; npm run dev                # interfaz con recarga en http://localhost:5173
```

## Arquitectura

```
backend/
  run.py            lanzador: elige puerto, arranca uvicorn y abre la ventana pywebview (WebView2)
  server.py         API FastAPI y servidor de la interfaz compilada
  puente/
    library.py      biblioteca, renderizado, búsqueda FTS5, notas, exportación
    translate.py    extracción por bloques, traducción por lotes y reconstrucción del PDF
    llm.py          Ollama o API compatible con OpenAI
    assistant.py    preguntas con recuperación de páginas y citas
    glossary.py     glosarios y extracción de términos
    literature.py   OpenAlex, acceso abierto y Sci-Hub (lógica de SciHubEVA)
    news.py         RSS/HTML, etiquetas y programador (lógica de science-hub)
frontend/           React + Vite, se compila a backend/static
build/              Python embebido, instalador Inno Setup, icono
```

## Aviso

Usa Sci-Hub conforme a la legislación de derechos de autor de tu país. La app prioriza las copias de acceso abierto cuando existen.
