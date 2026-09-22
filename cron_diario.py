"""
Corrida semanal automática: scrapea precios de Biggie y los carga
directo a Supabase, SIN pasar por archivos CSV en disco (pensado para
correr en GitHub Actions, donde no queremos depender de un filesystem
persistente).

Superseis está deshabilitado por ahora: los runners de GitHub Actions
reciben 403 de su WAF/Cloudflare (bloqueo por IP de datacenter). Ver
el comentario más abajo, junto a los imports comentados.

Requiere DATABASE_URL en el entorno (variable de entorno o .env local).
"""

import time

import scraper_biggie
from cargar_datos import (
    cargar_productos_biggie,
    get_connection,
)

# Superseis está deshabilitado acá a propósito: su WAF/Cloudflare devuelve
# 403 para las IPs de datacenter de los runners de GitHub Actions (confirmado:
# el mismo scraper corrido en local, desde IP residencial, funciona bien).
# Reactivar estos imports y el bloque de abajo una vez que el scraping de
# Superseis corra desde algo que no esté bloqueado (self-hosted runner,
# proxy residencial, VPS, etc.).
# import scraper_superseis
# from cargar_datos import cargar_productos_superseis


def main() -> None:
    inicio = time.time()
    conn = get_connection()

    try:
        print("=== Scrapeando Biggie ===")
        productos_biggie = scraper_biggie.fetch_catalogo_completo()
        print(f"Biggie: {len(productos_biggie)} productos scrapeados")
        cargar_productos_biggie(conn, productos_biggie)

        # print("=== Scrapeando Superseis (pasada rápida, solo precios) ===")
        # productos_superseis = scraper_superseis.fetch_catalogo_completo()
        # print(f"Superseis: {len(productos_superseis)} productos scrapeados")
        # cargar_productos_superseis(conn, productos_superseis)

    finally:
        conn.close()

    minutos = (time.time() - inicio) / 60
    print(f"=== Corrida diaria terminada en {minutos:.1f} minutos ===")


if __name__ == "__main__":
    main()