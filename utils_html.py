# utils_html.py
from __future__ import annotations
import re
from bs4 import BeautifulSoup


def _clean(num: str) -> float:
    """Convierte '20,50 €' → 20.50 (sin escapes redundantes)."""
    cleaned = re.sub(r"[^\d,.]", "", num)
    return float(cleaned.replace(",", "."))


# ─────────────────────────────── BENALMÁDENA ──────────────────────────────────
def _extract_benalmadena(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    tbl = soup.select_one("table#tablepress-17")
    if not tbl:
        raise ValueError("No se encontró tablepress-17")

    rows = []
    for tr in tbl.select("tbody tr")[2:]:  # saltamos cabeceras 0-1
        cells = [c.get_text(strip=True) for c in tr.select("td")]
        eslora = _clean(cells[0])
        manga = _clean(cells[1])
        baja = _clean(cells[3])
        alta = _clean(cells[2])
        # este puerto NO tiene “media”; ponemos None
        rows.append([eslora, manga, baja, None, alta])

    return {"temporadas": ["baja", "media", "alta"],
            "rows": rows}


# ─────────────────────────────── MARBELLA ─────────────────────────────────────
def _pick(tbl, col) -> list[list]:
    """Devuelve [eslora, precio] usando la columna deseada."""
    out = []
    for tr in tbl.select("tbody tr"):
        tds = [c.get_text(strip=True) for c in tr.select("td")]
        if len(tds) >= col:
            eslora = _clean(tds[0].split()[0])  # “12 x 4 m.” → 12
            out.append([eslora, _clean(tds[col - 1])])
    return out


def _extract_marbella(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    bajas = soup.find("strong", string=re.compile("TEMPORADA BAJA", re.I))
    altas = soup.find("strong", string=re.compile("TEMPORADA ALTA", re.I))
    if not (bajas and altas):
        raise ValueError("Tablas de baja/alta no encontradas")

    tbl_baja = bajas.find_parent("table")
    tbl_alta = altas.find_parent("table")

    rows = []
    for e_baja, p_baja in _pick(tbl_baja, 2):  # col-2 = “PRECIO S/IVA”
        # busca misma eslora en tabla alta
        p_alta = next((p for e_alta, p in _pick(tbl_alta, 2)
                       if e_alta == e_baja), None)
        rows.append([e_baja, p_baja, None, p_alta])

    return {"temporadas": ["baja", "media", "alta"],
            "rows": rows}


# ──────────────────────────── Dispatcher genérico ─────────────────────────────
PARSERS = {
    "benalmadena": _extract_benalmadena,
    "marbella": _extract_marbella,
    # "marina_este": usa PDF → parser aparte
}


def extract_html_prices(html: str, marina_id: str) -> dict:
    if marina_id not in PARSERS:
        raise ValueError(f"Sin parser específico para {marina_id}")
    return PARSERS[marina_id](html)
