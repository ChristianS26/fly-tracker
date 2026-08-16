# -*- coding: utf-8 -*-
"""
Rastreador de precios de vuelo GDL -> Houston (ida 2026-10-26, regreso 2026-11-18).

Consulta Google Flights via SerpAPI, guarda cada lectura en historial.csv,
archiva la respuesta cruda en data/ y regenera el reporte (index.html /
reporte.html) con la grafica de fluctuacion. Rastrea dos series: el precio
mas barato en general y el vuelo directo mas barato (escalas sobre la ida).

Uso:  python tracker.py
Requiere API key de SerpAPI en .serpapi_key o variable SERPAPI_KEY.
"""

import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
KEY_PATH = os.path.join(BASE, ".serpapi_key")
TG_TOKEN_PATH = os.path.join(BASE, ".telegram_token")
TG_CHAT_PATH = os.path.join(BASE, ".telegram_chat")
CSV_PATH = os.path.join(BASE, "historial.csv")
DATA_DIR = os.path.join(BASE, "data")
REPORT_PATH = os.path.join(BASE, "reporte.html")
INDEX_PATH = os.path.join(BASE, "index.html")

CSV_FIELDS = [
    "fecha_hora", "precio", "aerolinea", "escalas", "duracion_min",
    "precio_directo", "aerolinea_directo",
    "nivel_precio", "tipico_min", "tipico_max",
]

MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
         "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]

CIUDADES = {
    "GDL": "Guadalajara",
    "IAH,HOU": "Houston · IAH y HOU",
    "HOU": "Houston",
    "IAH": "Houston",
}

NIVELES = {
    "low": ("BAJO", "nivel-bajo",
            "Buen momento para comprar: el precio está por debajo de lo típico."),
    "typical": ("TÍPICO", "nivel-tipico",
                "Precio dentro del rango normal para esta ruta — sigue vigilando."),
    "high": ("ALTO", "nivel-alto",
             "Precio por arriba de lo típico — conviene esperar unos días."),
}


def fmt_fecha(iso):
    y, m, d = iso.split("-")
    return f"{int(d)} {MESES[int(m) - 1]} {y}"


def cargar_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    key = os.environ.get("SERPAPI_KEY") or cfg.get("serpapi_key", "")
    if not key.strip() and os.path.exists(KEY_PATH):
        with open(KEY_PATH, encoding="utf-8") as f:
            key = f.read()
    key = key.strip()
    if not key or "PON_TU_API_KEY" in key:
        print("ERROR: falta la API key de SerpAPI.")
        print("1. Crea una cuenta gratis en https://serpapi.com/users/sign_up")
        print("2. Copia tu key de https://serpapi.com/manage-api-key")
        print("3. Pegala en el archivo .serpapi_key (o variable de entorno SERPAPI_KEY)")
        sys.exit(1)
    cfg["serpapi_key"] = key
    return cfg


