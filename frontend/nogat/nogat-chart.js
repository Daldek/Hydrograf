// Nogat GUI kit: charts over axes (DEV-15.16, ECO-090), the one chart module of every GUI.
// drawChart(container, spec) draws a chart into an element: an SVG with its axes, series and
// marks, the readout by pointer and keys, the range bar and the legend; the handle it returns
// redraws (`update`), reads out (`readout`), zooms (`zoom`) and measures (`plotWidth`).
// A chart whose x is a time or a value shows a range of it: a drag over the plot selects the
// range (a rectangle on a `zoom: "xy"` chart), Ctrl with the wheel or a trackpad's pinch zooms
// around the cursor while the wheel alone scrolls the page, Shift with a drag or a drag with the
// middle button pans, a double click, the key 0 and „Cały zakres” show the whole; on a touch
// screen two fingers pinch and pan, one finger scrolls the page and reads the values. Under a
// zoomed chart the bar „−”, „+”, „Cały zakres” and the range shown; a lone „+” before.
// toPng(svg, options) writes a drawn SVG, a chart as shown or any other, as a PNG with the
// providers' lines under it (DEV-20.5). The module's words are CHART_TEXTS, in Polish; a GUI in
// another language passes its own in `spec.texts` and its language in `spec.locale`.
// The DOM only: no library, no shadow DOM, no style attribute; nogat-chart.css styles it with
// the tokens, so it runs under CSP 'self' (toPng: `img-src 'self' data: blob:`). Built from
// Obserwator's chart engine (its src/charts/ at b5a1c1a), with Hydrolog's short time axis and
// PNG footer. Copy this file byte for byte (DEV-15.6); change it in Nogat design/kit/.
//
// The spec:
// - x: {label, scale, min, max, domain, digits, short, tickList, tickLabels}. `scale`: "linear"
//   (the default), "log", "time" (minutes: ticks in minutes on a short axis, else in whole
//   hours, `{unit}` of `label` becoming min or h), "date" (day numbers, days since 1970-01-01:
//   ticks of years, months or days), "datetime" (fractional day numbers of UTC instants: the
//   reader's hours and days) or "gumbel" (the exceedance probability [%], ticks p and
//   T = 100 / p; `domain: [99, 0.1]` fixes its ends). `tickList: [{value, label, sub}]`
//   replaces the computed ticks; `tickLabels: false` draws the axis without its labels.
// - y: {label, unit, scale: "linear" | "log" | "band", min, max, zero, pad, ticks, digits,
//   width}: `band` draws one horizontal bar per point ({x: value, y: name, sub, cls, text});
//   `width` fixes the space left of the plot, so charts one above another align.
// - y2: the same for a second axis: a panel above the main one sharing x, its bars hanging
//   from its top (`share` its part of the height), or with `side: "right"` a second unit on
//   the right of the main panel (`width` the space right of the plot).
// - series: [{id, kind, data, axis, cls, label, unit, digits, width, align, shape, readout,
//   legend}]: `kind` "line" (the default), "step", "area", "band" (data [x, lo, hi]), "bars",
//   "points" or "rug" (x values); data [[x, y], …] or {x, y, cls, shape}; a point without a
//   value breaks a line. A points series' `shape`, or a point's: "dot", "hollow", "diamond".
//   `cls` "s1" to "s6", "bar-p", "bar-pe", … picks a colour of nogat-chart.css.
// - marks: {kind: "peak", x, y, label, cls, guides: "x" | "xy"}, {kind: "hline", y, label},
//   {kind: "vline", x, from, to, extend, label}, {kind: "note", x, y, label, dx, dy, anchor},
//   {kind: "span", from, to, cls} (a grey band over a range of x: a gap); `axis: "y2"` puts
//   a mark on the second axis.
// - legend: true (the labelled series) or items {label, kind, cls, shape}; kind "text" a
//   note, "stroke" a line drawn as the curves are, "break" a new line of the legend.
// - readout: true or {series, x: (x) => text, value: (value, series) => text}.
// - zoom: by default on a date, datetime, time, linear or log x, never on a gumbel x or a band
//   y; false for none (a chart of a year's months or days); "xy" zooms and pans x and y alike.
// - size: "wide" (760 × 432, the default), "small" (360 × 178) or {width, height}; `fit:
//   {ratio, minHeight}` draws it at its container's width, as a zoomable chart is drawn up to
//   860 px at its size's ratio. `title` (its aria-label) or `labelledBy` (an element's id).
// - texts: words over CHART_TEXTS; locale: the language of numbers and dates ("pl-PL");
//   dateFormat: "YYYY.MM.DD" and the like, the dates written so instead of the locale's way.
// - onReadout(index | null): the readout moved to that index of its series' data, or hid;
//   onRange({min, max, width, y} | null): a person settled a range (null: the whole), `width`
//   the plot's width [CSS px], `y` the range of y of a "xy" chart.

/** The module's own words, in Polish; a GUI in another language passes its own in spec.texts. */
export const CHART_TEXTS = {
  returnPeriod: "T [lata]",
  probabilityReadout: "p = {p} % · T = {years} lat",
  keysReadout:
    "Strzałki w lewo i w prawo: odczyt wartości; Shift albo Page Up i Page Down: dziesięć " +
    "kroków; Home, End: początek i koniec; Esc: ukryj odczyt.",
  keysZoom:
    "Plus i minus: przybliż i oddal; strzałki za brzegiem zakresu: przesuń go; 0, podwójne " +
    "kliknięcie albo „Cały zakres”: cały zakres; przeciągnij po wykresie, aby pokazać jego " +
    "część; Ctrl z kółkiem myszy: przybliż w miejscu kursora; Shift z przeciąganiem albo " +
    "przeciąganie środkowym przyciskiem myszy: przesuń; na ekranie dotykowym dwa palce: " +
    "przybliż i przesuń.",
  zoomIn: "Przybliż",
  zoomOut: "Oddal",
  reset: "Cały zakres",
  range: "{from} – {to}",
  rangeXY: "{x}: {xFrom} – {xTo}, {y}: {yFrom} – {yTo}",
  imageFailed: "Przeglądarka nie zdołała zapisać wykresu jako obrazu.",
};

/** The first row of the probability axis: a symbol in every language. */
const PROBABILITY_LABEL = "p [%]";
/** The minus sign of the labels and of the button „−”. */
const MINUS = "\u2212";
const SVG_NS = "http://www.w3.org/2000/svg";
/** The sizes of the viewBox: a wide chart and a small one. */
const SIZES = { wide: { width: 760, height: 432 }, small: { width: 360, height: 178 } };
/** The gap between the y2 panel and the main panel [viewBox units]. */
const PANEL_GAP = 28;
/** How far a series may spill over the frame [viewBox units]: a line on an edge stays whole. */
const SPILL = 4;
/** The least distance a drag covers to select a range [viewBox units]; a shorter one is a click. */
const DRAG = 6;
/** What a notch of the wheel with Ctrl does to the range: ÷ 1.25 in, × 1.25 out. */
const NOTCH = 1.25;
/** A notch's `deltaY` in pixels, and a line's (deltaMode 1: three lines a notch). */
const NOTCH_DELTA = 100;
const LINE_DELTA = NOTCH_DELTA / 3;
/** The wheel is idle, its range settled, after this many milliseconds. */
const WHEEL_IDLE = 200;
/** A zoom in stops at this many points of the readout's series in the range... */
const LEAST_POINTS = 4;
/** ...or, without a readout series, at this share of the whole. */
const LEAST_SHARE = 1 / 1000;
/** Up to this width a zoomable chart is drawn at its container's width. */
const PHONE = "(max-width: 860px)";
/** The x scales a range of which can be shown; a probability axis keeps its own ticks. */
const ZOOM_SCALES = new Set(["date", "datetime", "linear", "log", "time"]);
const DAY_MS = 86400000;
const HOUR_MS = 3600000;
/** The key of a point's index in its series' data. */
const AT = Symbol("index");
/** The light theme's surface and text: a PNG's background and footer where no token is set. */
const SURFACE = "#ffffff";
const TEXT = "#2b2b2b";

// --- elements ---------------------------------------------------------------------------------

/** Round a coordinate to 0.1 of the viewBox (short paths, stable tests). */
function c1(value) {
  return Math.round(value * 10) / 10;
}

function apply(node, attrs) {
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (typeof value === "number" && !Number.isFinite(value)) continue;
    node.setAttribute(name, typeof value === "number" ? String(c1(value)) : String(value));
  }
  return node;
}

/** An SVG element: numbers rounded to 0.1, `undefined`, `null`, `false` and NaN left out. */
function svgEl(tag, attrs = {}, children = []) {
  const node = apply(document.createElementNS(SVG_NS, tag), attrs);
  for (const child of children) node.append(child);
  return node;
}

/** An HTML element. */
function htmlEl(tag, attrs = {}, children = []) {
  const node = apply(document.createElement(tag), attrs);
  for (const child of children) node.append(child);
  return node;
}

/** An SVG text of the classes `cls` at x, y. */
function textEl(cls, x, y, text, anchor) {
  return svgEl("text", { class: cls, x, y, "text-anchor": anchor }, [text]);
}

/** A text's `{name}` placeholders filled; a name without a value stays as it is. */
function fill(template, values) {
  return String(template).replace(/\{(\w+)\}/g, (match, name) =>
    name in values ? String(values[name]) : match,
  );
}

// --- numbers and dates ------------------------------------------------------------------------

const FORMATS = new Map();

/**
 * The numbers and dates of a language: the formats a chart writes its ticks, readout and bar
 * with. Numbers through `Intl` (a decimal comma or point, thousands grouped from five digits,
 * the minus sign U+2212); dates through `Intl` (dd.mm.rrrr in Polish, dd/mm/rrrr in British
 * English, month names), or by `dateFormat` where a GUI writes them its own way.
 *
 * @param {{locale?: string, dateFormat?: string}} [options] `locale` ("pl-PL" by default);
 *   `dateFormat` a pattern of YYYY, MM and DD, e.g. "YYYY.MM.DD": a day so, a day of the
 *   current year without YYYY, a month without DD
 * @returns {{
 *   locale: string, number: (value: number, digits?: number) => string,
 *   time: (minutes: number) => string, day: (day: number) => string,
 *   dayMonth: (day: number) => string, month: (year: number, month: number, withYear: boolean)
 *   => string, dateTime: (day: number) => string, hour: (when: Date) => string,
 *   localDay: (when: Date, withYear: boolean) => string
 * }} cached per locale and pattern
 */
export function chartFormat(options = {}) {
  const locale = options.locale || "pl-PL";
  const pattern = options.dateFormat || "";
  const key = `${locale}\u0000${pattern}`;
  let format = FORMATS.get(key);
  if (!format) {
    format = makeFormat(locale, pattern);
    FORMATS.set(key, format);
  }
  return format;
}

/** A date pattern without a token and the separator beside it. */
function without(pattern, token) {
  const at = pattern.indexOf(token);
  if (at < 0) return pattern;
  if (at === 0) return pattern.slice(token.length).replace(/^[^YMD]+/, "");
  return pattern.slice(0, at).replace(/[^YMD]+$/, "") + pattern.slice(at + token.length);
}

/** The writers of a date pattern: a whole day, a day and its month, a month and its year. */
function datePattern(pattern) {
  const writer = (form) => (year, month, day) =>
    form.replace(/YYYY|MM|DD/g, (token) => {
      if (token === "YYYY") return String(year).padStart(4, "0");
      return String(token === "MM" ? month : day).padStart(2, "0");
    });
  return {
    full: writer(pattern),
    dayMonth: writer(without(pattern, "YYYY")),
    month: writer(without(pattern, "DD")),
  };
}

function makeFormat(locale, pattern) {
  const made = new Map();
  const intl = (name, make) => {
    let format = made.get(name);
    if (!format) {
      format = make();
      made.set(name, format);
    }
    return format;
  };
  const dates = pattern ? datePattern(pattern) : null;
  const utc = (day) => new Date(Math.round(day) * DAY_MS);
  // The calendar parts of an instant: in UTC (a date axis) or in the reader's time zone
  const utcParts = (when) => [when.getUTCFullYear(), when.getUTCMonth() + 1, when.getUTCDate()];
  const localParts = (when) => [when.getFullYear(), when.getMonth() + 1, when.getDate()];
  const dated = (options) =>
    intl(JSON.stringify(options), () => new Intl.DateTimeFormat(locale, options));
  const number = (value, digits = 0) => {
    if (!Number.isFinite(value)) return "–";
    const places = Math.max(0, Math.min(20, digits));
    const format = intl(`n${places}`, () =>
      new Intl.NumberFormat(locale, {
        minimumFractionDigits: places,
        maximumFractionDigits: places,
        useGrouping: "min2",
      }),
    );
    // A value that rounds to zero has no sign
    const shown = Number(value.toFixed(places)) === 0 ? 0 : value;
    return format.format(shown).replace("-", MINUS);
  };
  const hour = (when) =>
    dated({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(when);
  return {
    locale,
    number,
    hour,
    time(minutes) {
      const total = Math.round(minutes);
      const sign = total < 0 ? MINUS : "";
      const abs = Math.abs(total);
      return `${sign}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, "0")}`;
    },
    day(day) {
      const when = utc(day);
      if (dates) return dates.full(...utcParts(when));
      return dated({ day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }).format(
        when,
      );
    },
    dayMonth(day) {
      const when = utc(day);
      if (dates) return dates.dayMonth(...utcParts(when));
      return dated({ day: "2-digit", month: "2-digit", timeZone: "UTC" }).format(when);
    },
    month(year, month, withYear) {
      if (dates) return dates.month(year, month + 1, 1);
      const when = new Date(Date.UTC(2001, month, 1));
      if (withYear) when.setUTCFullYear(year);
      const options = { month: "short", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC" };
      return dated(options).format(when).replace(/\.$/, "");
    },
    dateTime(day) {
      const when = new Date(Math.round(day * DAY_MS));
      if (dates) return `${dates.full(...localParts(when))} ${hour(when)}`;
      const options = {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      };
      return dated(options).format(when);
    },
    localDay(when, withYear) {
      if (dates) return (withYear ? dates.full : dates.dayMonth)(...localParts(when));
      const year = withYear ? { year: "numeric" } : {};
      return dated({ day: "2-digit", month: "2-digit", ...year }).format(when);
    },
  };
}

// --- scales and ticks -------------------------------------------------------------------------

/**
 * The smallest and the largest of the values a test keeps, in one pass (spreading a long
 * series into `Math.min` overflows the call stack).
 *
 * @param {Iterable<number>} values the values
 * @param {(value: number) => boolean} [keep=Number.isFinite] which values count
 * @returns {[number, number] | null} null when none counts
 */
export function extent(values, keep = Number.isFinite) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const value of values) {
    if (!keep(value)) continue;
    if (value < lo) lo = value;
    if (value > hi) hi = value;
  }
  return lo <= hi ? [lo, hi] : null;
}

/**
 * The decimals that show every multiple of a step exactly.
 *
 * @param {number} step a tick step, e.g. 0.25
 * @returns {number} 2 for 0.25, 1 for 2.5, 0 for 50; 10 for a step 10 decimals do not show
 */
export function stepDigits(step) {
  for (let digits = 0; digits < 10; digits += 1) {
    const scaled = step * 10 ** digits;
    const whole = Math.round(scaled);
    if (whole >= 1 && Math.abs(scaled - whole) < 1e-9 * Math.max(1, scaled)) return digits;
  }
  return 10;
}

const NICE = [1, 2, 2.5, 5, 10];

/**
 * The smallest rounded step (1, 2, 2.5 or 5 times a power of ten) that divides a span into at
 * most `count` intervals.
 *
 * @param {number} span the span (> 0)
 * @param {number} [count=6] the most intervals
 * @returns {number}
 */
export function niceStep(span, count = 6) {
  if (!(span > 0)) return 1;
  const raw = span / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(raw));
  for (const factor of NICE) {
    const step = factor * power;
    if (span / step <= count + 1e-9) return step;
  }
  return 10 * power;
}

