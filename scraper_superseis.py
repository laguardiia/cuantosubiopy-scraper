"""
Scraper de Superseis (superseis.com.py), plataforma OpenCart.

Cada producto en el listado trae:
  - data-product-id   -> id interno de OpenCart
  - href del <a>       -> URL del producto (para la pasada lenta despues)
  - data-product-name  -> nombre
  - precio en <span class="price-new"> (con descuento) o
    <span class="price-normal"> (sin descuento)

NO trae EAN ni marca -- eso solo esta en el ld+json de la pagina de
producto individual. Por eso el scraping se separa en dos pasadas:
  1) fetch_category(): rapida, diaria, para precios
  2) (pendiente) fetch_product_detail(): lenta, ocasional, para EAN/marca

Paginacion: estandar OpenCart, ?page=2, ?page=3... Se para cuando una
pagina no trae productos.
"""

import csv
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

OUTPUT_DIR = r"C:\Users\Hp\Desktop\Faq\Projects\CuantoSubioPy"


def _limpiar_precio(texto: str) -> int | None:
    """Convierte '₲ 18.350' -> 18350. Devuelve None si no hay numero."""
    if not texto:
        return None
    solo_digitos = re.sub(r"[^\d]", "", texto)
    return int(solo_digitos) if solo_digitos else None


def parsear_listado(html: str) -> list[dict]:
    """Extrae los productos de una pagina de listado (HTML ya descargado)."""
    soup = BeautifulSoup(html, "html.parser")
    productos = []

    for thumb in soup.select("div.product-thumb"):
        product_id = thumb.get("data-product-id")

        link = thumb.select_one("h4 a")
        nombre = link.get("data-product-name") if link else None
        url = link.get("href") if link else None

        img_tag = thumb.select_one(".image img")
        imagen_url = img_tag.get("src") if img_tag else None

        precio_tag = thumb.select_one(".price .price-new") or thumb.select_one(
            ".price .price-normal"
        )
        precio_anterior_tag = thumb.select_one(".price .price-old")

        productos.append(
            {
                "product_id": product_id,
                "nombre": (nombre or "").strip(),
                "precio": _limpiar_precio(precio_tag.text if precio_tag else None),
                "precio_anterior": _limpiar_precio(
                    precio_anterior_tag.text if precio_anterior_tag else None
                ),
                "url": url,
                "imagen_url": imagen_url,
            }
        )

    return productos


def extraer_categorias_hoja(html_home: str) -> list[str]:
    """
    Recorre el mega-menu de Superseis y devuelve solo las URLs de categoria
    "hoja" (las que realmente listan productos, sin duplicar).

    Regla: un level-1-item que tiene un <ul class="submenu level-2"> adentro
    NO se scrapea directo (listaria productos repetidos de sus hijos).
    Un level-1-item SIN hijos (clase "single") SI es hoja.
    Todo level-2-item siempre es hoja.
    """
    soup = BeautifulSoup(html_home, "html.parser")
    hojas = []

    for li in soup.select("li.level-1-item"):
        submenu2 = li.find("ul", class_="level-2")
        if submenu2:
            for a in submenu2.select("a.level-2-link"):
                if a.get("href"):
                    hojas.append(a["href"])
        else:
            a = li.select_one("a.level-1-link")
            if a and a.get("href"):
                hojas.append(a["href"])

    return sorted(set(hojas))


