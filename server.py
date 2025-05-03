import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from fastmcp import FastMCP
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from utils_pdf import fetch_pdf_text

# ───────── utilidades ─────────
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)
DB_URL = os.getenv("DATABASE_URL")


def get_conn():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL no está definida")
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)


async def fetch_html(url: str) -> str:
    """Solo obtiene el HTML bruto de la página."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        await browser.close()
        return html


# ───────── FastAPI ─────────
app = FastAPI(
    title="Marinas MCP",
    description="API MCP para scraping de marinas y gestión de HTML histórico",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


@app.get("/", summary="Health check")
async def root():
    return {"status": "ok"}


# ───────── MCP ─────────
mcp = FastMCP(
    name="Marinas MCP",
    instructions="Scrape rápido de HTML de marinas para análisis posterior",
    host="0.0.0.0",
    port=8000,
    log_level="INFO",
    openapi_url="/openapi.json",
    docs_url="/docs"
)


@mcp.tool()
async def trigger_scrape() -> dict:
    """
    Descarga HTML o, si la URL acaba en .pdf, el texto plano del PDF.
    Guarda:
      • html_bruto  (solo HTML)
      • pdf_text    (solo texto de PDFs)
    """
    targets = {
        "benalmadena": "https://puertobenalmadena.es/tarifas",
        "marbella": "https://puertodeportivo.marbella.es/servicios-y-tarifas",
        "marina_este": "https://www.marinasmediterraneo.com/wp-content/uploads/2022/03/Tarifas_MEste.pdf",
    }

    conn, cur = get_conn(), None
    updated, now = [], datetime.utcnow()

    try:
        cur = conn.cursor()

        for marina_id, url in targets.items():
            is_pdf = url.lower().endswith(".pdf")

            if is_pdf:
                html_val, pdf_val = None, await fetch_pdf_text(url)
            else:
                html_val, pdf_val = await fetch_html(url), None

            # ───── upsert en tabla principal ─────
            cur.execute(
                """
                INSERT INTO marinas (id, html_bruto, pdf_text, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                   SET html_bruto = EXCLUDED.html_bruto,
                       pdf_text   = EXCLUDED.pdf_text,
                       updated_at = EXCLUDED.updated_at
                """,
                (marina_id, html_val, pdf_val, now),
            )

            # ───── insert en histórico ─────
            cur.execute(
                """
                INSERT INTO marinas_history (id, html_bruto, pdf_text, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (marina_id, html_val, pdf_val, now),
            )

            updated.append({
                "id": marina_id,
                "html_len": len(html_val or ""),
                "pdf_len": len(pdf_val or ""),
            })

        conn.commit()
        return {"updated": updated}

    finally:
        if cur:
            cur.close()
        conn.close()


@mcp.tool()
def get_marina_content(marina_id: str) -> dict:
    """
    Devuelve html_bruto y/o pdf_text según exista contenido.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT html_bruto, pdf_text, updated_at FROM marinas WHERE id = %s",
        (marina_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return {"error": "Marina no encontrada"}

    return {
        "id": marina_id,
        "html_bruto": row["html_bruto"],  # puede ser None
        "pdf_text": row["pdf_text"],  # puede ser None
        "updated_at": row["updated_at"].isoformat(),
    }


@mcp.tool()
def list_marinas() -> list[str]:
    """
    Devuelve la lista de todos los IDs de marina registrados.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM marinas ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r["id"] for r in rows]


@mcp.tool()
def list_history_dates(marina_id: str) -> list[str]:
    """
    Para un marina_id dado, devuelve la lista de fechas (YYYY-MM-DD)
    para las que hay HTML en marinas_history.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT DATE(updated_at) AS fecha FROM marinas_history WHERE id = %s ORDER BY fecha DESC",
        (marina_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r["fecha"].isoformat() for r in rows]


@mcp.tool()
def get_marina_history(marina_id: str) -> list[dict]:
    """
    Devuelve la lista histórica con html_bruto y pdf_text.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT html_bruto, pdf_text, updated_at
          FROM marinas_history
         WHERE id = %s
      ORDER BY updated_at DESC
        """,
        (marina_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "fecha": r["updated_at"].date().isoformat(),
            "html_bruto": r["html_bruto"],
            "pdf_text": r["pdf_text"],
        }
        for r in rows
    ]


@mcp.tool()
def health_check() -> dict:
    """
    Comprueba la conectividad con la base de datos.
    Devuelve {"status": "ok"} si la conexión y un SELECT trivial funcionan,
    o {"status": "error", "detail": "..."} en caso contrario.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@mcp.tool()
def cleanup_history(cutoff_date: str) -> dict:
    """
    Elimina de marinas_history todos los registros anteriores a `cutoff_date` (YYYY-MM-DD).
    Devuelve cuántas filas se borraron.
    """
    try:
        # parseamos la fecha
        cutoff = datetime.strptime(cutoff_date, "%Y-%m-%d")
    except ValueError:
        return {"error": "Formato de fecha inválido, use YYYY-MM-DD"}

    conn = get_conn()
    cur = conn.cursor()
    # Ejecutamos el DELETE
    cur.execute(
        """
        DELETE FROM marinas_history
         WHERE updated_at < %s
        """,
        (cutoff,)
    )
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return {"deleted_rows": deleted}


# ───────── Scheduler ─────────


scheduler = AsyncIOScheduler(timezone="Europe/Madrid")


# Cada día a las 02:00
def _schedule_scrape():
    # Lanza el coroutine en el loop actual
    asyncio.create_task(trigger_scrape())


scheduler.add_job(_schedule_scrape, "cron", hour=2, minute=0)
scheduler.start()

# ───────── Exportación ASGI ─────────
# Uvicorn loader busca `app` en server.py
# noinspection PyUnresolvedReferences
app = mcp.app
