// Nogat GUI kit: the app menu (DEV-15.4, ECO-058).
// <nogat-app-menu current="hydrolog" marks="nogat/marks/"> in the top bar, left of the
// theme switch. Its `apps` property (or an `apps` attribute holding JSON) is the
// deployment's `[nogat.gui]` table of `nogat.toml`: registry name in lower case -> address.
// The menu lists every GUI of that table, the current one marked and not a link; with no
// other GUI it is not drawn. An entry opens its GUI in the tab named "nogat-<name>".
// No shadow DOM: the page's stylesheet nogat-app-menu.css styles it with the tokens.
// Copy this file byte for byte (DEV-15.6); change it in Nogat design/kit/.

/** What each GUI is, in Polish (DEV-15.2). */
export const GUIS = {
  archiwista: { title: "Archiwista", text: "Magazyny danych: mapa, katalog, stacje" },
  hydrograf: { title: "Hydrograf", text: "Zlewnie i hydrogramy na mapie" },
  hydrolog: { title: "Hydrolog", text: "Obliczenia hydrologiczne" },
  obserwator: { title: "Obserwator", text: "Dane IMGW-PIB i ČHMÚ, PMAXTP" },
};

/** The menu's own texts, in Polish. */
export const MENU_TEXTS = {
  button: "Aplikacje",
  title: "Inne aplikacje ekosystemu",
  list: "Aplikacje ekosystemu",
  current: "Ta aplikacja",
};

const GRID_ICON =
  '<svg class="nogat-app-menu-icon" viewBox="0 0 20 20" aria-hidden="true">' +
  '<rect x="3" y="3" width="5" height="5" rx="1"/><rect x="12" y="3" width="5" height="5" rx="1"/>' +
  '<rect x="3" y="12" width="5" height="5" rx="1"/><rect x="12" y="12" width="5" height="5" rx="1"/></svg>';

let counter = 0;

/**
 * The deployment's table as [name, address] pairs: names in lower case, addresses
 * resolved against the page (a path such as "/hydrolog/" is allowed) and kept only when
 * they are http or https, in the table's order.
 *
 * @param {object|null|undefined} apps the `[nogat.gui]` table
 * @returns {Array<[string, string]>} the usable entries
 */
export function entries(apps) {
  const out = [];
  for (const [key, address] of Object.entries(apps ?? {})) {
    const name = String(key).toLowerCase();
    let url;
    try {
      url = new URL(String(address), globalThis.location?.href);
    } catch {
      continue;
    }
    if (url.protocol === "http:" || url.protocol === "https:") out.push([name, url.href]);
  }
  return out;
}

/** The custom element `<nogat-app-menu>`. */
export class NogatAppMenu extends HTMLElement {
  static observedAttributes = ["apps", "current", "marks"];

  constructor() {
    super();
    this._apps = null;
    this._id = `nogat-app-menu-${++counter}`;
    this._onDocument = (event) => {
      if (!this.contains(event.target)) this.close();
    };
    this.addEventListener("focusout", (event) => {
      if (event.relatedTarget && !this.contains(event.relatedTarget)) this.close();
    });
    this._onKey = (event) => {
      if (event.key === "Escape" && this.isOpen) {
        event.preventDefault();
        this.close();
        this.querySelector("button")?.focus();
      }
    };
  }

  /** @returns {object|null} the `[nogat.gui]` table */
  get apps() {
    if (this._apps) return this._apps;
    const attribute = this.getAttribute("apps");
    if (!attribute) return null;
    try {
      return JSON.parse(attribute);
    } catch {
      return null;
    }
  }

  /** @param {object|null} value the `[nogat.gui]` table */
  set apps(value) {
    this._apps = value;
    this.render();
  }

  /** @returns {boolean} whether the list is shown */
  get isOpen() {
    return this.querySelector("button")?.getAttribute("aria-expanded") === "true";
  }

  connectedCallback() {
    this.render();
    document.addEventListener("pointerdown", this._onDocument);
    document.addEventListener("keydown", this._onKey);
  }

  disconnectedCallback() {
    document.removeEventListener("pointerdown", this._onDocument);
    document.removeEventListener("keydown", this._onKey);
  }

  attributeChangedCallback() {
    if (this.isConnected) this.render();
  }

  /** Show the list. */
  open() {
    const button = this.querySelector("button");
    if (!button) return;
    button.setAttribute("aria-expanded", "true");
    this.querySelector(".nogat-app-menu-list").hidden = false;
  }

  /** Hide the list. */
  close() {
    const button = this.querySelector("button");
    if (!button) return;
    button.setAttribute("aria-expanded", "false");
    this.querySelector(".nogat-app-menu-list").hidden = true;
  }

  /** Draw the button and the list from the attributes and `apps`. */
  render() {
    const current = (this.getAttribute("current") || "").toLowerCase();
    const marks = this.getAttribute("marks") ?? "nogat/marks/";
    let list = entries(this.apps);
    if (current && !list.some(([name]) => name === current)) list = [[current, null], ...list];
    this.replaceChildren();
    this.hidden = !list.some(([name]) => name !== current);
    if (this.hidden) return;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "nogat-app-menu-button";
    button.title = MENU_TEXTS.title;
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", this._id);
    button.innerHTML = GRID_ICON;
    const label = document.createElement("span");
    label.className = "nogat-app-menu-label";
    label.textContent = MENU_TEXTS.button;
    button.append(label);
    button.addEventListener("click", () => (this.isOpen ? this.close() : this.open()));

    const panel = document.createElement("div");
    panel.className = "nogat-app-menu-list";
    panel.id = this._id;
    panel.hidden = true;
    const items = document.createElement("ul");
    items.setAttribute("aria-label", MENU_TEXTS.list);
    for (const [name, url] of list) items.append(this._item(name, url, name === current, marks));
    panel.append(items);
    panel.addEventListener("click", (event) => {
      if (event.target.closest("a")) this.close();
    });
    this.append(button, panel);
  }

  _item(name, url, isCurrent, marks) {
    const gui = GUIS[name] ?? { title: name.charAt(0).toUpperCase() + name.slice(1), text: "" };
    const li = document.createElement("li");
    const entry = document.createElement(isCurrent ? "div" : "a");
    entry.className = "nogat-app-menu-item";
    if (isCurrent) {
      entry.classList.add("current");
      entry.setAttribute("aria-current", "page");
    } else {
      entry.href = url;
      entry.target = `nogat-${name}`;
    }
    const mark = document.createElement("img");
    mark.src = `${marks}${name}.svg`;
    mark.alt = "";
    mark.width = 24;
    mark.height = 24;
    mark.addEventListener("error", () => (mark.style.visibility = "hidden"));
    const words = document.createElement("span");
    words.className = "nogat-app-menu-words";
    const title = document.createElement("strong");
    title.textContent = gui.title;
    const text = document.createElement("small");
    text.textContent = isCurrent ? MENU_TEXTS.current : gui.text;
    words.append(title, text);
    entry.append(mark, words);
    li.append(entry);
    return li;
  }
}

if (!customElements.get("nogat-app-menu")) customElements.define("nogat-app-menu", NogatAppMenu);