def consultar(cfg):
    params = {
        "engine": "google_flights",
        "departure_id": cfg["origen"],
        "arrival_id": cfg["destino"],
        "outbound_date": cfg["fecha_ida"],
        "return_date": cfg["fecha_regreso"],
        "type": "1",  # viaje redondo
        "adults": str(cfg.get("adultos", 1)),
        "currency": cfg.get("moneda", "MXN"),
        "hl": "es",
        "api_key": cfg["serpapi_key"],
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "fly-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _resumen(vuelo):
    tramos = vuelo.get("flights", [])
    aerolineas = sorted({t.get("airline", "?") for t in tramos})
    return {
        "precio": vuelo["price"],
        "aerolinea": " + ".join(aerolineas),
        "escalas": max(0, len(tramos) - 1),
        "duracion_min": vuelo.get("total_duration", ""),
    }


def extraer_mejores(data):
    """Devuelve (mas_barato, directo_mas_barato); cualquiera puede ser None."""
    vuelos = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    con_precio = [v for v in vuelos if v.get("price")]
    if not con_precio:
        return None, None
    mejor = _resumen(min(con_precio, key=lambda v: v["price"]))
    directos = [v for v in con_precio if len(v.get("flights", [])) == 1]
    directo = _resumen(min(directos, key=lambda v: v["price"])) if directos else None
    return mejor, directo


def guardar_csv(fila):
    nuevo = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if nuevo:
            w.writeheader()
        w.writerow(fila)


def _leer_secreto(env_var, ruta):
    valor = os.environ.get(env_var, "").strip()
    if not valor and os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            valor = f.read().strip()
    return valor


def notificar_telegram(texto):
    """Envia un mensaje al grupo de Telegram; si no hay bot configurado, no hace nada."""
    token = _leer_secreto("TELEGRAM_BOT_TOKEN", TG_TOKEN_PATH)
    chat = _leer_secreto("TELEGRAM_CHAT_ID", TG_CHAT_PATH)
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    datos = urllib.parse.urlencode({
        "chat_id": chat, "text": texto,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, data=datos), timeout=30):
            pass
        print("Alerta enviada al grupo de Telegram.")
        return True
    except Exception as e:
        print("Aviso: fallo el envio a Telegram:", e)
        return False


def leer_historial():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("precio")]


def generar_reporte(historial, cfg):
    puntos = [
        {"t": r["fecha_hora"], "p": float(r["precio"]),
         "pd": float(r["precio_directo"]) if r.get("precio_directo") else None,
         "a": r.get("aerolinea", ""),
         "ad": r.get("aerolinea_directo", ""),
         "e": r.get("escalas", "")}
        for r in historial
    ]
    ultimo = puntos[-1] if puntos else None
    minimo = min(puntos, key=lambda x: x["p"]) if puntos else None
    directos = [x for x in puntos if x["pd"] is not None]
    ult_directo = directos[-1] if directos else None
    tip_min = historial[-1].get("tipico_min") if historial else ""
    tip_max = historial[-1].get("tipico_max") if historial else ""

    nivel = (historial[-1].get("nivel_precio") or "").lower() if historial else ""
    nivel_txt, nivel_clase, consejo = NIVELES.get(
        nivel, ("—", "nivel-na", "Aún no hay datos del nivel de precio."))

    def celda_precio(v):
        return f"${float(v):,.0f}" if v else "—"

    filas_tabla = "\n".join(
        f"<tr><td>{r['fecha_hora']}</td><td class='num'>${float(r['precio']):,.0f}</td>"
        f"<td>{r.get('aerolinea','')}</td>"
        f"<td class='num'>{celda_precio(r.get('precio_directo'))}</td>"
        f"<td>{r.get('aerolinea_directo','')}</td></tr>"
        for r in reversed(historial)
    )

    origen = cfg["origen"]
    destino = cfg["destino"]
    dst_code = "HOU" if "HOU" in destino or "IAH" in destino else destino.split(",")[0]

    html = HTML_TEMPLATE
    html = html.replace("__DATOS__", json.dumps(puntos, ensure_ascii=False))
    html = html.replace("__ORI_CODE__", origen)
    html = html.replace("__ORI_CITY__", CIUDADES.get(origen, origen))
    html = html.replace("__DST_CODE__", dst_code)
    html = html.replace("__DST_CITY__", CIUDADES.get(destino, destino))
    html = html.replace("__IDA__", fmt_fecha(cfg["fecha_ida"]))
    html = html.replace("__REGRESO__", fmt_fecha(cfg["fecha_regreso"]))
    html = html.replace("__MONEDA__", cfg.get("moneda", "MXN"))
    html = html.replace("__NIVEL_TXT__", nivel_txt)
    html = html.replace("__NIVEL_CLASE__", nivel_clase)
    html = html.replace("__CONSEJO__", consejo)
    html = html.replace("__ACTUAL__", f"${ultimo['p']:,.0f}" if ultimo else "—")
    html = html.replace("__ACT_AERO__", ultimo["a"] if ultimo else "")
    html = html.replace("__DIRECTO__", f"${ult_directo['pd']:,.0f}" if ult_directo else "—")
    html = html.replace("__DIR_AERO__", ult_directo["ad"] if ult_directo else "")
    html = html.replace("__MINIMO__", f"${minimo['p']:,.0f}" if minimo else "—")
    html = html.replace("__MIN_FECHA__", minimo["t"] if minimo else "")
    html = html.replace("__TIPICO__",
                        f"${float(tip_min):,.0f} – ${float(tip_max):,.0f}"
                        if tip_min and tip_max else "—")
    html = html.replace("__TABLA__", filas_tabla)
    html = html.replace("__ACTUALIZADO__", ultimo["t"] if ultimo else "sin datos")

    for ruta in (REPORT_PATH, INDEX_PATH):
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(html)


