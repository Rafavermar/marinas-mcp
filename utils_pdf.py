# utils_pdf.py
import io
import httpx
import pdfplumber
import re
from utils_html import _clean


async def fetch_pdf_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        pdf_bytes = r.content
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def extract_pdf_prices(text: str, marina_id: str) -> dict:
    """
    Parser específico para el PDF de Marina del Este.
    Devuelve: {"temporadas": [...], "rows":[[eslora,baja,media,alta], ...]}
    """
    if marina_id != "marina_este":
        raise ValueError("solo implementado para marina_este")

    # Limpiamos líneas no vacías
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Buscamos encabezado de “Eslora … Baja”
    try:
        header_idx = next(i for i, ln in enumerate(lines)
                          if re.search(r"Eslora.*Baja", ln, re.I))
    except StopIteration:
        raise ValueError("Encabezado de tarifas no encontrado en PDF")

    rows = []
    for raw in lines[header_idx + 1:]:
        # Salimos al llegar a la parte descriptiva (no empieza por dígito)
        if not re.match(r"^\d", raw):
            break
        parts = raw.split()

        # Convierte seguro o devuelve None
        def safe(part_i):
            if part_i < len(parts):
                try:
                    return _clean(parts[part_i])
                except ValueError:
                    return None
            return None

        eslora = safe(0)
        baja = safe(1)
        media = safe(2)
        alta = safe(3)

        rows.append([eslora, baja, media, alta])

    return {"temporadas": ["baja", "media", "alta"], "rows": rows}
