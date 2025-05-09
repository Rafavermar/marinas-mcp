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

    # localiza la sección “Tarifas diarias”
    all_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    header_idx = next(i for i, ln in enumerate(all_lines)
                      if re.search(r"Eslora.*Baja", ln, re.I))

    rows = []
    for raw in all_lines[header_idx + 1:]:
        # un número al principio → nuevas tarifas; si no, salimos
        if not re.match(r"^\d", raw):  # llega a “*IVA incluido…”
            break
        parts = raw.split()
        eslora = _clean(parts[0])
        baja = _clean(parts[1])
        media = _clean(parts[2])
        alta = _clean(parts[3])
        rows.append([eslora, baja, media, alta])

    return {"temporadas": ["baja", "media", "alta"], "rows": rows}
