// Nogat GUI kit: the providers' lines on screen (DEV-20.5, DEV-20.7, ECO-064).
// <nogat-sources attribution='[…]' terms-notice='[…]' terms="regulamin.html"> once per
// view: a compact strip with the lines the providers require on the product (S, P, PS,
// PP and the short form CK of C), each once in the order of DEV-20.4, and the button
// „Źródła i warunki”, which opens a dialog with every line and the terms. `attribution`
// and `terms-notice` hold JSON arrays, the API's `attribution` and `terms_notice`; the
// properties `attribution` and `termsNotice` take the arrays themselves. `terms` is the
// address of the GUI's regulamin.html (DEV-15.7), linked from the dialog in a new tab, so
// the GUI's own tab and its session stay.
// `fillSources(container, {attribution, termsNotice, terms})` writes the same full
// content into a welcome window of the GUI's own.
// No shadow DOM: the page's stylesheet nogat-sources.css styles it with the tokens.
// Copy this file byte for byte (DEV-15.6); change it in Nogat design/kit/.

/** The lines of DEV §20 the element recognises, byte for byte. */
export const LINES = {
  S: "Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy",
  P: "Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego zostały przetworzone",
  PS: "Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy, dane pochodzą ze strony https://klimat.imgw.pl/opady-maksymalne",
  PP: "Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego pochodzące ze strony https://klimat.imgw.pl/opady-maksymalne zostały przetworzone",
  C: "Źródło danych: Český hydrometeorologický ústav (ČHMÚ), https://opendata.chmi.cz, licencja CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
  CK: "Źródło: ČHMÚ, CC BY 4.0",
};

/** The marks shown on screen, in the order of DEV-20.4; C is shown as CK. */
const SCREEN = ["S", "P", "PS", "PP", "C"];

/** Links of CK: the words of the short form and their addresses. */
const SHORT_LINKS = [
  ["ČHMÚ", "https://opendata.chmi.cz"],
  ["CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"],
];

/** The element's own texts, in Polish. */
export const SOURCES_TEXTS = {
  strip: "Źródła danych",
  button: "Źródła i warunki",
  title: "Źródła danych i warunki korzystania",
  intro:
    "Dane i wyniki pokazane w aplikacji pochodzą od dostawców wymienionych poniżej. Pliki, eksporty i obrazy z aplikacji zawierają te informacje w pełnym brzmieniu.",
  attribution: "Źródła danych",
  termsNotice: "Warunki korzystania z danych",
  regulamin: "Regulamin serwisu",
  close: "Zamknij",
};

const URL_IN_TEXT = /https?:\/\/[^\s()]+[^\s().,;:]/g;

let counter = 0;

/**
 * Strings of a JSON array, each once in their order; anything else gives none.
 *
 * @param {unknown} value an array or the JSON text of one
 * @returns {string[]} the lines
 */
