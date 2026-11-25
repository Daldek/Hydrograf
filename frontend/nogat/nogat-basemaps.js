// Nogat GUI kit: the base maps every GUI with a map shares (DEV-15.15, ECO-089).
// The catalogue nogat-basemaps.json lists them. A GUI's server hands its page the entries its
// deployment allows (`basemaps`, a copy in `basemap_mirrors` in its provider's place) and the
// deployment's own base maps (`basemap_extra`) in the catalogue's shape, and the page:
// - offers them in <nogat-basemaps>: radios in a radiogroup „Podkład kartograficzny”, the
//   catalogue's entries in its order, then the deployment's own, then „bez podkładu” (value
//   "none"). The property `entries` takes the entries, `value` is the id shown and `texts` the
//   words (BASEMAP_TEXTS by default); the event `change` ({detail: {id}}) tells of a person's
//   choice, and `fail(id)` marks an entry „Podkład nie odpowiada”. The choice is kept in the
//   browser's localStorage under `nogat-basemap`, no server and no cookie; the element opens
//   on it while it is offered, else on the first catalogue entry whose `default` is true,
//   else on „bez podkładu”. With remember="none" it keeps nothing and the GUI sets `value`;
// - draws the chosen entry with the GUI's own map library, passed in, never imported:
//   `maplibreBasemap(entry, {map, …})`, `removeMaplibreBasemap(map)` and, after a change of
//   theme, `repaintMaplibreBasemap(map)` on MapLibre GL JS; `leafletBasemap(L, entry, …)` on
//   Leaflet, a layer the GUI adds (a vector entry through maplibre-gl-leaflet).
// A vector entry is a TileJSON of the OpenMapTiles schema drawn in the kit's grey style, its
// tiles checked to stay on the entry's origin, the only one the GUI's CSP names for it, before
// any tile is asked; a raster entry is a tile template (XYZ, WMTS KVP, or WMS with
// {bbox-epsg-3857}). Each carries its entry's credit in the map's own attribution, never a
// TileJSON's. `onFailure(id)` fires when the TileJSON or the first tiles fail; the base map
// then leaves the map, the overlays stay and nothing switches by itself.
// No shadow DOM: the page's stylesheet nogat-basemaps.css styles the element and the credit
// and holds the grey style's colours in both themes.
// Copy this file byte for byte (DEV-15.6); change it in Nogat design/kit/.

/** The element's words and the entries' labels by id, in Polish; another language replaces them. */
export const BASEMAP_TEXTS = {
  group: "Podkłady kartograficzne",
  name: "Podkład kartograficzny",
  none: "bez podkładu",
  failed: "Podkład nie odpowiada",
  credit: "Pokaż lub ukryj źródło podkładu",
  labels: {},
};

/** The value of „bez podkładu”. */
const NONE = "none";
/** The browser's key of the person's choice, beside the theme's `nogat-theme`. */
const STORAGE = "nogat-basemap";
/** The id of the base map's source on a MapLibre map, and the prefix of its layers' ids. */
const SOURCE = "nogat-basemap";
/** The class the adapters set on the map's container, under which the credit is styled. */
const MAP_CLASS = "nogat-basemap-map";
/** The class of a grey raster entry on Leaflet. */
const GREY_CLASS = "nogat-basemap-grey";
/** The font of the names: the GUIs' vendored glyphs, `…/noto-sans-regular/{range}.pbf`. */
const FONT = "noto-sans-regular";
/** Half the width of the EPSG:3857 world [m]. */
const HALF_WORLD = 20037508.342789244;

/**
 * The grey style's colours in the light theme; nogat-basemaps.css gives both themes as
 * `--nogat-basemap-<name>`, which are read where a GUI passes no `colors`.
 */
const COLORS = {
  bg: "#eef0f3",
  landuse: "#e4e7eb",
  water: "#d3d9e1",
  road: "#d5dae1",
  state: "#c3c9d2",
  country: "#98a2b3",
  "water-text": "#5f6f82",
  halo: "rgba(255, 255, 255, 0.85)",
  "place-1": "#667085",
  "place-2": "#5d6878",
  "place-3": "#344054",
  "place-4": "#667085",
};

let counter = 0;

