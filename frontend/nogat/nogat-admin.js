// Nogat GUI kit: the admin panel (DEV-15.13, ECO-067).
// <nogat-admin app="Hydrolog" project="hydrolog" back="../"> is the admin page of a GUI, served
// at /admin/: the top bar „Hydrolog · Administracja” with „Wróć do aplikacji” and „Wyloguj”,
// the key prompt, the navigation „Zgłoszenia”, „Statystyki”, „Stan” and then each child
// <section data-admin-section="id" data-label="…"> of the app in document order, the section
// shown named by the URL hash. The key is kept in sessionStorage under "<project>/admin-key/1"
// and sent as X-Admin-Key; `adminFetch(path, init)` sends the app's own requests with it and
// returns to the prompt on 401. `auth = "session"` (an app with accounts) asks for no key and
// sends the page's cookies. The views <nogat-admin-feedback>, <nogat-admin-stats> and
// <nogat-admin-status> read the core API of DEV-15.13 and also work alone, inside an app's
// own view. Every text of a report is a text node, never markup.
// No shadow DOM: the page's stylesheet nogat-admin.css styles it with the tokens.
// Copy this file byte for byte (DEV-15.6); change it in Nogat design/kit/.

/** The admin API seen from the page at /admin/ (DEV-15.13). */
export const ADMIN_API = "../api/admin/";

/** Reports per page of <nogat-admin-feedback>. */
export const PAGE_SIZE = 50;

/** The day <nogat-admin-stats> asks from for the whole record. */
export const FIRST_DAY = "1970-01-01";

/** The panel's texts, in Polish (DEV-15.2). */
export const ADMIN_TEXTS = {
  admin: "Administracja",
  back: "Wróć do aplikacji",
  signOut: "Wyloguj",
  sections: "Sekcje panelu",
  feedback: "Zgłoszenia",
  stats: "Statystyki",
  status: "Stan",
  promptTitle: "Zaloguj się",
  promptText: "Podaj klucz administratora, aby kontynuować.",
  key: "Klucz administratora",
  signIn: "Zaloguj",
  checking: "Sprawdzanie…",
  refused: "Brak dostępu.",
  network: "Brak połączenia z serwerem.",
  failed: "Serwer odpowiedział błędem {status}.",
  loading: "Wczytywanie…",
  refresh: "Odśwież",
  unread: "Nieprzeczytane: {unread} z {total}",
  unreadOnly: "Tylko nieprzeczytane",
  empty: "Brak zgłoszeń.",
  emptyUnread: "Na tej stronie nie ma nieprzeczytanych zgłoszeń.",
  fresh: "nowe",
  context: "Kontekst",
  noContext: "Bez kontekstu.",
  view: "Widok",
  station: "Stacja",
  appVersion: "Wersja aplikacji",
  parameters: "Parametry widoku",
  markRead: "Oznacz jako przeczytane",
  markUnread: "Oznacz jako nieprzeczytane",
  remove: "Usuń",
  confirmTitle: "Usunąć zgłoszenie #{id}?",
  confirmText: "Usuniętego zgłoszenia nie da się przywrócić.",
  cancel: "Anuluj",
  removed: "Usunięto zgłoszenie #{id}.",
  gone: "Zgłoszenia #{id} już nie ma.",
  pages: "Strony zgłoszeń",
  previous: "Poprzednia strona",
  next: "Następna strona",
  range: "{first}–{last} z {total}",
  period: "Okres",
  table: "Dni okresu",
  caption: "Dni od {first} do {last}",
  noDays: "Brak danych z tego okresu.",
  total: "Razem",
  visitorsTotal: "suma dziennych odwiedzających",
  csv: "Pobierz CSV",
  app: "Aplikacja",
  version: "Wersja",
  started: "Uruchomiona",
  uptime: "Czas działania",
  dataDir: "Katalog danych",
  disk: "Wolne miejsce",
  diskValue: "{free} z {total} ({percent}%)",
  checks: "Kontrole",
  noChecks: "Brak kontroli.",
  oneDay: "1 dzień",
  days: "{n} dni",
  hours: "{n} godz.",
  minutes: "{n} min",
};

/** What the prompt says of each reason of a refused key (DEV-15.13). */
export const ADMIN_REASONS = {
  admin_key_not_configured: "Serwer nie ma ustawionego klucza administratora.",
  admin_key_missing: "Podaj klucz administratora.",
  admin_key_invalid: "Nieprawidłowy klucz. Spróbuj ponownie.",
};

/** The columns of <nogat-admin-stats>: the keys of DEV-15.11 and their headings. */
export const STATS_COLUMNS = [
  ["date", "Data"],
  ["visitors", "Odwiedzający"],
  ["page_views", "Odsłony"],
  ["stations_opened", "Otwarte stacje"],
  ["analyses_run", "Obliczenia"],
  ["downloads", "Pobrania"],
];

/** The periods of <nogat-admin-stats>: days up to today, 0 for the whole record. */
export const STATS_PERIODS = [
  [7, "7 dni"],
  [30, "30 dni"],
  [90, "90 dni"],
  [0, "Cały okres"],
];

/** The words of a check's status (DEV-15.13). */
export const CHECK_STATUS = { ok: "OK", warning: "Ostrzeżenie", failed: "Błąd" };

const VIEWS = "nogat-admin-feedback, nogat-admin-stats, nogat-admin-status";

const BACK_ICON =
  '<svg class="nogat-admin-icon" viewBox="0 0 20 20" aria-hidden="true">' +
  '<path d="M12.5 4.5 7 10l5.5 5.5"/></svg>';