/** Round away the binary noise of a multiple of a step. */
function clean(value, digits) {
  return Number(value.toFixed(Math.min(12, digits + 2)));
}

/** The most ticks of a linear domain: a step far below its span is no tick step. */
const MAX_TICKS = 1000;

/**
 * The ticks of a linear domain at multiples of a step.
 *
 * @param {number} min the start of the domain
 * @param {number} max its end
 * @param {number} step the step
 * @param {ReturnType<typeof chartFormat>} [format] the language of the labels
 * @returns {{value: number, label: string}[]} none when there would be more than 1000
 */
export function linearTicks(min, max, step, format = chartFormat()) {
  const digits = stepDigits(step);
  const ticks = [];
  const first = Math.ceil(min / step - 1e-9);
  const last = Math.floor(max / step + 1e-9);
  // Counted from 0, never from `first`: beyond 2^53 a whole number plus 1 is that number
  const count = last - first;
  if (!(count < MAX_TICKS)) return ticks;
  for (let k = 0; k <= count; k += 1) {
    const value = clean((first + k) * step, digits);
    ticks.push({ value, label: format.number(value, digits) });
  }
  return ticks;
}

/** The narrowest span of a linear domain, as a share of its largest absolute end (at least 1). */
const SPAN_RESOLUTION = 1e-9;

/**
 * A linear domain rounded outwards to rounded ticks: it covers the values and, with `zero`,
 * zero; `pad` adds a share of the span above the largest value and, below zero, under the
 * smallest. Values within `SPAN_RESOLUTION` of one another span 10 % of the value above it.
 *
 * @param {number[]} values the values (non-finite ones skipped)
 * @param {{count?: number, zero?: boolean, pad?: number, min?: number, max?: number,
 *   format?: ReturnType<typeof chartFormat>}} [options] `min` and `max` fix an end
 * @returns {{min: number, max: number, step: number, ticks: {value: number, label: string}[]}}
 */
export function niceDomain(values, options = {}) {
  const { count = 6, zero = true, pad = 0.08, format = chartFormat() } = options;
  const range = extent(values);
  let lo = options.min ?? (range ? range[0] : 0);
  let hi = options.max ?? (range ? range[1] : 1);
  if (zero && options.min === undefined) lo = Math.min(0, lo);
  if (zero && options.max === undefined) hi = Math.max(0, hi);
  if (!(hi - lo > SPAN_RESOLUTION * Math.max(1, Math.abs(lo), Math.abs(hi)))) {
    const width = Math.abs(lo) * 0.1;
    hi = lo + (width > SPAN_RESOLUTION ? width : 1);
  }
  const span = hi - lo;
  if (options.max === undefined) hi += pad * span;
  if (options.min === undefined && lo < 0) lo -= pad * span;
  const step = niceStep(hi - lo, count);
  const digits = stepDigits(step);
  const min = options.min === undefined ? clean(Math.floor(lo / step + 1e-9) * step, digits) : lo;
  const max = options.max ?? clean(Math.ceil(hi / step - 1e-9) * step, digits);
  return { min, max, step, ticks: linearTicks(min, max, step, format) };
}

/**
 * The ticks of a log domain: each power of ten, and 2 and 5 times it within two decades; a
 * part of a decade (a zoomed axis) gets rounded linear steps.
 *
 * @param {number} min the start (> 0)
 * @param {number} max the end (> min)
 * @param {ReturnType<typeof chartFormat>} [format]
 * @returns {{value: number, label: string}[]}
 */
export function logTicks(min, max, format = chartFormat()) {
  const first = Math.floor(Math.log10(min) + 1e-9);
  const last = Math.ceil(Math.log10(max) - 1e-9);
  const factors = last - first <= 2 ? [1, 2, 5] : [1];
  const ticks = [];
  for (let power = first; power <= last; power += 1) {
    for (const factor of factors) {
      const value = Number((factor * 10 ** power).toPrecision(12));
      if (value < min * (1 - 1e-9) || value > max * (1 + 1e-9)) continue;
      ticks.push({ value, label: format.number(value, Math.max(0, -power)) });
    }
  }
  if (ticks.length >= 2) return ticks;
  return linearTicks(min, max, niceStep(max - min, 5), format);
}

/**
 * A log domain rounded outwards to powers of ten.
 *
 * @param {number[]} values the values (those ≤ 0 skipped)
 * @param {ReturnType<typeof chartFormat>} [format]
 * @returns {{min: number, max: number, ticks: {value: number, label: string}[]}}
 */
export function logDomain(values, format = chartFormat()) {
  const range = extent(values, (value) => Number.isFinite(value) && value > 0);
  const lo = range ? range[0] : 1;
  const hi = range ? range[1] : 10;
  const min = 10 ** Math.floor(Math.log10(lo) + 1e-9);
  let max = 10 ** Math.ceil(Math.log10(hi) - 1e-9);
  if (max <= min) max = min * 10;
  return { min, max, ticks: logTicks(min, max, format) };
}

/** Tick steps of a time axis [min]: under an hour labelled in minutes, from an hour in hours. */
const TIME_STEPS = [1, 2, 5, 10, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440, 2880, 10080];

/**
 * The ticks of a time domain in minutes: a step under an hour (a short rain) labelled in
 * minutes, any other in whole hours, so no label is a fraction of an hour.
 *
 * @param {number} min the start [min]
 * @param {number} max the end [min]
 * @param {number} [count=13] the most ticks
 * @param {ReturnType<typeof chartFormat>} [format]
 * @returns {{step: number, unit: "min" | "h", ticks: {value: number, label: string}[]}}
 */
export function timeTicks(min, max, count = 13, format = chartFormat()) {
  const span = Math.max(max - min, 1);
  // Beyond the steps: whole weeks, still at most `count` ticks
  const week = TIME_STEPS.at(-1);
  const step =
    TIME_STEPS.find((candidate) => span / candidate <= count - 1) ??
    week * Math.ceil(span / (week * (count - 1)));
  const unit = step < 60 ? "min" : "h";
  const per = unit === "h" ? 60 : 1;
  const ticks = [];
  for (let k = Math.ceil(min / step - 1e-9); k * step <= max + 1e-9; k += 1) {
    ticks.push({ value: k * step, label: format.number((k * step) / per) });
  }
  return { step, unit, ticks };
}

/**
 * A time domain in minutes: from the first value (never before 0) to the last one rounded up
 * to the tick step.
 *
 * @param {number[]} values the times [min]
 * @param {{min?: number, max?: number, count?: number, format?: ReturnType<typeof chartFormat>}}
 *   [options] fixed ends
 * @returns {{min: number, max: number, step: number, unit: "min" | "h", ticks: object[]}}
 */
export function timeDomain(values, options = {}) {
  const range = extent(values);
  const lo = Math.max(0, options.min ?? (range ? range[0] : 0));
  let hi = options.max ?? (range ? range[1] : 60);
  if (hi <= lo) hi = lo + 60;
  const { step } = timeTicks(lo, hi, options.count, options.format);
  const max = options.max ?? Math.ceil(hi / step - 1e-9) * step;
  return { min: lo, max, ...timeTicks(lo, max, options.count, options.format) };
}

/** The `Date` of a day number (UTC midnight). */
function dateOfDay(day) {
  return new Date(Math.round(day) * DAY_MS);
}

/** The day number of a calendar day (month 0-based, may overflow into the next years). */
function dayOf(year, month, day = 1) {
  return Math.round(Date.UTC(year, month, day) / DAY_MS);
}

// Steps of a date axis, finest first: [unit, multiple]; the average length of each unit
const DATE_STEPS = [
  ["day", 1], ["day", 2], ["day", 7], ["day", 14],
  ["month", 1], ["month", 2], ["month", 3], ["month", 6],
  ["year", 1], ["year", 2], ["year", 5], ["year", 10], ["year", 20], ["year", 25], ["year", 50],
  ["year", 100],
];
const UNIT_DAYS = { day: 1, month: 30.44, year: 365.25 };

/**
 * The ticks of a date domain in day numbers: whole days, weeks (Mondays), months or years, the
 * finest step that keeps at most `count` ticks. Years read "1951"; months by their short name,
 * with the year at January and on the first tick ("sty 2020"); days by day and month ("12.03"),
 * with the year on the first tick. A `dateFormat` writes months and days its way.
 *
 * @param {number} min the first day number
 * @param {number} max the last day number
 * @param {number} [count=8] the most ticks
 * @param {ReturnType<typeof chartFormat>} [format]
 * @returns {{step: [string, number], ticks: {value: number, label: string}[]}}
 */
export function dateTicks(min, max, count = 8, format = chartFormat()) {
  const span = Math.max(max - min, 1);
  const most = Math.max(2, count);
  const step =
    DATE_STEPS.find(([unit, times]) => span / (UNIT_DAYS[unit] * times) <= most - 1) ??
    ["year", 100 * Math.ceil(span / (UNIT_DAYS.year * 100 * (most - 1)))];
  const [unit, times] = step;
  const ticks = [];
  const start = dateOfDay(Math.floor(min));
  if (unit === "year") {
    let year = Math.ceil(start.getUTCFullYear() / times) * times;
    if (dayOf(year, 0) < min) year += times;
    for (; dayOf(year, 0) <= max; year += times) {
      ticks.push({ value: dayOf(year, 0), label: String(year) });
    }
  } else if (unit === "month") {
    let index = start.getUTCFullYear() * 12 + Math.ceil(start.getUTCMonth() / times) * times;
    if (dayOf(Math.floor(index / 12), index % 12) < min) index += times;
    for (; dayOf(Math.floor(index / 12), index % 12) <= max; index += times) {
      const year = Math.floor(index / 12);
      const month = index % 12;
      const label = format.month(year, month, month === 0 || !ticks.length);
      ticks.push({ value: dayOf(year, month), label });
    }
  } else {
    // Weeks start on Mondays: day 4 (1970-01-05) is one
    const offset = times % 7 === 0 ? 4 : 0;
    for (let day = Math.ceil((min - offset) / times) * times + offset; day <= max; day += times) {
      ticks.push({ value: day, label: ticks.length ? format.dayMonth(day) : format.day(day) });
    }
  }
  return { step, ticks };
}

/**
 * A date domain in day numbers: the first and the last value (or the fixed ends), unrounded.
 *
 * @param {number[]} values day numbers
 * @param {{min?: number, max?: number, count?: number, format?: ReturnType<typeof chartFormat>}}
 *   [options]
 * @returns {{min: number, max: number, step: [string, number], ticks: object[]}}
 */
export function dateDomain(values, options = {}) {
  const range = extent(values);
  const today = Math.floor(Date.now() / DAY_MS);
  const min = options.min ?? (range ? range[0] : today - 365);
  let max = options.max ?? (range ? range[1] : today);
  if (max <= min) max = min + 1;
  return { min, max, ...dateTicks(min, max, options.count, options.format) };
}

/** Steps of a datetime axis in hours and in days, finest first. */
const HOUR_STEPS = [1, 2, 3, 6, 12];
const DAY_STEPS = [1, 2, 7, 14];

/**
 * The ticks of a datetime domain: the reader's whole hours (every 1, 2, 3, 6 or 12 h, a local
 * midnight labelled by its day), local midnights (every 1 or 2 days, Mondays every 1 or 2
 * weeks; the first with its year), or the months and years of `dateTicks`.
 *
 * @param {number} min the first fractional day number
 * @param {number} max the last
 * @param {number} [count=8] the most ticks
 * @param {ReturnType<typeof chartFormat>} [format]
 * @returns {{step: [string, number], ticks: {value: number, label: string}[]}}
 */
export function datetimeTicks(min, max, count = 8, format = chartFormat()) {
  const span = Math.max(max - min, 1 / 24);
  const most = Math.max(2, count);
  const hours = HOUR_STEPS.find((step) => (span * 24) / step <= most - 1);
  const ticks = [];
  if (hours !== undefined) {
    // Whole UTC hours are whole local hours in every time zone of the providers
    const first = Math.ceil((min * DAY_MS) / HOUR_MS) * HOUR_MS;
    for (let at = first; at <= max * DAY_MS; at += HOUR_MS) {
      const when = new Date(at);
      if (when.getHours() % hours !== 0) continue;
      const label = when.getHours() === 0 ? format.localDay(when, false) : format.hour(when);
      ticks.push({ value: at / DAY_MS, label });
    }
    return { step: ["hour", hours], ticks };
  }
  const days = DAY_STEPS.find((step) => span / step <= most - 1);
  if (days === undefined) return dateTicks(min, max, count, format);
  const start = new Date(min * DAY_MS);
  // Local calendar days, aligned as `dateTicks` aligns them: weeks start on Mondays
  const offset = days % 7 === 0 ? 4 : 0;
  let when = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const after = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1);
  for (; when.getTime() <= max * DAY_MS; when = after(when)) {
    const day = Math.round(Date.UTC(when.getFullYear(), when.getMonth(), when.getDate()) / DAY_MS);
    if (when.getTime() < min * DAY_MS || (day - offset) % days !== 0) continue;
    ticks.push({ value: when.getTime() / DAY_MS, label: format.localDay(when, !ticks.length) });
  }
  return { step: ["day", days], ticks };
}