def parsear_detalle_producto(html: str) -> dict:
    """Extrae EAN (sku) y marca del ld+json tipo 'Product' de una página de producto."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        if data.get("@type") == "Product":
            brand = data.get("brand") or {}
            return {
                "ean": data.get("sku"),
                "marca": brand.get("name"),
            }
    return {"ean": None, "marca": None}


def fetch_product_detail(url: str, intentos: int = 3) -> dict:
    """Con reintentos: las conexiones a Superseis se cortan de vez en
    cuando en corridas largas -- reintentamos un par de veces con una
    pausa creciente antes de rendirnos con ese producto."""
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return parsear_detalle_producto(resp.text)
        except requests.RequestException as e:
            ultimo_error = e
            if intento < intentos:
                time.sleep(1.5 * intento)  # pausa creciente: 1.5s, 3s...
    raise ultimo_error


def enriquecer_con_ean(csv_entrada: str, csv_salida: str, delay: float = 0.4) -> None:
    """
    Pasada lenta: lee un CSV ya scrapeado (con columna 'url') y le agrega
    EAN + marca entrando a cada página de producto. Pensado para correr
    UNA VEZ (o cada tanto), no todos los días -- es la parte cara.

    Escribe el CSV de salida de forma INCREMENTAL (fila por fila, no
    solo al final) -- si el script se corta a la mitad (Ctrl+C, corte
    de luz, etc.), el progreso ya hecho queda guardado en el archivo.
    """
    ruta_entrada = os.path.join(OUTPUT_DIR, csv_entrada)
    with open(ruta_entrada, encoding="utf-8") as f:
        productos = list(csv.DictReader(f))

    total = len(productos)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ruta_salida = os.path.join(OUTPUT_DIR, csv_salida)
    campos = [*productos[0].keys(), "ean", "marca"]

    with open(ruta_salida, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=campos)
        writer.writeheader()

        errores = 0
        for i, p in enumerate(productos, 1):
            if not p.get("url"):
                p["ean"] = None
                p["marca"] = None
            else:
                try:
                    detalle = fetch_product_detail(p["url"])
                    p["ean"] = detalle["ean"]
                    p["marca"] = detalle["marca"]
                except requests.RequestException as e:
                    errores += 1
                    print(f"  [{i}/{total}] error definitivo en {p['url']}: {e}")
                    p["ean"] = None
                    p["marca"] = None

            writer.writerow(p)
            f_out.flush()  # que quede en disco ya, no solo en el buffer

            if i % 50 == 0 or i == total:
                print(f"  [{i}/{total}] procesados ({errores} errores hasta ahora)")
            time.sleep(delay)

    print(f"Listo: {total} filas guardadas en {ruta_salida} ({errores} sin EAN por error de red)")


def fetch_category(category_url: str, delay: float = 0.5) -> list[dict]:
    """Recorre todas las paginas de una categoria hasta que una venga vacia."""
    todos = []
    page = 1

    while True:
        separador = "&" if "?" in category_url else "?"
        url = f"{category_url}{separador}page={page}" if page > 1 else category_url

        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        productos = parsear_listado(resp.text)
        if not productos:
            break

        todos.extend(productos)
        print(f"  página {page}: {len(productos)} productos")
        page += 1
        time.sleep(delay)

    return todos


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


def fetch_catalogo_completo(url_home: str = "https://www.superseis.com.py/", delay: float = 0.5) -> list[dict]:
    """Trae el HTML de la home, encuentra todas las categorías hoja, y las recorre todas."""
    resp = requests.get(url_home, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    categorias = extraer_categorias_hoja(resp.text)
    print(f"Encontradas {len(categorias)} categorías hoja")

    todos_los_productos = []
    for i, cat_url in enumerate(categorias, 1):
        print(f"[{i}/{len(categorias)}] {cat_url}")
        productos = fetch_category(cat_url, delay=delay)
        todos_los_productos.extend(productos)
        time.sleep(delay)

    return todos_los_productos


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--enrich":
        # python scraper_superseis.py --enrich superseis_catalogo_completo.csv
        csv_entrada = sys.argv[2] if len(sys.argv) > 2 else "superseis_catalogo_completo.csv"
        print(f"Enriqueciendo {csv_entrada} con EAN y marca (pasada lenta)...")
        enriquecer_con_ean(csv_entrada, "superseis_catalogo_con_ean.csv")
    elif len(sys.argv) > 1:
        url = sys.argv[1]
        print(f"Scrapeando: {url}")
        productos = fetch_category(url)
        guardar_csv(productos, "superseis_categoria.csv")
    else:
        productos = fetch_catalogo_completo()
        guardar_csv(productos, "superseis_catalogo_completo.csv")
