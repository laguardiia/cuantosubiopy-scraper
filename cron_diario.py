"""
Corrida diaria automática: scrapea precios de Biggie y Superseis y
los carga directo a Supabase, SIN pasar por archivos CSV en disco
(pensado para correr en GitHub Actions, donde no queremos depender
de un filesystem persistente).

Importante: esto NO corre la pasada lenta de --enrich de Superseis
(la que consigue EAN/marca entrando a cada producto, ~1 hora). Esa
pasada es un trabajo de UNA VEZ para establecer el cruce entre
tiendas -- una vez que un producto ya tiene su producto_id asignado,
las cargas diarias solo actualizan el PRECIO de ese mismo producto
(upsert_producto_tienda mantiene el producto_id ya asignado, ver
cargar_datos.py). Por eso la corrida diaria es rápida: es solo la
pasada rápida de precios de las dos tiendas.

Requiere DATABASE_URL en el entorno (variable de entorno o .env local).
"""

import time

import scraper_biggie
import scraper_superseis
from cargar_datos import (
    cargar_productos_biggie,
    cargar_productos_superseis,
    get_connection,
)


def main() -> None:
    inicio = time.time()
    conn = get_connection()

    try:
        print("=== Scrapeando Biggie ===")
        productos_biggie = scraper_biggie.fetch_catalogo_completo()
        print(f"Biggie: {len(productos_biggie)} productos scrapeados")
        cargar_productos_biggie(conn, productos_biggie)

        print("=== Scrapeando Superseis (pasada rápida, solo precios) ===")
        productos_superseis = scraper_superseis.fetch_catalogo_completo()
        print(f"Superseis: {len(productos_superseis)} productos scrapeados")
        cargar_productos_superseis(conn, productos_superseis)

    finally:
        conn.close()

    minutos = (time.time() - inicio) / 60
    print(f"=== Corrida diaria terminada en {minutos:.1f} minutos ===")


if __name__ == "__main__":
    main()