/**
 * A datetime domain in fractional day numbers: the first and the last value, unrounded.
 *
 * @param {number[]} values fractional day numbers
 * @param {{min?: number, max?: number, count?: number, format?: ReturnType<typeof chartFormat>}}
 *   [options]
 * @returns {{min: number, max: number, step: [string, number], ticks: object[]}}
 */
export function datetimeDomain(values, options = {}) {
  const range = extent(values);
  const now = Date.now() / DAY_MS;
  const min = options.min ?? (range ? range[0] : now - 7);
  let max = options.max ?? (range ? range[1] : now);
  if (max <= min) max = min + 1 / 24;
  return { min, max, ...datetimeTicks(min, max, options.count, options.format) };
}

/**
 * The reduced variate of the Gumbel distribution: u = −ln(−ln(1 − p/100)).
 *
 * @param {number} percent the exceedance probability p [%], 0 < p < 100
 * @returns {number}
 */
export function reducedVariate(percent) {
  return -Math.log(-Math.log(1 - percent / 100));
}

/**
 * The exceedance probability of a reduced variate (the inverse of `reducedVariate`).
 *
 * @param {number} variate u
 * @returns {number} p [%]
 */
export function exceedanceFromVariate(variate) {
  return 100 * (1 - Math.exp(-Math.exp(-variate)));
}

/** Exceedance probabilities [%] of the probability axis; the first ones win a crowded axis. */
const GUMBEL_MAJOR = [50, 10, 1, 0.1, 0.01, 90, 99];
const GUMBEL_MINOR = [20, 5, 2, 0.5, 0.2, 0.05, 0.02, 80, 95, 98, 99.9];

/**
 * The ticks of a Gumbel probability axis: each an exceedance probability p [%] labelled with p
 * and with the return period T = 100 / p [years]; a tick nearer than `gap` to a kept one is
 * dropped, the major ones kept first.
 *
 * @param {(percent: number) => number} scale a Gumbel scale (`gumbelScale`)
 * @param {number} [gap=30] the least distance between ticks [viewBox units]
 * @param {ReturnType<typeof chartFormat>} [format]
 * @returns {{value: number, label: string, sub: string}[]} ordered by position
 */
export function gumbelTicks(scale, gap = 30, format = chartFormat()) {
  const [left, right] = scale.domain;
  const lo = Math.min(left, right);
  const hi = Math.max(left, right);
  const kept = [];
  for (const percent of [...GUMBEL_MAJOR, ...GUMBEL_MINOR]) {
    if (percent < lo || percent > hi) continue;
    const at = scale(percent);
    if (Math.abs(at - scale.range[0]) < gap / 2) continue; // beside the row labels
    if (kept.some((tick) => Math.abs(scale(tick) - at) < gap)) continue;
    kept.push(percent);
  }
  kept.sort((a, b) => scale(a) - scale(b));
  return kept.map((percent) => {
    const years = 100 / percent;
    const yearsDigits = Math.abs(years - Math.round(years)) < 1e-9 ? 0 : 2;
    return {
      value: percent,
      label: format.number(percent, stepDigits(percent)),
      sub: format.number(years, yearsDigits),
    };
  });
}

/**
 * A Gumbel domain in exceedance probability [%] covering the values with a margin of `pad` of
 * the reduced variate's span on each side.
 *
 * @param {number[]} values exceedance probabilities [%]
 * @param {{pad?: number}} [options]
 * @returns {[number, number]} [left, right], the larger probability first
 */
export function gumbelDomain(values, options = {}) {
  const { pad = 0.04 } = options;
  const kept = values.filter((percent) => Number.isFinite(percent) && percent > 0 && percent < 100);
  const range = extent(kept.map(reducedVariate));
  let lo = range ? range[0] : reducedVariate(90);
  let hi = range ? range[1] : reducedVariate(1);
  if (hi - lo < 1) {
    lo -= 0.5;
    hi += 0.5;
  }
  const margin = pad * (hi - lo);
  return [exceedanceFromVariate(lo - margin), exceedanceFromVariate(hi + margin)];
}

function attach(map, type, domain, range, invert) {
  map.type = type;
  map.domain = domain;
  map.range = range;
  map.invert = invert;
  return map;
}

/**
 * A linear scale from a domain to a range of the viewBox, with `invert`.
 *
 * @param {[number, number]} domain [d0, d1]
 * @param {[number, number]} range [r0, r1]
 * @returns {((value: number) => number) & {type: string, domain: number[], range: number[],
 *   invert: (at: number) => number}}
 */
export function linearScale([d0, d1], [r0, r1]) {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const invert = (at) => (k === 0 ? d0 : d0 + (at - r0) / k);
  return attach((value) => r0 + (value - d0) * k, "linear", [d0, d1], [r0, r1], invert);
}

/**
 * A log (base 10) scale; values ≤ 0 map to NaN.
 *
 * @param {[number, number]} domain [d0, d1], both > 0
 * @param {[number, number]} range [r0, r1]
 * @returns {((value: number) => number) & {type: string, domain: number[], range: number[],
 *   invert: (at: number) => number}}
 */
export function logScale([d0, d1], [r0, r1]) {
  const l0 = Math.log10(d0);
  const k = (r1 - r0) / (Math.log10(d1) - l0 || 1);
  const map = (value) => (value > 0 ? r0 + (Math.log10(value) - l0) * k : NaN);
  return attach(map, "log", [d0, d1], [r0, r1], (at) => 10 ** (l0 + (at - r0) / k));
}

/**
 * A Gumbel probability scale: linear in the reduced variate.
 *
 * @param {[number, number]} domain exceedance probabilities [%], e.g. [99, 0.1]
 * @param {[number, number]} range [r0, r1]
 * @returns {((percent: number) => number) & {type: string, domain: number[], range: number[],
 *   invert: (at: number) => number}}
 */
export function gumbelScale([p0, p1], [r0, r1]) {
  const u0 = reducedVariate(p0);
  const k = (r1 - r0) / (reducedVariate(p1) - u0 || 1);
  const map = (percent) =>
    percent > 0 && percent < 100 ? r0 + (reducedVariate(percent) - u0) * k : NaN;
  const invert = (at) => exceedanceFromVariate(u0 + (at - r0) / k);
  return attach(map, "gumbel", [p0, p1], [r0, r1], invert);
}

// --- layout and axes --------------------------------------------------------------------------

/** The points of each series' data array, by its kind (a band's or the others'): built once. */
const POINTS = new WeakMap();

/**
 * A series' points as `{x, y, cls?, shape?, label?, sub?, text?}` objects (a band's `{x, lo,
 * hi}`), each with its index in `data`; built once per data array, so a spec's `data` is new
 * when its values change and never changed in place.
 */
function points(series) {
  const band = series.kind === "band";
  const data = series.data ?? [];
  const known = POINTS.get(data);
  if (known && known.band === band) return known.points;
  const built = data.map((datum, at) => {
    if (Array.isArray(datum)) {
      if (band) return { x: datum[0], lo: datum[1], hi: datum[2], [AT]: at };
      return { x: datum[0], y: datum[1], [AT]: at };
    }
    return typeof datum === "number" ? { x: datum, [AT]: at } : { ...datum, [AT]: at };
  });
  POINTS.set(data, { band, points: built });
  return built;
}

/** The width of a bar series in x units: its `width`, else its x values' least spacing. */
function barWidth(series, data = points(series)) {
  if (series.width > 0) return series.width;
  let width = Infinity;
  for (let i = 1; i < data.length; i += 1) {
    const step = Math.abs(data[i].x - data[i - 1].x);
    if (step > 0) width = Math.min(width, step);
  }
  return Number.isFinite(width) ? width : 1;
}

function sizeOf(spec) {
  const own = spec.size && typeof spec.size === "object";
  if (own) return { ...spec.size, small: spec.size.width < 500 };
  const name = spec.size === "small" ? "small" : "wide";
  return { ...SIZES[name], small: name === "small" };
}

function labelWidth(labels) {
  const longest = Math.max(0, ...labels.map((label) => String(label).length));
  return 14 + 6.5 * longest;
}

/**
 * The values of the x and y axes over the series and the marks. With both ends of a linear,
 * log, time or date x fixed (a zoomed chart's range), the y axes cover the points and marks
 * within them only: the y axis fits the part shown. A reference line (`hline`) always counts.
 */
function extents(spec, band) {
  const xs = [];
  const ys = { y: [], y2: [] };
  const lo = spec.x?.min;
  const hi = spec.x?.max;
  const ranged = spec.x?.scale !== "gumbel" && Number.isFinite(lo) && Number.isFinite(hi);
  const within = (x) => !ranged || (x >= Math.min(lo, hi) && x <= Math.max(lo, hi));
  for (const series of spec.series ?? []) {
    const axis = series.axis === "y2" ? "y2" : "y";
    const data = points(series);
    if (band) {
      for (const point of data) xs.push(point.x);
      continue;
    }
    const width = series.kind === "bars" ? barWidth(series, data) : 0;
    for (const point of data) {
      xs.push(point.x);
      if (width) xs.push(point.x + (series.align === "center" ? width / 2 : width));
      if (series.kind === "bars" && series.align === "center") xs.push(point.x - width / 2);
      if (!within(point.x)) continue;
      if (series.kind === "band") ys[axis].push(point.lo, point.hi);
      else if (series.kind !== "rug") ys[axis].push(point.y);
    }
  }
  for (const mark of spec.marks ?? []) {
    const axis = mark.axis === "y2" ? "y2" : "y";
    if (mark.kind === "span") {
      xs.push(mark.from, mark.to);
      continue;
    }
    if (Number.isFinite(mark.x) && mark.kind !== "hline") xs.push(mark.x);
    if (Number.isFinite(mark.x) && mark.kind !== "hline" && !within(mark.x)) continue;
    if (Number.isFinite(mark.y) && mark.kind !== "vline") ys[axis].push(mark.y);
  }
  return { xs, ys };
}

function yAxis(axisSpec, values, range, count, format) {
  const options = axisSpec ?? {};
  if (options.scale === "log") {
    const domain =
      options.min !== undefined && options.max !== undefined
        ? { min: options.min, max: options.max, ticks: logTicks(options.min, options.max, format) }
        : logDomain(values, format);
    return { ...domain, scale: logScale([domain.min, domain.max], range) };
  }
  const domain = niceDomain(values, {
    count: options.ticks ?? count,
    zero: options.zero ?? true,
    pad: options.pad ?? 0.08,
    min: options.min,
    max: options.max,
    format,
  });
  return { ...domain, scale: linearScale([domain.min, domain.max], range) };
}

/** The ticks of an axis: its own `tickList` within the domain, else the computed ones. */
function withTicks(options, domain) {
  if (!Array.isArray(options.tickList)) return domain;
  const lo = Math.min(domain.min, domain.max);
  const hi = Math.max(domain.min, domain.max);
  const span = hi - lo || 1;
  const ticks = options.tickList.filter(
    (tick) => tick.value >= lo - 1e-9 * span && tick.value <= hi + 1e-9 * span,
  );
  return { ...domain, ticks };
}

function xAxis(axisSpec, values, range, small, format) {
  const options = axisSpec ?? {};
  const kind = options.scale ?? "linear";
  // A date label takes about 54 viewBox units (≈ CSS px of a fitted chart)
  const dateCount = Math.max(2, Math.floor(Math.abs(range[1] - range[0]) / (small ? 50 : 58)));
  if (kind === "time") {
    const count = small ? 8 : 13;
    const domain = timeDomain(values, { min: options.min, max: options.max, count, format });
    // The label names the unit of the ticks: its `{unit}` becomes min or h
    const label = options.label && fill(options.label, { unit: domain.unit });
    const scale = linearScale([domain.min, domain.max], range);
    return withTicks(options, { ...domain, label, scale });
  }
  if (kind === "date" || kind === "datetime") {
    const make = kind === "date" ? dateDomain : datetimeDomain;
    const domain = make(values, { min: options.min, max: options.max, count: dateCount, format });
    return withTicks(options, { ...domain, scale: linearScale([domain.min, domain.max], range) });
  }
  if (kind === "gumbel") {
    const [left, right] = options.domain ?? gumbelDomain(values);
    const scale = gumbelScale([left, right], range);
    const ticks = gumbelTicks(scale, small ? 26 : 30, format);
    return withTicks(options, { min: left, max: right, ticks, scale });
  }
  if (kind === "log") {
    const domain =
      options.min !== undefined && options.max !== undefined
        ? { min: options.min, max: options.max, ticks: logTicks(options.min, options.max, format) }
        : logDomain(values, format);
    return withTicks(options, { ...domain, scale: logScale([domain.min, domain.max], range) });
  }
  const domain = niceDomain(values, {
    count: options.ticks ?? (small ? 6 : 10),
    zero: options.zero ?? false,
    pad: options.pad ?? 0,
    min: options.min,
    max: options.max,
    format,
  });
  return withTicks(options, { ...domain, scale: linearScale([domain.min, domain.max], range) });
}

/**
 * The layout of a chart: the viewBox, the plot, the panels (`y2` a panel above the main one,
 * or with `side: "right"` a second axis over it), each axis's scale and ticks.
 */
function chartLayout(spec, format) {
  const { width, height, small } = sizeOf(spec);
  const band = spec.y?.scale === "band";
  const gumbel = spec.x?.scale === "gumbel";
  const labelled = spec.x?.tickLabels !== false;
  const top = small ? 16 : 26;
  const bottom = height - (labelled ? (gumbel ? 60 : small ? 28 : 38) : small ? 6 : 8);
  const { xs, ys } = extents(spec, band);

  if (band) {
    const categories = [];
    for (const series of spec.series ?? []) {
      for (const point of points(series)) categories.push(point);
    }
    const left = spec.y.width ?? 160;
    const right = width - (small ? 10 : 16);
    const x = xAxis({ zero: true, pad: 0.3, ...spec.x }, xs, [left, right], small, format);
    const rows = Math.max(1, categories.length);
    const step = (bottom - top) / rows;
    return {
      width,
      height,
      small,
      band,
      plot: { left, right, top, bottom },
      main: { top, bottom },
      upper: null,
      x: { ...spec.x, ...x },
      y: { ...spec.y, step, bar: Math.min(24, step * 0.6) },
      y2: null,
      categories,
    };
  }

  const beside = spec.y2?.side === "right";
  let main = { top, bottom };
  let upper = null;
  if (spec.y2 && !beside) {
    const share = spec.y2.share ?? 0.27;
    const upperBottom = top + (bottom - top - PANEL_GAP) * share;
    upper = { top, bottom: upperBottom };
    main = { top: upperBottom + PANEL_GAP, bottom };
  }
  const y = yAxis(spec.y, ys.y, [main.bottom, main.top], small ? 5 : 7, format);
  let y2 = null;
  if (spec.y2) {
    const range = beside ? [main.bottom, main.top] : [upper.top, upper.bottom];
    y2 = yAxis(spec.y2, ys.y2, range, beside ? (small ? 5 : 7) : 4, format);
  }
  const leftLabels = [...y.ticks, ...(y2 && !beside ? y2.ticks : [])].map((tick) => tick.label);
  const base = gumbel ? 64 : small ? 40 : 56;
  const left = spec.y?.width ?? Math.max(base, labelWidth(leftLabels));
  const rim = beside
    ? (spec.y2.width ?? Math.max(small ? 40 : 56, labelWidth(y2.ticks.map((tick) => tick.label))))
    : small ? 10 : 16;
  const right = width - rim;
  const x = xAxis(spec.x, xs, [left, right], small, format);
  return {
    width,
    height,
    small,
    band,
    plot: { left, right, top, bottom },
    main,
    upper,
    x: { ...spec.x, ...x },
    y: { ...spec.y, ...y },
    y2: y2 ? { ...spec.y2, ...y2 } : null,
    categories: null,
  };
}