const NUMBER = new Intl.NumberFormat("pl-PL");

let counter = 0;

// The first request waits for the page's own module scripts (DOMContentLoaded, or load for a
// late import), so they attach their listeners and functions before it.
let ready = document.readyState === "complete";
const waiting = [];
if (!ready) {
  const start = () => {
    if (ready) return;
    ready = true;
    for (const callback of waiting.splice(0)) callback();
  };
  document.addEventListener("DOMContentLoaded", start, { once: true });
  window.addEventListener("load", start, { once: true });
}

function whenReady(callback) {
  if (ready) callback();
  else waiting.push(callback);
}

/** A text with its {name} fields filled. */
function fill(text, values) {
  return text.replace(/\{(\w+)\}/g, (field, name) =>
    name in values ? String(values[name]) : field,
  );
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** The objects of a JSON array; anything else gives none. */
function objects(value) {
  return Array.isArray(value) ? value.filter(isObject) : [];
}

/** A value as text, "–" for none. */
function shown(value) {
  return value === null || value === undefined || value === "" ? "–" : String(value);
}

/** A JSON number, or null for anything else. */
function finite(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** An address resolved against the page, or null unless it is http or https. */
function web(address) {
  let url;
  try {
    url = new URL(String(address), globalThis.location?.href);
  } catch {
    return null;
  }
  return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function button(text, className = "nogat-admin-button") {
  const node = el("button", className, text);
  node.type = "button";
  return node;
}

async function documentOf(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** The `details.reason` of an error document (AGI-6.3), or null. */
function reasonOf(doc) {
  const reason = doc?.details?.reason;
  return typeof reason === "string" ? reason : null;
}

function refusal(reason) {
  return ADMIN_REASONS[reason] ?? ADMIN_TEXTS.refused;
}

class AdminError extends Error {
  constructor(status, message, reason = null) {
    super(message);
    this.status = status;
    this.reason = reason;
  }
}

function number(value) {
  const n = Number(value);
  return value === null || value === undefined || !Number.isFinite(n) ? "–" : NUMBER.format(n);
}

/** A moment in the browser's time zone, "13.11.2026, 10:15". */
function moment(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso ?? "");
  return date.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
}

/** A duration in seconds as "2 dni 3 godz. 4 min". */
function duration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const parts = [];
  if (days) parts.push(days === 1 ? ADMIN_TEXTS.oneDay : fill(ADMIN_TEXTS.days, { n: days }));
  if (days || hours) parts.push(fill(ADMIN_TEXTS.hours, { n: hours }));
  parts.push(fill(ADMIN_TEXTS.minutes, { n: Math.floor((total % 3600) / 60) }));
  return parts.join(" ");
}

/** A number of bytes in SI units, "12,3 GB". */
function size(bytes) {
  const units = ["B", "kB", "MB", "GB", "TB"];
  let value = Number(bytes);
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const format = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: unit ? 1 : 0 });
  return `${format.format(value)} ${units[unit]}`;
}

/** The UTC days `from` and `to` of a period of `days` days up to today; 0 is the record. */
function statsRange(days, now) {
  const to = now.toISOString().slice(0, 10);
  if (!days) return { from: FIRST_DAY, to };
  const first = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - (days - 1)),
  );
  return { from: first.toISOString().slice(0, 10), to };
}

function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** The days as CSV: the keys of DEV-15.11 as the header, one line per day, LF. */
function statsCsv(days) {
  const keys = STATS_COLUMNS.map(([key]) => key);
  const lines = [keys.join(","), ...days.map((day) => keys.map((k) => csvCell(day[k])).join(","))];
  return `${lines.join("\n")}\n`;
}

