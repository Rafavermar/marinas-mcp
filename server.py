import inspect
import json
import os
from datetime import datetime
import psycopg2
from fastapi.openapi.utils import get_openapi
from psycopg2.extras import RealDictCursor
from fastmcp import FastMCP
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils_html import extract_html_prices
from utils_pdf import fetch_pdf_text, extract_pdf_prices
from fastapi import FastAPI, Body, HTTPException
import logging

# ───────── FastAPI principal ─────────
app = FastAPI(
    title="Marinas MCP",
    description="API MCP para scraping de marinas y gestión de HTML histórico",
    version="1.0.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url=None,
)


# Health-check estándar
@app.get("/", summary="Health check")
async def root():
    return {"status": "ok"}


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
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        html = await page.content()
        await browser.close()
        return html


# ───────── MCP ─────────
mcp = FastMCP(
    app=app,
    name="Marinas MCP",
    instructions="Scrape rápido de HTML de marinas para análisis posterior",
    host="0.0.0.0",
    port=8000,
    log_level="INFO",
    openapi_url="/openapi.json",
    docs_url="/docs",
)

# ─────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


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
                pdf_val = await fetch_pdf_text(url)
                tarifas = extract_pdf_prices(pdf_val, marina_id=marina_id)
            else:
                _html = await fetch_html(url)  # solo para parsear
                pdf_val = None
                tarifas = extract_html_prices(_html, marina_id=marina_id)

            cur.execute(
                """
            INSERT INTO marinas (id, pdf_text, tarifas_json, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET pdf_text     = EXCLUDED.pdf_text,
                tarifas_json = EXCLUDED.tarifas_json,
                updated_at   = EXCLUDED.updated_at
            """,
                (marina_id, pdf_val, json.dumps(tarifas, ensure_ascii=False), now)
            )

            # ───── insert en histórico ─────
            cur.execute(
                """
                INSERT INTO marinas_history (id, pdf_text, tarifas_json, updated_at)
                VALUES (%s, %s, %s, %s)
                """,
                (marina_id, pdf_val, json.dumps(tarifas, ensure_ascii=False), now)
            )

            updated.append({
                "id": marina_id,
                "pdf_len": len(pdf_val or ""),
            })

        conn.commit()
        logger.info("Scrape OK · %s marinas actualizadas", len(updated))
        return {"updated": updated}

    finally:
        if cur:
            cur.close()
        conn.close()


@mcp.tool()
def get_marina_content(marina_id: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT pdf_text, tarifas_json, updated_at FROM marinas WHERE id = %s",
        (marina_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or not row["tarifas_json"]:
        return {"error": "Tarifas no encontradas"}

    return {
        "id": marina_id,
        "pdf_text": row["pdf_text"],
        "tarifas": row["tarifas_json"],
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
        SELECT pdf_text, tarifas_json, updated_at
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
            "pdf_text": r["pdf_text"],
            "tarifas": r["tarifas_json"],
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


# Registro manual de herramientas:
TOOL_REGISTRY = {
    "trigger_scrape": trigger_scrape,
    "get_marina_content": get_marina_content,
    "list_marinas": list_marinas,
    "list_history_dates": list_history_dates,
    "get_marina_history": get_marina_history,
    "health_check": health_check,
}


# Función para generar el esquema OpenAPI completo, INYECTANDO servers ──────
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    # genera el esquema sobre TODAS las rutas de FastAPI (incluidos los tools de FastMCP)
    schema = get_openapi(
        title="Marinas MCP",
        version="1.0.0",
        description="API MCP para scraping de marinas y gestión de HTML histórico",
        routes=app.routes,
    )

    # 2) Forzar OpenAPI 3.1.0 + servidor
    schema["openapi"] = "3.1.0"
    schema["servers"] = [{"url": "https://marinas-mcp-app.azurewebsites.net"}]

    # Health-check mínimo
    paths = schema.setdefault("paths", {})
    paths["/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] = {
        "type": "object",
        "properties": {"status": {"type": "string", "example": "ok"}},
        "required": ["status"],
        "additionalProperties": False,
    }

    # INYECTAMOS /run con operationId="run"
    paths["/run"] = {
        "post": {
            "operationId": "run",
            "summary": "Invoca herramientas de FastMCP",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "marina_id": {"type": "string"},
                                "cutoff_date": {"type": "string", "pattern": r"^\\d{4}-\\d{2}-\\d{2}$"},
                                "args": {"type": "object"}  # ← si algún cliente aún la usa
                            },
                            "required": ["name"],
                            "additionalProperties": False
                        }
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Resultado de la herramienta invocada",
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {}, "additionalProperties": True}
                        }
                    }
                }
            },
        }
    }

    app.openapi_schema = schema
    return schema


# indícale a FastAPI que use custom_openapi()
app.openapi = custom_openapi


@app.post("/run", operation_id="run")
async def manual_run(payload: dict = Body(...)):
    name = payload.get("name")
    if not name or name not in TOOL_REGISTRY:
        raise HTTPException(404, detail=f"Herramienta '{name}' no registrada")
    fn = TOOL_REGISTRY[name]

    # ==> Aquí comprobamos si viene "args" y lo desempaquetamos
    if isinstance(payload.get("args", None), dict):
        kwargs = payload["args"]
    else:
        # tomamos todos los campos excepto 'name'
        kwargs = {k: v for k, v in payload.items() if k != "name"}

    if inspect.iscoroutinefunction(fn):
        return await fn(**kwargs)
    return fn(**kwargs)


# ───────── Scheduler ─────────


scheduler = AsyncIOScheduler(timezone="Europe/Madrid")

# Programa trigger_scrape (que es async) directamente como job:
scheduler.add_job(trigger_scrape, "cron", hour=2, minute=0)

scheduler.start()

if __name__ == "__main__":
    mcp.run(transport="sse")