function hLines(values, left, right) {
  return values.map((at) => svgEl("line", { x1: left, x2: right, y1: at, y2: at }));
}

/** The grid: a line at each y tick of each panel, a dashed one at each x tick across them. */
function drawGrid(layout) {
  const { plot, x, y, y2, band } = layout;
  const groups = [];
  if (!band) {
    const at = y.ticks.map((tick) => y.scale(tick.value));
    if (y2 && layout.upper) at.push(...y2.ticks.map((tick) => y2.scale(tick.value)));
    groups.push(svgEl("g", { class: "grid" }, hLines(at, plot.left, plot.right)));
  }
  const vertical = x.ticks
    .filter((tick) => !band || tick.value !== x.min)
    .map((tick) => {
      const at = x.scale(tick.value);
      return svgEl("line", { x1: at, x2: at, y1: plot.top, y2: plot.bottom });
    });
  groups.push(svgEl("g", { class: "grid v" }, vertical));
  return groups;
}

/** The axis lines, the tick labels and the axis labels. */
function drawAxes(layout, texts) {
  const { plot, main, upper, x, y, y2, small, band, categories } = layout;
  const beside = Boolean(y2) && !upper;
  const out = [];
  const tickY = plot.bottom + (small ? 14 : 15);
  if (band) {
    const axis = { class: "axis", x1: plot.left, x2: plot.left, y1: plot.top, y2: plot.bottom };
    out.push(svgEl("line", axis));
    categories.forEach((category, index) => {
      const middle = plot.top + y.step * (index + 0.5);
      const at = category.sub ? middle - 2 : middle + 4;
      out.push(textEl("bar-name", plot.left - 10, at, String(category.y), "end"));
      if (category.sub) {
        out.push(textEl("bar-sub", plot.left - 10, middle + 12, category.sub, "end"));
      }
    });
  } else {
    const across = (at) => ({ class: "axis", x1: plot.left, x2: plot.right, y1: at, y2: at });
    out.push(svgEl("line", across(main.bottom)));
    if (upper) out.push(svgEl("line", across(upper.top)));
    for (const tick of y.ticks) {
      out.push(textEl("tick", plot.left - 6, y.scale(tick.value) + 3, tick.label, "end"));
    }
    if (y2) {
      for (const tick of y2.ticks) {
        const at = y2.scale(tick.value) + 3;
        const tag = beside
          ? textEl("tick", plot.right + 6, at, tick.label, "start")
          : textEl("tick", plot.left - 6, at, tick.label, "end");
        out.push(tag);
      }
    }
  }
  if (x.tickLabels !== false) {
    for (const tick of x.ticks) {
      out.push(textEl("tick", x.scale(tick.value), tickY, tick.label, "middle"));
      if (tick.sub === undefined) continue;
      out.push(textEl("tick sub", x.scale(tick.value), tickY + 13, tick.sub, "middle"));
    }
    if (x.scale.type === "gumbel") {
      out.push(textEl("axis-label", plot.left - 6, tickY, PROBABILITY_LABEL, "end"));
      out.push(textEl("axis-label", plot.left - 6, tickY + 13, texts.returnPeriod, "end"));
      if (x.label) out.push(textEl("axis-label", plot.right, tickY + 31, x.label, "end"));
    } else if (x.label) {
      out.push(textEl("axis-label", plot.right, tickY + (small ? 13 : 17), x.label, "end"));
    }
  }
  const labelY = small ? 8 : 14;
  if (y2 && !beside) {
    if (y2.label) out.push(textEl("axis-label", 4, labelY, y2.label));
    if (y.label) out.push(textEl("axis-label", 4, main.top - 8, y.label));
  } else {
    if (y.label && !band) out.push(textEl("axis-label", 4, labelY, y.label));
    if (beside && y2.label) {
      out.push(textEl("axis-label", layout.width - 4, labelY, y2.label, "end"));
    }
  }
  return out;
}

// --- series and marks -------------------------------------------------------------------------

/** The default colour classes, by the series' order. */
const SERIES_CLASSES = ["s1", "s2", "s3", "s4", "s5", "s6"];