/** Keep Tab inside a dialog. */
function trapTab(event) {
  if (event.key !== "Tab") return;
  const stops = [...event.currentTarget.querySelectorAll("button, a[href], input")].filter(
    (stop) => !stop.disabled,
  );
  const first = stops[0];
  const last = stops[stops.length - 1];
  if (!first) return;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

/** A property the page set before the element was defined goes through its setter. */
function upgrade(element, name) {
  if (!Object.hasOwn(element, name)) return;
  const value = element[name];
  delete element[name];
  element[name] = value;
}

/** What the three views share: the route, the requests, the frame and the error line. */
class AdminView extends HTMLElement {
  static observedAttributes = ["endpoint", "auth"];

  constructor() {
    super();
    this._fetch = null;
    this._ticket = 0;
    this._alone = false;
    this._parts = null;
    this._id = `nogat-admin-view-${++counter}`;
  }

  /** @returns {string} the route, resolved against the page, without a final slash */
  get endpoint() {
    const route = this.getAttribute("endpoint") || `${ADMIN_API}${this.constructor.route}`;
    return new URL(route, document.baseURI).href.replace(/\/+$/, "");
  }

  /** @param {string} value the route, resolved against the page */
  set endpoint(value) {
    this.setAttribute("endpoint", value);
  }

  /**
   * The function every request of the view goes through: the app's own if it set one, else
   * the nearest <nogat-admin>'s adminFetch, else (alone or with auth="session") fetch with
   * the page's cookies.
   *
   * @returns {(url: string, init?: RequestInit) => Promise<Response>} the function
   */
  get adminFetch() {
    return this._fetch ?? ((url, init) => this._send(url, init));
  }

  /** @param {Function|null} value the app's own function; null restores the default */
  set adminFetch(value) {
    this._fetch = typeof value === "function" ? value : null;
  }

  connectedCallback() {
    upgrade(this, "adminFetch");
    upgrade(this, "endpoint");
    if (this._alone || this.closest("nogat-admin")) return;
    this._alone = true;
    whenReady(() => queueMicrotask(() => this.isConnected && this.load()));
  }

  attributeChangedCallback(name, old, value) {
    if (old !== value && this._alone && this.isConnected) this.load();
  }

  /** Drop what the view shows; the shell calls it when it returns to the prompt. */
  clear() {
    this._ticket += 1;
    this._settle?.(false);
    this._settle = null;
    this._reset();
    this._parts = null;
    this.removeAttribute("aria-busy");
    this.replaceChildren();
  }

  _reset() {}

  _shell() {
    return this.getAttribute("auth") === "session" ? null : this.closest("nogat-admin");
  }

  _send(url, init = {}) {
    const shell = this._shell();
    if (shell) return shell.adminFetch(url, init);
    return fetch(url, { credentials: "same-origin", cache: "no-store", ...init });
  }

  /** The JSON answer of a request; an AdminError with a Polish message otherwise. */
  async _call(url, init = {}) {
    const viaShell = !this._fetch && this._shell() !== null;
    let response;
    try {
      response = await this.adminFetch(url, init);
    } catch {
      throw new AdminError(0, ADMIN_TEXTS.network);
    }
    const doc = await documentOf(response);
    if (response.status === 401) {
      const reason = reasonOf(doc);
      // Through the shell its adminFetch answers the refusal; alone the view reports it.
      if (!viaShell) {
        const detail = { status: 401, reason };
        this.dispatchEvent(new CustomEvent("nogat-admin-unauthorized", { bubbles: true, detail }));
      }
      throw new AdminError(401, refusal(reason), reason);
    }
    if (!response.ok) {
      throw new AdminError(response.status, fill(ADMIN_TEXTS.failed, { status: response.status }));
    }
    return doc;
  }

  /** The heading, the tools, the error and note lines and the body, built once. */
  _frame() {
    if (this._parts) return this._parts;
    const head = el("div", "nogat-admin-head");
    const heading = el("h2", "nogat-admin-heading", this.constructor.heading);
    heading.tabIndex = -1;
    const tools = el("div", "nogat-admin-tools");
    head.append(heading, tools);
    const error = el("p", "nogat-admin-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    const note = el("p", "nogat-admin-note");
    note.setAttribute("role", "status");
    const body = el("div", "nogat-admin-content");
    this.replaceChildren(head, error, note, body);
    this._parts = { head, heading, tools, error, note, body };
    this._build(this._parts);
    const refresh = button(ADMIN_TEXTS.refresh);
    refresh.addEventListener("click", () => this.load());
    tools.append(refresh);
    return this._parts;
  }

  /**
   * Ask `url` and hand its answer to `draw`; true once drawn. A newer load, or clear(), drops
   * the answer of an older one.
   */
  async _load(url, draw) {
    const parts = this._frame();
    const ticket = ++this._ticket;
    parts.note.textContent = ADMIN_TEXTS.loading;
    this.setAttribute("aria-busy", "true");
    let doc;
    try {
      doc = await this._call(url);
    } catch (error) {
      if (ticket === this._ticket) this._show(error.message);
      return false;
    }
    if (ticket !== this._ticket) return false;
    this._show("");
    await draw(doc ?? {});
    return true;
  }

  /** End a request: no busy state, and the error line shows `message` or nothing. */
  _show(message) {
    const parts = this._parts;
    this.removeAttribute("aria-busy");
    if (!parts) return;
    parts.note.textContent = "";
    parts.error.textContent = message;
    parts.error.hidden = !message;
  }
}

/** The custom element `<nogat-admin-feedback>`: the reports of „Zgłoś uwagę” (DEV-15.12). */
export class NogatAdminFeedback extends AdminView {
  static route = "feedback";
  static heading = ADMIN_TEXTS.feedback;

  constructor() {
    super();
    this._reset();
  }

  /** Ask the page of reports shown again and redraw. */
  load() {
    return this._page(true);
  }

  _reset() {
    this._offset = 0;
    this._data = { items: [], total: 0, unread: 0 };
    this._unreadOnly = false;
    this._opener = null;
  }

  _build(parts) {
    const count = el("p", "nogat-admin-count");
    parts.head.insertBefore(count, parts.tools);
    const filter = el("label", "nogat-admin-filter");
    const box = el("input");
    box.type = "checkbox";
    box.addEventListener("change", () => {
      this._unreadOnly = box.checked;
      this._draw();
    });
    filter.append(box, ADMIN_TEXTS.unreadOnly);
    parts.tools.append(filter);
    const list = el("ol", "nogat-admin-reports");
    list.hidden = true;
    const empty = el("p", "nogat-admin-empty");
    empty.hidden = true;
    const pager = el("nav", "nogat-admin-pager");
    pager.setAttribute("aria-label", ADMIN_TEXTS.pages);
    pager.hidden = true;
    const previous = button(ADMIN_TEXTS.previous);
    const range = el("span", "nogat-admin-range");
    const next = button(ADMIN_TEXTS.next);
    previous.addEventListener("click", () => this._turn(-1));
    next.addEventListener("click", () => this._turn(1));
    pager.append(previous, range, next);
    parts.body.append(list, empty, pager, this._dialog());
    Object.assign(parts, { count, list, empty, pager, previous, range, next });
  }

  _page(again) {
    const url = new URL(this.endpoint);
    url.searchParams.set("limit", String(PAGE_SIZE));
    url.searchParams.set("offset", String(this._offset));
    return this._load(url.href, (doc) => {
      const items = objects(doc.items);
      const total = Math.max(0, Number(doc.total) || 0);
      if (!items.length && this._offset > 0 && total > 0 && again) {
        // The page emptied (reports deleted elsewhere): show the last one there is.
        this._offset = Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE;
        return this._page(false);
      }
      this._data = { items, total, unread: Math.max(0, Number(doc.unread_count) || 0) };
      this._draw();
      return undefined;
    });
  }

  _turn(step) {
    this._offset = Math.max(0, this._offset + step * PAGE_SIZE);
    this.load();
  }

  _draw() {
    const parts = this._parts;
    if (!parts) return;
    const { items, total, unread } = this._data;
    const counts = { unread: number(unread), total: number(total) };
    parts.count.textContent = fill(ADMIN_TEXTS.unread, counts);
    const visible = this._unreadOnly ? items.filter((item) => !item.is_read) : items;
    parts.list.replaceChildren(...visible.map((item) => this._report(item)));
    parts.list.hidden = visible.length === 0;
    parts.empty.textContent = items.length ? ADMIN_TEXTS.emptyUnread : ADMIN_TEXTS.empty;
    parts.empty.hidden = visible.length > 0;
    parts.pager.hidden = total <= PAGE_SIZE && this._offset === 0;
    parts.previous.disabled = this._offset === 0;
    parts.next.disabled = this._offset + items.length >= total;
    parts.range.textContent = items.length
      ? fill(ADMIN_TEXTS.range, {
          first: number(this._offset + 1),
          last: number(this._offset + items.length),
          total: number(total),
        })
      : "";
  }

  _report(item) {
    const id = String(item.id);
    const row = el("li", "nogat-admin-report");
    row.dataset.id = id;
    if (!item.is_read) row.classList.add("nogat-admin-unread");
    const head = el("p", "nogat-admin-report-head");
    head.id = `${this._id}-report-${counter++}`;
    const time = el("time", null, moment(item.created_at));
    time.dateTime = String(item.created_at ?? "");
    head.append(el("strong", "nogat-admin-report-id", `#${id}`), time);
    if (!item.is_read) {
      head.append(el("span", "nogat-admin-badge nogat-admin-info", ADMIN_TEXTS.fresh));
    }
    const message = el("p", "nogat-admin-message", String(item.message ?? ""));
    const actions = el("div", "nogat-admin-report-actions");
    const toggle = button(
      item.is_read ? ADMIN_TEXTS.markUnread : ADMIN_TEXTS.markRead,
      "nogat-admin-button nogat-admin-small",
    );
    toggle.addEventListener("click", () => this._setRead(item, !item.is_read, toggle));
    const remove = button(
      ADMIN_TEXTS.remove,
      "nogat-admin-button nogat-admin-small nogat-admin-danger",
    );
    remove.addEventListener("click", () => this._remove(item, remove));
    for (const control of [toggle, remove]) control.setAttribute("aria-describedby", head.id);
    actions.append(toggle, remove);
    row.append(head, message, this._context(item.context), actions);
    return row;
  }

  /** The context the GUI added to a report (DEV-15.12), folded. */
  _context(context) {
    if (!context || typeof context !== "object" || !Object.keys(context).length) {
      return el("p", "nogat-admin-note", ADMIN_TEXTS.noContext);
    }
    const labels = {
      view: ADMIN_TEXTS.view,
      station: ADMIN_TEXTS.station,
      app_version: ADMIN_TEXTS.appVersion,
      parameters: ADMIN_TEXTS.parameters,
    };
    const keys = [
      ...Object.keys(labels).filter((key) => key in context),
      ...Object.keys(context).filter((key) => !(key in labels)),
    ];
    const details = el("details", "nogat-admin-context");
    const list = el("dl");
    for (const key of keys) {
      const value = context[key];
      const cell = el("dd");
      if (isObject(value) || Array.isArray(value)) {
        cell.append(el("pre", "nogat-admin-json", JSON.stringify(value, null, 2)));
      } else {
        cell.textContent = shown(value);
      }
      list.append(el("dt", null, labels[key] ?? key), cell);
    }
    details.append(el("summary", null, ADMIN_TEXTS.context), list);
    return details;
  }

  _url(id) {
    return `${this.endpoint}/${encodeURIComponent(id)}`;
  }

  _index(id) {
    const rows = [...this._parts.list.children];
    return Math.max(0, rows.findIndex((row) => row.dataset.id === String(id)));
  }

  /** Focus the report `id`'s first button, else the one now at `index`, else the heading. */
  _focus(id, index) {
    const { list, heading } = this._parts;
    const rows = [...list.children];
    const same = rows.find((other) => other.dataset.id === String(id));
    const row = same ?? rows[Math.min(index, rows.length - 1)];
    (row?.querySelector("button") ?? heading).focus();
  }

  async _setRead(item, read, control) {
    const ticket = this._ticket;
    const index = this._index(item.id);
    control.disabled = true;
    let report;
    try {
      report = await this._call(this._url(item.id), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_read: read }),
      });
    } catch (error) {
      if (ticket !== this._ticket) return;
      control.disabled = false;
      this._show(error.message);
      return;
    }
    if (ticket !== this._ticket) return;
    const items = this._data.items;
    const at = items.findIndex((other) => String(other.id) === String(item.id));
    if (at >= 0) {
      const updated = isObject(report) && "is_read" in report ? report : { ...item, is_read: read };
      if (Boolean(items[at].is_read) !== Boolean(updated.is_read)) {
        this._data.unread += updated.is_read ? -1 : 1;
      }
      items[at] = updated;
    }
    this._show("");
    this._draw();
    this._focus(item.id, index);
  }

  async _remove(item, opener) {
    if (!(await this._confirm(item, opener))) return;
    const ticket = this._ticket;
    const index = this._index(item.id);
    let message = fill(ADMIN_TEXTS.removed, { id: item.id });
    try {
      await this._call(this._url(item.id), { method: "DELETE" });
    } catch (error) {
      if (ticket !== this._ticket) return;
      if (error.status !== 404) {
        this._show(error.message);
        return;
      }
      message = fill(ADMIN_TEXTS.gone, { id: item.id });
    }
    if (ticket !== this._ticket) return;
    if (await this.load()) {
      this._parts.note.textContent = message;
      this._focus(null, index);
    }
  }

  /** Ask before a report is deleted: true for „Usuń”, false for „Anuluj”, Esc or outside. */
  _confirm(item, opener) {
    const dialog = this.querySelector(".nogat-admin-dialog");
    dialog.querySelector("h2").textContent = fill(ADMIN_TEXTS.confirmTitle, { id: item.id });
    dialog.returnValue = "";
    this._opener = opener;
    dialog.showModal();
    dialog.querySelector(".nogat-admin-cancel").focus();
    return new Promise((resolve) => {
      this._settle = resolve;
    });
  }

  _dialog() {
    const dialog = el("dialog", "nogat-admin-dialog");
    dialog.setAttribute("aria-labelledby", `${this._id}-confirm`);
    dialog.setAttribute("aria-describedby", `${this._id}-confirm-text`);
    // A form of method "dialog" closes the dialog with the value of the button pressed.
    const form = el("form", "nogat-admin-dialog-body");
    form.method = "dialog";
    const title = el("h2");
    title.id = `${this._id}-confirm`;
    const text = el("p", null, ADMIN_TEXTS.confirmText);
    text.id = `${this._id}-confirm-text`;
    const cancel = el("button", "nogat-admin-button nogat-admin-cancel", ADMIN_TEXTS.cancel);
    cancel.value = "cancel";
    const confirm = el("button", "nogat-admin-button nogat-admin-danger", ADMIN_TEXTS.remove);
    confirm.value = "confirm";
    const actions = el("div", "nogat-admin-dialog-actions");
    actions.append(cancel, confirm);
    form.append(title, text, actions);
    dialog.append(form);
    dialog.addEventListener("keydown", trapTab);
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close("cancel");
    });
    dialog.addEventListener("close", () => {
      const confirmed = dialog.returnValue === "confirm";
      const settle = this._settle;
      this._settle = null;
      if (!confirmed && this._opener?.isConnected) this._opener.focus();
      settle?.(confirmed);
    });
    return dialog;
  }
}

