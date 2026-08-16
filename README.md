# Rastreador de vuelo GDL → Houston

Rastrea el precio del viaje redondo **Guadalajara (GDL) → Houston (IAH/HOU)**,
ida **26 oct 2026** y regreso **18 nov 2026**, con datos reales de Google
Flights (vía SerpAPI). Sigue dos series: el precio más barato en general y el
vuelo directo más barato.

## Cómo funciona

- **GitHub Actions** ejecuta `tracker.py` en la nube todos los días a las
  **9:00 y 21:00** (hora de Guadalajara) — no necesita ninguna PC encendida.
- Cada corrida agrega una fila a `historial.csv` y regenera el reporte
  (`index.html` / `reporte.html`), que **GitHub Pages** publica como página web.
- La API key vive en el *secret* `SERPAPI_KEY` del repo (nunca en el código).
  El plan gratuito de SerpAPI da 100 búsquedas/mes; 2 diarias usan ~60.

## Correr manualmente

- Desde GitHub: pestaña **Actions → Rastrear precio de vuelo → Run workflow**.
- Localmente: pon tu API key en un archivo `.serpapi_key` (está en
  `.gitignore`) y corre `python tracker.py`. Ojo: una corrida local no se
  publica; la página solo refleja lo que corre en Actions.

## Archivos

| Archivo | Qué es |
|---|---|
| `config.json` | Ruta, fechas, moneda y `precio_alerta` opcional |
| `tracker.py` | El rastreador |
| `historial.csv` | Una fila por consulta; las filas "Google (histórico)" son el historial de 61 días que da Google Flights |
| `index.html` / `reporte.html` | Gráfica de fluctuación + tabla (mismo contenido) |
| `.github/workflows/tracker.yml` | La programación en la nube |
| `data/` | (solo local) respuestas JSON crudas de cada consulta |

## Alerta de precio

En `config.json` pon por ejemplo `"precio_alerta": 4800` y el script lo
señalará en el log de la corrida cuando el mejor precio sea ≤ ese monto.

## Consejos de compra

- Google marca cada lectura como *low / typical / high* (columna
  `nivel_precio` del CSV y tile "Rango típico" del reporte): si aparece
  **low**, suele ser buen momento de comprar.
- Para un vuelo de finales de octubre, históricamente los mejores precios
  aparecen entre 3 semanas y 2 meses antes del vuelo.