HTML_TEMPLATE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigía de Vuelo · GDL–HOU</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,600;0,9..144,700;1,9..144,500&family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{color-scheme:light;
    --paper:#f3f5f9; --card:#ffffff; --card2:#f6f8fb;
    --ink:#16243d; --ink2:#46536b; --muted:#7b8494;
    --line:#e2e6ee; --grid:#eef1f6; --axis:#ccd3de;
    --sky:#2a78d6; --coral:#eb6834; --coral-ink:#b8431a;
    --bueno:#0a7d0a;
    --sombra:0 1px 2px rgba(22,36,61,.05),0 8px 24px -12px rgba(22,36,61,.16)}
  *{box-sizing:border-box;margin:0}
  body{background:var(--paper);color:var(--ink);
    background-image:radial-gradient(circle at 1px 1px, rgba(22,36,61,.05) 1px, transparent 0);
    background-size:22px 22px;
    font:15px/1.55 "Archivo",sans-serif;
    padding:32px 20px 48px;max-width:940px;margin:0 auto}
  .brand{margin-bottom:16px;animation:rise .5s ease both}
  .brand .fila{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
  .brand h1{font:italic 500 1.35rem/1 "Fraunces",serif;letter-spacing:.01em}
  .brand .tag-brand{font:500 .68rem/1 "IBM Plex Mono",monospace;color:var(--muted);
    letter-spacing:.14em;text-transform:uppercase}
  .brand .tagline{font:400 .92rem/1.5 "Archivo",sans-serif;color:var(--ink2);
    margin-top:6px;max-width:56ch}

  /* ---------- pase de abordar ---------- */
  .pass{display:flex;background:var(--card);border:1px solid var(--line);
    border-radius:14px;box-shadow:var(--sombra);overflow:hidden;
    animation:rise .55s .05s ease both}
  .pass-main{flex:1;padding:20px 26px 22px;min-width:0}
  .pass-top{display:flex;justify-content:space-between;gap:12px;
    font:500 .66rem/1 "IBM Plex Mono",monospace;letter-spacing:.14em;
    color:var(--muted);text-transform:uppercase;
    border-bottom:1px dashed var(--line);padding-bottom:12px}
  .route{display:flex;align-items:center;gap:18px;padding:20px 0 8px}
  .apt{text-align:left}
  .apt.der{text-align:right}
  .apt .code{font:700 clamp(2.2rem,7vw,3.4rem)/1 "Archivo",sans-serif;
    letter-spacing:.02em}
  .apt .city{font:500 .72rem/1.3 "IBM Plex Mono",monospace;color:var(--ink2);
    letter-spacing:.06em;margin-top:6px;text-transform:uppercase}
  .arc{flex:1;position:relative;height:64px;min-width:120px}
  .arc svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
  .arc .avion{position:absolute;top:50%;left:0;font-size:1.15rem;
    color:var(--coral-ink);transform:translate(-50%,-58%);
    animation:volar 2.4s .4s cubic-bezier(.45,.05,.35,1) both}
  @keyframes volar{
    0%{left:4%;transform:translate(-50%,-30%) rotate(8deg)}
    50%{transform:translate(-50%,-95%) rotate(0)}
    100%{left:96%;transform:translate(-50%,-30%) rotate(-8deg)}}
  .fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
    gap:14px 20px;border-top:1px dashed var(--line);padding-top:14px}
  .fields span{display:block;font:500 .62rem/1 "IBM Plex Mono",monospace;
    letter-spacing:.14em;color:var(--muted);text-transform:uppercase;
    margin-bottom:5px}
  .fields b{font:600 .95rem/1.2 "Archivo",sans-serif}
  .chip{display:inline-flex;align-items:center;gap:7px;
    font:600 .78rem/1 "IBM Plex Mono",monospace;letter-spacing:.08em;
    border:1.5px solid var(--ink);border-radius:999px;padding:5px 12px}
  .chip::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--ink)}
  .chip.nivel-bajo{border-color:var(--bueno);color:var(--bueno)}
  .chip.nivel-bajo::before{background:var(--bueno)}
  .chip.nivel-alto{border-color:var(--coral-ink);color:var(--coral-ink)}
  .chip.nivel-alto::before{background:var(--coral-ink)}
  .pass-stub{width:118px;flex:none;position:relative;background:var(--card2);
    border-left:2px dashed var(--axis);display:flex;flex-direction:column;
    align-items:center;justify-content:space-between;padding:16px 0}
  .pass-stub::before,.pass-stub::after{content:"";position:absolute;left:-10px;
    width:18px;height:18px;border-radius:50%;background:var(--paper);
    border:1px solid var(--line)}
  .pass-stub::before{top:-10px}
  .pass-stub::after{bottom:-10px}
  .barcode{width:64px;height:110px;
    background:repeating-linear-gradient(0deg,var(--ink) 0 2px,transparent 2px 5px),
               repeating-linear-gradient(0deg,var(--ink) 0 1px,transparent 1px 9px);
    opacity:.85}
  .stub-txt{font:500 .6rem/1 "IBM Plex Mono",monospace;color:var(--muted);
    letter-spacing:.18em;writing-mode:vertical-rl;text-transform:uppercase}

  .consejo{display:flex;align-items:center;gap:10px;margin:16px 0 22px;
    font:500 .9rem/1.4 "Archivo",sans-serif;color:var(--ink2);
    animation:rise .55s .12s ease both}
  .consejo::before{content:"◆";color:var(--coral);font-size:.7rem}

  /* ---------- boletos de resumen ---------- */
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
    gap:14px;margin-bottom:22px}
  .tile{background:var(--card);border:1px solid var(--line);border-radius:12px;
    padding:16px 18px 14px;box-shadow:var(--sombra);position:relative;
    animation:rise .55s ease both}
  .tile:nth-child(1){animation-delay:.16s;border-top:3px solid var(--sky)}
  .tile:nth-child(2){animation-delay:.22s;border-top:3px solid var(--coral)}
  .tile:nth-child(3){animation-delay:.28s}
  .tile:nth-child(4){animation-delay:.34s}
  .tile .k{font:500 .62rem/1.3 "IBM Plex Mono",monospace;letter-spacing:.13em;
    color:var(--muted);text-transform:uppercase}
  .tile .v{font:600 1.7rem/1.15 "IBM Plex Mono",monospace;margin-top:8px;
    letter-spacing:-.01em}
  .tile .v.chico{font-size:1.15rem;padding-top:6px}
  .tile .d{font:400 .8rem/1.35 "Archivo",sans-serif;color:var(--ink2);margin-top:4px}

  /* ---------- tarjetas ---------- */
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
    padding:20px 22px;margin-bottom:22px;box-shadow:var(--sombra);
    animation:rise .55s .3s ease both}
  .card h2{font:600 1.15rem/1.2 "Fraunces",serif;margin-bottom:4px}
  .card .nota{font-size:.82rem;color:var(--muted);margin-bottom:12px}
  .legend{display:flex;gap:20px;font:500 .78rem/1 "Archivo",sans-serif;
    color:var(--ink2);margin-bottom:10px;flex-wrap:wrap}
  .legend .sw{display:inline-block;width:16px;height:3px;border-radius:2px;
    vertical-align:middle;margin-right:7px}
  #chartwrap{position:relative}
  svg.grafica{display:block;width:100%;height:auto}
  #tip{position:absolute;pointer-events:none;display:none;
    background:var(--card);border:1px solid var(--ink);border-radius:8px;
    padding:7px 11px;font-size:.78rem;box-shadow:var(--sombra);
    white-space:nowrap;z-index:2}
  #tip .tp{font:600 .82rem/1.5 "IBM Plex Mono",monospace}
  #tip .tt{color:var(--ink2);font-family:"Archivo",sans-serif}
  table{width:100%;border-collapse:collapse;font-size:.84rem}
  th{text-align:left;font:500 .64rem/1.3 "IBM Plex Mono",monospace;
    letter-spacing:.12em;text-transform:uppercase;color:var(--muted);
    border-bottom:2px solid var(--line);padding:7px 9px}
  td{padding:6px 9px;border-bottom:1px solid var(--grid)}
  tr:hover td{background:var(--card2)}
  .num{text-align:right;font-family:"IBM Plex Mono",monospace;
    font-variant-numeric:tabular-nums}
  th.num{text-align:right}
  .foot{color:var(--muted);font-size:.76rem;margin-top:6px;
    border-top:1px dashed var(--line);padding-top:12px}
  @keyframes rise{from{opacity:0;transform:translateY(14px)}}
  @media (max-width:640px){
    body{padding:20px 12px 36px}
    .pass-main{padding:14px 16px 16px}
    .pass-top{font-size:.56rem;letter-spacing:.1em;padding-bottom:10px}
    .route{gap:8px;padding:14px 0 6px}
    .apt .code{font-size:clamp(1.7rem,9vw,2.4rem)}
    .apt .city{font-size:.6rem}
    .arc{min-width:60px;height:44px}
    .arc .avion{font-size:.95rem}
    .fields{grid-template-columns:1fr 1fr;gap:11px 12px;padding-top:12px}
    .fields span{font-size:.56rem}
    .fields b{font-size:.85rem}
    .chip{font-size:.68rem;padding:4px 10px}
    .pass-stub{width:64px;padding:12px 0}
    .barcode{width:34px;height:78px}
    .stub-txt{font-size:.52rem;letter-spacing:.14em}
    .tiles{grid-template-columns:1fr 1fr;gap:10px}
    .tile{padding:12px 13px 11px}
    .tile .v{font-size:1.3rem}
    .tile .v.chico{font-size:.98rem}
    .card{padding:16px 14px}
    .card h2{font-size:1.02rem}
    .brand .tagline{font-size:.88rem}}
  @media (prefers-reduced-motion:reduce){
    *{animation:none!important}}