/** The custom element `<nogat-admin-stats>`: the daily totals of DEV-15.11. */
export class NogatAdminStats extends AdminView {
  static route = "stats";
  static heading = ADMIN_TEXTS.stats;

  constructor() {
    super();
    this._reset();
  }

  /** Ask the period chosen again and redraw. */
  load() {
    const { from, to } = statsRange(this._days, new Date());
    const url = new URL(this.endpoint);
    url.searchParams.set("from", from);
    url.searchParams.set("to", to);
    return this._load(url.href, (doc) => {
      const days = objects(doc.days);
      const totals = isObject(doc.totals) ? doc.totals : {};
      this._data = { days, totals };
      this._draw();
    });
  }

  _reset() {
    this._days = 30;
    this._data = { days: [], totals: {} };
  }

  _build(parts) {
    const periods = el("div", "nogat-admin-periods");
    periods.setAttribute("role", "group");
    periods.setAttribute("aria-label", ADMIN_TEXTS.period);
    const choices = STATS_PERIODS.map(([days, label]) => {
      const choice = button(label);
      choice.setAttribute("aria-pressed", String(days === this._days));
      choice.addEventListener("click", () => {
        this._days = days;
        for (const other of choices) other.setAttribute("aria-pressed", String(other === choice));
        this.load();
      });
      return choice;
    });
    periods.append(...choices);
    const csv = button(ADMIN_TEXTS.csv);
    csv.disabled = true;
    csv.addEventListener("click", () => this._download());
    parts.tools.append(periods, csv);
    const scroll = el("div", "nogat-admin-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", ADMIN_TEXTS.table);
    scroll.hidden = true;
    const table = el("table", "nogat-admin-table");
    const caption = el("caption");
    const head = el("thead");
    const headings = el("tr");
    for (const [, label] of STATS_COLUMNS) {
      const cell = el("th", null, label);
      cell.scope = "col";
      headings.append(cell);
    }
    head.append(headings);
    const rows = el("tbody");
    const foot = el("tfoot");
    table.append(caption, head, rows, foot);
    scroll.append(table);
    const empty = el("p", "nogat-admin-empty", ADMIN_TEXTS.noDays);
    empty.hidden = true;
    parts.body.append(scroll, empty);
    Object.assign(parts, { csv, scroll, caption, rows, foot, empty });
  }

