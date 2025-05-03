import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from fastmcp import FastMCP
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

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


# ───────── MCP ─────────
mcp = FastMCP(
    name="Marinas MCP",
    instructions="Scrape rápido de HTML de marinas para análisis posterior",
    host="0.0.0.0",
    port=8000,
    log_level="INFO",
)


@mcp.tool()
async def trigger_scrape() -> dict:
    """
    Trae solo el HTML de cada marina y lo guarda en la tabla `marinas`.
    El campo `html_bruto` es JSONB (o TEXT), y `updated_at` la UTC actual.
    """
    targets = {
        "benalmadena": "https://puertobenalmadena.es/tarifas/",
        "marbella": "https://puertodeportivo.marbella.es/servicios-y-tarifas/...",
    }

    conn = get_conn()
    cur = conn.cursor()
    updated = []
    now = datetime.utcnow()

    try:
        for marina_id, url in targets.items():
            html = await fetch_html(url)
            # Upsert en Marinas
            cur.execute(
                """
                INSERT INTO marinas (id, html_bruto, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  html_bruto = EXCLUDED.html_bruto,
                  updated_at = EXCLUDED.updated_at
                """,
                (marina_id, html, now),
            )
            # Insert en histórico
            cur.execute(
                """
                INSERT INTO marinas_history (id, html_bruto, updated_at)
                VALUES (%s, %s, %s)
                """,
                (marina_id, html, now),
            )
            updated.append({"id": marina_id, "html_length": len(html)})

        conn.commit()
        return {"updated": updated}

    finally:
        cur.close()
        conn.close()


@mcp.tool()
def get_marina_html(marina_id: str) -> dict:
    """
    Recupera el HTML bruto almacenado y la fecha de última actualización.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT html_bruto, updated_at FROM marinas WHERE id = %s",
        (marina_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return {"error": "Marina no encontrada"}
    return {
        "id": marina_id,
        "html_bruto": row["html_bruto"],
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
    Devuelve todas las entradas históricas de HTML para esa marina.
    Cada dict tiene: fecha y html_bruto.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT html_bruto, updated_at FROM marinas_history WHERE id = %s ORDER BY updated_at DESC",
        (marina_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"fecha": r["updated_at"].date().isoformat(), "html_bruto": r["html_bruto"]}
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
# …
if __name__ == "__main__":
    mcp.run(transport="sse")
