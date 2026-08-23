"""
Carga los CSVs de Biggie y Superseis a la base de Postgres (Supabase),
siguiendo el esquema de schema.sql.

Requiere un archivo .env en la misma carpeta con:
    DATABASE_URL=postgresql://...

Uso:
    python cargar_datos.py biggie biggie_catalogo_completo.csv
    python cargar_datos.py superseis superseis_catalogo_con_ean.csv
"""

import csv
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = r"C:\Users\Hp\Desktop\Faq\Projects\CuantoSubioPy"

SUPERMERCADOS = {
    "biggie": "Biggie",
    "superseis": "Superseis",
}


def get_connection():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "No encontré DATABASE_URL. Creá un archivo .env en esta carpeta "
            "(mirá .env.example) con tu connection string de Supabase."
        )
    return psycopg2.connect(url)


def asegurar_supermercado(conn, slug: str) -> int:
    """Inserta el supermercado si no existe, devuelve su id."""
    nombre = SUPERMERCADOS[slug]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO supermercados (nombre, slug)
            VALUES (%s, %s)
            ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug
            RETURNING id
            """,
            (nombre, slug),
        )
        supermercado_id = cur.fetchone()[0]
    conn.commit()
    return supermercado_id


def buscar_o_crear_producto(
    conn,
    ean: str | None,
    nombre: str,
    marca: str | None,
    categoria: str | None = None,
    imagen_url: str | None = None,
    preferir_imagen: bool = False,
) -> int | None:
    """
    Si hay EAN: busca o crea el producto canonico automaticamente.
    Si ya existia:
      - categoria: se completa solo si estaba vacia (nunca se pisa)
      - imagen_url: si preferir_imagen=True (Biggie), la nueva imagen
        SIEMPRE pisa la anterior cuando llega una; si es False
        (Superseis), solo se usa cuando no habia ninguna todavia.
    Si NO hay EAN: devuelve None (queda pendiente de matching manual).
    """
    if not ean:
        return None

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM productos WHERE ean = %s", (ean,))
        fila = cur.fetchone()
        if fila:
            producto_id = fila[0]
            if preferir_imagen:
                sql_imagen = "imagen_url = COALESCE(%s, imagen_url)"
            else:
                sql_imagen = "imagen_url = COALESCE(imagen_url, %s)"

            cur.execute(
                f"""
                UPDATE productos
                SET categoria = COALESCE(categoria, %s),
                    {sql_imagen}
                WHERE id = %s
                """,
                (categoria, imagen_url, producto_id),
            )
            return producto_id

        cur.execute(
            """
            INSERT INTO productos (ean, nombre, marca, categoria, imagen_url)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (ean, nombre, marca, categoria, imagen_url),
        )
        return cur.fetchone()[0]