  _draw() {
    const parts = this._parts;
    const { days, totals } = this._data;
    parts.scroll.hidden = days.length === 0;
    parts.empty.hidden = days.length > 0;
    parts.csv.disabled = days.length === 0;
    parts.caption.textContent = days.length
      ? fill(ADMIN_TEXTS.caption, { first: shown(days[0].date), last: shown(days.at(-1).date) })
      : "";
    parts.rows.replaceChildren(
      ...days.map((day) => {
        const row = el("tr");
        const date = el("th", null, String(day.date ?? ""));
        date.scope = "row";
        const cells = STATS_COLUMNS.slice(1).map(([key]) => el("td", null, number(day[key])));
        row.append(date, ...cells);
        return row;
      }),
    );
    const sum = (key) => days.reduce((all, day) => all + (Number(day[key]) || 0), 0);
    const row = el("tr");
    const label = el("th", null, ADMIN_TEXTS.total);
    label.scope = "row";
    row.append(label);
    for (const [key] of STATS_COLUMNS.slice(1)) {
      const cell = el("td");
      if (key === "visitors") {
        // Distinct visitors are counted per day only, so the period has their daily sum.
        cell.append(el("span", "nogat-admin-sum", number(sum(key))));
        cell.append(el("span", "nogat-admin-note", ADMIN_TEXTS.visitorsTotal));
      } else {
        cell.textContent = number(key in totals ? totals[key] : sum(key));
      }
      row.append(cell);
    }
    parts.foot.replaceChildren(row);
  }