</style></head><body>

<div class="brand">
  <div class="fila"><h1>Vigía de Vuelo</h1><span class="tag-brand">rastreador de tarifas</span></div>
  <p class="tagline">Seguimiento automático del precio del vuelo redondo
  <b>Guadalajara → Houston</b> (26 oct – 18 nov 2026). Se consulta Google Flights
  dos veces al día para detectar el mejor momento de compra.</p>
</div>

<header class="pass">
  <div class="pass-main">
    <div class="pass-top"><span>Tarjeta de monitoreo</span><span>Viaje redondo · __MONEDA__</span></div>
    <div class="route">
      <div class="apt"><div class="code">__ORI_CODE__</div><div class="city">__ORI_CITY__</div></div>
      <div class="arc">
        <svg viewBox="0 0 300 64" aria-hidden="true">
          <path d="M8 52 Q150 -18 292 52" fill="none" stroke="#ccd3de"
            stroke-width="2" stroke-dasharray="1 7" stroke-linecap="round"/>
          <circle cx="8" cy="52" r="3.5" fill="#16243d"/>
          <circle cx="292" cy="52" r="3.5" fill="none" stroke="#16243d" stroke-width="2"/>
        </svg>
        <span class="avion">✈</span>
      </div>
      <div class="apt der"><div class="code">__DST_CODE__</div><div class="city">__DST_CITY__</div></div>
    </div>
    <div class="fields">
      <div><span>Salida</span><b>__IDA__</b></div>
      <div><span>Regreso</span><b>__REGRESO__</b></div>
      <div><span>Estado del precio</span><b class="chip __NIVEL_CLASE__">__NIVEL_TXT__</b></div>
      <div><span>Actualizado</span><b>__ACTUALIZADO__</b></div>
    </div>
  </div>
  <div class="pass-stub">
    <span class="stub-txt">GDL–HOU</span>
    <div class="barcode"></div>
    <span class="stub-txt">2026</span>
  </div>