def upsert_producto_tienda(
    conn,
    producto_id: int | None,
    supermercado_id: int,
    id_externo: str,
    url: str | None,
    nombre_en_tienda: str,
    marca_en_tienda: str | None,
    categoria_en_tienda: str | None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO productos_tienda
                (producto_id, supermercado_id, id_externo, url, nombre_en_tienda,
                 marca_en_tienda, categoria_en_tienda)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (supermercado_id, id_externo) DO UPDATE SET
                producto_id = COALESCE(productos_tienda.producto_id, EXCLUDED.producto_id),
                nombre_en_tienda = EXCLUDED.nombre_en_tienda,
                marca_en_tienda = EXCLUDED.marca_en_tienda,
                categoria_en_tienda = EXCLUDED.categoria_en_tienda,
                url = EXCLUDED.url
            RETURNING id
            """,
            (
                producto_id,
                supermercado_id,
                id_externo,
                url,
                nombre_en_tienda,
                marca_en_tienda,
                categoria_en_tienda,
            ),
        )
        return cur.fetchone()[0]


def insertar_precio(conn, producto_tienda_id: int, precio: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO precios_historicos (producto_tienda_id, precio) VALUES (%s, %s)",
            (producto_tienda_id, precio),
        )


def cargar_productos_biggie(conn, productos: list[dict]) -> None:
    """
    Carga una lista de productos de Biggie (dicts con las mismas claves
    que devuelve scraper_biggie.fetch_category/fetch_catalogo_completo).
    No depende de un CSV -- se puede llamar directo con datos en memoria
    (por eso lo usa cron_diario.py para no pasar por el disco).
    """
    supermercado_id = asegurar_supermercado(conn, "biggie")

    total = len(productos)
    for i, fila in enumerate(productos, 1):
        ean = fila.get("ean") or None
        precio = fila.get("precio")
        if not precio or not str(precio).isdigit():
            continue

        producto_id = buscar_o_crear_producto(
            conn,
            ean,
            fila["nombre"],
            fila.get("marca"),
            categoria=fila.get("categoria"),
            imagen_url=fila.get("imagen_url"),
            preferir_imagen=True,  # Biggie manda: su imagen siempre gana
        )
        pt_id = upsert_producto_tienda(
            conn,
            producto_id=producto_id,
            supermercado_id=supermercado_id,
            id_externo=ean or fila["nombre"],  # Biggie no trae un id interno propio
            url=None,
            nombre_en_tienda=fila["nombre"],
            marca_en_tienda=fila.get("marca"),
            categoria_en_tienda=fila.get("categoria"),
        )
        insertar_precio(conn, pt_id, int(precio))

        if i % 500 == 0:
            conn.commit()
            print(f"  [{i}/{total}] cargados")

    conn.commit()
    print(f"Listo: {total} filas de Biggie procesadas.")


def cargar_productos_superseis(conn, productos: list[dict]) -> None:
    """
    Carga una lista de productos de Superseis (dicts con las mismas
    claves que devuelve scraper_superseis.fetch_category/fetch_catalogo_completo).
    Si los dicts no traen 'ean'/'marca' (pasada rapida, sin --enrich),
    el producto igual se actualiza de precio -- el producto_id que ya
    tenia de una carga anterior con EAN se mantiene (ver upsert_producto_tienda:
    COALESCE(existente, nuevo), nunca lo pisa con None).
    """
    supermercado_id = asegurar_supermercado(conn, "superseis")

    total = len(productos)
    for i, fila in enumerate(productos, 1):
        ean = fila.get("ean") or None
        precio = fila.get("precio")
        if not precio or not str(precio).isdigit():
            continue

        producto_id = buscar_o_crear_producto(
            conn,
            ean,
            fila["nombre"],
            fila.get("marca"),
            categoria=None,  # Superseis no tiene una taxonomía limpia como Biggie
            imagen_url=fila.get("imagen_url"),
            preferir_imagen=False,  # Superseis solo completa si no había imagen
        )
        pt_id = upsert_producto_tienda(
            conn,
            producto_id=producto_id,
            supermercado_id=supermercado_id,
            id_externo=fila["product_id"],
            url=fila.get("url"),
            nombre_en_tienda=fila["nombre"],
            marca_en_tienda=fila.get("marca"),
            categoria_en_tienda=None,
        )
        insertar_precio(conn, pt_id, int(precio))

        if i % 500 == 0:
            conn.commit()
            print(f"  [{i}/{total}] cargados")

    conn.commit()
    print(f"Listo: {total} filas de Superseis procesadas.")


def cargar_biggie(conn, ruta_csv: str) -> None:
    """Wrapper para uso manual desde la terminal: lee un CSV y carga."""
    with open(ruta_csv, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    cargar_productos_biggie(conn, filas)


def cargar_superseis(conn, ruta_csv: str) -> None:
    """Wrapper para uso manual desde la terminal: lee un CSV y carga."""
    with open(ruta_csv, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    cargar_productos_superseis(conn, filas)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("biggie", "superseis"):
        print("Uso: python cargar_datos.py [biggie|superseis] nombre_del_csv.csv")
        sys.exit(1)

    tienda = sys.argv[1]
    nombre_csv = sys.argv[2]
    ruta_csv = os.path.join(OUTPUT_DIR, nombre_csv)

    conexion = get_connection()
    try:
        if tienda == "biggie":
            cargar_biggie(conexion, ruta_csv)
        else:
            cargar_superseis(conexion, ruta_csv)
    finally:
        conexion.close()