export function lines(value) {
  let list = value;
  if (typeof value === "string") {
    try {
      list = JSON.parse(value);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(list)) return [];
  return [...new Set(list.filter((line) => typeof line === "string" && line.trim() !== ""))];
}

/**
 * The marks of the on-screen lines found among the full lines, in the order of DEV-20.4;
 * a line other than S, P, PS, PP and C (M, CP, another provider's) stays in the dialog.
 *
 * @param {string[]} attribution the full lines a product carries
 * @returns {string[]} the marks, C standing for its short form
 */
export function screenMarks(attribution) {
  const present = new Set(attribution);
  return SCREEN.filter((mark) => present.has(LINES[mark]));
}

/**
 * An address resolved against the page, or null unless it is http or https.
 *
 * @param {unknown} address an absolute address or a path
 * @returns {string|null} the resolved address
 */
export function web(address) {
  let url;
  try {
    url = new URL(String(address), globalThis.location?.href);
  } catch {
    return null;
  }
  return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
}

function link(text, href) {
  const a = document.createElement("a");
  a.href = href;
  a.textContent = text;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

/** The nodes of a line, its http(s) addresses as links; the text stays byte for byte. */
function linked(text) {
  const nodes = [];
  let at = 0;
  for (const match of text.matchAll(URL_IN_TEXT)) {
    if (match.index > at) nodes.push(document.createTextNode(text.slice(at, match.index)));
    nodes.push(link(match[0], match[0]));
    at = match.index + match[0].length;
  }
  if (at < text.length) nodes.push(document.createTextNode(text.slice(at)));
  return nodes;
}

/** The nodes of CK, „ČHMÚ” and „CC BY 4.0” as links. */
function short() {
  const nodes = [];
  let rest = LINES.CK;
  for (const [words, href] of SHORT_LINKS) {
    const at = rest.indexOf(words);
    nodes.push(document.createTextNode(rest.slice(0, at)), link(words, href));
    rest = rest.slice(at + words.length);
  }
  if (rest) nodes.push(document.createTextNode(rest));
  return nodes;
}

function section(heading, items, headingId) {
  const part = document.createElement("section");
  const title = document.createElement("h3");
  title.textContent = heading;
  if (headingId) title.id = headingId;
  const list = document.createElement("ul");
  for (const text of items) {
    const item = document.createElement("li");
    item.append(...linked(text));
    list.append(item);
  }
  part.append(title, list);
  return part;
}

/**
 * Fill a container with every line and the terms: the dialog's content, for a GUI's own
 * welcome window. The container's children are replaced.
 *
 * @param {Element} container where the content goes
 * @param {{attribution?: unknown, termsNotice?: unknown, terms?: string|null}} sources
 *   the full lines, the terms lines and the address of the regulamin
 * @returns {Element} the container
 */
export function fillSources(container, { attribution, termsNotice, terms } = {}) {
  const full = lines(attribution);
  const notice = lines(termsNotice);
  const intro = document.createElement("p");
  intro.className = "nogat-sources-intro";
  intro.textContent = SOURCES_TEXTS.intro;
  const parts = [intro];
  if (full.length) parts.push(section(SOURCES_TEXTS.attribution, full));
  if (notice.length) parts.push(section(SOURCES_TEXTS.termsNotice, notice));
  const regulamin = terms ? web(terms) : null;
  if (regulamin) {
    const line = document.createElement("p");
    line.className = "nogat-sources-regulamin";
    const a = document.createElement("a");
    a.href = regulamin;
    a.textContent = SOURCES_TEXTS.regulamin;
    a.target = "_blank";
    a.rel = "noopener";
    line.append(a);
    parts.push(line);
  }
  container.classList.add("nogat-sources-content");
  container.replaceChildren(...parts);
  return container;
}

/** The custom element `<nogat-sources>`. */
export class NogatSources extends HTMLElement {
  static observedAttributes = ["attribution", "terms-notice", "terms"];

  constructor() {
    super();
    this._attribution = null;
    this._termsNotice = null;
    this._id = `nogat-sources-${++counter}`;
  }

  /** @returns {string[]} the full lines */
  get attribution() {
    return lines(this._attribution ?? this.getAttribute("attribution"));
  }

  /** @param {string[]|null} value the full lines, as the API's `attribution` */
  set attribution(value) {
    this._attribution = value;
    if (this.isConnected) this.render();
  }

  /** @returns {string[]} the terms lines */
  get termsNotice() {
    return lines(this._termsNotice ?? this.getAttribute("terms-notice"));
  }

  /** @param {string[]|null} value the terms lines, as the API's `terms_notice` */
  set termsNotice(value) {
    this._termsNotice = value;
    if (this.isConnected) this.render();
  }

  /** @returns {boolean} whether the dialog is shown */
  get isOpen() {
    return Boolean(this.querySelector("dialog")?.open);
  }

  connectedCallback() {
    this.render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this.render();
  }

  /** Open the dialog; fires `nogat-sources-open`. */
  open() {
    const dialog = this.querySelector("dialog");
    if (!dialog || dialog.open) return;
    dialog.showModal();
    dialog.querySelector(".nogat-sources-close")?.focus();
    this.dispatchEvent(new CustomEvent("nogat-sources-open", { bubbles: true }));
  }

  /** Close the dialog; focus returns to the button. */
  close() {
    this.querySelector("dialog")?.close();
  }

  /** Draw the strip and the dialog from the lines. */
  render() {
    const full = this.attribution;
    const notice = this.termsNotice;
    this.replaceChildren();
    this.hidden = full.length === 0 && notice.length === 0;
    if (this.hidden) return;

    const strip = document.createElement("p");
    strip.className = "nogat-sources-strip";
    strip.setAttribute("aria-label", SOURCES_TEXTS.strip);
    for (const mark of screenMarks(full)) {
      const line = document.createElement("span");
      line.className = "nogat-sources-line";
      line.append(...(mark === "C" ? short() : linked(LINES[mark])));
      strip.append(line, " ");
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nogat-sources-more";
    button.textContent = SOURCES_TEXTS.button;
    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-controls", this._id);
    button.addEventListener("click", () => this.open());
    strip.append(button);

    this.append(strip, this._dialog(full, notice, button));
  }

  _dialog(full, notice, button) {
    const dialog = document.createElement("dialog");
    dialog.className = "nogat-sources-dialog";
    dialog.id = this._id;
    dialog.setAttribute("aria-labelledby", `${this._id}-title`);
    const head = document.createElement("header");
    const title = document.createElement("h2");
    title.id = `${this._id}-title`;
    title.textContent = SOURCES_TEXTS.title;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "nogat-sources-close";
    close.textContent = SOURCES_TEXTS.close;
    close.addEventListener("click", () => this.close());
    head.append(title, close);
    const body = document.createElement("div");
    fillSources(body, { attribution: full, termsNotice: notice, terms: this.getAttribute("terms") });
    dialog.append(head, body);

    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const stops = [...dialog.querySelectorAll("a[href], button")];
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) this.close();
    });
    dialog.addEventListener("close", () => {
      button.focus();
      this.dispatchEvent(new CustomEvent("nogat-sources-close", { bubbles: true }));
    });
    return dialog;
  }
}

if (!customElements.get("nogat-sources")) customElements.define("nogat-sources", NogatSources);