  /** Save the days shown as `<project>-stats-<first>-<last>.csv`, built in the browser. */
  _download() {
    const { days } = this._data;
    if (!days.length) return;
    const project =
      this.getAttribute("project") || this.closest("nogat-admin")?.getAttribute("project");
    const prefix = project ? `${project.toLowerCase()}-` : "";
    const name = `${prefix}stats-${shown(days[0].date)}-${shown(days.at(-1).date)}.csv`;
    const blob = new Blob([statsCsv(days)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = el("a");
    link.href = url;
    link.download = name;
    link.hidden = true;
    this.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

/** The custom element `<nogat-admin-status>`: the server and its checks (DEV-15.13). */
export class NogatAdminStatus extends AdminView {
  static route = "status";
  static heading = ADMIN_TEXTS.status;

  /** Ask the status again and redraw. */
  load() {
    return this._load(this.endpoint, (doc) => this._draw(doc));
  }

  _build(parts) {
    const facts = el("dl", "nogat-admin-facts");
    const title = el("h3", "nogat-admin-subheading", ADMIN_TEXTS.checks);
    const checks = el("ul", "nogat-admin-checks");
    parts.body.hidden = true;
    parts.body.append(facts, title, checks);
    Object.assign(parts, { facts, checks });
  }

  _draw(doc) {
    const parts = this._parts;
    const disk = isObject(doc.disk) ? doc.disk : {};
    const free = finite(disk.free_bytes);
    const total = finite(disk.total_bytes);
    const space =
      free !== null && total
        ? fill(ADMIN_TEXTS.diskValue, {
            free: size(free),
            total: size(total),
            percent: Math.round((free / total) * 100),
          })
        : null;
    const uptime = finite(doc.uptime_s);
    const facts = [
      [ADMIN_TEXTS.app, doc.app],
      [ADMIN_TEXTS.version, doc.version],
      [ADMIN_TEXTS.started, doc.started_at ? moment(doc.started_at) : null],
      [ADMIN_TEXTS.uptime, uptime === null ? null : duration(uptime)],
      [ADMIN_TEXTS.dataDir, doc.data_dir, "nogat-admin-path"],
      [ADMIN_TEXTS.disk, space],
    ];
    parts.facts.replaceChildren(
      ...facts.flatMap(([label, value, className]) => [
        el("dt", null, label),
        el("dd", className, shown(value)),
      ]),
    );
    const checks = objects(doc.checks);
    parts.checks.replaceChildren(
      ...checks.map((check) => {
        const status = String(check.status ?? "");
        const known = Object.hasOwn(CHECK_STATUS, status);
        const item = el("li", "nogat-admin-check");
        const badge = el("span", "nogat-admin-badge", known ? CHECK_STATUS[status] : status);
        badge.classList.add(known ? `nogat-admin-${status}` : "nogat-admin-neutral");
        item.append(badge, el("strong", "nogat-admin-check-name", String(check.name ?? "")));
        if (check.detail) item.append(el("span", "nogat-admin-check-detail", String(check.detail)));
        return item;
      }),
    );
    if (!checks.length) parts.checks.append(el("li", "nogat-admin-note", ADMIN_TEXTS.noChecks));
    parts.body.hidden = false;
  }
}

/** The custom element `<nogat-admin>`: the admin page of a GUI (DEV-15.13). */
export class NogatAdmin extends HTMLElement {
  static observedAttributes = ["app", "project", "back", "api", "marks", "auth"];

  constructor() {
    super();
    this._parts = null;
    this._sections = [];
    this._open = false;
    this._current = null;
    this._memory = "";
    this._started = false;
    this._id = `nogat-admin-${++counter}`;
    this._onHash = () => this._route();
    this._observer = new MutationObserver(() => this._adopt());
  }

  /** @returns {"key"|"session"} how the panel signs in */
  get auth() {
    return this.getAttribute("auth") === "session" ? "session" : "key";
  }

  /** @param {"key"|"session"} value "session" for an app with accounts and its cookie */
  set auth(value) {
    if (value === "session") this.setAttribute("auth", "session");
    else this.removeAttribute("auth");
  }

  /** @returns {string|null} the id of the section shown, null at the prompt */
  get section() {
    return this._open ? this._current : null;
  }

  /** @param {string} id the section to show, through the URL hash */
  set section(id) {
    window.location.hash = `#${encodeURIComponent(id)}`;
  }

  connectedCallback() {
    upgrade(this, "auth");
    if (!this._parts) this._build();
    this._adopt();
    this._observer.observe(this, { childList: true });
    window.addEventListener("hashchange", this._onHash);
    if (this._started) return;
    this._started = true;
    whenReady(() => this._start());
  }

  disconnectedCallback() {
    this._observer.disconnect();
    window.removeEventListener("hashchange", this._onHash);
  }

  attributeChangedCallback(name, old, value) {
    if (!this._parts || old === value) return;
    if (name === "auth") {
      if (this._started && ready) this._start();
    } else if (name === "api") {
      this._endpoints();
      if (this._open) this._route();
    } else {
      this._bar();
    }
  }

  /**
   * `fetch` for the app's own sections: `path` resolved against the admin API (`api`), the
   * key added as X-Admin-Key (none with auth="session"), `credentials: "same-origin"` and
   * `cache: "no-store"` unless `init` sets them. It resolves to the Response; a 401 returns
   * to the prompt (with auth="session" it fires `nogat-admin-unauthorized` instead).
   *
   * @param {string|URL} path the route below the admin API, or an address
   * @param {RequestInit} [init] what `fetch` takes
   * @returns {Promise<Response>} the answer
   */
  async adminFetch(path, init = {}) {
    const session = this.auth === "session";
    const key = session ? "" : this._key();
    const headers = new Headers(init.headers ?? {});
    if (key) headers.set("X-Admin-Key", key);
    const url = new URL(String(path), this._api()).href;
    const request = { credentials: "same-origin", cache: "no-store", ...init, headers };
    const response = await fetch(url, request);
    if (response.status === 401) {
      const reason = reasonOf(await documentOf(response.clone()));
      if (session) {
        const detail = { status: 401, reason };
        this.dispatchEvent(new CustomEvent("nogat-admin-unauthorized", { bubbles: true, detail }));
      } else if (this._open && key === this._key()) {
        // Only the key that was refused is forgotten, not one entered since the request left.
        this._leave(reason ?? "unauthorized", refusal(reason));
      }
    }
    return response;
  }

  /** What „Wyloguj” does: forget the key and show the prompt (not with auth="session"). */
  signOut() {
    if (this.auth === "session" || !this._open) return;
    this._leave("signout", "");
  }

  _api() {
    const base = new URL(this.getAttribute("api") || ADMIN_API, document.baseURI).href;
    return base.endsWith("/") ? base : `${base}/`;
  }

  _project() {
    return (this.getAttribute("project") || "nogat").toLowerCase();
  }

  _storage() {
    return `${this._project()}/admin-key/1`;
  }

  _key() {
    try {
      return window.sessionStorage.getItem(this._storage()) || this._memory;
    } catch {
      return this._memory;
    }
  }

  _keep(key) {
    try {
      window.sessionStorage.setItem(this._storage(), key);
      this._memory = "";
    } catch {
      this._memory = key; // storage blocked: the key lasts until the page closes
    }
  }

  _forget() {
    this._memory = "";
    try {
      window.sessionStorage.removeItem(this._storage());
    } catch {
      // storage blocked: nothing kept there
    }
  }

  _build() {
    const bar = el("header", "nogat-admin-bar");
    const mark = el("img", "nogat-admin-mark");
    mark.alt = "";
    mark.width = 24;
    mark.height = 24;
    mark.hidden = true;
    mark.addEventListener("error", () => {
      mark.hidden = true;
    });
    const title = el("h1", "nogat-admin-title");
    const actions = el("div", "nogat-admin-actions");
    const back = el("a", "nogat-admin-button nogat-admin-back");
    back.innerHTML = BACK_ICON;
    back.append(el("span", "nogat-admin-back-label", ADMIN_TEXTS.back));
    const signOut = button(ADMIN_TEXTS.signOut, "nogat-admin-button nogat-admin-signout");
    signOut.hidden = true;
    signOut.addEventListener("click", () => this.signOut());
    actions.append(back, signOut);
    bar.append(mark, title, actions);

    const layout = el("div", "nogat-admin-layout nogat-admin-signed-out");
    const nav = el("nav", "nogat-admin-nav");
    nav.setAttribute("aria-label", ADMIN_TEXTS.sections);
    nav.hidden = true;
    const list = el("ul");
    nav.append(list);
    const main = el("main", "nogat-admin-main");
    const prompt = this._prompt();
    main.append(prompt.form);
    const core = [
      ["feedback", ADMIN_TEXTS.feedback, "nogat-admin-feedback"],
      ["stats", ADMIN_TEXTS.stats, "nogat-admin-stats"],
      ["status", ADMIN_TEXTS.status, "nogat-admin-status"],
    ];
    for (const [id, label, tag] of core) {
      const section = el("section", "nogat-admin-section");
      section.dataset.adminSection = id;
      section.dataset.label = label;
      section.hidden = true;
      section.append(document.createElement(tag));
      main.append(section);
      this._sections.push({ id, label, element: section, core: true });
    }
    layout.append(nav, main);
    this.append(bar, layout);
    this._parts = { bar, mark, title, back, signOut, layout, nav, list, main, ...prompt };
    this._endpoints();
    this._bar();
    this._nav();
  }

  _prompt() {
    const form = el("form", "nogat-admin-prompt");
    form.noValidate = true;
    form.hidden = true;
    const id = `${this._id}-key`;
    const label = el("label", null, ADMIN_TEXTS.key);
    label.htmlFor = id;
    const input = el("input", "nogat-admin-input");
    input.id = id;
    input.type = "password";
    input.autocomplete = "off";
    input.spellcheck = false;
    const submit = el("button", "nogat-admin-button nogat-admin-primary", ADMIN_TEXTS.signIn);
    submit.type = "submit";
    const error = el("p", "nogat-admin-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    form.append(
      el("h2", null, ADMIN_TEXTS.promptTitle),
      el("p", "nogat-admin-note", ADMIN_TEXTS.promptText),
      label,
      input,
      submit,
      error,
    );
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      this._check();
    });
    return { form, input, submit, error };
  }

  /** Move each child section of the app into the panel, in document order. */
  _adopt() {
    if (!this._parts) return;
    const added = [];
    for (const child of [...this.children]) {
      if (!child.matches("section[data-admin-section]")) continue;
      const id = child.dataset.adminSection.trim();
      child.classList.add("nogat-admin-section");
      child.hidden = true;
      this._parts.main.append(child);
      if (id && !this._sections.some((section) => section.id === id)) {
        this._sections.push({ id, label: child.dataset.label || id, element: child, core: false });
        added.push(id);
      }
    }
    if (!added.length) return;
    this._nav();
    if (this._open && added.includes(this._hash())) this._route();
  }

  _endpoints() {
    for (const { id, element, core } of this._sections) {
      if (core) element.firstElementChild.setAttribute("endpoint", new URL(id, this._api()).href);
    }
  }

  _bar() {
    const { mark, title, back } = this._parts;
    const app = this.getAttribute("app");
    title.replaceChildren();
    if (app) title.append(el("span", "nogat-admin-app", app), " · ");
    title.append(ADMIN_TEXTS.admin);
    const marks = this.getAttribute("marks");
    mark.hidden = !marks;
    if (marks) mark.src = `${marks}${this._project()}.svg`;
    const href = web(this.getAttribute("back") ?? "../");
    back.hidden = !href;
    if (href) back.href = href;
  }

  _nav() {
    this._parts.list.replaceChildren(
      ...this._sections.map(({ id, label }) => {
        const item = el("li");
        const link = el("a", "nogat-admin-nav-link", label);
        link.href = `#${encodeURIComponent(id)}`;
        link.dataset.section = id;
        item.append(link);
        return item;
      }),
    );
    this._mark();
  }

  _mark() {
    for (const link of this._parts.list.querySelectorAll("a")) {
      const current = this._open && link.dataset.section === this._current;
      if (current) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
  }

  _hash() {
    try {
      return decodeURIComponent(window.location.hash.slice(1));
    } catch {
      return "";
    }
  }

  _start() {
    if (this.auth === "session" || this._key()) this._enter();
    else this._signedOut("");
  }

  _enter() {
    const { form, nav, layout, signOut } = this._parts;
    this._open = true;
    form.hidden = true;
    nav.hidden = false;
    signOut.hidden = this.auth === "session";
    layout.classList.remove("nogat-admin-signed-out");
    this._route();
  }

  /** The prompt, with `message` under it; nothing of the panel stays shown. */
  _signedOut(message) {
    const { form, input, error, nav, layout, signOut } = this._parts;
    this._open = false;
    this._current = null;
    for (const view of this.querySelectorAll(VIEWS)) view.clear();
    for (const { element } of this._sections) element.hidden = true;
    nav.hidden = true;
    signOut.hidden = true;
    layout.classList.add("nogat-admin-signed-out");
    this._mark();
    error.textContent = message;
    error.hidden = !message;
    form.hidden = false;
    input.value = "";
    input.focus();
  }

  _leave(reason, message) {
    this._forget();
    this._signedOut(message);
    const detail = { reason };
    this.dispatchEvent(new CustomEvent("nogat-admin-signout", { bubbles: true, detail }));
  }

  /** Check a key with GET feedback?limit=1 before it is kept. */
  async _check() {
    const { input, submit, error } = this._parts;
    const key = input.value.trim();
    let message = ADMIN_REASONS.admin_key_missing;
    if (key) {
      submit.disabled = true;
      submit.textContent = ADMIN_TEXTS.checking;
      try {
        const response = await fetch(new URL("feedback?limit=1", this._api()).href, {
          headers: { "X-Admin-Key": key },
          credentials: "same-origin",
          cache: "no-store",
        });
        if (response.ok) {
          this._keep(key);
          input.value = "";
          error.hidden = true;
          this._enter();
          this._parts.list.querySelector('[aria-current="page"]')?.focus();
          return;
        }
        const reason = reasonOf(await documentOf(response));
        const failed = fill(ADMIN_TEXTS.failed, { status: response.status });
        message = response.status === 401 ? refusal(reason) : failed;
      } catch {
        message = ADMIN_TEXTS.network;
      } finally {
        submit.disabled = false;
        submit.textContent = ADMIN_TEXTS.signIn;
      }
    }
    error.textContent = message;
    error.hidden = false;
    input.value = "";
    input.focus();
  }

  /** Show the section the hash names, else the first; load its views. */
  _route() {
    if (!this._open || !this._sections.length) return;
    const hash = this._hash();
    const shown = this._sections.find((section) => section.id === hash) ?? this._sections[0];
    this._current = shown.id;
    for (const { id, element } of this._sections) element.hidden = id !== shown.id;
    this._mark();
    for (const view of shown.element.querySelectorAll(VIEWS)) view.load();
    const detail = { id: shown.id };
    this.dispatchEvent(new CustomEvent("nogat-admin-section", { bubbles: true, detail }));
  }
}

for (const [name, element] of [
  ["nogat-admin-feedback", NogatAdminFeedback],
  ["nogat-admin-stats", NogatAdminStats],
  ["nogat-admin-status", NogatAdminStatus],
  ["nogat-admin", NogatAdmin],
]) {
  if (!customElements.get(name)) customElements.define(name, element);
}