/** A polyline's `d`; a non-finite point starts a new subpath. */
function linePath(xy) {
  let d = "";
  let pen = false;
  for (const [x, y] of xy) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${c1(x)},${c1(y)}`;
    pen = true;
  }
  return d;
}

/** The corners of a step line: each value holds until the next point. */
function stepPoints(xy) {
  const out = [];
  xy.forEach(([x, y], index) => {
    if (index > 0) out.push([x, xy[index - 1][1]]);
    out.push([x, y]);
  });
  return out;
}

/** An area between a line and a baseline: "M…Z" for each finite run. */
function areaPath(xy, base) {
  const runs = [];
  let run = [];
  for (const point of xy) {
    if (Number.isFinite(point[0]) && Number.isFinite(point[1])) run.push(point);
    else if (run.length) {
      runs.push(run);
      run = [];
    }
  }
  if (run.length) runs.push(run);
  const closed = (part) => `${linePath([[part[0][0], base], ...part, [part.at(-1)[0], base]])}Z`;
  return runs.map(closed).join("");
}

/** A band between two lines: "M…Z" for each run where both ends are finite. */
function bandPath(px, hi, lo) {
  const runs = [];
  let run = [];
  px.forEach((x, at) => {
    if (Number.isFinite(x) && Number.isFinite(hi[at]) && Number.isFinite(lo[at])) run.push(at);
    else if (run.length) {
      runs.push(run);
      run = [];
    }
  });
  if (run.length) runs.push(run);
  return runs
    .map((part) => {
      const upper = part.map((at) => [px[at], hi[at]]);
      const lower = [...part].reverse().map((at) => [px[at], lo[at]]);
      return `${linePath([...upper, ...lower])}Z`;
    })
    .join("");
}

/**
 * The value of a series at an x of the viewBox: linear between points, the last one before it
 * (steps), the bar that holds it (bars), the nearest point within `snap` (points); none of a rug.
 */
function valueAt(geometry, at, snap = 6) {
  const { kind, px, values, spans } = geometry;
  if (!px.length || kind === "rug") return null;
  if (kind === "bars") {
    const index = spans.findIndex(([a, b]) => at >= a - 1e-6 && at < b - 1e-6);
    return index < 0 ? null : values[index];
  }
  if (kind === "points") {
    let best = -1;
    for (let i = 0; i < px.length; i += 1) {
      const near = Math.abs(px[i] - at) <= snap;
      if (near && (best < 0 || Math.abs(px[i] - at) < Math.abs(px[best] - at))) best = i;
    }
    return best < 0 ? null : values[best];
  }
  if (at < px[0] - 1e-6 || at > px.at(-1) + 1e-6) return null;
  const hi = px.findIndex((x) => x >= at - 1e-6);
  if (Math.abs(px[hi] - at) <= 1e-6) return values[hi];
  const lo = hi - 1;
  if (kind === "step") return values[lo];
  const share = (at - px[lo]) / (px[hi] - px[lo]);
  return values[lo] + share * (values[hi] - values[lo]);
}

/** The value of a point for `thinPoints` by default: its y. */
const yOf = (point) => point.y;

/**
 * The points of a long line, area, step or band as drawn (the data keep every value): with
 * more than four points per column of the plot, each column keeps its first, last, lowest and
 * highest point and its first gap, so the line and its peaks look the same with a few thousand
 * points instead of a hundred thousand.
 *
 * @param {{x: number, y?: number}[]} data the points in increasing x
 * @param {(x: number) => number} place the x scale (to viewBox units)
 * @param {number} columns the plot's width in viewBox units
 * @param {{low?: (point: object) => number, high?: (point: object) => number}} [values] the low
 *   and the high value of a point (both its `y` by default; a band's `lo` and `hi`)
 * @returns {object[]} the points kept, in their order
 */
export function thinPoints(data, place, columns, values = {}) {
  if (data.length <= 4 * columns) return data;
  const lowOf = values.low ?? yOf;
  const highOf = values.high ?? yOf;
  const start = place(data[0].x);
  const width = place(data.at(-1).x) - start || 1;
  const out = [];
  let column = -1;
  let first = -1;
  let last = -1;
  let low = -1;
  let high = -1;
  let gap = -1;
  let lowest = 0;
  let highest = 0;
  const kept = [0, 0, 0, 0, 0];
  const flush = () => {
    let count = 0;
    for (const index of [first, low, high, gap, last]) if (index >= 0) kept[count++] = index;
    const row = kept.slice(0, count).sort((a, b) => a - b);
    for (let at = 0; at < count; at += 1) {
      if (at === 0 || row[at] !== row[at - 1]) out.push(data[row[at]]);
    }
  };
  for (let index = 0; index < data.length; index += 1) {
    const point = data[index];
    const at = Math.min(columns - 1, Math.floor(((place(point.x) - start) / width) * columns));
    if (at !== column) {
      if (column >= 0) flush();
      column = at;
      first = index;
      low = -1;
      high = -1;
      gap = -1;
    }
    last = index;
    const lo = lowOf(point);
    const hi = highOf(point);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
      if (gap < 0) gap = index;
      continue;
    }
    if (low < 0 || lo < lowest) {
      low = index;
      lowest = lo;
    }
    if (high < 0 || hi > highest) {
      high = index;
      highest = hi;
    }
  }
  flush();
  return out;
}

/**
 * A series' points sorted by x and cut to the plot's width: those within it and the nearest one
 * beyond each edge, so a line leaves the frame towards its next point.
 */
function visiblePoints(data, place, plot) {
  let ordered = data;
  let previous = -Infinity;
  for (const point of data) {
    const at = place(point.x);
    if (!Number.isFinite(at) || at < previous) {
      // Unordered or with points off the scale: placed once, sorted
      ordered = data
        .map((item) => ({ item, at: place(item.x) }))
        .filter((entry) => Number.isFinite(entry.at))
        .sort((a, b) => a.at - b.at)
        .map((entry) => entry.item);
      break;
    }
    previous = at;
  }
  let first = 0;
  while (first < ordered.length && place(ordered[first].x) < plot.left - 1e-6) first += 1;
  let last = ordered.length - 1;
  while (last >= 0 && place(ordered[last].x) > plot.right + 1e-6) last -= 1;
  const from = Math.max(0, first - 1);
  const to = Math.min(ordered.length - 1, last + 1);
  return from === 0 && to === ordered.length - 1 ? ordered : ordered.slice(from, to + 1);
}

/** The geometry of each series: its viewBox points, values and class. */
function seriesGeometry(spec, layout) {
  let row = 0;
  return (spec.series ?? []).map((series, index) => {
    const kind = layout.band ? "hbars" : (series.kind ?? "line");
    const cls = series.cls ?? SERIES_CLASSES[index % SERIES_CLASSES.length];
    const data = points(series);
    if (kind === "hbars") {
      row += data.length;
      const empty = { px: [], py: [], values: [], xs: [] };
      return { series, kind, cls, axis: "y", data, row: row - data.length, ...empty };
    }
    const onY2 = series.axis === "y2" && layout.y2;
    const axis = onY2 ? layout.y2 : layout.y;
    const sorted = visiblePoints(data, layout.x.scale, layout.plot);
    const columns = Math.ceil(layout.plot.right - layout.plot.left);
    let order = sorted;
    const lined = kind === "line" || kind === "area" || kind === "step";
    if (lined) order = thinPoints(sorted, layout.x.scale, columns);
    else if (kind === "band") {
      const ends = { low: (point) => point.lo, high: (point) => point.hi };
      order = thinPoints(sorted, layout.x.scale, columns, ends);
    }
    const px = order.map((point) => layout.x.scale(point.x));
    const place = (value) => (Number.isFinite(value) ? axis.scale(value) : NaN);
    const xs = order.map((point) => point.x);
    const common = { series, kind, cls, axis: onY2 ? "y2" : "y", data: order, xs, px };
    if (kind === "band") {
      return {
        ...common,
        py: order.map((point) => place(point.hi)),
        py2: order.map((point) => place(point.lo)),
        values: order.map((point) => point.hi),
        lows: order.map((point) => point.lo),
      };
    }
    let spans;
    if (kind === "bars") {
      const width = barWidth(series, order);
      const shift = series.align === "center" ? width / 2 : 0;
      const xAt = layout.x.scale;
      spans = order.map((point) => [xAt(point.x - shift), xAt(point.x - shift + width)]);
    }
    const values = order.map((point) => point.y);
    return { ...common, py: values.map((value) => place(value)), values, spans };
  });
}

function drawBars(geometry, layout) {
  const axis = geometry.axis === "y2" ? layout.y2 : layout.y;
  const zero = axis.scale(Math.max(axis.min, Math.min(axis.max, 0)));
  const rects = [];
  geometry.spans.forEach(([a, b], index) => {
    const value = geometry.values[index];
    if (!Number.isFinite(value) || value === 0) return;
    const at = axis.scale(value);
    const gap = b - a > 3 ? 0.5 : 0;
    rects.push(
      svgEl("rect", {
        x: a + gap,
        y: Math.min(at, zero),
        width: Math.max(0.5, b - a - 2 * gap),
        height: Math.abs(at - zero),
        class: geometry.data[index].cls,
      }),
    );
  });
  return svgEl("g", { class: `bars ${geometry.cls}`, "data-series": geometry.series.id }, rects);
}

function drawHorizontalBars(geometry, layout) {
  const { plot, x, y } = layout;
  const zero = x.scale(0);
  const group = svgEl("g", { class: `hbars ${geometry.cls}`, "data-series": geometry.series.id });
  geometry.data.forEach((point, index) => {
    const middle = plot.top + y.step * (geometry.row + index + 0.5);
    const end = x.scale(point.x);
    group.append(
      svgEl("rect", {
        class: ["hbar", point.cls].filter(Boolean).join(" "),
        x: Math.min(zero, end),
        y: middle - y.bar / 2,
        width: Math.max(0.5, Math.abs(end - zero)),
        height: y.bar,
        rx: 3,
      }),
    );
    if (!point.text) return;
    group.append(textEl("bar-val", Math.max(zero, end) + 8, middle + 4, point.text));
  });
  return group;
}

/** The points of a series: dots, hollow dots or diamonds, by the point's shape or the series'. */
function drawPoints(geometry, layout) {
  const { series } = geometry;
  const radius = layout.small ? 3 : 3.6;
  const marks = [];
  geometry.data.forEach((point, at) => {
    const x = geometry.px[at];
    const y = geometry.py[at];
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const shape = point.shape ?? series.shape ?? "dot";
    const cls = [shape === "dot" ? null : shape, point.cls].filter(Boolean).join(" ") || undefined;
    if (shape === "diamond") {
      const r = radius * 1.4;
      const d = `${linePath([[x, y - r], [x + r, y], [x, y + r], [x - r, y]])}Z`;
      marks.push(svgEl("path", { class: cls, d }));
    } else marks.push(svgEl("circle", { class: cls, cx: x, cy: y, r: radius }));
  });
  // Points take a colour only from their own `cls` (plain dots otherwise: empirical points)
  return svgEl("g", { class: `emp ${series.cls ?? ""}`.trim(), "data-series": series.id }, marks);
}

/** The series: areas and bands first, then bars, lines and points on top. */
function drawSeries(geometries, layout) {
  const rank = { area: 0, band: 0, bars: 1, hbars: 1, step: 2, line: 2, points: 3, rug: 3 };
  const ordered = [...geometries].sort((a, b) => (rank[a.kind] ?? 2) - (rank[b.kind] ?? 2));
  const out = [];
  for (const geometry of ordered) {
    const { kind, cls, series } = geometry;
    const xy = geometry.px.map((x, i) => [x, geometry.py[i]]);
    if (kind === "bars") out.push(drawBars(geometry, layout));
    else if (kind === "band") {
      const d = bandPath(geometry.px, geometry.py, geometry.py2);
      out.push(svgEl("path", { class: `band ${cls}`, d, "data-series": series.id }));
    } else if (kind === "hbars") out.push(drawHorizontalBars(geometry, layout));
    else if (kind === "points") out.push(drawPoints(geometry, layout));
    else if (kind === "rug") {
      const { bottom } = geometry.axis === "y2" && layout.upper ? layout.upper : layout.main;
      const length = layout.small ? 6 : 8;
      const ticks = geometry.px
        .filter((x) => Number.isFinite(x))
        .map((x) => svgEl("line", { x1: x, x2: x, y1: bottom, y2: bottom - length }));
      out.push(svgEl("g", { class: `rug ${cls}`, "data-series": series.id }, ticks));
    } else {
      const path = kind === "step" ? stepPoints(xy) : xy;
      if (kind === "area") {
        const axis = geometry.axis === "y2" ? layout.y2 : layout.y;
        const base = axis.scale(Math.max(axis.min, Math.min(axis.max, 0)));
        const d = areaPath(path, base);
        out.push(svgEl("path", { class: `q-area ${cls}`, d, "data-series": series.id }));
      }
      out.push(svgEl("path", { class: `ser ${cls}`, d: linePath(path), "data-series": series.id }));
    }
  }
  return out;
}

/** The spans: grey bands over ranges of x (gaps), under the series. */
function drawSpans(marks, layout) {
  const out = [];
  for (const mark of marks ?? []) {
    if (mark.kind !== "span") continue;
    const a = layout.x.scale(mark.from);
    const b = layout.x.scale(mark.to);
    if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
    const panel = mark.axis === "y2" && layout.upper ? layout.upper : layout.main;
    out.push(
      svgEl("rect", {
        class: `span ${mark.cls ?? ""}`.trim(),
        "data-mark": mark.id,
        x: Math.min(a, b),
        y: panel.top,
        width: Math.max(0.5, Math.abs(b - a)),
        height: panel.bottom - panel.top,
      }),
    );
  }
  return out;
}

/** An estimate of a text's width in viewBox units, corrected after drawing (`fitBoxes`). */
function textWidth(text, size = 12) {
  return String(text).length * size * 0.56;
}

/**
 * The baselines of the labels of reference lines, kept apart: from the top down each label sits
 * just above its line, else just below it, else `gap` under the label before.
 */
function spreadLabels(lines, gap = 12) {
  const order = lines.map((py, at) => ({ py, at })).sort((a, b) => a.py - b.py);
  const out = new Array(lines.length);
  let previous = -Infinity;
  for (const { py, at } of order) {
    const above = py - 4;
    const below = py + gap - 1;
    let place = above;
    if (above - previous < gap) place = below - previous >= gap ? below : previous + gap;
    out[at] = place;
    previous = place;
  }
  return out;
}

/** The marks: peaks, reference lines, moments and notes (spans are drawn under the series). */
function drawMarks(marks, layout) {
  const { plot, main, upper, x } = layout;
  const out = [];
  // The labels of the reference lines of each axis, spread apart
  const tags = new Map();
  const axisOf = (mark) => (mark.axis === "y2" && layout.y2 ? "y2" : "y");
  for (const panelAxis of ["y", "y2"]) {
    const labelled = (marks ?? []).filter(
      (mark) => mark.kind === "hline" && mark.label && axisOf(mark) === panelAxis,
    );
    const axis = panelAxis === "y2" ? layout.y2 : layout.y;
    const places = spreadLabels(labelled.map((mark) => axis.scale(mark.y)), layout.small ? 11 : 13);
    labelled.forEach((mark, at) => tags.set(mark, places[at]));
  }
  for (const mark of marks ?? []) {
    const axis = mark.axis === "y2" && layout.y2 ? layout.y2 : layout.y;
    const panel = mark.axis === "y2" && upper ? upper : main;
    const cls = mark.cls ?? "s1";
    if (mark.kind === "peak") {
      const px = x.scale(mark.x);
      const py = axis.scale(mark.y);
      const group = svgEl("g", { class: "mark peak", "data-mark": mark.id });
      group.append(svgEl("line", { class: "peak-line", x1: px, x2: px, y1: py, y2: panel.bottom }));
      if (mark.guides === "xy") {
        group.append(svgEl("line", { class: "peak-line", x1: plot.left, x2: px, y1: py, y2: py }));
      }
      const r = layout.small ? 3.5 : 4.5;
      group.append(svgEl("circle", { class: `peak-dot ${cls}`, cx: px, cy: py, r }));
      if (mark.label) {
        if (layout.small) {
          const right = px > plot.left + (plot.right - plot.left) * 0.66;
          const at = right ? px - 7 : px + 7;
          group.append(textEl("peak-tag", at, py - 5, mark.label, right ? "end" : undefined));
        } else {
          const width = textWidth(mark.label) + 16;
          const left = px + 12 + width > plot.right ? px - 12 - width : px + 12;
          group.append(
            svgEl("rect", { class: "peak-box", x: left, y: py - 15, width, height: 22, rx: 4 }),
            textEl("peak-label", left + 8, py, mark.label),
          );
        }
      }
      out.push(group);
    } else if (mark.kind === "hline") {
      const py = axis.scale(mark.y);
      const classes = `mark hline ${mark.cls ?? ""}`.trim();
      const group = svgEl("g", { class: classes, "data-mark": mark.id });
      const line = { class: "peak-line ref", x1: plot.left, x2: plot.right, y1: py, y2: py };
      group.append(svgEl("line", line));
      const tagY = tags.get(mark) ?? py - 4;
      if (mark.label) group.append(textEl("peak-tag", plot.right - 2, tagY, mark.label, "end"));
      out.push(group);
    } else if (mark.kind === "vline") {
      const px = x.scale(mark.x);
      const from = Number.isFinite(mark.from) ? axis.scale(mark.from) : panel.top;
      const to = Number.isFinite(mark.to) ? axis.scale(mark.to) : panel.bottom;
      const group = svgEl("g", { class: "mark vline", "data-mark": mark.id });
      const end = to + (mark.extend ?? 0);
      group.append(svgEl("line", { class: "mark-line", x1: px, x2: px, y1: from, y2: end }));
      if (mark.label) group.append(textEl("note", px + 5, end - 2, mark.label));
      out.push(group);
    } else if (mark.kind === "note") {
      const px = x.scale(mark.x);
      const py = axis.scale(mark.y);
      const at = [px + (mark.dx ?? 0), py + (mark.dy ?? 0)];
      out.push(textEl(mark.cls ?? "note", at[0], at[1], mark.label, mark.anchor));
    }
  }
  return out;
}

/** The boxes of the peak labels fitted to their measured texts (an attached SVG only). */
function fitBoxes(svg, plot) {
  if (!svg.isConnected) return;
  for (const group of svg.querySelectorAll("g.mark.peak")) {
    const box = group.querySelector(".peak-box");
    const text = group.querySelector(".peak-label");
    const dot = group.querySelector(".peak-dot");
    if (!box || !text || !dot) continue;
    let width;
    try {
      width = text.getComputedTextLength() + 16;
    } catch {
      continue;
    }
    if (!(width > 16)) continue;
    const px = Number(dot.getAttribute("cx"));
    const left = px + 12 + width > plot.right ? px - 12 - width : px + 12;
    box.setAttribute("x", String(c1(left)));
    box.setAttribute("width", String(c1(width)));
    text.setAttribute("x", String(c1(left + 8)));
  }
}

// --- readout and legend -----------------------------------------------------------------------

/** A readout value: the axis's `digits`, else by magnitude. */
function readoutNumber(value, digits, format) {
  if (digits !== undefined) return format.number(value, digits);
  const size = Math.abs(value);
  return format.number(value, size >= 1000 ? 0 : size >= 100 ? 1 : size >= 1 || size === 0 ? 2 : 3);
}

/** An x value as the readout and the range bar write it. */
function xText(spec, type, x, format) {
  if (spec.x?.scale === "time") return format.time(x);
  if (spec.x?.scale === "date") return format.day(x);
  if (spec.x?.scale === "datetime") return format.dateTime(x);
  if (type === "gumbel") return readoutNumber(x, x >= 1 ? 1 : 2, format);
  return readoutNumber(x, spec.x?.digits, format);
}

function headingText(layout, x, spec, format, texts) {
  const custom = spec.readout?.x;
  if (typeof custom === "function") return custom(x);
  const type = layout.x.scale.type;
  if (spec.x?.scale === "time") return `t = ${format.time(x)}`;
  if (spec.x?.scale === "date") return format.day(x);
  if (spec.x?.scale === "datetime") return format.dateTime(x);
  if (type === "gumbel") {
    const years = 100 / x;
    return fill(texts.probabilityReadout, {
      p: readoutNumber(x, x >= 1 ? 1 : 2, format),
      years: readoutNumber(years, years >= 10 ? 0 : 1, format),
    });
  }
  return `${spec.x?.short ?? "x"} = ${xText(spec, type, x, format)}`;
}

/** The lines of the readout at an index of the readout series' points. */
function readoutAt(spec, layout, geometries, master, index, format, texts) {
  const middleOf = (span) => (span[0] + span[1]) / 2;
  const at = master.kind === "bars" ? middleOf(master.spans[index]) : master.px[index];
  const where = master.kind === "bars" ? master.spans[index][0] : at;
  const rows = [];
  for (const geometry of geometries) {
    if (geometry.series.readout === false) continue;
    const axisSpec = geometry.axis === "y2" ? layout.y2 : layout.y;
    const custom = spec.readout?.value;
    const text = (value) =>
      typeof custom === "function"
        ? custom(value, geometry.series)
        : readoutNumber(value, geometry.series.digits ?? axisSpec.digits, format);
    const unit = geometry.series.unit ?? axisSpec.unit;
    const label = geometry.series.label ?? geometry.series.id;
    const suffix = unit ? `\u00a0${unit}` : "";
    if (geometry.kind === "band") {
      // A band reads as its two ends: "min–maks: 12–40 cm"
      const own = geometry === master;
      const high = own ? geometry.values[index] : valueAt(geometry, where);
      const lows = { ...geometry, values: geometry.lows };
      const low = own ? geometry.lows[index] : valueAt(lows, where);
      if (!Number.isFinite(low) || !Number.isFinite(high)) continue;
      const line = `${label}: ${text(low)}–${text(high)}${suffix}`;
      rows.push({ id: geometry.series.id, cls: geometry.cls, kind: "band", text: line, py: null });
      continue;
    }
    const value = geometry === master ? master.values[index] : valueAt(geometry, where);
    if (value === null || !Number.isFinite(value)) continue;
    rows.push({
      id: geometry.series.id,
      cls: geometry.cls,
      kind: geometry.kind,
      text: `${label}: ${text(value)}${suffix}`,
      py: geometry.kind === "bars" ? null : axisSpec.scale(value),
    });
  }
  return { heading: headingText(layout, master.xs[index], spec, format, texts), at, rows };
}

/** The series the readout steps over: `readout.series`, else the first line, else a band. */
function readoutSeries(spec, band) {
  if (!spec.readout || band) return null;
  const readable = (series) => series.kind !== "rug" && points(series).length > 0;
  const usable = (spec.series ?? []).filter(readable);
  const wanted = spec.readout?.series;
  if (wanted) return usable.find((series) => series.id === wanted) ?? null;
  const kind = (series) => series.kind ?? "line";
  return (
    usable.find((series) => kind(series) !== "bars" && kind(series) !== "band") ??
    usable.find((series) => kind(series) === "band") ??
    usable[0] ??
    null
  );
}

function legendItems(spec, geometries) {
  if (Array.isArray(spec.legend)) return spec.legend;
  return geometries
    .filter((geometry) => geometry.series.label && geometry.series.legend !== false)
    .map((geometry) => ({
      label: geometry.series.label,
      kind: geometry.kind,
      cls: geometry.kind === "points" ? geometry.series.cls : geometry.cls,
      shape: geometry.series.shape,
    }));
}

function swatch(item) {
  const classes = (...names) => names.filter(Boolean).join(" ");
  const box = (cls) => htmlEl("i", { class: cls });
  if (["bars", "hbars", "box"].includes(item.kind)) return box(classes("sw", item.cls));
  if (item.kind === "band") return htmlEl("i", { class: classes("sw band", item.cls ?? "s1") });
  if (item.kind === "span") return htmlEl("i", { class: classes("sw span", item.cls) });
  if (item.kind === "points") {
    const shape = item.shape && item.shape !== "dot" ? item.shape : null;
    return htmlEl("i", { class: classes("sw-dot", item.cls, shape) });
  }
  if (item.kind === "rug") return htmlEl("i", { class: "sw-rug" });
  if (item.kind === "stroke") {
    const line = svgEl("line", { x1: 1, y1: 3, x2: 23, y2: 3 });
    const attrs = { class: classes("sw-stroke", item.cls), viewBox: "0 0 24 6" };
    return svgEl("svg", { ...attrs, "aria-hidden": "true" }, [line]);
  }
  return htmlEl("i", { class: classes("sw-line", item.cls ?? "s1") });
}

function drawLegend(spec, geometries) {
  const legend = htmlEl("div", { class: "nogat-chart-legend" });
  for (const item of legendItems(spec, geometries)) {
    if (item.kind === "text") legend.append(htmlEl("span", { class: "muted" }, [item.label]));
    else if (item.kind === "break") {
      legend.append(htmlEl("span", { class: "legend-break", "aria-hidden": "true" }));
    } else legend.append(htmlEl("span", {}, [swatch(item), item.label]));
  }
  return legend;
}

/** The ids of the frames' clip paths: one per chart, unique on the page. */
let clips = 0;

/** The series cut at the frame (an axis from 0, a fixed end, a zoomed range). */
function framed(id, plot, nodes) {
  const rect = svgEl("rect", {
    x: plot.left - SPILL,
    y: plot.top - SPILL,
    width: plot.right - plot.left + 2 * SPILL,
    height: plot.bottom - plot.top + 2 * SPILL,
  });
  const clip = svgEl("defs", {}, [svgEl("clipPath", { id }, [rect])]);
  return [clip, svgEl("g", { class: "framed", "clip-path": `url(#${id})` }, nodes)];
}

/** The first and the last index of the readout series' points within the frame, or null. */
function withinFrame(master, plot) {
  let first = -1;
  let last = -1;
  master.px.forEach((x, at) => {
    const middle = master.kind === "bars" ? (master.spans[at][0] + master.spans[at][1]) / 2 : x;
    if (middle < plot.left - 0.5 || middle > plot.right + 0.5) return;
    if (first < 0) first = at;
    last = at;
  });
  return first < 0 ? null : { first, last };
}

// --- zoom -------------------------------------------------------------------------------------

/** How a chart zooms: "x", "xy", or null (a gumbel x, a band y, `zoom: false`). */
function zoomMode(spec) {
  const kind = spec.x?.scale ?? "linear";
  if (spec.zoom === false || spec.y?.scale === "band" || !ZOOM_SCALES.has(kind)) return null;
  return spec.zoom === "xy" ? "xy" : "x";
}

/** Whether two specs draw the same data on the same axes: a range outlives such a redraw. */
function sameData(a, b) {
  const keys = ["scale", "min", "max"];
  if (keys.some((key) => a.x?.[key] !== b.x?.[key])) return false;
  const xy = a.zoom === "xy" || b.zoom === "xy";
  if (xy && keys.some((key) => a.y?.[key] !== b.y?.[key])) return false;
  const left = a.series ?? [];
  const right = b.series ?? [];
  return left.length === right.length && left.every((series, at) => series.data === right[at].data);
}

/** Two ranges ({min, max, y?} or null) alike. */
function sameRange(a, b) {
  if (!a || !b) return !a && !b;
  return a.min === b.min && a.max === b.max && sameRange(a.y ?? null, b.y ?? null);
}

const LINEAR_SPACE = { to: (value) => value, from: (t) => t };
const LOG_SPACE = { to: (value) => Math.log10(value), from: (t) => 10 ** t };

/** The coordinates in which an axis zooms: its values, or their logarithms on a log axis. */
function spaceOf(type) {
  return type === "log" ? LOG_SPACE : LINEAR_SPACE;
}

function toSpace(space, range) {
  return [space.to(range.min), space.to(range.max)];
}

/** A range of `size` with `at` at `share` of it, moved within `all` (zoom coordinates). */
function placed(at, share, size, all) {
  let a = at - share * size;
  let b = a + size;
  if (a < all[0]) {
    a = all[0];
    b = a + size;
  }
  if (b > all[1]) {
    b = all[1];
    a = Math.max(all[0], b - size);
  }
  return [a, b];
}

/** The x values of a series' points with a value, sorted: built once per data array. */
const SORTED = new WeakMap();

function sortedXs(series) {
  const data = series.data ?? [];
  let xs = SORTED.get(data);
  if (!xs) {
    const band = series.kind === "band";
    const valued = points(series).filter((point) => {
      if (!Number.isFinite(point.x)) return false;
      if (band) return Number.isFinite(point.lo) && Number.isFinite(point.hi);
      return Number.isFinite(point.y);
    });
    xs = Float64Array.from(valued, (point) => point.x).sort();
    SORTED.set(data, xs);
  }
  return xs;
}

/** The first index of sorted values above `value` (`after`) or not below it. */
function bound(xs, value, after) {
  let lo = 0;
  let hi = xs.length;
  while (lo < hi) {
    const middle = (lo + hi) >> 1;
    if (after ? xs[middle] <= value : xs[middle] < value) lo = middle + 1;
    else hi = middle;
  }
  return lo;
}

/**
 * How many sorted values lie within [lo, hi], each a hair inside its ends: a range found to
 * hold four points holds them still once it is written back from zoom coordinates.
 */
function countWithin(xs, lo, hi) {
  const hair = 1e-9 * Math.max(1, Math.abs(lo), Math.abs(hi));
  return Math.max(0, bound(xs, hi - hair, true) - bound(xs, lo + hair, false));
}

function barButton(cls, text) {
  return htmlEl("button", { type: "button", class: `btn sm ${cls}` }, [text]);
}

// --- the chart --------------------------------------------------------------------------------

/**
 * Draw a chart into a container (see the spec at the top of this file).
 *
 * @param {HTMLElement} container it gets the class `nogat-chart`, with `nogat-chart-wide`,
 *   `-fit`, `-zoomable` and `-zoomed` as they hold
 * @param {object} spec the chart spec
 * @returns {{
 *   svg: SVGSVGElement, update: (spec: object) => void, destroy: () => void,
 *   plotWidth: () => number,
 *   readout: {show: (index: number) => void, hide: () => void, index: () => number | null},
 *   zoom: {set: (min: number, max: number, y?: {min: number, max: number}) => void,
 *     reset: () => void, range: () => {min: number, max: number, y?: object} | null}
 * }} `readout` takes and gives an index of its series' data; `zoom.set` and `zoom.reset` take
 *   a range back without calling `onRange`
 */
export function drawChart(container, spec) {
  container.classList.add("nogat-chart");
  const svg = svgEl("svg", { class: "nogat-chart-svg", role: "img", focusable: "false" });
  const zoomOut = barButton("nogat-chart-zoom-out", MINUS);
  const zoomIn = barButton("nogat-chart-zoom-in", "+");
  const zoomReset = barButton("nogat-chart-zoom-reset", "");
  const zoomText = htmlEl("span", { class: "nogat-chart-zoom-range" });
  const parts = [zoomOut, zoomIn, zoomReset, zoomText];
  const bar = htmlEl("div", { class: "nogat-chart-zoom", hidden: "" }, parts);
  const legendSlot = htmlEl("div", { class: "nogat-chart-legend-slot" });
  const live = htmlEl("div", { class: "nogat-chart-sr", "aria-live": "polite" });
  container.append(svg, bar, legendSlot, live);
  clips += 1;
  const clipId = `nogat-chart-frame-${clips}`;
  const selection = svgEl("rect", { class: "zoom-selection", visibility: "hidden" });
  const phone = typeof window.matchMedia === "function" ? window.matchMedia(PHONE) : null;

  let current = spec;
  let texts = CHART_TEXTS;
  let format = chartFormat();
  let mode = null;
  let layout;
  let geometries;
  // The readout: its series, its geometry, the indexes within the frame, the index shown
  let wanted = null;
  let master = null;
  let shown = null;
  let index = null;
  let layer = null;
  let readText = "";
  // The x the readout read last, around which + and − zoom after it hid
  let anchor = null;
  // The container's width a fitted chart is drawn at [CSS px]
  let width = 0;
  // The ranges shown (null: the whole) and the wholes, of x and of a "xy" chart's y
  let view = null;
  let viewY = null;
  let whole = null;
  let wholeY = null;
  // A mouse drag (a selection or a pan), the touch points and a pinch of two of them
  let drag = null;
  const touches = new Map();
  let pinch = null;
  let frame = 0;
  let idle = 0;
  // The range onRange told or a GUI set last, and the index onReadout told last
  let reported = null;
  let told = null;

  /** The fit a chart is drawn with: its own, or a zoomable chart's on a phone. */
  function fitOf(next) {
    if (next.fit) return next.fit;
    if (!phone?.matches || !zoomMode(next)) return null;
    const size = sizeOf(next);
    return { ratio: size.height / size.width };
  }

  /** The spec as drawn: at the container's width when fitted, over the range shown. */
  function drawn(next) {
    let out = next;
    const fit = fitOf(next);
    if (fit && width) {
      const height = Math.max(fit.minHeight ?? 0, Math.round(width * fit.ratio));
      out = { ...out, size: { width, height } };
    }
    if (view) out = { ...out, x: { ...out.x, min: view.min, max: view.max } };
    if (mode === "xy" && (view || viewY)) {
      const y = viewY ?? wholeY;
      out = { ...out, y: { ...out.y, min: y.min, max: y.max } };
    }
    return out;
  }

  function tell(at) {
    if (at === told) return;
    told = at;
    current.onReadout?.(at);
  }

  function hide() {
    layer?.replaceChildren();
    layer?.setAttribute("visibility", "hidden");
    index = null;
    readText = "";
    live.textContent = "";
    tell(null);
  }

  function show(next) {
    if (!master || !layer) return;
    index = Math.max(shown.first, Math.min(shown.last, next));
    anchor = master.xs[index];
    const reading = readoutAt(current, layout, geometries, master, index, format, texts);
    const { plot } = layout;
    const top = layout.upper ? layout.upper.top : layout.main.top;
    layer.replaceChildren();
    layer.removeAttribute("visibility");
    const { at } = reading;
    const line = { class: "readout-line", x1: at, x2: at, y1: top, y2: plot.bottom };
    layer.append(svgEl("line", line));
    for (const row of reading.rows) {
      if (row.py === null || !Number.isFinite(row.py)) continue;
      const dot = { class: `readout-dot ${row.cls}`, cx: at, cy: row.py, r: 3.5 };
      layer.append(svgEl("circle", dot));
    }
    const lines = [reading.heading, ...reading.rows.map((row) => row.text)];
    const size = layout.small ? 10 : 11;
    const lineHeight = size + 4;
    const boxWidth = Math.max(...lines.map((line) => line.length)) * size * 0.56 + 16;
    const boxHeight = lines.length * lineHeight + 8;
    // Right of the cursor when it fits, else left of it, never past the chart's left edge
    const right = reading.at + 10 + boxWidth <= plot.right;
    const left = right ? reading.at + 10 : Math.max(0, reading.at - 10 - boxWidth);
    const boxTop = top + 4;
    const boxAttrs = { class: "readout-box", x: left, y: boxTop, rx: 4 };
    layer.append(svgEl("rect", { ...boxAttrs, width: boxWidth, height: boxHeight }));
    lines.forEach((line, row) => {
      const cls = row === 0 ? "readout-head" : "readout-text";
      layer.append(textEl(cls, left + 8, boxTop + 4 + lineHeight * (row + 1) - 4, line));
    });
    if (svg.isConnected) {
      const measured = [...layer.querySelectorAll("text")];
      try {
        const fitted = Math.max(...measured.map((text) => text.getComputedTextLength())) + 16;
        if (fitted > 16) {
          const box = layer.querySelector(".readout-box");
          const fitLeft = right ? reading.at + 10 : Math.max(0, reading.at - 10 - fitted);
          box.setAttribute("width", String(c1(fitted)));
          box.setAttribute("x", String(c1(fitLeft)));
          for (const text of measured) text.setAttribute("x", String(c1(fitLeft + 8)));
        }
      } catch {
        // an SVG without layout (display: none) keeps the estimate
      }
    }
    readText = lines.join(" · ");
    live.textContent = readText;
    tell(master.data[index][AT]);
  }

  /** The marks within the range shown (a zoomed chart leaves out those beyond it). */
  function marksShown() {
    const marks = current.marks ?? [];
    if (!view && !viewY) return marks;
    const { left, right, top, bottom } = layout.plot;
    return marks.filter((mark) => {
      if (view && mark.kind !== "hline" && Number.isFinite(mark.x)) {
        const at = layout.x.scale(mark.x);
        if (!(at >= left - 0.5 && at <= right + 0.5)) return false;
      }
      if (viewY && mark.kind !== "vline" && Number.isFinite(mark.y) && mark.axis !== "y2") {
        const at = layout.y.scale(mark.y);
        if (!(at >= top - 0.5 && at <= bottom + 0.5)) return false;
      }
      return true;
    });
  }

  /** The range shown, as the bar writes it. */
  function rangeText() {
    const x = view ?? whole;
    const type = layout.x.scale.type;
    const xFrom = xText(current, type, x.min, format);
    const xTo = xText(current, type, x.max, format);
    if (mode !== "xy") return fill(texts.range, { from: xFrom, to: xTo });
    const y = viewY ?? wholeY;
    const digits = current.y?.digits;
    return fill(texts.rangeXY, {
      x: current.x?.short ?? "x",
      xFrom,
      xTo,
      y: current.y?.short ?? "y",
      yFrom: readoutNumber(y.min, digits, format),
      yTo: readoutNumber(y.max, digits, format),
    });
  }

  /** The bar: the lone „+” of a chart not zoomed; „−”, „+”, „Cały zakres” and the range. */
  function drawBar(zoomed) {
    bar.hidden = !mode;
    for (const [button, name] of [[zoomIn, texts.zoomIn], [zoomOut, texts.zoomOut]]) {
      button.setAttribute("aria-label", name);
      button.title = name;
    }
    zoomReset.textContent = texts.reset;
    zoomOut.hidden = !zoomed;
    zoomReset.hidden = !zoomed;
    zoomText.hidden = !zoomed;
    zoomText.textContent = zoomed ? rangeText() : "";
    zoomText.title = zoomText.textContent;
  }

  function render(next) {
    const kept = master && index !== null ? master.xs[index] : null;
    current = next;
    texts = { ...CHART_TEXTS, ...next.texts };
    format = chartFormat({ locale: next.locale, dateFormat: next.dateFormat });
    mode = zoomMode(next);
    if (!mode) view = null;
    if (mode !== "xy") viewY = null;
    if (fitOf(next) && !width) width = Math.floor(container.clientWidth);
    layout = chartLayout(drawn(next), format);
    if (!view) whole = { min: layout.x.min, max: layout.x.max };
    if (mode === "xy" && !view && !viewY) wholeY = { min: layout.y.min, max: layout.y.max };
    geometries = seriesGeometry(next, layout);
    wanted = readoutSeries(next, layout.band);
    const readable = (geometry) => geometry.series === wanted && geometry.px.length > 0;
    master = (wanted && geometries.find(readable)) || null;
    shown = master ? withinFrame(master, layout.plot) : null;
    if (!shown) master = null;
    const zoomed = Boolean(view || viewY);
    container.classList.toggle("nogat-chart-wide", !layout.small);
    container.classList.toggle("nogat-chart-fit", Boolean(fitOf(next)));
    container.classList.toggle("nogat-chart-zoomable", Boolean(mode));
    container.classList.toggle("nogat-chart-zoomed", zoomed);
    svg.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
    if (next.title) svg.setAttribute("aria-label", next.title);
    else svg.removeAttribute("aria-label");
    if (next.labelledBy) svg.setAttribute("aria-labelledby", next.labelledBy);
    else svg.removeAttribute("aria-labelledby");
    if (master || mode) {
      svg.setAttribute("tabindex", "0");
      const hint = [master ? texts.keysReadout : "", mode ? texts.keysZoom : ""];
      svg.setAttribute("aria-description", hint.filter(Boolean).join(" "));
    } else {
      svg.removeAttribute("tabindex");
      svg.removeAttribute("aria-description");
    }
    layer = master ? svgEl("g", { class: "readout", visibility: "hidden" }) : null;
    index = null;
    const series = drawSeries(geometries, layout);
    const framedSeries = layout.band
      ? series
      : framed(clipId, layout.plot, [...drawSpans(next.marks, layout), ...series]);
    svg.replaceChildren(
      ...drawGrid(layout),
      ...framedSeries,
      ...drawMarks(marksShown(), layout),
      ...drawAxes(layout, texts),
      ...(mode ? [selection] : []),
      ...(layer ? [layer] : []),
    );
    fitBoxes(svg, layout.plot);
    drawBar(zoomed);
    legendSlot.replaceChildren(...(next.legend ? [drawLegend(next, geometries)] : []));
    if (kept !== null && master && document.activeElement === svg) show(indexOfX(kept));
    else if (kept !== null) {
      readText = "";
      live.textContent = "";
      tell(null);
    }
  }

  /** Draw now, or once at the next animation frame for a burst of wheel, pinch or pan events. */
  function redraw(now) {
    if (now) {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      render(current);
    } else if (!frame) {
      frame = requestAnimationFrame(() => {
        frame = 0;
        render(current);
      });
    }
  }

  /** The index of the readout series' point within the frame nearest to an x value. */
  function indexOfX(value) {
    let best = shown.first;
    for (let at = shown.first; at <= shown.last; at += 1) {
      if (Math.abs(master.xs[at] - value) < Math.abs(master.xs[best] - value)) best = at;
    }
    return best;
  }

  function svgPoint(clientX, clientY) {
    const matrix = svg.getScreenCTM();
    if (!matrix) return null;
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    return { x: point.x, y: point.y };
  }

  function inPlot(at) {
    const { left, right, top, bottom } = layout.plot;
    return at.x >= left && at.x <= right && at.y >= top && at.y <= bottom;
  }

  /** The readout at a point of the viewBox: the nearest point by x, hidden off the plot. */
  function readAt(at) {
    if (!master) return;
    if (at.x < layout.plot.left - 8 || at.x > layout.plot.right + 8) {
      hide();
      return;
    }
    const middle = (i) =>
      master.kind === "bars" ? (master.spans[i][0] + master.spans[i][1]) / 2 : master.px[i];
    let best = shown.first;
    for (let i = shown.first; i <= shown.last; i += 1) {
      if (Math.abs(middle(i) - at.x) < Math.abs(middle(best) - at.x)) best = i;
    }
    show(best);
  }

  // The zoom works in zoom coordinates (values, or their logarithms on a log axis): a share
  // of the plot is a share of the range there.

  function space(axis) {
    return spaceOf(axis === "x" ? layout.x.scale.type : layout.y.scale.type);
  }

  function shownOf(axis) {
    return axis === "x" ? (view ?? whole) : (viewY ?? wholeY);
  }

  function wholeOf(axis) {
    return axis === "x" ? whole : wholeY;
  }

  /** A range in zoom coordinates as values; null when it is the whole. */
  function rangeFrom(axis, t) {
    const s = space(axis);
    const all = toSpace(s, wholeOf(axis));
    const slack = 1e-9 * (all[1] - all[0]);
    if (t[0] <= all[0] + slack && t[1] >= all[1] - slack) return null;
    return { min: s.from(t[0]), max: s.from(t[1]) };
  }

  /** The share of the plot (x from the left, y from the bottom) of a viewBox coordinate. */
  function shareOf(axis, coordinate) {
    const { left, right } = layout.plot;
    const { top, bottom } = layout.main;
    const share =
      axis === "x" ? (coordinate - left) / (right - left) : (bottom - coordinate) / (bottom - top);
    return Math.max(0, Math.min(1, share));
  }

  /**
   * A zoom in to `size` with `at` at `share`, stopped at its limit: four points of the readout's
   * series in the range (x), else a thousandth of the whole. Null when the range shown is at
   * the limit already.
   */
  function narrowed(axis, at, share, size, now, all) {
    const place = (wide) => placed(at, share, wide, all);
    const nowSize = now[1] - now[0];
    if (axis === "x" && wanted) {
      const xs = sortedXs(wanted);
      const s = space("x");
      const count = (t) => countWithin(xs, s.from(t[0]), s.from(t[1]));
      if (count(place(size)) >= LEAST_POINTS) return place(size);
      if (count(now) <= LEAST_POINTS) return null;
      let lo = size;
      let hi = all[1] - all[0];
      for (let step = 0; step < 60; step += 1) {
        const middle = (lo + hi) / 2;
        if (count(place(middle)) >= LEAST_POINTS) hi = middle;
        else lo = middle;
      }
      return hi < nowSize ? place(hi) : null;
    }
    const least = (all[1] - all[0]) * LEAST_SHARE;
    if (size >= least) return place(size);
    return nowSize > least * (1 + 1e-9) ? place(least) : null;
  }

  /** An axis zoomed by a factor around a value: a range, null for the whole, false unchanged. */
  function zoomAxis(axis, factor, value) {
    const s = space(axis);
    const all = toSpace(s, wholeOf(axis));
    const now = toSpace(s, shownOf(axis));
    const t = Number.isFinite(value) ? s.to(value) : NaN;
    const at = t >= now[0] && t <= now[1] ? t : (now[0] + now[1]) / 2;
    const share = now[1] > now[0] ? (at - now[0]) / (now[1] - now[0]) : 0.5;
    const size = (now[1] - now[0]) * factor;
    if (size >= all[1] - all[0]) return null;
    const next =
      factor < 1 ? narrowed(axis, at, share, size, now, all) : placed(at, share, size, all);
    return next ? rangeFrom(axis, next) : false;
  }

  /** Zoom by a factor (< 1 in) around a point's values, the middle where it gives none. */
  function zoomBy(factor, point = {}) {
    if (!mode || !whole) return false;
    const before = [view, viewY];
    const x = zoomAxis("x", factor, point.x);
    if (x !== false) view = x;
    if (mode === "xy") {
      const y = zoomAxis("y", factor, point.y);
      if (y !== false) viewY = y;
    }
    return !sameRange(before[0], view) || !sameRange(before[1], viewY);
  }

  /** The range of an axis between two viewBox coordinates of a drag. */
  function between(axis, a, b) {
    const s = space(axis);
    const all = toSpace(s, wholeOf(axis));
    const now = toSpace(s, shownOf(axis));
    const [p, q] = [shareOf(axis, a), shareOf(axis, b)].sort((u, v) => u - v);
    const lo = now[0] + p * (now[1] - now[0]);
    const hi = now[0] + q * (now[1] - now[0]);
    const next = narrowed(axis, (lo + hi) / 2, 0.5, hi - lo, now, all);
    return next ? rangeFrom(axis, next) : false;
  }

  /** Show what a drag selected: x, and y on a "xy" chart, where it covers DRAG units. */
  function zoomBox(from, to) {
    const before = [view, viewY];
    if (Math.abs(to.x - from.x) >= DRAG) {
      const x = between("x", from.x, to.x);
      if (x !== false) view = x;
    }
    if (mode === "xy" && Math.abs(to.y - from.y) >= DRAG) {
      const y = between("y", from.y, to.y);
      if (y !== false) viewY = y;
    }
    return !sameRange(before[0], view) || !sameRange(before[1], viewY);
  }

  /** A range moved by a share of its width, held within the whole. */
  function shifted(axis, start, by) {
    const s = space(axis);
    const all = toSpace(s, wholeOf(axis));
    const now = toSpace(s, start ?? wholeOf(axis));
    let a = now[0] + by * (now[1] - now[0]);
    let b = now[1] + by * (now[1] - now[0]);
    if (a < all[0]) {
      b += all[0] - a;
      a = all[0];
    }
    if (b > all[1]) {
      a -= b - all[1];
      b = all[1];
    }
    return rangeFrom(axis, [Math.max(all[0], a), b]);
  }

  /** Move the range of x by a share of its width (keys); false at the whole's edge. */
  function panBy(share, axis = "x") {
    const before = axis === "x" ? view : viewY;
    if (!before) return false;
    const next = shifted(axis, before, share);
    if (sameRange(next, before)) return false;
    if (axis === "x") view = next;
    else viewY = next;
    return true;
  }

  /** The values under a point of the viewBox, by its shares of the ranges shown. */
  function valuesAt(at) {
    const value = (axis, coordinate) => {
      const s = space(axis);
      const now = toSpace(s, shownOf(axis));
      return s.from(now[0] + shareOf(axis, coordinate) * (now[1] - now[0]));
    };
    return { x: value("x", at.x), y: mode === "xy" ? value("y", at.y) : undefined };
  }

  /** Where „+” and „−” zoom: the readout, or the x it read last, else the middle. */
  function anchorPoint() {
    if (master && index !== null) {
      const value = master.values[index];
      return { x: master.xs[index], y: Number.isFinite(value) ? value : undefined };
    }
    return { x: anchor ?? undefined };
  }

  function resetView() {
    const was = Boolean(view || viewY);
    view = null;
    viewY = null;
    return was;
  }

  function rangeNow() {
    if (!view && !viewY) return null;
    const x = view ?? whole;
    const range = { min: x.min, max: x.max };
    return mode === "xy" ? { ...range, y: { ...(viewY ?? wholeY) } } : range;
  }

  /** Tell `onRange` of a range a person settled; true when it differs from the one told last. */
  function settle() {
    const now = rangeNow();
    if (sameRange(now, reported)) return false;
    reported = now;
    current.onRange?.(now ? { ...now, width: plotWidth() } : null);
    return true;
  }

  /** The live region says the range shown, after the readout when it shows. */
  function announce() {
    const range = view || viewY ? rangeText() : texts.reset;
    live.textContent = [readText, range].filter(Boolean).join(" · ");
  }

  /** A zoom of a key, a button, a drag or a double click: drawn, said and settled at once. */
  function act(change) {
    if (!change()) return false;
    redraw(true);
    announce();
    settle();
    return true;
  }

  function plotWidth() {
    const box = svg.getBoundingClientRect();
    if (!layout || !box.width) return 0;
    return Math.round(((layout.plot.right - layout.plot.left) * box.width) / layout.width);
  }

  /** The selection of a drag: x over the plot's height, a rectangle on a "xy" chart. */
  function drawSelection(move) {
    const { from, to } = move;
    const { left, right, top, bottom } = layout.plot;
    const wideX = Math.abs(to.x - from.x) >= DRAG;
    const wideY = mode === "xy" && Math.abs(to.y - from.y) >= DRAG;
    if (!wideX && !wideY) {
      selection.setAttribute("visibility", "hidden");
      return;
    }
    hide();
    const xs = wideX ? [Math.min(from.x, to.x), Math.max(from.x, to.x)] : [left, right];
    const ys = wideY ? [Math.min(from.y, to.y), Math.max(from.y, to.y)] : [top, bottom];
    selection.setAttribute("x", String(c1(xs[0])));
    selection.setAttribute("width", String(c1(xs[1] - xs[0])));
    selection.setAttribute("y", String(c1(ys[0])));
    selection.setAttribute("height", String(c1(ys[1] - ys[0])));
    selection.removeAttribute("visibility");
  }

  function startPinch() {
    const [a, b] = [...touches.values()];
    const middle = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    pinch = { x: view, y: viewY, middle, distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)) };
    hide();
  }

  /** A pinch's range of an axis: the value under the fingers' middle at its start stays there. */
  function pinched(axis, start, factor, from, to) {
    const s = space(axis);
    const all = toSpace(s, wholeOf(axis));
    const now = toSpace(s, start ?? wholeOf(axis));
    const at = now[0] + shareOf(axis, from) * (now[1] - now[0]);
    const share = shareOf(axis, to);
    const size = Math.min(all[1] - all[0], (now[1] - now[0]) * factor);
    const next =
      factor < 1 ? narrowed(axis, at, share, size, now, all) : placed(at, share, size, all);
    // At its limit the fingers still pan
    return rangeFrom(axis, next ?? placed(at, share, now[1] - now[0], all));
  }

  function movePinch() {
    const [a, b] = [...touches.values()];
    const factor = pinch.distance / Math.max(1, Math.hypot(a.x - b.x, a.y - b.y));
    const middle = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const x = pinched("x", pinch.x, factor, pinch.middle.x, middle.x);
    const y = mode === "xy" ? pinched("y", pinch.y, factor, pinch.middle.y, middle.y) : null;
    if (sameRange(x, view) && sameRange(y, viewY)) return;
    view = x;
    viewY = y;
    redraw(false);
  }

  function onPointerDown(event) {
    const at = svgPoint(event.clientX, event.clientY);
    if (!at) return;
    if (event.pointerType !== "mouse") {
      // A finger reads out where it lands and along the plot; two pinch and pan
      touches.set(event.pointerId, at);
      if (touches.size === 2 && mode) startPinch();
      else if (touches.size === 1) readAt(at);
      return;
    }
    const panning = event.button === 1 || (event.button === 0 && event.shiftKey);
    if (!mode || (event.button !== 0 && !panning) || !inPlot(at)) return;
    drag = { pan: panning, pointer: event.pointerId, from: at, to: at, x: view, y: viewY };
    svg.setPointerCapture(event.pointerId);
    container.classList.toggle("nogat-chart-panning", panning);
    // A press prevented takes no focus by itself: the chart takes it, so its keys follow the
    // mouse, without the ring a keyboard's focus draws
    event.preventDefault();
    svg.focus({ preventScroll: true, focusVisible: false });
  }

  function onPointerMove(event) {
    const at = svgPoint(event.clientX, event.clientY);
    if (!at) return;
    if (touches.has(event.pointerId)) {
      touches.set(event.pointerId, at);
      if (pinch) movePinch();
      else if (touches.size === 1) readAt(at);
      return;
    }
    if (drag && event.pointerId === drag.pointer) {
      if (drag.pan) {
        drag.to = at;
        const { left, right } = layout.plot;
        const { top, bottom } = layout.main;
        const x = shifted("x", drag.x, -(at.x - drag.from.x) / (right - left));
        const by = (at.y - drag.from.y) / (bottom - top);
        const y = mode === "xy" ? shifted("y", drag.y, by) : null;
        if (sameRange(x, view) && sameRange(y, viewY)) return;
        view = x;
        viewY = y;
        redraw(false);
        return;
      }
      const { left, right, top, bottom } = layout.plot;
      const within = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
      drag.to = { x: within(at.x, left, right), y: within(at.y, top, bottom) };
      drawSelection(drag);
      return;
    }
    if (!drag && !touches.size) readAt(at);
  }

  function finish(event, apply) {
    if (touches.delete(event.pointerId)) {
      if (pinch && touches.size < 2) {
        pinch = null;
        if (settle()) announce();
      }
      return;
    }
    if (!drag || event.pointerId !== drag.pointer) return;
    const move = drag;
    drag = null;
    selection.setAttribute("visibility", "hidden");
    container.classList.remove("nogat-chart-panning");
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    if (move.pan) {
      if (settle()) announce();
    } else if (apply) act(() => zoomBox(move.from, move.to));
  }

  const onPointerUp = (event) => finish(event, true);
  const onPointerCancel = (event) => finish(event, false);

  function onPointerLeave() {
    if (document.activeElement !== svg && !drag && !touches.size) hide();
  }

  function onDoubleClick() {
    if (mode) act(resetView);
  }

  /** The middle button's autoscroll and paste are not the page's over a zoomable chart. */
  function onMiddle(event) {
    if (event.button === 1 && mode) event.preventDefault();
  }

  /** Ctrl with the wheel, a trackpad's pinch too, zooms at the cursor; the wheel alone scrolls. */
  function onWheel(event) {
    if (!event.ctrlKey || !mode || !whole) return;
    event.preventDefault();
    const at = svgPoint(event.clientX, event.clientY);
    if (!at) return;
    const unit = event.deltaMode === 1 ? LINE_DELTA : event.deltaMode === 2 ? NOTCH_DELTA : 1;
    const notches = Math.max(-1, Math.min(1, (event.deltaY * unit) / NOTCH_DELTA));
    if (notches && zoomBy(NOTCH ** notches, valuesAt(at))) redraw(false);
    clearTimeout(idle);
    idle = setTimeout(() => {
      idle = 0;
      if (settle()) announce();
    }, WHEEL_IDLE);
  }

  /** The readout past the edge of a zoomed range: the range moves a quarter on. */
  function stepBeyond(direction, step) {
    const kept = master.xs[index];
    if (!panBy(direction * 0.25)) return false;
    redraw(true);
    if (master) show(indexOfX(kept) + direction * step);
    announce();
    settle();
    return true;
  }

  function press(event, change) {
    event.preventDefault();
    act(change);
  }

  function onKeyDown(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const { key } = event;
    if (mode && (key === "+" || key === "=")) return press(event, () => zoomBy(0.5, anchorPoint()));
    if (mode && (key === "-" || key === "_")) return press(event, () => zoomBy(2, anchorPoint()));
    if (mode && key === "0") return press(event, resetView);
    if (!master) {
      // Without a readout the arrows move a zoomed range
      const moves = { ArrowLeft: ["x", -0.25], ArrowRight: ["x", 0.25] };
      if (mode === "xy") Object.assign(moves, { ArrowDown: ["y", -0.25], ArrowUp: ["y", 0.25] });
      const move = mode && moves[key];
      if (move) press(event, () => panBy(move[1], move[0]));
      return;
    }
    const { first, last } = shown;
    const step = event.shiftKey || key === "PageUp" || key === "PageDown" ? 10 : 1;
    const from = index ?? first;
    let next = null;
    const forward = key === "ArrowRight" || key === "ArrowUp" || key === "PageUp";
    const back = key === "ArrowLeft" || key === "ArrowDown" || key === "PageDown";
    if (forward) next = index === null ? first : from + step;
    else if (back) next = index === null ? last : from - step;
    else if (key === "Home") next = first;
    else if (key === "End") next = last;
    else if (key === "Escape") {
      anchor = null;
      hide();
      return;
    } else return;
    event.preventDefault();
    const beyond = next > last || next < first;
    if (index !== null && view && beyond && stepBeyond(next > last ? 1 : -1, step)) return;
    show(next);
  }

  function onFocus() {
    if (master && anchor !== null) show(indexOfX(anchor));
  }

  function onBlur() {
    hide();
  }

  /** A button of the bar; focus goes to „+” when the button pressed leaves with the zoom. */
  function onBar(change) {
    return (event) => {
      act(change);
      if (event.currentTarget.hidden) zoomIn.focus({ preventScroll: true });
    };
  }

  function onPhone() {
    width = Math.floor(container.clientWidth);
    render(current);
  }

  const listeners = [
    ["pointerdown", onPointerDown],
    ["pointermove", onPointerMove],
    ["pointerup", onPointerUp],
    ["pointercancel", onPointerCancel],
    ["pointerleave", onPointerLeave],
    ["dblclick", onDoubleClick],
    ["mousedown", onMiddle],
    ["auxclick", onMiddle],
    ["keydown", onKeyDown],
    ["focus", onFocus],
    ["blur", onBlur],
  ];
  for (const [name, listener] of listeners) svg.addEventListener(name, listener);
  svg.addEventListener("wheel", onWheel, { passive: false });
  const actions = [
    [zoomIn, onBar(() => zoomBy(0.5, anchorPoint()))],
    [zoomOut, onBar(() => zoomBy(2, anchorPoint()))],
    [zoomReset, onBar(resetView)],
  ];
  for (const [button, listener] of actions) button.addEventListener("click", listener);
  // A fitted chart is drawn again when its container's width changes
  const resized =
    typeof ResizeObserver === "function"
      ? new ResizeObserver(() => {
          const next = Math.floor(container.clientWidth);
          if (!fitOf(current) || !next || next === width) return;
          width = next;
          render(current);
        })
      : null;
  resized?.observe(container);
  phone?.addEventListener?.("change", onPhone);
  render(spec);

  return {
    svg,
    update(next) {
      if (!sameData(current, next)) {
        anchor = null;
        view = null;
        viewY = null;
        reported = null;
      }
      render(next);
    },
    destroy() {
      for (const [name, listener] of listeners) svg.removeEventListener(name, listener);
      svg.removeEventListener("wheel", onWheel);
      for (const [button, listener] of actions) button.removeEventListener("click", listener);
      resized?.disconnect();
      phone?.removeEventListener?.("change", onPhone);
      if (frame) cancelAnimationFrame(frame);
      clearTimeout(idle);
      container.replaceChildren();
      container.classList.remove(
        "nogat-chart",
        "nogat-chart-wide",
        "nogat-chart-fit",
        "nogat-chart-zoomable",
        "nogat-chart-zoomed",
        "nogat-chart-panning",
      );
    },
    plotWidth,
    readout: {
      show(at) {
        if (!master) return;
        const point = points(master.series)[at];
        if (point) show(indexOfX(point.x));
      },
      hide() {
        anchor = null;
        hide();
      },
      index: () => (master && index !== null ? master.data[index][AT] : null),
    },
    zoom: {
      set(min, max, y) {
        if (!mode || !whole || !(max > min)) return;
        const lo = Math.max(whole.min, min);
        const hi = Math.min(whole.max, max);
        if (!(hi > lo)) return;
        view = lo <= whole.min && hi >= whole.max ? null : { min: lo, max: hi };
        if (mode === "xy" && y && y.max > y.min) {
          const bottom = Math.max(wholeY.min, y.min);
          const top = Math.min(wholeY.max, y.max);
          const all = bottom <= wholeY.min && top >= wholeY.max;
          if (top > bottom) viewY = all ? null : { min: bottom, max: top };
        }
        reported = rangeNow();
        redraw(true);
      },
      reset() {
        view = null;
        viewY = null;
        reported = null;
        redraw(true);
      },
      range: () => rangeNow(),
    },
  };
}

