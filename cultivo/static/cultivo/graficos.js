// Gráficos con Plotly. Colores tomados de las variables CSS para respetar el tema.
function css(nombre) {
  return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
}

function layoutBase(titulo, ejeY) {
  return {
    title: {text: titulo, font: {size: 14, color: css("--texto")}, x: 0, xanchor: "left"},
    margin: {l: 48, r: 16, t: 36, b: 36},
    height: 280,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {family: "inherit", color: css("--texto-2"), size: 12},
    xaxis: {gridcolor: css("--grilla"), linecolor: css("--borde")},
    yaxis: {title: {text: ejeY}, gridcolor: css("--grilla"), zeroline: false},
    legend: {orientation: "h", y: -0.18},
    hovermode: "x unified",
    shapes: [],
  };
}

const CONFIG = {displaylogo: false, responsive: true, locale: "es"};

function bandasComoFormas(bandas) {
  return (bandas || []).map(b => ({
    type: "rect", xref: "x", yref: "y", layer: "below",
    x0: b.inicio, x1: b.fin, y0: b.minimo, y1: b.maximo,
    fillcolor: css("--ok-fondo"), line: {width: 0},
  }));
}

function graficarConBanda(id, serie, titulo) {
  if (!serie) return;
  const layout = layoutBase(titulo, serie.unidad);
  layout.shapes = bandasComoFormas(serie.bandas);
  layout.showlegend = false;
  Plotly.react(id, [{
    x: serie.x, y: serie.y, type: "scatter", mode: "lines", name: serie.etiqueta,
    line: {color: css("--acento"), width: 1.8},
    hovertemplate: "%{y:.2f} " + serie.unidad + "<extra></extra>",
  }], layout, CONFIG);
}

// Mapa de calor días × horas. Escala divergente: azul = por debajo del rango,
// gris = dentro del rango, rojo = por encima. Mismo criterio en claro y oscuro.
function graficarMapa(id, datos) {
  const oscuro = matchMedia("(prefers-color-scheme: dark)").matches;
  const medio = oscuro ? "#383835" : "#f0efec";
  const [bajo, ideal, alto] = datos.escala;
  const texto = datos.mapa.z.map((fila, i) => fila.map((z, h) => {
    const v = datos.mapa.valores[i][h];
    if (v === null) return "Sin datos";
    const estado = z < 0 ? bajo : (z > 0 ? alto : ideal);
    return `${datos.mapa.dias[i]} · ${h}:00 a ${h + 1}:00<br>${v} ${datos.unidad} · <b>${estado}</b>`;
  }));
  const layout = layoutBase("", "");
  layout.height = Math.max(220, 28 * datos.mapa.dias.length + 90);
  layout.margin = {l: 56, r: 16, t: 8, b: 48};
  layout.xaxis = {title: {text: "Hora del día"}, dtick: 2, ticksuffix: " h", showgrid: false, fixedrange: true};
  layout.yaxis = {autorange: "reversed", showgrid: false, fixedrange: true, type: "category"};
  layout.hovermode = "closest";
  Plotly.react(id, [{
    type: "heatmap", x: datos.mapa.horas, y: datos.mapa.dias, z: datos.mapa.z,
    zmin: -1, zmax: 1, zmid: 0, xgap: 2, ygap: 2,
    colorscale: [[0, "#1c5cab"], [0.3, "#86b6ef"], [0.5, medio], [0.7, "#f2a3a2"], [1, "#d03b3b"]],
    text: texto, hovertemplate: "%{text}<extra></extra>", hoverongaps: false,
    colorbar: {tickvals: [-1, 0, 1], ticktext: [bajo, ideal, alto], thickness: 12, outlinewidth: 0, len: 0.9},
  }], layout, CONFIG);
}
