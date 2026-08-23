"""
Scraper de la API pública de Biggie Express (biggie.com.py).

Descubrimiento (via DevTools -> Network -> Fetch/XHR):
  GET https://api.app.biggie.com.py/api/articles
      ?take=24
      &skip=0
      &classificationName=asado

No requiere autenticación. Pagina con take/skip hasta llegar a "count".
"""

import csv
import sys
import time
import os

import requests

BASE_URL = "https://api.app.biggie.com.py/api/articles"
CLASSIFICATIONS_URL = "https://api.app.biggie.com.py/api/classifications"
TAKE = 24
OUTPUT_DIR = r"C:\Users\Hp\Desktop\Faq\Projects\CuantoSubioPy"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def fetch_classifications() -> list[str]:
    """Trae la lista de slugs de categorías desde /api/classifications."""
    resp = requests.get(CLASSIFICATIONS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return [item["slug"] for item in data.get("items", [])]


def fetch_category(classification_name: str, delay: float = 0.5) -> list[dict]:
    """Trae todos los productos de una categoría de Biggie, paginando con skip."""
    productos = []
    skip = 0
    total = None

    while total is None or skip < total:
        params = {
            "take": TAKE,
            "skip": skip,
            "classificationName": classification_name,
        }
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        total = data.get("count", 0)
        descartados = 0

        for item in items:
            code = item.get("code") or ""
            # Biggie tiene ~0.8% de productos con datos corruptos en origen:
            # el campo "code" a veces trae una fila de CSV entera pegada como
            # texto en vez de un código de barras. Los detectamos y saltamos.
            if not code.isdigit():
                descartados += 1
                continue

            brand = item.get("brand") or {}
            family = item.get("family") or {}
            imagenes = item.get("images") or []
            # type 0 = imagen grande (1000x1000), la que más nos sirve
            imagen = next((im for im in imagenes if im.get("type") == 0), None) or (
                imagenes[0] if imagenes else None
            )
            productos.append(
                {
                    "ean": code,
                    "nombre": (item.get("name") or "").strip(),
                    "precio": item.get("price"),
                    "marca": (brand.get("name") or "").strip(),
                    "categoria": classification_name,
                    "familia": family.get("slug"),
                    "imagen_url": imagen.get("src") if imagen else None,
                    "actualizado": item.get("updatedAt"),
                }
            )

        if descartados:
            print(f"    (descartados {descartados} productos con datos corruptos)")

        print(f"  {classification_name}: {min(skip + TAKE, total)}/{total}")
        skip += TAKE
        time.sleep(delay)  # ser prudente con la frecuencia de requests

    return productos


def guardar_csv(productos: list[dict], nombre_archivo: str) -> None:
    if not productos:
        print("No hay productos para guardar.")
        return
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ruta_completa = os.path.join(OUTPUT_DIR, nombre_archivo)
    campos = productos[0].keys()
    with open(ruta_completa, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(productos)
    print(f"Guardados {len(productos)} productos en {ruta_completa}")


def fetch_catalogo_completo(delay_entre_categorias: float = 1.0) -> list[dict]:
    """Recorre TODAS las categorías de Biggie y devuelve el catálogo completo."""
    categorias = fetch_classifications()
    print(f"Encontradas {len(categorias)} categorías: {categorias}")

    todos_los_productos = []
    for categoria in categorias:
        print(f"Scrapeando categoría: {categoria}")
        todos_los_productos.extend(fetch_category(categoria))
        time.sleep(delay_entre_categorias)

    return todos_los_productos


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Modo categoría única: python scraper_biggie.py asado
        categoria = sys.argv[1]
        print(f"Scrapeando categoría: {categoria}")
        productos = fetch_category(categoria)
        guardar_csv(productos, f"biggie_{categoria}.csv")
    else:
        # Sin argumentos: recorre TODO el catálogo
        productos = fetch_catalogo_completo()
        guardar_csv(productos, "biggie_catalogo_completo.csv")
