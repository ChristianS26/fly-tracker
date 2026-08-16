# -*- coding: utf-8 -*-
"""
Comparador Amadeus vs Google Flights para la ruta GDL -> Houston.

Consulta la API de Amadeus Self-Service (Flight Offers Search) para los mismos
parametros del tracker (viaje redondo, 1 adulto, MXN) y compara contra la
ultima lectura de Google Flights guardada en data/.

Uso:  python comparador.py
Requiere credenciales de Amadeus (gratis en https://developers.amadeus.com):
archivo .amadeus_creds con dos lineas (API Key y API Secret), o variables
de entorno AMADEUS_CLIENT_ID y AMADEUS_CLIENT_SECRET.
"""

import glob
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CREDS_PATH = os.path.join(BASE, ".amadeus_creds")
DATA_DIR = os.path.join(BASE, "data")
AMADEUS = "https://test.api.amadeus.com"

sys.path.insert(0, BASE)
import tracker  # noqa: E402  (reutiliza config y extraccion de Google)


def credenciales():
    cid = os.environ.get("AMADEUS_CLIENT_ID", "").strip()
    sec = os.environ.get("AMADEUS_CLIENT_SECRET", "").strip()
    if not (cid and sec) and os.path.exists(CREDS_PATH):
        lineas = [l.strip() for l in open(CREDS_PATH, encoding="utf-8")
                  if l.strip()]
        if len(lineas) >= 2:
            cid, sec = lineas[0], lineas[1]
    if not (cid and sec):
        print("ERROR: faltan credenciales de Amadeus.")
        print("1. Registrate gratis en https://developers.amadeus.com")
        print("2. My Self-Service Workspace -> Create new app")
        print("3. Guarda API Key y API Secret (una por linea) en .amadeus_creds")
        sys.exit(1)
    return cid, sec


def token(cid, sec):
    datos = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": cid, "client_secret": sec,
    }).encode()
    req = urllib.request.Request(
        f"{AMADEUS}/v1/security/oauth2/token", data=datos,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def ofertas(tok, cfg, destino, solo_directos):
    params = {
        "originLocationCode": cfg["origen"],
        "destinationLocationCode": destino,
        "departureDate": cfg["fecha_ida"],
        "returnDate": cfg["fecha_regreso"],
        "adults": str(cfg.get("adultos", 1)),
        "currencyCode": cfg.get("moneda", "MXN"),
        "max": "20",
    }
    if solo_directos:
        params["nonStop"] = "true"
    url = f"{AMADEUS}/v2/shopping/flight-offers?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get("data", [])
    except urllib.error.HTTPError as e:
        print(f"  aviso: {destino} ({'directos' if solo_directos else 'todos'}) "
              f"-> HTTP {e.code}: {e.read().decode()[:200]}")
        return []


def resumen_oferta(of, aerolineas):
    precio = float(of["price"]["grandTotal"])
    ida = of["itineraries"][0]
    segs = ida["segments"]
    codigos = sorted({s["carrierCode"] for s in segs})
    nombres = [aerolineas.get(c, c) for c in codigos]
    return {
        "precio": precio,
        "aerolinea": " + ".join(nombres),
        "escalas": len(segs) - 1,
        "duracion": ida.get("duration", "").replace("PT", "").lower(),
    }


def nombres_aerolineas(tok, codigos):
    if not codigos:
        return {}
    url = (f"{AMADEUS}/v1/reference-data/airlines?airlineCodes="
           + ",".join(sorted(codigos)))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r).get("data", [])
        return {a["iataCode"]: a.get("commonName") or a.get("businessName", a["iataCode"])
                for a in data}
    except Exception:
        return {}


def mejor(lista):
    return min(lista, key=lambda o: o["precio"]) if lista else None


def main():
    cfg = tracker.cargar_config()
    cid, sec = credenciales()
    print("Autenticando con Amadeus (entorno de prueba)...")
    tok = token(cid, sec)

    todos, directos = [], []
    for destino in ("IAH", "HOU"):
        print(f"Consultando {cfg['origen']} -> {destino}...")
        todos += ofertas(tok, cfg, destino, False)
        directos += ofertas(tok, cfg, destino, True)

    if not todos:
        print("Amadeus no devolvio ofertas (el entorno de prueba tiene "
              "cobertura parcial).")
        sys.exit(1)

    codigos = set()
    for of in todos + directos:
        for s in of["itineraries"][0]["segments"]:
            codigos.add(s["carrierCode"])
    nombres = nombres_aerolineas(tok, codigos)

    am_todos = [resumen_oferta(o, nombres) for o in todos]
    am_dir = [resumen_oferta(o, nombres) for o in directos]
    if not am_dir:  # por si nonStop no devolvio nada, filtra de los generales
        am_dir = [r for r in am_todos if r["escalas"] == 0]
    a_gen, a_dir = mejor(am_todos), mejor(am_dir)

    ultimo_json = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))[-1]
    with open(ultimo_json, encoding="utf-8") as f:
        g_gen, g_dir = tracker.extraer_mejores(json.load(f))
    fecha_google = os.path.basename(ultimo_json).replace(".json", "")

    moneda = cfg.get("moneda", "MXN")
    print()
    print("=" * 62)
    print(f"  COMPARATIVA GDL -> HOUSTON  ({cfg['fecha_ida']} / {cfg['fecha_regreso']})")
    print("=" * 62)
    print(f"{'':22}{'GOOGLE FLIGHTS':>18}{'AMADEUS (test)':>20}")
    fila = "{:<22}{:>18}{:>20}"
    print(fila.format(
        "Mas barato general",
        f"${g_gen['precio']:,.0f} {moneda}" if g_gen else "—",
        f"${a_gen['precio']:,.0f} {moneda}" if a_gen else "—"))
    print(fila.format(
        "  aerolinea",
        g_gen["aerolinea"][:17] if g_gen else "—",
        a_gen["aerolinea"][:19] if a_gen else "—"))
    print(fila.format(
        "Directo mas barato",
        f"${g_dir['precio']:,.0f} {moneda}" if g_dir else "—",
        f"${a_dir['precio']:,.0f} {moneda}" if a_dir else "—"))
    print(fila.format(
        "  aerolinea",
        g_dir["aerolinea"][:17] if g_dir else "—",
        a_dir["aerolinea"][:19] if a_dir else "—"))
    print("-" * 62)
    aero_am = sorted({r["aerolinea"] for r in am_todos})
    print(f"Aerolineas vistas por Amadeus: {', '.join(aero_am)}")
    print(f"(lectura de Google del archivo {fecha_google})")
    print()
    print("Nota: el entorno de PRUEBA de Amadeus usa datos cacheados y una")
    print("cobertura parcial de aerolineas (las low-cost que no distribuyen")
    print("por GDS, como Viva Aerobus, pueden no aparecer). En produccion la")
    print("cobertura y frescura son mayores.")


if __name__ == "__main__":
    main()