// --- PNG --------------------------------------------------------------------------------------

/** The footer of a PNG [px of the drawn chart]: its size, its line height and the margins. */
const FOOTER = Object.freeze({ size: 11, leading: 1.4, margin: 8 });

/** The properties that carry a drawing's look. */
const PROPERTIES = [
  "display",
  "visibility",
  "opacity",
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  "paint-order",
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "font-variant-numeric",
  "text-anchor",
  "dominant-baseline",
];

/** The computed styles of `source` and its descendants written into `clone` through the CSSOM. */
function inlineStyles(source, clone) {
  const sources = [source, ...source.querySelectorAll("*")];
  const clones = [clone, ...clone.querySelectorAll("*")];
  sources.forEach((element, at) => {
    const target = clones[at];
    if (!target?.style) return;
    const computed = getComputedStyle(element);
    for (const name of PROPERTIES) {
      const value = computed.getPropertyValue(name);
      if (value) target.style.setProperty(name, value);
    }
  });
}

/**
 * A drawn SVG serialized with its styles at its drawn size, without the readout and the
 * selection. While its styles are read it has the class `nogat-chart-exporting`, under which a
 * GUI hides what is not part of a picture.
 *
 * @param {SVGSVGElement} svg a drawn SVG (attached and visible)
 * @returns {{text: string, width: number, height: number}}
 */