</header>

<p class="consejo">__CONSEJO__</p>

<div class="tiles">
  <div class="tile"><div class="k">Más barato hoy</div><div class="v">__ACTUAL__</div>
    <div class="d">__ACT_AERO__</div></div>
  <div class="tile"><div class="k">Directo más barato</div><div class="v">__DIRECTO__</div>
    <div class="d">__DIR_AERO__</div></div>
  <div class="tile"><div class="k">Mínimo registrado</div><div class="v">__MINIMO__</div>
    <div class="d">__MIN_FECHA__</div></div>
  <div class="tile"><div class="k">Rango típico según Google</div>
    <div class="v chico">__TIPICO__</div>
    <div class="d">para esta ruta y fechas</div></div>
</div>

<div class="card"><h2>Fluctuación del precio</h2>
  <p class="nota">Viaje redondo completo; pasa el cursor sobre la línea para ver cada lectura.</p>
  <div class="legend">
    <span><span class="sw" style="background:var(--sky)"></span>Más barato (con o sin escalas)</span>
    <span><span class="sw" style="background:var(--coral)"></span>Directo más barato</span>
  </div>
  <div id="chartwrap"><svg id="chart" class="grafica" viewBox="0 0 860 300"></svg><div id="tip"></div></div>
</div>

<div class="card"><h2>Historial de lecturas</h2>
  <p class="nota">Las filas «Google (histórico)» son el historial de 61 días que publica Google Flights.</p>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>Fecha de consulta</th><th class="num">Más barato</th><th>Aerolínea</th><th class="num">Directo</th><th>Aerolínea</th></tr></thead>
    <tbody>__TABLA__</tbody>
  </table></div>
