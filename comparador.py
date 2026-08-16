# -*- coding: utf-8 -*-
"""
Comparador Duffel vs Google Flights para la ruta GDL -> Houston.

Consulta la API de Duffel (offer requests) con los mismos parametros del
tracker (viaje redondo, 1 adulto) y compara contra la ultima lectura de
Google Flights guardada en data/.

Uso:  python comparador.py
Requiere token de Duffel (https://duffel.com) en .duffel_token o en la
variable de entorno DUFFEL_TOKEN. Con un token duffel_test_* los resultados
son de la aerolinea ficticia "Duffel Airways" (precios NO reales): sirven
para validar la integracion. Con un token live la comparativa es real.
"""

import glob
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE, ".duffel_token")
DATA_DIR = os.path.join(BASE, "data")
DUFFEL = "https://api.duffel.com"

sys.path.insert(0, BASE)
import tracker  # noqa: E402  (reutiliza config y extraccion de Google)


def token_duffel():
    tok = os.environ.get("DUFFEL_TOKEN", "").strip()
    if not tok and os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, encoding="utf-8") as f:
            tok = f.read().strip()
    if not tok:
        print("ERROR: falta el token de Duffel.")
        print("1. Crea una cuenta en https://duffel.com/signup")
        print("2. Dashboard -> Developer test mode -> Access tokens")
        print("3. Guarda el token en el archivo .duffel_token")
        sys.exit(1)
    return tok


def ofertas_duffel(tok, cfg, destino):
    cuerpo = json.dumps({
        "data": {
            "slices": [
                {"origin": cfg["origen"], "destination": destino,
                 "departure_date": cfg["fecha_ida"]},
                {"origin": destino, "destination": cfg["origen"],
                 "departure_date": cfg["fecha_regreso"]},
            ],
            "passengers": [{"type": "adult"}] * int(cfg.get("adultos", 1)),
            "cabin_class": "economy",
        }
    }).encode()
    req = urllib.request.Request(
        f"{DUFFEL}/air/offer_requests?return_offers=true", data=cuerpo,
        headers={
            "Authorization": f"Bearer {tok}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)["data"].get("offers", [])
    except urllib.error.HTTPError as e:
        print(f"  aviso: {cfg['origen']}->{destino} HTTP {e.code}: "
              f"{e.read().decode()[:300]}")
        return []


def resumen_oferta(of):
    ida = of["slices"][0]
    segs = ida.get("segments", [])
    nombres = sorted({(s.get("marketing_carrier") or {}).get("name", "?")
                      for s in segs})
    return {
        "precio": float(of["total_amount"]),
        "moneda": of.get("total_currency", ""),
        "aerolinea": " + ".join(nombres) or of.get("owner", {}).get("name", "?"),
        "escalas": max(0, len(segs) - 1),
    }


def mejor(lista):
    return min(lista, key=lambda o: o["precio"]) if lista else None


def main():
    cfg = tracker.cargar_config()
    tok = token_duffel()
    modo = "PRUEBA (Duffel Airways, precios ficticios)" \
        if tok.startswith("duffel_test") else "LIVE (precios reales)"
    print(f"Consultando Duffel en modo {modo}...")

    crudas = []
    for destino in ("IAH", "HOU"):
        print(f"  {cfg['origen']} -> {destino}...")
        crudas += ofertas_duffel(tok, cfg, destino)

    if not crudas:
        print("Duffel no devolvio ofertas para esta ruta.")
        sys.exit(1)

    du_todos = [resumen_oferta(o) for o in crudas]
    du_dir = [r for r in du_todos if r["escalas"] == 0]
    d_gen, d_dir = mejor(du_todos), mejor(du_dir)

    ultimo_json = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))[-1]
    with open(ultimo_json, encoding="utf-8") as f:
        g_gen, g_dir = tracker.extraer_mejores(json.load(f))
    fecha_google = os.path.basename(ultimo_json).replace(".json", "")

    def celda(r, con_moneda=True):
        if not r:
            return "—"
        m = r.get("moneda", "") if con_moneda else ""
        return f"${r['precio']:,.0f} {m}".strip()

    print()
    print("=" * 64)
    print(f"  COMPARATIVA GDL -> HOUSTON  ({cfg['fecha_ida']} / {cfg['fecha_regreso']})")
    print("=" * 64)
    fila = "{:<22}{:>18}{:>22}"
    print(fila.format("", "GOOGLE FLIGHTS", "DUFFEL"))
    print(fila.format("Mas barato general",
                      f"${g_gen['precio']:,.0f} MXN" if g_gen else "—",
                      celda(d_gen)))
    print(fila.format("  aerolinea",
                      g_gen["aerolinea"][:17] if g_gen else "—",
                      d_gen["aerolinea"][:21] if d_gen else "—"))
    print(fila.format("Directo mas barato",
                      f"${g_dir['precio']:,.0f} MXN" if g_dir else "—",
                      celda(d_dir)))
    print(fila.format("  aerolinea",
                      g_dir["aerolinea"][:17] if g_dir else "—",
                      d_dir["aerolinea"][:21] if d_dir else "—"))
    print("-" * 64)
    aero = sorted({r["aerolinea"] for r in du_todos})
    print(f"Ofertas Duffel: {len(du_todos)} ({len(du_dir)} directas)")
    print(f"Aerolineas vistas por Duffel: {', '.join(aero)}")
    print(f"(lectura de Google del archivo {fecha_google})")
    if tok.startswith("duffel_test"):
        print()
        print("NOTA: token de PRUEBA -> Duffel responde con su aerolinea")
        print("ficticia y precios inventados. La integracion queda validada;")
        print("para la comparativa real hay que activar el modo live y")
        print("cambiar el token en .duffel_token.")


if __name__ == "__main__":
    main()