export function svgText(svg) {
  const box = svg.getBoundingClientRect();
  const width = Math.max(1, Math.round(box.width));
  const height = Math.max(1, Math.round(box.height));
  const clone = svg.cloneNode(true);
  svg.classList.add("nogat-chart-exporting");
  try {
    inlineStyles(svg, clone);
  } finally {
    svg.classList.remove("nogat-chart-exporting");
  }
  clone.setAttribute("xmlns", SVG_NS);
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.removeAttribute("tabindex");
  clone.style.removeProperty("display");
  for (const transient of clone.querySelectorAll(".readout, .zoom-selection")) transient.remove();
  return { text: new XMLSerializer().serializeToString(clone), width, height };
}

/** The rows of a footer wrapped to a width: at spaces, a word wider than it at its characters. */
function wrapRows(context, rows, width) {
  const fits = (text) => context.measureText(text).width <= width;
  const out = [];
  for (const row of rows) {
    let line = "";
    for (const word of String(row).split(/\s+/).filter(Boolean)) {
      const joined = line ? `${line} ${word}` : word;
      if (fits(joined)) {
        line = joined;
        continue;
      }
      if (line) out.push(line);
      line = "";
      for (const char of word) {
        if (line && !fits(line + char)) {
          out.push(line);
          line = "";
        }
        line += char;
      }
    }
    if (line) out.push(line);
  }
  return out;
}

