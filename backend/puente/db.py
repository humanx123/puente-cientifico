"""Base de datos SQLite (con búsqueda de texto completo FTS5)."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS carpetas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    padre_id INTEGER REFERENCES carpetas(id) ON DELETE SET NULL,
    creada TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    autores TEXT DEFAULT '',
    anio INTEGER,
    doi TEXT,
    archivo TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    paginas INTEGER DEFAULT 0,
    tamano INTEGER DEFAULT 0,
    carpeta_id INTEGER REFERENCES carpetas(id) ON DELETE SET NULL,
    favorito INTEGER DEFAULT 0,
    origen TEXT DEFAULT 'importado',
    agregado TEXT DEFAULT (datetime('now','localtime')),
    abierto TEXT,
    pagina_actual INTEGER DEFAULT 1,
    papelera TEXT
);
CREATE INDEX IF NOT EXISTS idx_doc_doi ON documentos(doi);
CREATE TABLE IF NOT EXISTS notas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    pagina INTEGER NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'nota',   -- nota | resaltado | subrayado | marcador | asistente
    texto TEXT DEFAULT '',
    cita TEXT DEFAULT '',
    color TEXT DEFAULT '#ffe600',
    creada TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS traducciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    origen TEXT NOT NULL,
    destino TEXT NOT NULL,
    archivo TEXT NOT NULL,
    estado TEXT DEFAULT 'pendiente',
    actualizada TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(documento_id, origen, destino)
);
CREATE TABLE IF NOT EXISTS segmentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    traduccion_id INTEGER NOT NULL REFERENCES traducciones(id) ON DELETE CASCADE,
    pagina INTEGER NOT NULL,
    bloque INTEGER NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    tam_fuente REAL DEFAULT 10,
    color INTEGER DEFAULT 0,
    negrita INTEGER DEFAULT 0,
    original TEXT NOT NULL,
    traducido TEXT,
    estado TEXT DEFAULT 'pendiente',   -- pendiente | ok | error | omitido
    error TEXT,
    UNIQUE(traduccion_id, pagina, bloque)
);
CREATE INDEX IF NOT EXISTS idx_seg_pag ON segmentos(traduccion_id, pagina);
CREATE VIRTUAL TABLE IF NOT EXISTS texto_fts USING fts5(
    documento_id UNINDEXED, pagina UNINDEXED, tipo UNINDEXED, contenido,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS glosarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    origen TEXT NOT NULL DEFAULT 'en',
    destino TEXT NOT NULL DEFAULT 'es',
    integrado INTEGER DEFAULT 0,
    terminos TEXT NOT NULL DEFAULT '[]',
    actualizado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS fuentes_noticias (
    id TEXT PRIMARY KEY,
    organizacion TEXT NOT NULL,
    tipo_org TEXT DEFAULT 'medio',
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'rss',   -- rss | html
    url TEXT NOT NULL,
    base_url TEXT DEFAULT '',
    selectores TEXT DEFAULT '{}',
    etiquetas TEXT DEFAULT '{}',
    activa INTEGER DEFAULT 1,
    ultimo_estado TEXT DEFAULT '',
    ultima_vez TEXT
);
CREATE TABLE IF NOT EXISTS noticias (
    uid TEXT PRIMARY KEY,
    fuente_id TEXT,
    organizacion TEXT,
    tipo_org TEXT,
    titulo TEXT NOT NULL,
    enlace TEXT NOT NULL,
    resumen TEXT DEFAULT '',
    fecha TEXT,
    nivel TEXT DEFAULT '[]',
    area TEXT DEFAULT '[]',
    categoria TEXT DEFAULT '[]',
    leida INTEGER DEFAULT 0,
    guardada INTEGER DEFAULT 0,
    recogida TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_not_fecha ON noticias(fecha);
CREATE TABLE IF NOT EXISTS descargas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consulta TEXT NOT NULL,
    estado TEXT NOT NULL,
    mensaje TEXT DEFAULT '',
    documento_id INTEGER,
    creada TEXT DEFAULT (datetime('now','localtime'))
);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = _connect()
        conn.executescript(SCHEMA)
        # Migración idempotente: bases creadas antes de las subcarpetas no tienen padre_id.
        columnas = {r[1] for r in conn.execute("PRAGMA table_info(carpetas)").fetchall()}
        if "padre_id" not in columnas:
            conn.execute("ALTER TABLE carpetas ADD COLUMN padre_id INTEGER REFERENCES carpetas(id) ON DELETE SET NULL")
        conn.commit()
        conn.close()
        _initialized = True


def conn() -> sqlite3.Connection:
    init()
    c = getattr(_local, "conn", None)
    if c is None:
        c = _connect()
        _local.conn = c
    return c


@contextmanager
def tx():
    c = conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def rows(sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def row(sql: str, params=()) -> dict | None:
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None