/**
 * The grey style's colours: `colors` over those of nogat-basemaps.css at `element`, over the
 * light ones.
 *
 * @param {Element} element where the stylesheet's custom properties are read
 * @param {Object<string, string>|null|undefined} colors colours the GUI passes, by name
 * @returns {Object<string, string>} every colour by name
 */
function palette(element, colors) {
  const style = getComputedStyle(element);
  const read = Object.fromEntries(
    Object.entries(COLORS).map(([name, light]) => [
      name,
      style.getPropertyValue(`--nogat-basemap-${name}`).trim() || light,
    ]),
  );
  return { ...read, ...colors };
}

function escape(text) {
  return String(text).replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);
}

/** An absolute http(s) address, or null. */
function absolute(address) {
  try {
    const url = new URL(String(address));
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/**
 * The HTML of an entry's credit: its text escaped, each word of its links linked at its next
 * occurrence; a word the rest of the text lacks, or one without an http(s) address, stays text.
 *
 * @param {{text: string, links?: string[][]}|string} credit the entry's credit
 * @returns {string} the HTML a map's attribution shows
 */
function creditHtml(credit) {
  const text = typeof credit === "string" ? credit : String(credit?.text ?? "");
  let html = "";
  let rest = text;
  for (const pair of Array.isArray(credit?.links) ? credit.links : []) {
    const [word, address] = Array.isArray(pair) ? pair : [];
    const href = absolute(address);
    const at = typeof word === "string" && word !== "" && href ? rest.indexOf(word) : -1;
    if (at < 0) continue;
    const a = `<a href="${escape(href)}" target="_blank" rel="noopener noreferrer">`;
    html += `${escape(rest.slice(0, at))}${a}${escape(word)}</a>`;
    rest = rest.slice(at + word.length);
  }
  return html + escape(rest);
}

/**
 * Check an entry before anything is asked: an id, a kind, an address on its origin.
 *
 * @param {object} entry an entry in the catalogue's shape
 * @returns {object} the entry
 */
function checked(entry) {
  if (typeof entry?.id !== "string" || entry.id === "" || entry.id === NONE) {
    throw new Error("A base map needs an id");
  }
  if (entry.kind !== "vector" && entry.kind !== "raster") {
    throw new Error(`Base map ${entry.id}: kind ${entry.kind}`);
  }
  if (typeof entry.url !== "string" || new URL(entry.url).origin !== entry.origin) {
    throw new Error(`Base map ${entry.id}: its address is not on its origin ${entry.origin}`);
  }
  return entry;
}

/** A zoom: `own` where it is a number, else `fallback`. */
function zoom(own, fallback) {
  return Number.isFinite(own) ? own : fallback;
}

/** A box [west, south, east, north], or null. */
function box(value) {
  return Array.isArray(value) && value.length === 4 && value.every(Number.isFinite) ? value : null;
}

/**
 * The tile templates of a vector entry's TileJSON, each checked to stay on the entry's origin
 * (Obserwator's and Archiwista's loadBasemapSource).
 *
 * @param {object} entry a vector entry
 * @returns {Promise<object>} the TileJSON's tiles, zooms, bounds and scheme
 */
async function tileJson(entry) {
  const response = await fetch(entry.url);
  if (!response.ok) throw new Error(`TileJSON ${entry.url}: ${response.status}`);
  const doc = await response.json();
  if (!Array.isArray(doc?.tiles) || !doc.tiles.length) {
    throw new Error(`TileJSON ${entry.url}: no tiles`);
  }
  const tiles = doc.tiles.map((tile) => {
    if (typeof tile !== "string") throw new Error(`TileJSON ${entry.url}: a tile is not text`);
    const url = new URL(tile, entry.url);
    if (url.origin !== entry.origin) {
      throw new Error(`TileJSON ${entry.url}: tiles on ${url.origin}`);
    }
    return url.href.replace(/%7B/gi, "{").replace(/%7D/gi, "}");
  });
  const { minzoom, maxzoom, bounds, scheme } = doc;
  return { tiles, minzoom, maxzoom, bounds, scheme };
}

/**
 * The MapLibre source of an entry. A vector entry's zooms are those both the entry and its
 * TileJSON have; a raster entry's are 0–19 where a deployment's own base map gives none.
 *
 * @param {object} entry a checked entry
 * @returns {Promise<object>} a MapLibre source with the entry's credit as its attribution
 */
async function sourceOf(entry) {
  const attribution = creditHtml(entry.credit);
  if (entry.kind === "raster") {
    const bounds = box(entry.bounds);
    return {
      type: "raster",
      tiles: [entry.url],
      tileSize: 256,
      minzoom: zoom(entry.minzoom, 0),
      maxzoom: zoom(entry.maxzoom, 19),
      ...(bounds ? { bounds } : {}),
      attribution,
    };
  }
  const doc = await tileJson(entry);
  const bounds = box(entry.bounds) ?? box(doc.bounds);
  return {
    type: "vector",
    tiles: doc.tiles,
    minzoom: Math.max(zoom(entry.minzoom, 0), zoom(doc.minzoom, 0)),
    maxzoom: Math.min(zoom(entry.maxzoom, 22), zoom(doc.maxzoom, 22)),
    ...(bounds ? { bounds } : {}),
    scheme: doc.scheme === "tms" ? "tms" : "xyz",
    attribution,
  };
}

/** A name in the page's language where the tiles have it, else the Latin one, else the local one. */
function placeName(locale) {
  const lang = typeof locale === "string" && /^[a-z]{2,3}$/.test(locale) ? locale : "pl";
  return ["coalesce", ["get", `name:${lang}`], ["get", "name:latin"], ["get", "name"]];
}

/** The paint properties of `painted` (property → colour name) in the palette's colours. */
function paint(painted, colors) {
  return Object.fromEntries(
    Object.entries(painted).map(([property, name]) => [property, colors[name]]),
  );
}

const LINES = ["match", ["geometry-type"], ["LineString", "MultiLineString"], true, false];
const POINTS = ["match", ["geometry-type"], ["Point", "MultiPoint"], true, false];
const BUILT_UP = [
  "residential", "suburb", "quarter", "neighbourhood", "commercial", "industrial", "retail",
];
const ROADS = ["motorway", "trunk", "primary", "secondary", "tertiary", "minor"];

/**
 * The grey layers over the OpenMapTiles schema (Obserwator's map.js after Archiwista's
 * map/style.js), bottom to top, from its own background up. Each names in its metadata the
 * colour of each painted property, so a change of theme repaints it. The names need glyphs;
 * without them none is drawn.
 *
 * @param {Object<string, string>} colors the palette
 * @param {string} locale the page's language
 * @param {boolean} named whether the map has glyphs for the names
 * @returns {object[]} MapLibre layers
 */
function vectorLayers(colors, locale, named) {
  const zoomed = (...stops) => ["interpolate", ["linear"], ["zoom"], ...stops];
  const layer = (id, type, sourceLayer, filter, painted, rest = {}) => ({
    id: `${SOURCE}-${id}`,
    type,
    ...(sourceLayer ? { source: SOURCE, "source-layer": sourceLayer } : {}),
    ...(filter ? { filter } : {}),
    ...rest,
    paint: { ...rest.paint, ...paint(painted, colors) },
    metadata: { [SOURCE]: painted },
  });
  const classes = (list) => ["match", ["get", "class"], list, true, false];
  const boundary = (level, disputed) => [
    "all",
    ["==", ["get", "admin_level"], level],
    ["!=", ["get", "maritime"], 1],
    [disputed ? "==" : "!=", ["get", "disputed"], 1],
  ];
  const roads = ["all", classes(ROADS), ["!=", ["get", "brunnel"], "tunnel"]];
  const of = (motorway, primary, other) => [
    "match", ["get", "class"], ["motorway", "trunk"], motorway, "primary", primary, other,
  ];
  const roadWidth = [
    "interpolate", ["exponential", 1.5], ["zoom"],
    5, of(0.5, 0.35, 0.25), 10, of(1.4, 1, 0.5), 16, of(9, 7, 4),
  ];
  const label = (id, sourceLayer, filter, color, options) => {
    const { size, minzoom = 0, maxzoom = 24, line = false, layout = {} } = options;
    return layer(id, "symbol", sourceLayer, filter, {
      "text-color": color,
      "text-halo-color": "halo",
    }, {
      minzoom,
      maxzoom,
      layout: {
        "text-field": placeName(locale),
        "text-font": [FONT],
        "text-size": size,
        "text-max-width": 8,
        ...(line ? { "symbol-placement": "line" } : {}),
        ...layout,
      },
      paint: { "text-halo-width": 1.2 },
    });
  };
  const place = (id, kinds, color, options) =>
    label(id, "place", classes(kinds), color, {
      ...options,
      layout: { "symbol-sort-key": ["coalesce", ["get", "rank"], 99], ...options.layout },
    });
  const shapes = [
    layer("background", "background", null, null, { "background-color": "bg" }),
    layer("landuse", "fill", "landuse", classes(BUILT_UP), { "fill-color": "landuse" }),
    layer("water", "fill", "water", null, { "fill-color": "water" }),
    layer("waterway", "line", "waterway", classes(["river", "canal"]), { "line-color": "water" }, {
      paint: { "line-width": zoomed(7, 0.6, 14, 3) },
    }),
    layer("state", "line", "boundary", boundary(4, false), { "line-color": "state" }, {
      minzoom: 5,
      paint: { "line-width": zoomed(5, 0.6, 12, 1.2), "line-dasharray": [3, 2] },
    }),
    layer("road", "line", "transportation", roads, { "line-color": "road" }, {
      minzoom: 6,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-width": roadWidth },
    }),
    layer("country", "line", "boundary", boundary(2, false), { "line-color": "country" }, {
      paint: { "line-width": zoomed(3, 0.8, 10, 1.8) },
    }),
    layer("country-disputed", "line", "boundary", boundary(2, true), { "line-color": "country" }, {
      paint: { "line-width": zoomed(3, 0.8, 10, 1.8), "line-dasharray": [2, 2] },
    }),
  ];
  if (!named) return shapes;
  const river = ["==", ["get", "class"], "river"];
  return [
    ...shapes,
    label("waterway-name", "waterway", river, "water-text", {
      minzoom: 9,
      line: true,
      size: zoomed(9, 10, 14, 12),
    }),
    label("water-name", "water_name", POINTS, "water-text", {
      minzoom: 6,
      size: zoomed(6, 10, 10, 12),
    }),
    label("water-line-name", "water_name", LINES, "water-text", {
      minzoom: 8,
      line: true,
      size: 11,
    }),
    place("village", ["village"], "place-1", { minzoom: 10, size: zoomed(10, 10, 15, 13) }),
    place("town", ["town"], "place-2", { minzoom: 7.5, size: zoomed(7, 10, 13, 13) }),
    place("city", ["city"], "place-3", { minzoom: 5, size: zoomed(5, 10.5, 9, 13, 13, 16) }),
    place("country-name", ["country"], "place-4", {
      maxzoom: 6.5,
      size: zoomed(3, 10, 6, 12),
      layout: { "text-transform": "uppercase", "text-letter-spacing": 0.08 },
    }),
  ];
}

/** The layer of a raster entry: grey as `raster-saturation: -1` where the entry is grey. */
function rasterLayers(entry) {
  const paint = entry.grey ? { "raster-saturation": -1 } : {};
  return [{ id: `${SOURCE}-raster`, type: "raster", source: SOURCE, paint }];
}

/** The rejection of a call that a later call or a removal overtook. */
function superseded() {
  return new DOMException("Another base map replaced this one", "AbortError");
}

/** Each MapLibre map's latest call and the watch of its base map's first tiles. */
const drawn = new WeakMap();

/** Take the map for a new call; an earlier one still loading then draws nothing. */
function claim(map) {
  const state = drawn.get(map) ?? { call: 0, unwatch: null };
  state.call += 1;
  drawn.set(map, state);
  return state.call;
}

/** Take the kit's base map off a MapLibre map: its layers, its source and its watch. */
function clear(map) {
  const state = drawn.get(map);
  state?.unwatch?.();
  if (state) state.unwatch = null;
  for (const layer of map.getStyle()?.layers ?? []) {
    if (layer.id.startsWith(`${SOURCE}-`)) map.removeLayer(layer.id);
  }
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
  forgetCredit(map);
}

/** The MapLibre maps whose attribution control the kit watches. */
const watchedCredit = new WeakSet();

/**
 * Empty the words of a MapLibre map's AttributionControl whenever it has no credited source
 * left: MapLibre 6.14.0 then only hides the control (`maplibregl-attrib-empty`) and keeps
 * the last base map's credit in its inner element, where it still reads.
 *
 * @param {object} map a MapLibre map
 */
function forgetCredit(map) {
  const control = map.getContainer().querySelector(".maplibregl-ctrl-attrib");
  const inner = control?.querySelector(".maplibregl-ctrl-attrib-inner");
  if (!inner) return;
  const empty = () => {
    if (control.classList.contains("maplibregl-attrib-empty")) inner.replaceChildren();
  };
  empty();
  if (watchedCredit.has(map)) return;
  watchedCredit.add(map);
  new MutationObserver(empty).observe(control, { attributes: true, attributeFilter: ["class"] });
}

/**
 * Watch a MapLibre map's base map until a first tile loads: when tiles fail (a 404 is a tile
 * without data, not a failure) and none has loaded once those asked are settled, `failed`
 * runs once. Obserwator's check of its basemap's first tiles.
 *
 * @param {object} map a MapLibre map with the kit's source
 * @param {Function} failed called on a failure
 * @returns {Function} the end of the watch
 */
function watchTiles(map, failed) {
  let errors = false;
  const settled = () => {
    try {
      return map.isSourceLoaded(SOURCE);
    } catch {
      return true;
    }
  };
  const check = () => {
    if (!errors || !settled()) return;
    unwatch();
    setTimeout(failed, 0);
  };
  const onData = (event) => {
    if (event.sourceId !== SOURCE) return;
    if (event.dataType === "source" && event.tile) unwatch();
    else check();
  };
  const onError = (event) => {
    if (event.sourceId !== SOURCE) return;
    errors = true;
    check();
  };
  const unwatch = () => {
    map.off("data", onData);
    map.off("error", onError);
  };
  map.on("data", onData);
  map.on("error", onError);
  return unwatch;
}

/** The lowest layer of the GUI above its background, under which the base map goes. */
function beneath(map, before) {
  if (before && map.getLayer(before)) return before;
  const first = map.getStyle().layers.find(
    (layer) => layer.type !== "background" && !layer.id.startsWith(`${SOURCE}-`),
  );
  return first?.id;
}

/**
 * Build an entry for MapLibre GL JS and, given `map`, draw it there: its source and layers
 * under the GUI's lowest overlay, in place of the kit's base map drawn before. A vector entry
 * asks its TileJSON first and checks its tiles' origin; a failure, or tiles off the entry's
 * origin, calls `onFailure(id)` and rejects before any tile is asked. On the map, first tiles
 * that fail take the base map off again and call `onFailure(id)`. A call that a later call or
 * `removeMaplibreBasemap` overtakes rejects with an AbortError and draws nothing.
 *
 * @param {object} entry an entry of the catalogue, or a deployment's own, in its shape
 * @param {object} [options] the map and how to draw on it
 * @param {object} [options.map] the MapLibre map to draw on; without it the entry is only built
 * @param {string} [options.glyphs] the GUI's glyph template, `…/{fontstack}/{range}.pbf`, for
 *   a style without one (the names use the font `noto-sans-regular`)
 * @param {string} [options.locale] the page's language: names `name:<locale>`, else Latin,
 *   else local; `pl` by default
 * @param {Object<string, string>} [options.colors] colours of the grey style by name, over
 *   those of nogat-basemaps.css
 * @param {string} [options.before] the GUI's lowest overlay, under which the base map goes
 * @param {(id: string) => void} [options.onFailure] called when the entry fails
 * @returns {Promise<{sources: Object<string, object>, layers: object[]}>} what is drawn
 */
export async function maplibreBasemap(entry, options = {}) {
  const { map = null, glyphs = null, locale = "pl", colors = null } = options;
  const { before = null, onFailure = null } = options;
  const call = map ? claim(map) : 0;
  const current = () => !map || drawn.get(map)?.call === call;
  let source;
  try {
    source = await sourceOf(checked(entry));
  } catch (error) {
    if (!current()) throw superseded();
    onFailure?.(entry?.id);
    throw error;
  }
  if (!current()) throw superseded();
  const element = map ? map.getContainer() : document.documentElement;
  const named = Boolean(glyphs || map?.getStyle().glyphs);
  const layers =
    entry.kind === "vector"
      ? vectorLayers(palette(element, colors), locale, named)
      : rasterLayers(entry);
  const sources = { [SOURCE]: source };
  if (!map) return { sources, layers };
  element.classList.add(MAP_CLASS);
  clear(map);
  if (glyphs && !map.getStyle().glyphs) map.setGlyphs(glyphs);
  const under = beneath(map, before);
  map.addSource(SOURCE, source);
  for (const layer of layers) map.addLayer(layer, under);
  drawn.get(map).unwatch = watchTiles(map, () => {
    if (!current()) return;
    clear(map);
    onFailure?.(entry.id);
  });
  return { sources, layers };
}

/**
 * Take the kit's base map off a MapLibre map („bez podkładu”); a call of `maplibreBasemap`
 * still loading for the map then draws nothing.
 *
 * @param {object} map a MapLibre map
 */
export function removeMaplibreBasemap(map) {
  claim(map);
  clear(map);
}

/**
 * Repaint the kit's vector base map in the theme's colours after the GUI switches its theme;
 * a raster entry keeps its tiles' colours. On Leaflet, pass the vector layer's
 * `getMaplibreMap()`.
 *
 * @param {object} map a MapLibre map
 * @param {Object<string, string>} [colors] colours by name, over those of nogat-basemaps.css
 */
export function repaintMaplibreBasemap(map, colors) {
  const theme = palette(map.getContainer(), colors);
  for (const layer of map.getStyle()?.layers ?? []) {
    const painted = layer.metadata?.[SOURCE];
    if (!layer.id.startsWith(`${SOURCE}-`) || !painted) continue;
    for (const [property, name] of Object.entries(painted)) {
      map.setPaintProperty(layer.id, property, theme[name]);
    }
  }
}

/** The EPSG:3857 box of a tile, as MapLibre fills {bbox-epsg-3857} of a WMS template. */
function tileBox({ x, y, z }) {
  const size = (2 * HALF_WORLD) / 2 ** z;
  const west = -HALF_WORLD + x * size;
  const north = HALF_WORLD - y * size;
  return `${west},${north - size},${west + size},${north}`;
}

/** The Leaflet maps whose credit the kit has prepared. */
const prepared = new WeakSet();

/**
 * Prepare a Leaflet map for the kit's credit: the class `nogat-basemap-map` on its container
 * and, in its attribution control, the button „i”, with which up to 860 px the credit folds
 * at the first drag and shows again (nogat-basemaps.css), as MapLibre's compact control does.
 *
 * @param {object} map a Leaflet map
 * @param {object} texts the words, `credit` the button's name
 */
function prepareLeaflet(map, texts) {
  map.getContainer().classList.add(MAP_CLASS);
  if (prepared.has(map)) return;
  prepared.add(map);
  const credit = map.attributionControl?.getContainer?.();
  if (!credit) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "nogat-basemap-credit-toggle";
  button.textContent = "i";
  button.title = texts.credit;
  button.setAttribute("aria-label", texts.credit);
  const show = (open) => {
    credit.classList.toggle("nogat-basemap-credit-open", open);
    button.setAttribute("aria-expanded", String(open));
  };
  button.addEventListener("click", () => {
    show(!credit.classList.contains("nogat-basemap-credit-open"));
  });
  map.on("dragstart", () => show(false));
  // Leaflet writes the control anew whenever a layer's attribution comes or goes.
  const keep = () => {
    if (button.parentNode !== credit) credit.append(button);
  };
  new MutationObserver(keep).observe(credit, { childList: true });
  credit.classList.add("nogat-basemap-credit");
  show(true);
  keep();
}

/** A raster entry as `L.tileLayer`, which fills {bbox-epsg-3857} of a WMS template itself. */
function rasterLayer(L, entry) {
  const bounds = box(entry.bounds);
  const [west, south, east, north] = bounds ?? [];
  const layer = L.tileLayer(entry.url, {
    attribution: creditHtml(entry.credit),
    className: entry.grey ? GREY_CLASS : "",
    minZoom: zoom(entry.minzoom, 0),
    maxZoom: zoom(entry.maxzoom, 19),
    ...(bounds ? { bounds: L.latLngBounds([south, west], [north, east]) } : {}),
    "bbox-epsg-3857": tileBox,
  });
  layer.on("add", () => layer.bringToBack());
  return layer;
}

/** Watch a Leaflet tile layer until a first tile loads: `failed` runs when its tiles in view fail. */
function watchLeaflet(layer, failed) {
  let loaded = false;
  let errors = false;
  layer.on("tileload", () => {
    loaded = true;
  });
  layer.on("tileerror", () => {
    errors = true;
  });
  layer.on("load", () => {
    if (loaded || !errors) return;
    loaded = true;
    setTimeout(failed, 0);
  });
}

/**
 * Build an entry as a Leaflet layer, which the GUI adds to its map and removes: a raster entry
 * `L.tileLayer` with its bounds, zooms and, where grey, the class `nogat-basemap-grey`, put
 * under the other tile layers when added; a vector entry `L.maplibreGL` (maplibre-gl-leaflet)
 * in the kit's grey style. A vector entry asks its TileJSON first and checks its tiles'
 * origin; a failure calls `onFailure(id)` and rejects. Once on a map, first tiles that fail
 * take the layer off it and call `onFailure(id)`. On a vector layer a change of theme is
 * `repaintMaplibreBasemap(layer.getMaplibreMap())`.
 *
 * @param {object} L Leaflet, with maplibre-gl-leaflet for a vector entry
 * @param {object} entry an entry of the catalogue, or a deployment's own, in its shape
 * @param {object} [options] how to draw it
 * @param {string} [options.glyphs] the GUI's glyph template, `…/{fontstack}/{range}.pbf`
 * @param {string} [options.locale] the page's language, `pl` by default
 * @param {Object<string, string>} [options.colors] colours of the grey style by name
 * @param {(id: string) => void} [options.onFailure] called when the entry fails
 * @param {object} [options.texts] the words, BASEMAP_TEXTS by default (`credit` names „i”)
 * @returns {Promise<object>} the Leaflet layer
 */
export async function leafletBasemap(L, entry, options = {}) {
  const { glyphs = null, locale = "pl", colors = null, onFailure = null } = options;
  const texts = { ...BASEMAP_TEXTS, ...options.texts };
  const failed = (layer) => {
    layer.remove();
    onFailure?.(entry.id);
  };
  let layer;
  try {
    checked(entry);
    if (entry.kind === "raster") {
      layer = rasterLayer(L, entry);
      watchLeaflet(layer, () => failed(layer));
    } else {
      if (typeof L.maplibreGL !== "function") throw new Error("maplibre-gl-leaflet is not loaded");
      const { sources, layers } = await maplibreBasemap(entry, { glyphs, locale, colors });
      const style = { version: 8, ...(glyphs ? { glyphs } : {}), sources, layers };
      const attribution = sources[SOURCE].attribution;
      layer = L.maplibreGL({ style, attribution, interactive: false });
      layer.on("add", () => {
        const gl = layer.getMaplibreMap();
        // The layer's own map: a tile that fails once the base map is drawn is no fault of the
        // page (Obserwator's handler), and anything else is said, not thrown.
        gl.on("error", (event) => {
          if (event.sourceId !== SOURCE) console.warn(event.error);
        });
        const unwatch = watchTiles(gl, () => {
          if (layer.getMaplibreMap() === gl) failed(layer);
        });
        layer.once("remove", unwatch);
      });
    }
  } catch (error) {
    onFailure?.(entry?.id);
    throw error;
  }
  layer.on("add", () => prepareLeaflet(layer._map, texts));
  return layer;
}

/**
 * The entries the element offers: each id once, never "none", with a label; the catalogue's
 * (those with `blocks`) first in their order, then the deployment's own.
 */
function offered(value) {
  const seen = new Set([NONE]);
  const shared = [];
  const own = [];
  for (const entry of Array.isArray(value) ? value : []) {
    const id = entry?.id;
    if (typeof id !== "string" || id === "" || seen.has(id)) continue;
    if (typeof entry.label !== "string" || entry.label === "") continue;
    seen.add(id);
    (Array.isArray(entry.blocks) ? shared : own).push(entry);
  }
  return [...shared, ...own];
}

/** The custom element `<nogat-basemaps>`. */
export class NogatBasemaps extends HTMLElement {
  static observedAttributes = ["remember"];

  constructor() {
    super();
    this._entries = [];
    this._texts = BASEMAP_TEXTS;
    this._chosen = null;
    this._failed = new Set();
    this._name = `nogat-basemaps-${++counter}`;
  }

  /** @returns {object[]} the entries offered, in the order shown */
  get entries() {
    return [...this._entries];
  }

  /** @param {object[]} value the entries the GUI's server allows, then the deployment's own */
  set entries(value) {
    this._entries = offered(value);
    const ids = new Set(this._entries.map((entry) => entry.id));
    this._failed = new Set([...this._failed].filter((id) => ids.has(id)));
    if (this.isConnected) this.render();
  }

  /** @returns {object} the words */
  get texts() {
    return this._texts;
  }

  /** @param {object} value words in place of BASEMAP_TEXTS; `labels` by id replace the entries' */
  set texts(value) {
    this._texts = { ...BASEMAP_TEXTS, ...value, labels: { ...value?.labels } };
    if (this.isConnected) this.render();
  }

  /** @returns {string} the id of the base map shown, "none" for „bez podkładu” */
  get value() {
    if (!this._entries.length) return NONE;
    const ids = new Set([NONE, ...this._entries.map((entry) => entry.id)]);
    for (const id of [this._chosen, this._remembered()]) {
      if (ids.has(id)) return id;
    }
    const first = this._entries.find((entry) => entry.default === true && entry.blocks);
    return first?.id ?? NONE;
  }

  /** @param {string} id the base map to show while it is offered; fires no event */
  set value(id) {
    this._chosen = typeof id === "string" ? id : null;
    const shown = this.value;
    for (const radio of this.querySelectorAll("input")) radio.checked = radio.value === shown;
  }

  /** @returns {string[]} the ids marked „Podkład nie odpowiada” */
  get failed() {
    return [...this._failed];
  }

  /**
   * Mark an entry whose provider does not answer; the person choosing it again clears the mark.
   *
   * @param {string} id the entry's id
   */
  fail(id) {
    if (!this._entries.some((entry) => entry.id === id)) return;
    this._failed.add(id);
    this._marks();
  }

  connectedCallback() {
    // A property set before the element was defined shadows its setter; take it over.
    for (const name of ["entries", "texts", "value"]) {
      if (!Object.prototype.hasOwnProperty.call(this, name)) continue;
      const value = this[name];
      delete this[name];
      this[name] = value;
    }
    this.render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this.render();
  }

  /** The choice kept in the browser, unless remember="none". */
  _remembered() {
    if (this.getAttribute("remember") === "none") return null;
    try {
      return localStorage.getItem(STORAGE);
    } catch {
      return null;
    }
  }

  /** A person's choice: kept, its mark cleared, then `change`. */
  _choose(id) {
    this._chosen = id;
    if (this.getAttribute("remember") !== "none") {
      try {
        localStorage.setItem(STORAGE, id);
      } catch {
        // A browser that keeps nothing still shows the choice.
      }
    }
    this._failed.delete(id);
    this._marks();
    this.dispatchEvent(new CustomEvent("change", { bubbles: true, detail: { id } }));
  }

  /** Show „Podkład nie odpowiada” beside exactly the marked entries. */
  _marks() {
    for (const row of this.querySelectorAll(".nogat-basemaps-entry")) {
      const id = row.querySelector("input").value;
      const mark = row.querySelector(".nogat-basemaps-failed");
      if (this._failed.has(id) && !mark) {
        const text = document.createElement("span");
        text.className = "nogat-basemaps-failed";
        text.textContent = this._texts.failed;
        row.append(text);
      } else if (!this._failed.has(id) && mark) {
        mark.remove();
      }
    }
  }

  /** Draw the radios: the entries, then „bez podkładu”; nothing without an entry. */
  render() {
    this.replaceChildren();
    this.hidden = this._entries.length === 0;
    if (this.hidden) return;
    const list = document.createElement("div");
    list.className = "nogat-basemaps-list";
    list.setAttribute("role", "radiogroup");
    list.setAttribute("aria-label", this._texts.name);
    const shown = this.value;
    for (const { id, label } of [...this._entries, { id: NONE }]) {
      const row = document.createElement("label");
      row.className = "nogat-basemaps-entry";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = this._name;
      radio.value = id;
      radio.checked = id === shown;
      const text = document.createElement("span");
      text.className = "nogat-basemaps-label";
      text.textContent = id === NONE ? this._texts.none : (this._texts.labels[id] ?? label);
      row.append(radio, text);
      list.append(row);
    }
    // The radios' own change stays inside; the element tells of the choice by its id.
    list.addEventListener("change", (event) => {
      event.stopPropagation();
      if (event.target.checked) this._choose(event.target.value);
    });
    this.append(list);
    this._marks();
  }
}

if (!customElements.get("nogat-basemaps")) customElements.define("nogat-basemaps", NogatBasemaps);