/**
 * A drawn SVG as a PNG: a chart as shown (the range shown, its y fitted, without the readout
 * and the selection) or any other SVG, on the theme's `--surface`, with the providers' lines
 * of its data (DEV-20.5) under it in the theme's `--text`, each wrapped to the image's width.
 * The image is loaded from a `blob:` address (`img-src 'self' data: blob:`).
 *
 * @param {SVGSVGElement} svg a drawn SVG (attached and visible)
 * @param {{scale?: number, background?: string, footer?: string[], texts?: object}} [options]
 *   `scale` (2) multiplies the drawn size; `background` replaces `--surface`; `footer` the
 *   lines under the image (none by default); `texts` the words (`imageFailed`)
 * @returns {Promise<Blob>} the PNG, `scale` times the drawn size, taller by the footer
 */
export async function toPng(svg, options = {}) {
  const { scale = 2, footer = [] } = options;
  const texts = { ...CHART_TEXTS, ...options.texts };
  const { text, width, height } = svgText(svg);
  const style = getComputedStyle(svg);
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  const family = style.getPropertyValue("--font-sans").trim() || style.fontFamily || "sans-serif";
  const font = `${FOOTER.size * scale}px ${family}`;
  context.font = font;
  const rows = footer.length ? wrapRows(context, footer, (width - 2 * FOOTER.margin) * scale) : [];
  const step = FOOTER.size * FOOTER.leading;
  const added = rows.length ? Math.ceil(FOOTER.margin * 2 + rows.length * step) : 0;
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
    } catch {
      throw new Error(texts.imageFailed);
    }
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round((height + added) * scale);
    const surface = style.getPropertyValue("--surface").trim() || SURFACE;
    const background = options.background ?? surface;
    if (background) {
      context.fillStyle = background;
      context.fillRect(0, 0, canvas.width, canvas.height);
    }
    context.drawImage(image, 0, 0, Math.round(width * scale), Math.round(height * scale));
    if (rows.length) {
      // The canvas's size reset its state: the footer's font again, in the theme's text
      context.font = font;
      context.fillStyle = style.getPropertyValue("--text").trim() || TEXT;
      context.textBaseline = "top";
      rows.forEach((row, at) => {
        const top = height + FOOTER.margin + at * step + (step - FOOTER.size) / 2;
        context.fillText(row, FOOTER.margin * scale, top * scale);
      });
    }
    return await new Promise((resolve, reject) => {
      const done = (blob) => (blob ? resolve(blob) : reject(new Error(texts.imageFailed)));
      canvas.toBlob(done, "image/png");
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}