</div>

<p class="foot">Datos de Google Flights vía SerpAPI · se actualiza automáticamente a las
9:00 y 21:00 (hora de Guadalajara) · generado por tracker.py</p>

<script>
const D = __DATOS__;
const svg = document.getElementById('chart'), tip = document.getElementById('tip');
const W=860,H=300,m={t:16,r:16,b:34,l:68};
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function fmt(n){return '$'+Math.round(n).toLocaleString('es-MX')}
function draw(){
  svg.innerHTML='';
  if(D.length===0){
    svg.innerHTML='<text x="430" y="150" text-anchor="middle" fill="'+css('--muted')+'" font-size="14">Aún no hay lecturas — corre tracker.py</text>';
    return [];
  }
  const vals=D.map(d=>d.p).concat(D.filter(d=>d.pd!=null).map(d=>d.pd));
  let lo=Math.min(...vals), hi=Math.max(...vals);
  if(lo===hi){lo-=lo*0.05||100; hi+=hi*0.05||100}
  const pad=(hi-lo)*0.12; lo-=pad; hi+=pad;
  const X=i=>D.length<2 ? (m.l+(W-m.l-m.r)/2) : m.l+(W-m.l-m.r)*i/(D.length-1);
  const Y=p=>m.t+(H-m.t-m.b)*(1-(p-lo)/(hi-lo));
  let g='';
  const ticks=4;
  for(let k=0;k<=ticks;k++){
    const v=lo+(hi-lo)*k/ticks, y=Y(v);
    g+='<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+y+'" y2="'+y+'" stroke="'+css('--grid')+'" stroke-width="1"/>';
    g+='<text x="'+(m.l-10)+'" y="'+(y+4)+'" text-anchor="end" fill="'+css('--muted')+'" font-size="11" font-family="IBM Plex Mono,monospace">'+fmt(v)+'</text>';
  }
  g+='<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+(H-m.b)+'" y2="'+(H-m.b)+'" stroke="'+css('--axis')+'" stroke-width="1"/>';
  const step=Math.max(1,Math.ceil(D.length/6));
  D.forEach((d,i)=>{
    if(i%step===0||i===D.length-1){
      g+='<text x="'+X(i)+'" y="'+(H-m.b+18)+'" text-anchor="middle" fill="'+css('--muted')+'" font-size="11" font-family="IBM Plex Mono,monospace">'+d.t.slice(5,10)+'</text>';
    }
  });
  function path(get){
    let s='',pen=false;
    D.forEach((d,i)=>{
      const v=get(d);
      if(v==null){pen=false;return}
      s+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)+' ';
      pen=true;
    });
    return s;
  }
  g+='<path d="'+path(d=>d.p)+'" fill="none" stroke="'+css('--sky')+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
  g+='<path d="'+path(d=>d.pd)+'" fill="none" stroke="'+css('--coral')+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
  const pts=[];
  const dense = D.length>40;
  D.forEach((d,i)=>{
    const cx=X(i);
    pts.push({cx,d,cy:Y(d.p)});
    if(!dense||i===D.length-1){
      g+='<circle cx="'+cx+'" cy="'+Y(d.p)+'" r="3.5" fill="'+css('--sky')+'" stroke="'+css('--card')+'" stroke-width="2"/>';
      if(d.pd!=null) g+='<circle cx="'+cx+'" cy="'+Y(d.pd)+'" r="3.5" fill="'+css('--coral')+'" stroke="'+css('--card')+'" stroke-width="2"/>';
    }
  });
  const ps=D.map(d=>d.p);
  const minP=Math.min(...ps), iMin=ps.indexOf(minP);
  g+='<text x="'+X(iMin)+'" y="'+(Y(minP)+20)+'" text-anchor="middle" fill="'+css('--ink2')+'" font-size="11" font-weight="600" font-family="IBM Plex Mono,monospace">'+fmt(minP)+'</text>';
  g+='<rect x="'+m.l+'" y="'+m.t+'" width="'+(W-m.l-m.r)+'" height="'+(H-m.t-m.b)+'" fill="transparent"/>';
  svg.innerHTML=g;
  return pts;
}
const PTS=draw();
svg.addEventListener('mousemove',ev=>{
  if(!PTS.length) return;
  const r=svg.getBoundingClientRect(), sx=W/r.width;
  const x=(ev.clientX-r.left)*sx;
  let best=PTS[0];
  for(const p of PTS) if(Math.abs(p.cx-x)<Math.abs(best.cx-x)) best=p;
  const d=best.d;
  let htm='<div class="tt">'+d.t+'</div><div class="tp">'+fmt(d.p)+' <span class="tt">más barato'+(d.a?' · '+d.a:'')+'</span></div>';
  if(d.pd!=null) htm+='<div class="tp">'+fmt(d.pd)+' <span class="tt">directo'+(d.ad?' · '+d.ad:'')+'</span></div>';
  tip.innerHTML=htm;
  tip.style.display='block';
  const wrap=document.getElementById('chartwrap').getBoundingClientRect();
  let tx=best.cx/sx+12, ty=best.cy/sx-10;
  tip.style.left=Math.min(tx,wrap.width-tip.offsetWidth-4)+'px';
  tip.style.top=Math.max(0,ty)+'px';
});
svg.addEventListener('mouseleave',()=>{tip.style.display='none'});
</script>
</body></html>
"""


def main():
    cfg = cargar_config()
    print(f"Consultando {cfg['origen']} -> {cfg['destino']} "
          f"({cfg['fecha_ida']} / {cfg['fecha_regreso']})...")

    data = consultar(cfg)
    if data.get("error"):
        print("ERROR de SerpAPI:", data["error"])
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    with open(os.path.join(DATA_DIR, f"{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    mejor, directo = extraer_mejores(data)
    if not mejor:
        print("No se encontraron vuelos con precio en la respuesta.")
        sys.exit(1)

    insights = data.get("price_insights", {}) or {}
    rango = insights.get("typical_price_range") or ["", ""]
    fila = {
        "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "precio": mejor["precio"],
        "aerolinea": mejor["aerolinea"],
        "escalas": mejor["escalas"],
        "duracion_min": mejor["duracion_min"],
        "precio_directo": directo["precio"] if directo else "",
        "aerolinea_directo": directo["aerolinea"] if directo else "",
        "nivel_precio": insights.get("price_level", ""),
        "tipico_min": rango[0],
        "tipico_max": rango[1],
    }

    historial_previo = leer_historial()
    minimo_previo = min((float(r["precio"]) for r in historial_previo), default=None)

    guardar_csv(fila)
    historial = leer_historial()
    generar_reporte(historial, cfg)

    moneda = cfg.get("moneda", "MXN")
    print(f"Mas barato: ${mejor['precio']:,} {moneda} "
          f"({mejor['aerolinea']}, {mejor['escalas']} escala(s) a la ida)")
    if directo:
        print(f"Directo:    ${directo['precio']:,} {moneda} ({directo['aerolinea']})")
    if insights.get("price_level"):
        nivel = insights["price_level"]
        if rango[0]:
            print(f"Google lo califica como: {nivel} (rango tipico ${rango[0]:,} - ${rango[1]:,})")
        else:
            print(f"Google lo califica como: {nivel}")

    eventos = []
    if minimo_previo is not None and mejor["precio"] < minimo_previo:
        print(f"*** NUEVO MINIMO: bajo de ${minimo_previo:,.0f} a ${mejor['precio']:,} ***")
        eventos.append(f"📉 <b>Nuevo mínimo</b>: ${mejor['precio']:,} {moneda} "
                       f"(antes ${minimo_previo:,.0f})")
    alerta = cfg.get("precio_alerta")
    if alerta and mejor["precio"] <= alerta:
        print(f"*** ALERTA: precio <= ${alerta:,} — considera comprar ya ***")
        eventos.append(f"🎯 Precio en o bajo tu alerta de ${alerta:,} {moneda}")
    nivel_previo = ((historial_previo[-1].get("nivel_precio") or "").lower()
                    if historial_previo else "")
    if insights.get("price_level") == "low" and nivel_previo != "low":
        eventos.append("🟢 Google ahora califica el precio como <b>BAJO</b> "
                       "— suele ser buen momento de comprar")

    if eventos:
        cuerpo = "\n".join(eventos)
        detalle = (f"Más barato: ${mejor['precio']:,} {moneda} ({mejor['aerolinea']})")
        if directo:
            detalle += f"\nDirecto: ${directo['precio']:,} {moneda} ({directo['aerolinea']})"
        enlace = cfg.get("url_reporte", "")
        pie = f"\n📊 {enlace}" if enlace else ""
        notificar_telegram(
            f"✈️ <b>GDL → Houston</b> (26 oct – 18 nov)\n{cuerpo}\n\n{detalle}{pie}")

    print(f"Reporte actualizado: {REPORT_PATH}")


if __name__ == "__main__":
    main()
