# -*- coding: utf-8 -*-
"""
Rastreador de precios de vuelo GDL -> Houston (ida 2026-10-26, regreso 2026-11-18).

Consulta Google Flights via SerpAPI, guarda cada lectura en historial.csv,
archiva la respuesta cruda en data/ y regenera reporte.html con la grafica
de fluctuacion de precios. Rastrea dos series: el precio mas barato en general
y el vuelo directo mas barato (escalas medidas sobre el tramo de ida).

Uso:  python tracker.py
Requiere: config.json con tu API key de SerpAPI (gratis en https://serpapi.com)
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
CSV_PATH = os.path.join(BASE, "historial.csv")
DATA_DIR = os.path.join(BASE, "data")
REPORT_PATH = os.path.join(BASE, "reporte.html")
INDEX_PATH = os.path.join(BASE, "index.html")

CSV_FIELDS = [
    "fecha_hora", "precio", "aerolinea", "escalas", "duracion_min",
    "precio_directo", "aerolinea_directo",
    "nivel_precio", "tipico_min", "tipico_max",
]


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
    moneda = cfg.get("moneda", "MXN")

    def celda_precio(v):
        return f"${float(v):,.0f}" if v else "—"

    filas_tabla = "\n".join(
        f"<tr><td>{r['fecha_hora']}</td><td class='num'>${float(r['precio']):,.0f}</td>"
        f"<td>{r.get('aerolinea','')}</td>"
        f"<td class='num'>{celda_precio(r.get('precio_directo'))}</td>"
        f"<td>{r.get('aerolinea_directo','')}</td></tr>"
        for r in reversed(historial)
    )

    html = HTML_TEMPLATE
    html = html.replace("__DATOS__", json.dumps(puntos, ensure_ascii=False))
    html = html.replace("__RUTA__", f"{cfg['origen']} → Houston ({cfg['destino']})")
    html = html.replace("__FECHAS__", f"ida {cfg['fecha_ida']} · regreso {cfg['fecha_regreso']}")
    html = html.replace("__MONEDA__", moneda)
    html = html.replace("__ACTUAL__", f"${ultimo['p']:,.0f}" if ultimo else "—")
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
<title>Vuelo GDL–Houston</title>
<style>
  :root{color-scheme:light dark;
    --surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
    --muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
    --serie1:#2a78d6;--serie2:#eb6834;
    --border:rgba(11,11,11,.10)}
  @media (prefers-color-scheme:dark){:root{
    --surface:#1a1a19;--page:#0d0d0d;--ink:#ffffff;--ink2:#c3c2b7;
    --muted:#898781;--grid:#2c2c2a;--axis:#383835;
    --serie1:#3987e5;--serie2:#d95926;
    --border:rgba(255,255,255,.10)}}
  *{box-sizing:border-box;margin:0}
  body{background:var(--page);color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
    padding:24px;max-width:880px;margin:0 auto}
  h1{font-size:1.25rem;font-weight:650}
  .sub{color:var(--ink2);margin-bottom:20px}
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
    gap:12px;margin-bottom:20px}
  .tile{background:var(--surface);border:1px solid var(--border);
    border-radius:10px;padding:14px 16px}
  .tile .k{font-size:.78rem;color:var(--muted);text-transform:uppercase;
    letter-spacing:.04em}
  .tile .v{font-size:1.55rem;font-weight:650;margin-top:2px}
  .tile .d{font-size:.78rem;color:var(--ink2)}
  .card{background:var(--surface);border:1px solid var(--border);
    border-radius:10px;padding:18px;margin-bottom:20px}
  .card h2{font-size:.95rem;font-weight:600;margin-bottom:4px}
  .legend{display:flex;gap:18px;font-size:.8rem;color:var(--ink2);
    margin-bottom:8px;flex-wrap:wrap}
  .legend .sw{display:inline-block;width:14px;height:3px;border-radius:2px;
    vertical-align:middle;margin-right:6px}
  #chartwrap{position:relative}
  svg{display:block;width:100%;height:auto}
  #tip{position:absolute;pointer-events:none;display:none;
    background:var(--surface);border:1px solid var(--border);border-radius:8px;
    padding:6px 10px;font-size:.8rem;box-shadow:0 2px 8px rgba(0,0,0,.12);
    white-space:nowrap;z-index:2}
  #tip .tp{font-weight:650}
  #tip .tt{color:var(--ink2)}
  table{width:100%;border-collapse:collapse;font-size:.85rem}
  th{text-align:left;color:var(--muted);font-weight:500;
    border-bottom:1px solid var(--grid);padding:6px 8px}
  td{padding:6px 8px;border-bottom:1px solid var(--grid)}
  .num{text-align:right;font-variant-numeric:tabular-nums}
  th.num{text-align:right}
  .foot{color:var(--muted);font-size:.78rem;margin-top:8px}
</style></head><body>
<h1>Vuelo __RUTA__</h1>
<p class="sub">__FECHAS__ · precios en __MONEDA__ (viaje redondo)</p>

<div class="tiles">
  <div class="tile"><div class="k">Más barato hoy</div><div class="v">__ACTUAL__</div></div>
  <div class="tile"><div class="k">Directo más barato hoy</div><div class="v">__DIRECTO__</div>
    <div class="d">__DIR_AERO__</div></div>
  <div class="tile"><div class="k">Mínimo registrado</div><div class="v">__MINIMO__</div>
    <div class="d">__MIN_FECHA__</div></div>
  <div class="tile"><div class="k">Rango típico (Google)</div><div class="v" style="font-size:1.1rem">__TIPICO__</div></div>
</div>

<div class="card"><h2>Fluctuación del precio</h2>
  <div class="legend">
    <span><span class="sw" style="background:var(--serie1)"></span>Más barato (con o sin escalas)</span>
    <span><span class="sw" style="background:var(--serie2)"></span>Directo más barato</span>
  </div>
  <div id="chartwrap"><svg id="chart" viewBox="0 0 820 300"></svg><div id="tip"></div></div>
</div>

<div class="card"><h2>Historial de lecturas</h2>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>Fecha de consulta</th><th class="num">Más barato</th><th>Aerolínea</th><th class="num">Directo</th><th>Aerolínea</th></tr></thead>
    <tbody>__TABLA__</tbody>
  </table></div>
</div>
<p class="foot">Última actualización: __ACTUALIZADO__ · generado por tracker.py ·
las lecturas "Google (histórico)" vienen del historial de precios de Google Flights</p>

<script>
const D = __DATOS__;
const svg = document.getElementById('chart'), tip = document.getElementById('tip');
const W=820,H=300,m={t:16,r:16,b:34,l:64};
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function fmt(n){return '$'+Math.round(n).toLocaleString('es-MX')}
function draw(){
  svg.innerHTML='';
  if(D.length===0){
    svg.innerHTML='<text x="410" y="150" text-anchor="middle" fill="'+css('--muted')+'" font-size="14">Aún no hay lecturas — corre tracker.py</text>';
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
    g+='<text x="'+(m.l-8)+'" y="'+(y+4)+'" text-anchor="end" fill="'+css('--muted')+'" font-size="11" style="font-variant-numeric:tabular-nums">'+fmt(v)+'</text>';
  }
  g+='<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+(H-m.b)+'" y2="'+(H-m.b)+'" stroke="'+css('--axis')+'" stroke-width="1"/>';
  const step=Math.max(1,Math.ceil(D.length/6));
  D.forEach((d,i)=>{
    if(i%step===0||i===D.length-1){
      g+='<text x="'+X(i)+'" y="'+(H-m.b+18)+'" text-anchor="middle" fill="'+css('--muted')+'" font-size="11">'+d.t.slice(5,10)+'</text>';
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
  g+='<path d="'+path(d=>d.p)+'" fill="none" stroke="'+css('--serie1')+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
  g+='<path d="'+path(d=>d.pd)+'" fill="none" stroke="'+css('--serie2')+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
  const pts=[];
  const dense = D.length>40;
  D.forEach((d,i)=>{
    const cx=X(i);
    pts.push({cx,d,cy:Y(d.p)});
    if(!dense||i===D.length-1){
      g+='<circle cx="'+cx+'" cy="'+Y(d.p)+'" r="3.5" fill="'+css('--serie1')+'" stroke="'+css('--surface')+'" stroke-width="2"/>';
      if(d.pd!=null) g+='<circle cx="'+cx+'" cy="'+Y(d.pd)+'" r="3.5" fill="'+css('--serie2')+'" stroke="'+css('--surface')+'" stroke-width="2"/>';
    }
  });
  const ps=D.map(d=>d.p);
  const minP=Math.min(...ps), iMin=ps.indexOf(minP);
  g+='<text x="'+X(iMin)+'" y="'+(Y(minP)+20)+'" text-anchor="middle" fill="'+css('--ink2')+'" font-size="11" font-weight="600">'+fmt(minP)+'</text>';
  g+='<rect x="'+m.l+'" y="'+m.t+'" width="'+(W-m.l-m.r)+'" height="'+(H-m.t-m.b)+'" fill="transparent"/>';
  svg.innerHTML=g;
  return pts;
}
let PTS=draw();
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{PTS=draw()});
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

    if minimo_previo is not None and mejor["precio"] < minimo_previo:
        print(f"*** NUEVO MINIMO: bajo de ${minimo_previo:,.0f} a ${mejor['precio']:,} ***")
    alerta = cfg.get("precio_alerta")
    if alerta and mejor["precio"] <= alerta:
        print(f"*** ALERTA: precio <= ${alerta:,} — considera comprar ya ***")

    print(f"Reporte actualizado: {REPORT_PATH}")


if __name__ == "__main__":
    main()
