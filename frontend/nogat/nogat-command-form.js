// Nogat GUI kit: the command builder (DEV-15.17, ECO-093), the form of one catalog command
// generated from its commands-1 entry (AGI-2.2, AGI-2.3), so that a new option of a command
// appears in every GUI without GUI work. <nogat-command-form> shows:
// - a field per option, by its type: a number with its unit, a choice among `enum` (radios up
//   to four values, a select above, the meaning of the value shown under it), a checkbox, a
//   text (a date where `format` says so), a list of numbers or of texts (checkboxes for a few
//   allowed values), a JSON value, a path typed as text; grouped by `section`, the optional
//   options without a default under „Opcje dodatkowe”; the texts of `i18n.pl` where the
//   catalog has them, else its English ones;
// - a choice per `one_of`: the command's `one_of`, alternatives of which exactly one is given,
//   and each mutual exclusion group of its options, of which at most one is given („—” none);
// - the rules of the options: `applies_to` shows a field only where it applies, `excludes`
//   disables the options a given one refuses, `requires` and `required_when` mark the options
//   a call needs;
// - paths="hidden" leaves out every path option (`path_role`), where the app owns the paths,
//   and `hide` the options the app supplies itself: neither is shown, checked or sent;
// - the line: given `format`, the GUI's binding of the tool's `format_command` (a route of its
//   server or its own code), the command line of the form with „Kopiuj”, written again after
//   each change; given `parse`, the binding of `parse_command`, „Wklej polecenie” reads a line
//   into the form;
// - the messages: `check()` checks the values against the catalog and shows each message under
//   its field; `errors`, or `showError(doc)` with an error document of the tool, places a
//   message under the field `details.option` names, else above the form.
// `options` is the call: the values in the catalog's types, of the active fields only, nothing
// for an empty field, so the tool's defaults apply. `change` ({detail: {options, valid}}) tells
// of a person's edit; the controls' own events stay inside.
// No shadow DOM: the page's stylesheet nogat-command-form.css styles the element.
// Copy this file byte for byte (DEV-15.6); change it in Nogat design/kit/.

/** The element's words, in Polish; a GUI in another language passes its own as `texts`. */
export const COMMAND_FORM_TEXTS = {
  required: "wymagane",
  defaultIs: "domyślnie {value}",
  excludedBy: "nie razem z {name}",
  more: "Opcje dodatkowe",
  choice: "Sposób podania",
  exactlyOne: "jedna z {count}",
  atMostOne: "najwyżej jedna z {count}",
  none: "—",
  noneTitle: "bez wartości: domyślne zachowanie polecenia",
  yes: "tak",
  no: "nie",
  example: "np. {value}",
  rules: "Zasady",
  pathInput: "ścieżka do odczytu",
  pathOutput: "ścieżka zapisu",
  pathRoot: "katalog magazynu",
  numbersHint: "Wartości oddziel spacją albo średnikiem.",
  textsHint: "Wartości oddziel przecinkiem.",
  aboveForm: "Popraw polecenie",
  missing: "Podaj wartość: opcja wymagana",
  notNumber: "Podaj liczbę",
  notInteger: "Podaj liczbę całkowitą",
  notNumberItem: "Wartość {index} („{text}”) nie jest liczbą",
  minimum: "Najmniej {limit} (podano {value})",
  maximum: "Najwyżej {limit} (podano {value})",
  exclusiveMinimum: "Musi być większa od {limit} (podano {value})",
  exclusiveMaximum: "Musi być mniejsza od {limit} (podano {value})",
  notAllowed: "Dozwolone wartości: {allowed}",
  pattern: "Nie pasuje do wzorca {pattern}",
  date: "Podaj datę w formacie RRRR-MM-DD",
  dateTime: "Podaj datę i godzinę w formacie RRRR-MM-DDTgg:mm",
  json: "Nieprawidłowy JSON: {message}",
  jsonObject: "Podaj obiekt JSON: {…}",
  jsonList: "Podaj listę JSON: [ … ]",
  requires: "Podaj też: {names}",
  excludes: "Nie łącz z: {names}",
  line: "Polecenie",
  incomplete: "Uzupełnij albo popraw: {names}",
  lineFailed: "Nie udało się zapisać polecenia: {message}",
  copy: "Kopiuj",
  copied: "Skopiowano do schowka",
  copyFailed: "Nie udało się skopiować: zaznacz polecenie i skopiuj je ręcznie",
  paste: "Wklej polecenie",
  read: "Wczytaj",
  pasteFailed: "Nie udało się odczytać polecenia: {message}",
  otherCommand: "To polecenie {command}, nie {current}",
};

/** The key of a message that belongs to no field: it stands above the form. */
export const FORM_ERROR = "#form";

/** Choices shown as radios up to this many values; a select above. */
const RADIOS_MAX = 4;
/** A list of allowed values shown as checkboxes up to this many; a text above. */
const CHECKBOXES_MAX = 8;
/** Milliseconds between the last change and the line asked of `format`. */
const LINE_DELAY = 150;
/** The type names `items` may give. */
const ITEM_TYPES = new Set(["string", "integer", "number", "boolean", "object"]);
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DATE_TIME =
  /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(:(\d{2})(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;
/** Placeholders of the string formats a field checks. */
const FORMAT_HINTS = { date: "RRRR-MM-DD", "date-time": "RRRR-MM-DDTgg:mm" };
let counter = 0;

/** Fill the `{name}` placeholders of a text; one without a value stays. */
function fill(text, values = {}) {
  return String(text).replace(/\{(\w+)\}/g, (whole, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : whole,
  );
}

/** A message and its machine reason, as the error documents' `details.reason`. */
function message(text, reason = null) {
  return { text: String(text), reason };
}

/**
 * Read a typed number: a decimal comma or dot, spaces between thousands and the minus sign
 * U+2212 allowed.
 *
 * @param {string|number|null|undefined} text the typed text or a number
 * @returns {number|null} the number, null for an empty text, NaN for a text that is none
 */
export function parseNumber(text) {
  if (typeof text === "number") return Number.isFinite(text) ? text : Number.NaN;
  if (text === null || text === undefined) return null;
  const compact = String(text)
    .replace(/[\s\u00a0\u202f]/g, "")
    .replace(/\u2212/g, "-")
    .replace(",", ".");
  if (compact === "") return null;
  if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(compact)) return Number.NaN;
  return Number(compact);
}

/** A number as a field shows it: its shortest exact form with a decimal comma. */
function numberText(value) {
  return typeof value === "number" && Number.isFinite(value) ? String(value).replace(".", ",") : "";
}

/**
 * The values of a list of numbers as typed: semicolons, tabs, new lines and spaces separate
 * them; a comma is a decimal comma, unless the text has a decimal dot, when commas separate
 * values too ("16.5,51.0").
 *
 * @param {string} text the list as typed
 * @returns {{values: number[], bad: {index: number, text: string}|null}} the numbers, and the
 *   first value that is not a number
 */
export function parseNumbers(text) {
  const source = String(text ?? "").trim();
  const tokens = source ? source.split(source.includes(".") ? /[\s;,]+/ : /[\s;]+/) : [];
  const values = [];
  for (const [index, token] of tokens.filter(Boolean).entries()) {
    const value = parseNumber(token);
    if (value === null || Number.isNaN(value)) return { values, bad: { index, text: token } };
    values.push(value);
  }
  return { values, bad: null };
}

/** The values of a list of texts as typed: commas, semicolons and new lines separate them. */
function textTokens(text) {
  return String(text ?? "")
    .split(/[,;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/** Whether a text is a day of the calendar, RRRR-MM-DD. */
function isDate(text) {
  const found = DATE.exec(text);
  if (!found) return false;
  const [year, month, day] = found.slice(1).map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  );
}

/** Whether a text is a day and a time, seconds and a zone optional. */
function isDateTime(text) {
  const found = DATE_TIME.exec(text);
  if (!found || !isDate(found[1])) return false;
  const seconds = found[5] === undefined || Number(found[5]) < 60;
  return Number(found[2]) < 24 && Number(found[3]) < 60 && seconds;
}

/** Two catalog values alike: equal, or equal as text (a choice's 1 and "1"). */
function same(one, other) {
  return one === other || String(one) === String(other);
}

/** A value as the form shows it beside a label: „domyślnie 4”, „domyślnie tak”. */
function shownValue(value, texts) {
  if (typeof value === "number") return numberText(value);
  if (typeof value === "boolean") return value ? texts.yes : texts.no;
  if (Array.isArray(value)) return value.map((item) => shownValue(item, texts)).join("; ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * The entry of one command: the first command of a `<tool>-commands/1` document, or the entry.
 *
 * @param {object} doc the document or the entry
 * @returns {object|null} the entry (name, options, one_of, i18n…), null for neither
 */
export function commandEntry(doc) {
  const entry = doc && Array.isArray(doc.commands) ? doc.commands[0] : doc;
  return entry && typeof entry.name === "string" && Array.isArray(entry.options) ? entry : null;
}

/** The type of an array's items: `items` as a type name or as a JSON Schema of the items. */
function itemType(option) {
  const items = option.items;
  if (typeof items === "string") return ITEM_TYPES.has(items) ? items : "string";
  if (items && typeof items === "object") {
    if (typeof items.type === "string") return items.type;
    if (Array.isArray(items.enum) && items.enum.length) {
      return typeof items.enum[0] === "number" ? "number" : "string";
    }
  }
  return "string";
}

/** The allowed values of an option, or of an array's items, each with its meaning. */
function choicesOf(option) {
  const polish = option.i18n?.pl?.enum;
  const meanings = polish && typeof polish === "object" ? polish : {};
  const listed = Array.isArray(option.enum)
    ? option.enum.filter((item) => item && typeof item === "object" && "value" in item)
    : [];
  const items = option.type === "array" && !listed.length && Array.isArray(option.items?.enum);
  const raw = items ? option.items.enum.map((value) => ({ value, meaning: "" })) : listed;
  return raw.map((item) => {
    const key = String(item.value);
    const meaning = Object.hasOwn(meanings, key) ? meanings[key] : item.meaning;
    return { value: item.value, meaning: typeof meaning === "string" ? meaning : "" };
  });
}

/**
 * The control of an option: number | integer | choice | boolean | numbers | multi | texts |
 * json | path | text.
 */
function kindOf(option, choices) {
  if (option.path_role) return "path";
  switch (option.type) {
    case "boolean":
      return "boolean";
    case "object":
      return "json";
    case "array": {
      if (choices.length) return choices.length <= CHECKBOXES_MAX ? "multi" : "texts";
      const type = itemType(option);
      if (type === "number" || type === "integer") return "numbers";
      return type === "string" ? "texts" : "json";
    }
    case "number":
    case "integer":
      return choices.length ? "choice" : option.type;
    default:
      return choices.length ? "choice" : "text";
  }
}

/** A JavaScript pattern from the catalog's, or null where the browser cannot read it. */
function patternOf(text) {
  if (typeof text !== "string" || !text) return null;
  try {
    return new RegExp(text);
  } catch {
    return null;
  }
}

/** A condition of `applies_to` or `required_when`: option → true or the values it may have. */
function conditionOf(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const entries = Object.entries(value).filter(
    ([, want]) => want === true || (Array.isArray(want) && want.length),
  );
  return entries.length ? Object.fromEntries(entries) : null;
}

/** The names of a list of option names in the catalog, the others left out. */
function namesOf(value) {
  return Array.isArray(value) ? value.filter((name) => typeof name === "string") : [];
}

/** One field of the form: what the element reads of an option. */
function fieldOf(option, labels) {
  const polish = option.i18n?.pl ?? {};
  const choices = choicesOf(option);
  const hasDefault = Object.hasOwn(option, "default") && option.default !== null;
  const bound = (key) => (typeof option[key] === "number" ? option[key] : null);
  // A list's pattern holds for each of its values: the option's, or that of its items.
  const pattern = option.pattern ?? option.items?.pattern;
  return {
    name: option.name,
    kind: kindOf(option, choices),
    items: option.type === "array" ? itemType(option) : null,
    label: typeof labels[option.name] === "string" ? labels[option.name] : null,
    description: String(polish.description || option.description || ""),
    unit: typeof option.unit === "string" && option.unit ? option.unit : null,
    required: option.required === true,
    hasDefault,
    default: hasDefault ? option.default : null,
    min: bound("min"),
    max: bound("max"),
    exclusiveMin: bound("exclusive_minimum"),
    exclusiveMax: bound("exclusive_maximum"),
    pattern: patternOf(pattern),
    patternText: typeof pattern === "string" ? pattern : "",
    format: typeof option.format === "string" ? option.format : null,
    choices,
    pathRole: option.path_role || null,
    examples: Array.isArray(option.examples) ? option.examples : [],
    section: typeof option.section === "string" && option.section ? option.section : null,
    sectionTitle: String(polish.section || option.section || ""),
    oneOf: typeof option.one_of === "string" && option.one_of ? option.one_of : null,
    requires: namesOf(option.requires),
    excludes: namesOf(option.excludes),
    appliesTo: conditionOf(option.applies_to),
    requiredWhen: conditionOf(option.required_when),
    group: null,
    alternatives: [],
    attached: false,
  };
}

/**
 * The choices of a command: its `one_of`, alternatives of which exactly one is given, and each
 * mutual exclusion group of its options not in them, of which at most one is given. Only
 * shown options count; a choice left with one alternative is no choice: the options of the
 * command's become required, a group's stay as they are.
 */
function choiceGroups(entry, fields, byName, labels, texts) {
  const groups = [];
  const join = (index, names, alternatives) => {
    for (const name of names) {
      const field = byName.get(name);
      field.group = index;
      field.alternatives = alternatives(name);
    }
  };
  const declared = (Array.isArray(entry.one_of) ? entry.one_of : [])
    .map((names) => namesOf(names).filter((name) => byName.has(name)))
    .filter((names) => names.length);
  if (declared.length === 1) {
    for (const name of declared[0]) byName.get(name).required = true;
  } else if (declared.length > 1) {
    const index = groups.length;
    groups.push({
      id: "one_of",
      key: "#one_of",
      required: true,
      legend: labels["#one_of"] ?? texts.choice,
      code: false,
      alternatives: declared.map((names) => ({ names, attached: [] })),
    });
    const members = [...new Set(declared.flat())];
    join(index, members, (name) =>
      declared.flatMap((names, alternative) => (names.includes(name) ? [alternative] : [])),
    );
  }
  const byGroup = new Map();
  for (const field of fields) {
    if (!field.oneOf || field.group !== null) continue;
    if (!byGroup.has(field.oneOf)) byGroup.set(field.oneOf, []);
    byGroup.get(field.oneOf).push(field.name);
  }
  for (const [id, names] of byGroup) {
    if (names.length < 2) continue;
    const index = groups.length;
    groups.push({
      id,
      key: `#${id}`,
      required: false,
      legend: labels[`#${id}`] ?? id,
      code: !Object.hasOwn(labels, `#${id}`),
      alternatives: names.map((name) => ({ names: [name], attached: [] })),
    });
    join(index, names, (name) => [names.indexOf(name)]);
  }
  // A field that applies only with the options of one alternative stands in its pane.
  for (const field of fields) {
    if (field.group !== null || !field.appliesTo) continue;
    const wants = Object.entries(field.appliesTo);
    if (!wants.every(([, want]) => want === true)) continue;
    const members = wants.map(([name]) => byName.get(name));
    if (members.some((member) => !member || member.group === null)) continue;
    const group = members[0].group;
    if (members.some((member) => member.group !== group)) continue;
    const common = members
      .map((member) => member.alternatives)
      .reduce((one, other) => one.filter((index) => other.includes(index)));
    if (common.length !== 1) continue;
    field.group = group;
    field.alternatives = common;
    field.attached = true;
    groups[group].alternatives[common[0]].attached.push(field.name);
  }
  return groups;
}

/**
 * The form of one command: its fields and choices, placed in its sections.
 *
 * @param {object} command a `<tool>-commands/1` document of one command, or its entry
 * @param {{hide?: string[], paths?: string, labels?: Object<string, string>, texts?: object}}
 *   [settings] the options the GUI supplies itself; "hidden" to leave out every path option;
 *   Polish labels by option name (and by "#<group>" for a choice); the words
 * @returns {{command: object, fields: object[], byName: Map<string, object>,
 *   groups: object[], sections: object[], left: string[]}} the entry, the fields in catalog
 *   order, the choices, the sections (`main`, the catalog's in order, `more`) each listing
 *   `{field}` and `{group}` items, and the options left out
 */
export function formModel(command, settings = {}) {
  const entry = commandEntry(command);
  if (!entry) throw new TypeError("nogat-command-form: not a commands-1 entry");
  const hide = new Set(namesOf(settings.hide));
  const labels = settings.labels && typeof settings.labels === "object" ? settings.labels : {};
  const texts = { ...COMMAND_FORM_TEXTS, ...settings.texts };
  const fields = [];
  const left = [];
  for (const option of entry.options) {
    if (!option || typeof option.name !== "string") continue;
    const hidden = hide.has(option.name) || (settings.paths === "hidden" && option.path_role);
    if (hidden) left.push(option.name);
    else fields.push(fieldOf(option, labels));
  }
  const byName = new Map(fields.map((field) => [field.name, field]));
  const groups = choiceGroups(entry, fields, byName, labels, texts);
  const main = { id: "main", title: null, items: [] };
  const more = { id: "more", title: texts.more, items: [] };
  const named = new Map();
  const sectionOf = (field) => {
    if (!field.section) return null;
    if (!named.has(field.section)) {
      named.set(field.section, { id: field.section, title: field.sectionTitle, items: [] });
    }
    return named.get(field.section);
  };
  const placed = new Set();
  for (const field of fields) {
    if (field.group !== null) {
      if (field.attached || placed.has(field.group)) continue;
      placed.add(field.group);
      (sectionOf(field) ?? main).items.push({ group: field.group });
      continue;
    }
    const section = sectionOf(field);
    const first =
      field.required ||
      field.hasDefault ||
      field.requiredWhen !== null ||
      field.kind === "boolean" ||
      field.kind === "path";
    (section ?? (first ? main : more)).items.push({ field: field.name });
  }
  const sections = [main, ...named.values(), more].filter((section) => section.items.length);
  return { command: entry, fields, byName, groups, sections, left };
}

/** Whether a form value counts as given. */
function isGiven(field, value) {
  if (field.kind === "boolean") return typeof value === "boolean";
  if (field.kind === "multi") return Array.isArray(value) && value.length > 0;
  if (field.kind === "choice") return value !== undefined && value !== null && value !== "";
  return value !== undefined && value !== null && String(value).trim() !== "";
}

/** Whether a value is set for the rules: given, and a boolean other than its default. */
function isSet(field, value) {
  if (!isGiven(field, value)) return false;
  return field.kind !== "boolean" || value !== Boolean(field.default);
}

/** A field's value in the catalog's type, its default where none is given. */
function currentValue(field, value) {
  if (!isGiven(field, value)) return field.hasDefault ? field.default : undefined;
  if (field.kind === "number" || field.kind === "integer") return parseNumber(value);
  if (typeof value === "string") return value.trim();
  return value;
}

/** The given members of each alternative of a choice: the most, the first of equals. */
function bestAlternative(model, group, given) {
  let best = -1;
  let most = 0;
  group.alternatives.forEach((alternative, index) => {
    const count = alternative.names.filter((name) => given(model.byName.get(name), name)).length;
    if (count > most) {
      best = index;
      most = count;
    }
  });
  return best;
}

/** The alternative chosen in each choice: the person's, else the one given, else the first. */
function chosenAlternatives(model, values) {
  return model.groups.map((group) => {
    const picked = values[group.key];
    const count = group.alternatives.length;
    if (Number.isInteger(picked) && picked >= (group.required ? 0 : -1) && picked < count) {
      return picked;
    }
    const given = (field, name) =>
      field.kind === "boolean" ? values[name] === true : isGiven(field, values[name]);
    const found = bestAlternative(model, group, given);
    return found >= 0 ? found : group.required ? 0 : -1;
  });
}

/**
 * The state of each field for the values: whether it is active (shown and sent), shown,
 * required now, and the option that disables it.
 *
 * @param {object} model the result of formModel
 * @param {object} values the form's values
 * @returns {{choices: number[], state: Map<string, {active: boolean, shown: boolean,
 *   required: boolean, disabledBy: string|null}>}} the alternative chosen in each choice (-1
 *   none) and the state by option name
 */
export function formState(model, values) {
  const choices = chosenAlternatives(model, values);
  const state = new Map();
  for (const field of model.fields) {
    const active = field.group === null || field.alternatives.includes(choices[field.group]);
    state.set(field.name, { active, shown: active, required: false, disabledBy: null });
  }
  const holds = (condition) =>
    Object.entries(condition).every(([name, want]) => {
      const field = model.byName.get(name);
      if (!field) return true;
      if (!state.get(name).active) return false;
      if (want === true) {
        const chosen = field.group !== null && field.kind === "boolean" && !field.attached;
        return chosen || isSet(field, values[name]);
      }
      const current = currentValue(field, values[name]);
      return current !== undefined && want.some((item) => same(item, current));
    });
  for (let changed = true; changed; ) {
    changed = false;
    for (const field of model.fields) {
      const own = state.get(field.name);
      if (!own.active || field.attached || !field.appliesTo || holds(field.appliesTo)) continue;
      own.active = false;
      own.shown = false;
      changed = true;
    }
  }
  for (const field of model.fields) {
    if (!state.get(field.name).active || !isSet(field, values[field.name])) continue;
    for (const name of field.excludes) {
      const other = model.byName.get(name);
      const its = state.get(name);
      if (!other || !its.active || isSet(other, values[name])) continue;
      its.active = false;
      its.disabledBy = field.name;
    }
  }
  for (const field of model.fields) {
    const own = state.get(field.name);
    if (!own.active) continue;
    const member = field.group !== null && !field.attached;
    own.required =
      field.required ||
      (member && (model.groups[field.group].required || choices[field.group] >= 0)) ||
      (field.requiredWhen !== null && holds(field.requiredWhen));
  }
  for (const field of model.fields) {
    if (!state.get(field.name).active || !isSet(field, values[field.name])) continue;
    for (const name of field.requires) {
      const other = state.get(name);
      if (other?.active) other.required = true;
    }
  }
  return { choices, state };
}

/** The message of a number outside the field's bounds, or null. */
function boundMessage(field, value, texts, index = null) {
  const at = (text) => (index === null ? text : `${index + 1}: ${text}`);
  const shown = numberText(value);
  const broken = [
    [field.exclusiveMin, (limit) => !(value > limit), texts.exclusiveMinimum, "exclusive_minimum"],
    [field.min, (limit) => value < limit, texts.minimum, "minimum"],
    [field.max, (limit) => value > limit, texts.maximum, "maximum"],
    [field.exclusiveMax, (limit) => !(value < limit), texts.exclusiveMaximum, "exclusive_maximum"],
  ].find(([limit, breaks]) => limit !== null && breaks(limit));
  if (!broken) return null;
  const [limit, , text, reason] = broken;
  return message(at(fill(text, { limit: numberText(limit), value: shown })), reason);
}

/** The allowed values of a field, as a message lists them. */
function allowedText(field) {
  return field.choices.map((choice) => String(choice.value)).join(", ");
}

/** The message of one field's value, or null when it is right. */
function fieldMessage(field, value, required, texts) {
  if (!isGiven(field, value)) {
    return required && field.kind !== "boolean" ? message(texts.missing, "required") : null;
  }
  switch (field.kind) {
    case "number":
    case "integer": {
      const number = parseNumber(value);
      if (Number.isNaN(number)) {
        return message(field.kind === "integer" ? texts.notInteger : texts.notNumber, "type");
      }
      if (field.kind === "integer" && !Number.isInteger(number)) {
        return message(texts.notInteger, "type");
      }
      return boundMessage(field, number, texts);
    }
    case "numbers": {
      const { values, bad } = parseNumbers(value);
      if (bad) return message(fill(texts.notNumberItem, { ...bad, index: bad.index + 1 }), "type");
      for (const [index, number] of values.entries()) {
        if (field.items === "integer" && !Number.isInteger(number)) {
          return message(`${index + 1}: ${texts.notInteger}`, "type");
        }
        const problem = boundMessage(field, number, texts, index);
        if (problem) return problem;
      }
      return null;
    }
    case "choice":
      return field.choices.some((choice) => same(choice.value, value))
        ? null
        : message(fill(texts.notAllowed, { allowed: allowedText(field) }), "choice");
    case "multi":
    case "texts": {
      const list = field.kind === "multi" ? value : textTokens(value);
      const strange =
        field.choices.length &&
        list.some((item) => !field.choices.some((choice) => same(choice.value, item)));
      const allowed = { allowed: allowedText(field) };
      if (strange) return message(fill(texts.notAllowed, allowed), "choice");
      const bad = field.pattern ? list.find((item) => !field.pattern.test(String(item))) : null;
      if (bad === undefined || bad === null) return null;
      const pattern = fill(texts.pattern, { pattern: field.patternText });
      return message(`„${bad}”: ${pattern}`, "pattern");
    }
    case "json": {
      let parsed;
      try {
        parsed = JSON.parse(value);
      } catch (error) {
        return message(fill(texts.json, { message: error.message }), "type");
      }
      const list = field.items !== null;
      if (list !== Array.isArray(parsed) || parsed === null || typeof parsed !== "object") {
        return message(list ? texts.jsonList : texts.jsonObject, "type");
      }
      return null;
    }
    default: {
      const text = String(value).trim();
      if (field.format === "date" && !isDate(text)) return message(texts.date, "format");
      if (field.format === "date-time" && !isDateTime(text)) {
        return message(texts.dateTime, "format");
      }
      if (field.pattern && !field.pattern.test(text)) {
        return message(fill(texts.pattern, { pattern: field.patternText }), "pattern");
      }
      return null;
    }
  }
}

/**
 * Check a form's values against the catalog: the required options (the members of each chosen
 * alternative among them), types, bounds, allowed values, `pattern`, `format`, JSON, and the
 * rules `requires`, `excludes` and the mutual exclusion of a group's options.
 *
 * @param {object} model the result of formModel
 * @param {object} values the form's values
 * @param {object} [texts] the words, COMMAND_FORM_TEXTS by default
 * @returns {Object<string, {text: string, reason: string|null}>} a message by option name;
 *   empty when the form is right
 */
export function checkValues(model, values, texts = COMMAND_FORM_TEXTS) {
  const words = { ...COMMAND_FORM_TEXTS, ...texts };
  const { state } = formState(model, values);
  const given = (name) => {
    const other = model.byName.get(name);
    return Boolean(other) && state.get(name).active && isSet(other, values[name]);
  };
  const found = {};
  model.fields.forEach((field, position) => {
    const own = state.get(field.name);
    if (!own.active) return;
    const value = values[field.name];
    const problem = fieldMessage(field, value, own.required, words);
    if (problem || !isSet(field, value)) {
      if (problem) found[field.name] = problem;
      return;
    }
    const missing = field.requires.filter((name) => model.byName.has(name) && !given(name));
    if (missing.length) {
      found[field.name] = message(fill(words.requires, { names: missing.join(", ") }), "requires");
      return;
    }
    const mates = model.fields
      .slice(0, position)
      .filter((other) => field.oneOf !== null && other.oneOf === field.oneOf)
      .map((other) => other.name);
    const clashing = [...new Set([...field.excludes, ...mates])].filter(given);
    if (clashing.length) {
      found[field.name] = message(fill(words.excludes, { names: clashing.join(", ") }), "excludes");
    }
  });
  return found;
}

/**
 * The options of a call: the values in the catalog's types, of the active fields only, nothing
 * for an empty field, a boolean only where it differs from its default, `true` for a boolean
 * alternative chosen. A value that is not of its type is sent as typed, for the tool to refuse.
 *
 * @param {object} model the result of formModel
 * @param {object} values the form's values
 * @returns {object} the options by name
 */
export function toOptions(model, values) {
  const { state } = formState(model, values);
  const options = {};
  for (const field of model.fields) {
    if (!state.get(field.name).active) continue;
    const value = values[field.name];
    if (field.kind === "boolean" && field.group !== null && !field.attached) {
      options[field.name] = true;
      continue;
    }
    if (!isGiven(field, value)) continue;
    switch (field.kind) {
      case "number":
      case "integer": {
        const number = parseNumber(value);
        options[field.name] = Number.isFinite(number) ? number : String(value).trim();
        break;
      }
      case "numbers": {
        const { values: numbers, bad } = parseNumbers(value);
        options[field.name] = bad ? String(value).trim() : numbers;
        break;
      }
      case "boolean":
        if (value !== Boolean(field.default)) options[field.name] = value;
        break;
      case "choice":
        options[field.name] = value;
        break;
      case "multi":
        options[field.name] = [...value];
        break;
      case "texts":
        options[field.name] = textTokens(value);
        break;
      case "json":
        try {
          options[field.name] = JSON.parse(value);
        } catch {
          options[field.name] = String(value);
        }
        break;
      default:
        options[field.name] = String(value).trim();
    }
  }
  return options;
}

/** A catalog value as the field holds it. */
function formValue(field, value) {
  if (value === undefined || value === null) return undefined;
  switch (field.kind) {
    case "number":
    case "integer":
      return typeof value === "number" ? numberText(value) : String(value);
    case "numbers":
      return Array.isArray(value) ? value.map(numberText).join("; ") : String(value);
    case "texts":
      return Array.isArray(value) ? value.map(String).join(", ") : String(value);
    case "json":
      return typeof value === "string" ? value : JSON.stringify(value, null, 2);
    case "boolean":
      return typeof value === "boolean" ? value : undefined;
    case "multi":
      return Array.isArray(value) ? [...value] : [value];
    case "choice":
      return value;
    default:
      return String(value);
  }
}

/**
 * The values of a form holding a call's options, as `parse_command` reads a line: each option
 * of a shown field, and in each choice the alternative they give.
 *
 * @param {object} model the result of formModel
 * @param {object} options the options by name
 * @returns {object} the form's values
 */
export function toValues(model, options) {
  const values = {};
  for (const [name, value] of Object.entries(options || {})) {
    const field = model.byName.get(name);
    const held = field ? formValue(field, value) : undefined;
    if (held !== undefined) values[name] = held;
  }
  const given = (field, name) =>
    field.kind === "boolean" ? values[name] === true : isGiven(field, values[name]);
  model.groups.forEach((group) => {
    const found = bestAlternative(model, group, given);
    values[group.key] = found >= 0 ? found : group.required ? 0 : -1;
  });
  return values;
}

/**
 * The messages of an error document of a tool (`<tool>-error/1`, or a problem document with its
 * fields, AGI-6.3): its message under the option `details.option` names, else above the form.
 *
 * @param {object} doc the error document
 * @returns {Object<string, {text: string, reason: string|null}>} the message by option name,
 *   FORM_ERROR for one that names none
 */
export function errorMessages(doc) {
  if (!doc || typeof doc !== "object") return {};
  const details = doc.details && typeof doc.details === "object" ? doc.details : {};
  const text = doc.message || doc.detail || doc.title || doc.code || String(doc);
  const option = typeof details.option === "string" && details.option ? details.option : null;
  const reason = typeof details.reason === "string" ? details.reason : null;
  return { [option ?? FORM_ERROR]: message(text, reason) };
}

/** The messages set by a GUI: a string or {text, reason} by option name. */
function messagesOf(value) {
  const found = {};
  for (const [name, item] of Object.entries(value && typeof value === "object" ? value : {})) {
    if (typeof item === "string" && item) found[name] = message(item);
    else if (item && typeof item.text === "string") found[name] = message(item.text, item.reason);
  }
  return found;
}

/** An element with a class and a text. */
function make(tag, className = null, text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}

/** A catalog text with its `code` spans as <code>, no HTML parsed. */
function richText(text) {
  return String(text ?? "")
    .split("`")
    .map((part, index) => (index % 2 ? make("code", null, part) : document.createTextNode(part)));
}

/** The custom element `<nogat-command-form>`. */
export class NogatCommandForm extends HTMLElement {
  static observedAttributes = ["paths"];

  constructor() {
    super();
    this._entry = null;
    this._model = null;
    this._values = {};
    this._hide = [];
    this._labels = {};
    this._texts = COMMAND_FORM_TEXTS;
    this._format = null;
    this._parse = null;
    this._touched = new Set();
    this._all = false;
    this._errors = {};
    this._lineErrors = {};
    this._line = { state: "none", text: "" };
    this._turn = 0;
    this._timer = null;
    this._pasteText = "";
    this._pasteMessage = null;
    this._moreOpen = null;
    this._structure = "";
    this._parts = new Map();
    this._id = `nogat-command-form-${++counter}`;
  }

  /** @returns {object|null} the command's entry */
  get command() {
    return this._entry;
  }

  /** @param {object} value a `<tool>-commands/1` document of one command, or its entry */
  set command(value) {
    const entry = commandEntry(value);
    if (!entry) throw new TypeError("nogat-command-form: not a commands-1 entry");
    this._entry = entry;
    this._values = {};
    this._touched = new Set();
    this._all = false;
    this._errors = {};
    this._lineErrors = {};
    this._line = { state: "none", text: "" };
    this._moreOpen = null;
    this._rebuild();
  }

  /** @returns {object} the call: the options in the catalog's types */
  get options() {
    return this._model ? toOptions(this._model, this._values) : {};
  }

  /** @param {object} value options to show in place of the form's values; fires no event */
  set options(value) {
    if (!this._model) return;
    this._values = toValues(this._model, value);
    this._touched = new Set();
    this._all = false;
    this._errors = {};
    this._lineErrors = {};
    this._refresh(true);
  }

  /** @returns {boolean} whether the values pass the checks of the catalog */
  get valid() {
    if (!this._model) return true;
    return Object.keys(checkValues(this._model, this._values, this._texts)).length === 0;
  }

  /** @returns {string|null} the line `format` wrote for the values shown, null while none */
  get line() {
    return this._line.state === "ok" ? this._line.text : null;
  }

  /** @returns {string[]} the options the GUI supplies itself */
  get hide() {
    return [...this._hide];
  }

  /** @param {string[]} value options the GUI supplies itself: not shown, checked or sent */
  set hide(value) {
    this._hide = namesOf(value);
    this._rebuild();
  }

  /** @returns {Object<string, string>} the labels by option name */
  get labels() {
    return { ...this._labels };
  }

  /** @param {Object<string, string>} value Polish labels by option name, "#<group>" a choice's */
  set labels(value) {
    this._labels = value && typeof value === "object" ? { ...value } : {};
    this._rebuild();
  }

  /** @returns {object} the words */
  get texts() {
    return this._texts;
  }

  /** @param {object} value words in place of COMMAND_FORM_TEXTS */
  set texts(value) {
    this._texts = { ...COMMAND_FORM_TEXTS, ...value };
    this._rebuild();
  }

  /** @returns {Function|null} the binding of the tool's format_command */
  get format() {
    return this._format;
  }

  /** @param {(command: string, options: object) => string|Promise<string>} value the line */
  set format(value) {
    this._format = typeof value === "function" ? value : null;
    this._line = { state: "none", text: "" };
    this._refresh(true);
  }

  /** @returns {Function|null} the binding of the tool's parse_command */
  get parse() {
    return this._parse;
  }

  /** @param {(line: string) => {command: string, options: object}|Promise<object>} value */
  set parse(value) {
    this._parse = typeof value === "function" ? value : null;
    this._refresh(true);
  }

  /** @returns {object} the GUI's messages by option name */
  get errors() {
    return { ...this._errors };
  }

  /** @param {Object<string, string|{text: string, reason?: string}>} value messages by option */
  set errors(value) {
    this._errors = messagesOf(value);
    this._refresh(false);
  }

  /**
   * Place an error document of the tool: its message under the field `details.option` names,
   * else above the form, until the person edits that field.
   *
   * @param {object} doc a `<tool>-error/1` document or a problem document with its fields
   */
  showError(doc) {
    this.errors = errorMessages(doc);
  }

  /**
   * Show one option's value, as from the GUI's map; its choice moves to it. Fires no event.
   *
   * @param {string} name the option
   * @param {unknown} value its value in the catalog's type, undefined to empty it
   */
  setOption(name, value) {
    const field = this._model?.byName.get(name);
    if (!field) return;
    const held = formValue(field, value);
    if (held === undefined) delete this._values[name];
    else this._values[name] = held;
    if (field.group !== null && held !== undefined) {
      const key = this._model.groups[field.group].key;
      const { choices } = formState(this._model, this._values);
      if (!field.alternatives.includes(choices[field.group])) {
        this._values[key] = field.alternatives[0];
      }
    }
    delete this._errors[name];
    delete this._lineErrors[name];
    this._refresh(true);
  }

  /**
   * Check every field and show its message, as before a run.
   *
   * @returns {boolean} whether the values pass
   */
  check() {
    this._all = true;
    this._refresh(false);
    return this.valid;
  }

  connectedCallback() {
    // A property set before the element was defined shadows its setter; take it over.
    const names = ["command", "hide", "labels", "texts", "format", "parse", "options", "errors"];
    for (const name of names) {
      if (!Object.prototype.hasOwnProperty.call(this, name)) continue;
      const value = this[name];
      delete this[name];
      this[name] = value;
    }
    this.render();
    this._scheduleLine();
  }

  disconnectedCallback() {
    clearTimeout(this._timer);
  }

  attributeChangedCallback() {
    this._rebuild();
  }

  /** The model again for a new command, hidden options or words; the values kept. */
  _rebuild() {
    if (!this._entry) return;
    this._model = formModel(this._entry, {
      hide: this._hide,
      paths: this.getAttribute("paths"),
      labels: this._labels,
      texts: this._texts,
    });
    // A choice's alternatives may have changed: each is chosen again by the values given.
    for (const name of Object.keys(this._values)) {
      if (!this._model.byName.has(name)) delete this._values[name];
    }
    this._refresh(true);
  }

  /** Draw the form again where its fields change, else update them; then ask for the line. */
  _refresh(again) {
    this._draw(again);
    this._scheduleLine();
  }

  /** Draw the form again where its fields change (or `again`), else update them in place. */
  _draw(again) {
    if (!this.isConnected || !this._model) return;
    const { choices, state } = formState(this._model, this._values);
    if (again || this._structureOf(choices, state) !== this._structure) this.render();
    else this._patch(state);
  }

  /** What makes the form drawn again: the choices and the fields shown. */
  _structureOf(choices, state) {
    const shown = this._model.fields.filter((field) => state.get(field.name).shown);
    return JSON.stringify([choices, shown.map((field) => field.name)]);
  }

  /** The messages shown: the checks of the fields touched, then the line's, then the GUI's. */
  _messages() {
    const checked = checkValues(this._model, this._values, this._texts);
    const found = {};
    for (const [name, problem] of Object.entries(checked)) {
      if (this._all || this._touched.has(name)) found[name] = problem;
    }
    return Object.assign(found, this._lineErrors, this._errors);
  }

  /** The messages that stand above the form: of no field shown. */
  _loose(messages) {
    return Object.entries(messages)
      .filter(([name]) => name === FORM_ERROR || !this._parts.has(name))
      .map(([name, problem]) => ({ name, problem }));
  }

  /** Draw the form. */
  render() {
    const focus = this._focused();
    this.replaceChildren();
    this._parts = new Map();
    if (!this._model) return;
    const { choices, state } = formState(this._model, this._values);
    const root = make("div", "nogat-command-form");
    // The controls' own events stay inside; the element tells of a change with its options.
    for (const type of ["change", "input"]) {
      root.addEventListener(type, (event) => event.stopPropagation());
    }
    if (this._parse) root.append(this._pasteBox());
    const loose = make("div", "nogat-command-form-errors");
    loose.setAttribute("role", "alert");
    root.append(loose);
    for (const section of this._model.sections) {
      const items = section.items.flatMap((item) => this._item(item, choices, state));
      if (!items.length) continue;
      if (section.id === "main") root.append(...items);
      else if (section.id === "more") root.append(this._more(section, items));
      else {
        const box = make("fieldset", "nogat-command-form-section");
        box.append(make("legend", null, section.title), ...items);
        root.append(box);
      }
    }
    const rules = this._entry.i18n?.pl?.rules;
    if (Array.isArray(rules) && rules.length) {
      const note = make("p", "nogat-command-form-rules");
      note.append(make("strong", null, `${this._texts.rules}: `), ...richText(rules.join(" ")));
      root.append(note);
    }
    if (this._format) root.append(this._lineBox());
    this.append(root);
    this._structure = this._structureOf(choices, state);
    this._patch(state);
    this._restore(focus);
  }

  /** The elements of one item of a section: a field or a choice, nothing when not shown. */
  _item(item, choices, state) {
    if (item.group !== undefined) return [this._choice(item.group, choices, state)];
    const field = this._model.byName.get(item.field);
    return state.get(field.name).shown ? [this._field(field)] : [];
  }

  /** „Opcje dodatkowe”: open as the person left it, at first only when nothing else is. */
  _more(section, items) {
    const details = make("details", "nogat-command-form-more");
    const summary = make("summary", null, `${section.title} `);
    summary.append(make("span", "nogat-command-form-count", String(items.length)));
    details.append(summary, ...items);
    const alone = this._model.sections.length === 1;
    details.open = this._moreOpen ?? alone;
    details.addEventListener("toggle", () => {
      this._moreOpen = details.open;
    });
    return details;
  }

  /** A choice: a radio per alternative („—” first where none may be given), then its pane. */
  _choice(index, choices, state) {
    const group = this._model.groups[index];
    const chosen = choices[index];
    const texts = this._texts;
    const box = make("fieldset", "nogat-command-form-choice");
    box.dataset.group = group.id;
    const legend = make("legend", "nogat-command-form-label");
    legend.append(group.code ? make("code", null, group.legend) : group.legend);
    const count = group.alternatives.length;
    const key = fill(group.required ? texts.exactlyOne : texts.atMostOne, { count });
    legend.append(" ", make("span", "nogat-command-form-key", key));
    const radios = make("div", "nogat-command-form-radios");
    const name = `${this._id}-${group.key}`;
    const none = { index: -1, label: [texts.none], title: texts.noneTitle };
    const items = group.required ? [] : [none];
    group.alternatives.forEach((alternative, at) => {
      const label = [];
      alternative.names.forEach((option, place) => {
        if (place) label.push(" + ");
        const field = this._model.byName.get(option);
        label.push(field.label ?? make("code", null, option));
      });
      items.push({ index: at, label, title: alternative.names.join(" + ") });
    });
    for (const item of items) {
      const row = make("label", "nogat-command-form-radio");
      row.title = item.title;
      const radio = make("input");
      radio.type = "radio";
      radio.name = name;
      radio.id = `${name}-${item.index}`;
      radio.value = String(item.index);
      radio.checked = item.index === chosen;
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        this._values[group.key] = item.index;
        this._edited();
      });
      row.append(radio, ...item.label);
      radios.append(row);
    }
    box.append(legend, radios);
    if (chosen >= 0) {
      const alternative = group.alternatives[chosen];
      const pane = make("div", "nogat-command-form-pane");
      const names = new Set([...alternative.names, ...alternative.attached]);
      for (const field of this._model.fields) {
        if (names.has(field.name) && state.get(field.name).shown) {
          pane.append(this._field(field));
        }
      }
      box.append(pane);
    }
    return box;
  }

  /** One field: its label, control, hint and message; a checkbox inside its label. */
  _field(field) {
    const id = `${this._id}-${field.name}`;
    const alternative = field.kind === "boolean" && field.group !== null && !field.attached;
    const grouped = !alternative && (field.kind === "multi" || this._radios(field));
    const box = make(grouped ? "fieldset" : "div", "nogat-command-form-field");
    box.dataset.option = field.name;
    box.dataset.kind = field.kind;
    const tag = grouped ? "legend" : alternative ? "span" : "label";
    const label = make(tag, "nogat-command-form-label");
    const controls = alternative ? [] : this._controls(field, id);
    if (tag === "label") label.htmlFor = id;
    if (field.kind === "boolean" && !alternative) {
      label.classList.add("nogat-command-form-check");
      label.append(controls[0], " ");
    }
    if (field.label) label.append(make("span", "nogat-command-form-name", field.label), " ");
    label.append(make("code", null, field.name));
    if (field.unit) label.append(" ", make("span", "nogat-command-form-unit", `[${field.unit}]`));
    const flag = make("span", "nogat-command-form-flag");
    label.append(" ", flag);
    box.append(label);
    if (controls.length && field.kind !== "boolean") box.append(this._wrap(field, controls));
    const meaning = field.kind === "choice" ? make("span", "nogat-command-form-meaning") : null;
    if (meaning) box.append(meaning);
    const hint = field.description ? make("span", "nogat-command-form-hint") : null;
    if (hint) {
      hint.id = `${id}-hint`;
      hint.append(...richText(field.description));
      box.append(hint);
    }
    const note = make("span", "nogat-command-form-message");
    note.id = `${id}-message`;
    box.append(note);
    this._parts.set(field.name, { box, controls, flag, meaning, hint, note, id });
    return box;
  }

  /** Whether a choice is drawn as radios: up to four values, „—” included. */
  _radios(field) {
    return field.kind === "choice" && field.choices.length <= RADIOS_MAX;
  }

  /** The controls of a field, wrapped where a choice lays them out in a row. */
  _wrap(field, controls) {
    if (field.kind === "multi" || this._radios(field)) {
      const row = make("div", "nogat-command-form-radios");
      row.append(...controls.map((control) => control.closest("label") ?? control));
      return row;
    }
    return controls[0];
  }

  /** The value a choice shows: the value given, else the default, else none. */
  _shownChoice(field) {
    const value = this._values[field.name];
    if (isGiven(field, value)) return value;
    return field.hasDefault ? field.default : undefined;
  }

  /** The control or controls of a field. */
  _controls(field, id) {
    const value = this._values[field.name];
    const set = (next) => {
      if (next === undefined) delete this._values[field.name];
      else this._values[field.name] = next;
      delete this._errors[field.name];
      delete this._lineErrors[field.name];
    };
    const commit = () => {
      this._touched.add(field.name);
      this._edited();
    };
    switch (field.kind) {
      case "boolean": {
        const box = make("input");
        box.type = "checkbox";
        box.id = id;
        box.checked = typeof value === "boolean" ? value : Boolean(field.default);
        box.addEventListener("change", () => {
          set(box.checked);
          commit();
        });
        return [box];
      }
      case "choice":
        return this._radios(field) ? this._choiceRadios(field, id, set, commit)
          : [this._choiceSelect(field, id, set, commit)];
      case "multi": {
        const chosen = Array.isArray(value) ? value : [];
        return field.choices.map((choice, index) => {
          const row = make("label", "nogat-command-form-radio");
          row.title = choice.meaning;
          const box = make("input");
          box.type = "checkbox";
          box.id = `${id}-${index}`;
          box.value = String(index);
          box.checked = chosen.some((item) => same(item, choice.value));
          box.addEventListener("change", () => {
            const boxes = [...row.parentElement.querySelectorAll("input")];
            const picked = field.choices.filter((_, at) => boxes[at]?.checked);
            set(picked.length ? picked.map((item) => item.value) : undefined);
            commit();
          });
          row.append(box, String(choice.value));
          return box;
        });
      }
      default: {
        const json = field.kind === "json";
        const input = make(json ? "textarea" : "input");
        if (json) input.rows = 4;
        else input.type = "text";
        input.id = id;
        input.value = value ?? "";
        input.autocomplete = "off";
        input.spellcheck = false;
        const numeric = { number: "decimal", integer: "numeric" }[field.kind];
        if (numeric) input.inputMode = numeric;
        input.placeholder = this._placeholder(field);
        input.addEventListener("input", () => {
          set(input.value === "" ? undefined : input.value);
          this._edited();
        });
        input.addEventListener("change", () => {
          this._touched.add(field.name);
          this._refresh(false);
        });
        return [input];
      }
    }
  }

  /** The radios of a choice of up to four values, „—” first where it may stay empty. */
  _choiceRadios(field, id, set, commit) {
    const shown = this._shownChoice(field);
    const items = [
      ...(field.required || field.hasDefault ? [] : [{ value: undefined, none: true }]),
      ...field.choices,
    ];
    return items.map((choice, index) => {
      const row = make("label", "nogat-command-form-radio");
      row.title = choice.none ? this._texts.noneTitle : choice.meaning;
      const radio = make("input");
      radio.type = "radio";
      radio.name = id;
      radio.id = `${id}-${index}`;
      radio.value = String(index);
      const checked = shown !== undefined && same(shown, choice.value);
      radio.checked = choice.none ? shown === undefined : checked;
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        set(choice.none ? undefined : choice.value);
        commit();
      });
      row.append(radio, choice.none ? this._texts.none : String(choice.value));
      return radio;
    });
  }

  /** The select of a choice of more than four values, „—” first where it may stay empty. */
  _choiceSelect(field, id, set, commit) {
    const shown = this._shownChoice(field);
    const select = make("select");
    select.id = id;
    const empty = !field.hasDefault;
    if (empty) select.append(make("option", null, this._texts.none));
    field.choices.forEach((choice, index) => {
      const short = choice.meaning.replace(/`/g, "").replace(/\.$/, "");
      const text = short && short.length <= 48 ? `${choice.value} — ${short}` : `${choice.value}`;
      const item = make("option", null, text);
      item.value = String(index);
      item.selected = shown !== undefined && same(shown, choice.value);
      select.append(item);
    });
    if (empty) select.options[0].value = "";
    select.addEventListener("change", () => {
      const choice = field.choices[Number(select.value)];
      set(select.value === "" || !choice ? undefined : choice.value);
      commit();
    });
    return select;
  }

  /** The placeholder of a text: the format, the default, a path's role or „np.” an example. */
  _placeholder(field) {
    const texts = this._texts;
    if (field.format && FORMAT_HINTS[field.format]) return FORMAT_HINTS[field.format];
    if (field.hasDefault) {
      const value = field.kind === "json" ? JSON.stringify(field.default) : field.default;
      return shownValue(value, texts);
    }
    if (field.pathRole) {
      return { input: texts.pathInput, output: texts.pathOutput, root: texts.pathRoot }[
        field.pathRole
      ] ?? "";
    }
    if (field.kind === "json") {
      const json = field.examples.length ? JSON.stringify(field.examples[0]) : null;
      return json ? fill(texts.example, { value: json }) : field.items ? "[ … ]" : "{ … }";
    }
    const example = field.examples.find((item) => item !== null && typeof item !== "object")
      ?? field.examples.find((item) => Array.isArray(item));
    if (example === undefined) {
      if (field.kind === "numbers") return texts.numbersHint;
      if (field.kind === "texts") return texts.textsHint;
      return "";
    }
    return fill(texts.example, { value: shownValue(example, texts) });
  }

  /** Update the fields in place: flags, disabled controls, meanings and messages. */
  _patch(state) {
    const messages = this._messages(state);
    const texts = this._texts;
    for (const [name, part] of this._parts) {
      const field = this._model.byName.get(name);
      const own = state.get(name);
      const problem = messages[name] ?? null;
      part.box.classList.toggle("nogat-command-form-invalid", Boolean(problem));
      part.box.classList.toggle("nogat-command-form-disabled", Boolean(own.disabledBy));
      part.flag.className = "nogat-command-form-flag";
      if (own.disabledBy) {
        part.flag.textContent = fill(texts.excludedBy, { name: own.disabledBy });
      } else if (own.required && field.kind !== "boolean") {
        part.flag.textContent = texts.required;
        part.flag.classList.add("nogat-command-form-required");
      } else if (field.hasDefault && field.kind !== "boolean") {
        part.flag.textContent = fill(texts.defaultIs, { value: shownValue(field.default, texts) });
      } else {
        part.flag.textContent = "";
      }
      part.note.replaceChildren();
      part.note.hidden = !problem;
      if (problem) {
        part.note.append(problem.text);
        if (problem.reason) {
          part.note.append(" ", make("span", "nogat-command-form-reason", `· ${problem.reason}`));
        }
      }
      const described = [part.hint && part.hint.id, problem && part.note.id].filter(Boolean);
      for (const control of part.controls) {
        control.disabled = Boolean(own.disabledBy);
        control.setAttribute("aria-invalid", problem ? "true" : "false");
        if (control.type !== "radio" && control.type !== "checkbox") {
          control.setAttribute("aria-required", own.required ? "true" : "false");
        }
        if (described.length) control.setAttribute("aria-describedby", described.join(" "));
        else control.removeAttribute("aria-describedby");
      }
      if (part.meaning) {
        const shown = this._shownChoice(field);
        const choice = field.choices.find((item) => shown !== undefined && same(item.value, shown));
        part.meaning.replaceChildren();
        part.meaning.hidden = !choice?.meaning;
        if (choice?.meaning) {
          part.meaning.append(make("code", null, String(choice.value)), " ");
          part.meaning.append(...richText(choice.meaning));
        }
      }
      const more = part.box.closest(".nogat-command-form-more");
      if (problem && more && !more.open) more.open = true;
    }
    const loose = this.querySelector(".nogat-command-form-errors");
    if (loose) {
      const items = this._loose(messages);
      loose.replaceChildren();
      loose.hidden = !items.length;
      if (items.length) {
        loose.append(make("strong", null, texts.aboveForm));
        const list = make("ul");
        for (const { name, problem } of items) {
          const row = make("li");
          if (name !== FORM_ERROR) row.append(make("code", null, name), " ");
          row.append(problem.text);
          if (problem.reason) {
            row.append(" ", make("span", "nogat-command-form-reason", `· ${problem.reason}`));
          }
          list.append(row);
        }
        loose.append(list);
      }
    }
    this._showPaste();
    this._showLine();
  }

  /** „Wklej polecenie”: a line read by `parse` into the form. */
  _pasteBox() {
    const texts = this._texts;
    const box = make("div", "nogat-command-form-paste");
    const id = `${this._id}-paste`;
    const label = make("label", "nogat-command-form-label", texts.paste);
    label.htmlFor = id;
    const row = make("div", "nogat-command-form-paste-row");
    const input = make("input");
    input.type = "text";
    input.id = id;
    input.value = this._pasteText;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.placeholder = this._entry.examples?.[0]?.call ?? this._entry.name;
    input.addEventListener("input", () => {
      this._pasteText = input.value;
      this._pasteMessage = null;
      this._showPaste();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      this._read();
    });
    const button = make("button", "btn sm nogat-command-form-read", texts.read);
    button.type = "button";
    button.addEventListener("click", () => this._read());
    row.append(input, button);
    const note = make("span", "nogat-command-form-message");
    note.id = `${id}-message`;
    box.append(label, row, note);
    return box;
  }

  /** The paste field's text and message as they are now. */
  _showPaste() {
    const input = this.querySelector(".nogat-command-form-paste input");
    const note = this.querySelector(".nogat-command-form-paste .nogat-command-form-message");
    if (!input || !note) return;
    if (input.value !== this._pasteText) input.value = this._pasteText;
    note.replaceChildren();
    note.hidden = !this._pasteMessage;
    if (this._pasteMessage) note.append(this._pasteMessage.text);
    note.setAttribute("role", "alert");
    if (this._pasteMessage) input.setAttribute("aria-describedby", note.id);
    else input.removeAttribute("aria-describedby");
    input.setAttribute("aria-invalid", this._pasteMessage ? "true" : "false");
  }

  /** Read the pasted line with `parse` and show it, or say why not. */
  async _read() {
    const line = this._pasteText.trim();
    if (!line || !this._parse) return;
    const texts = this._texts;
    let parsed;
    try {
      parsed = await this._parse(line);
    } catch (error) {
      const problem = Object.values(errorMessages(error))[0] ?? message(String(error));
      this._pasteMessage = message(fill(texts.pasteFailed, { message: problem.text }));
      this._showPaste();
      return;
    }
    const command = String(parsed?.command ?? "");
    const options = parsed?.options && typeof parsed.options === "object" ? parsed.options : {};
    const detail = { line, command, options };
    const event = new CustomEvent("nogat-command-paste", {
      bubbles: true,
      cancelable: true,
      detail,
    });
    if (!this.dispatchEvent(event)) {
      this._pasteText = "";
      this._pasteMessage = null;
      this._showPaste();
      return;
    }
    if (command !== this._entry.name && command !== this._entry.operation_id) {
      const words = { command, current: this._entry.name };
      this._pasteMessage = message(fill(texts.otherCommand, words));
      this._showPaste();
      return;
    }
    this._pasteText = "";
    this._pasteMessage = null;
    this.options = options;
    this._emit();
  }

  /** The line: its label, the text `format` wrote, „Kopiuj” and its status. */
  _lineBox() {
    const texts = this._texts;
    const box = make("div", "nogat-command-form-line");
    const label = make("span", "nogat-command-form-label", texts.line);
    label.id = `${this._id}-line-label`;
    const text = make("code", "nogat-command-form-line-text");
    text.setAttribute("aria-labelledby", label.id);
    const button = make("button", "btn sm nogat-command-form-copy", texts.copy);
    button.type = "button";
    button.addEventListener("click", () => this._copy());
    const status = make("span", "nogat-command-form-status");
    status.setAttribute("role", "status");
    box.append(label, text, button, status);
    return box;
  }

  /** The line as it is now: written, being written, incomplete or failed. */
  _showLine() {
    const box = this.querySelector(".nogat-command-form-line");
    if (!box) return;
    const texts = this._texts;
    const { state, text } = this._line;
    box.dataset.state = state;
    const shown =
      state === "incomplete"
        ? fill(texts.incomplete, { names: text })
        : state === "failed"
          ? fill(texts.lineFailed, { message: text })
          : text;
    const code = box.querySelector(".nogat-command-form-line-text");
    if (code.textContent === shown) {
      // The same text: nothing to draw again.
    } else if (state === "ok" || state === "pending") {
      // Each word of the line its own box, so the line breaks between words, never at the
      // hyphen of a flag; a selection still copies the words and their spaces.
      const words = shown.split(" ").map((word) => make("span", null, word));
      code.replaceChildren(...words.flatMap((word, at) => (at ? [" ", word] : [word])));
    } else {
      code.textContent = shown;
    }
    box.querySelector(".nogat-command-form-copy").disabled = state !== "ok";
  }

  /** Ask `format` for the line after the last change, the latest answer only. */
  _scheduleLine() {
    if (!this._format || !this._model) return;
    clearTimeout(this._timer);
    const turn = ++this._turn;
    this._timer = setTimeout(() => this._writeLine(turn), LINE_DELAY);
  }

  /** Write the line of the values, or name the fields it still needs. */
  async _writeLine(turn) {
    const problems = checkValues(this._model, this._values, this._texts);
    const names = Object.keys(problems).filter((name) => name !== FORM_ERROR);
    if (names.length) {
      this._line = { state: "incomplete", text: names.join(", ") };
      this._showLine();
      return;
    }
    this._line = { state: "pending", text: this._line.state === "ok" ? this._line.text : "" };
    this._showLine();
    let written;
    try {
      written = await this._format(this._entry.name, this.options);
    } catch (error) {
      if (turn !== this._turn) return;
      const placed = errorMessages(error);
      const [[name, problem]] = Object.entries(placed).length
        ? Object.entries(placed)
        : [[FORM_ERROR, message(String(error))]];
      this._lineErrors = name === FORM_ERROR ? {} : { [name]: problem };
      this._line = { state: "failed", text: problem.text };
      this._draw(false);
      return;
    }
    if (turn !== this._turn) return;
    const had = Object.keys(this._lineErrors).length > 0;
    this._lineErrors = {};
    this._line = { state: "ok", text: String(written) };
    if (had) this._patch(formState(this._model, this._values).state);
    else this._showLine();
  }

  /** Copy the line, or select it for the person to copy where the browser refuses. */
  async _copy() {
    const box = this.querySelector(".nogat-command-form-line");
    if (!box || this._line.state !== "ok") return;
    const status = box.querySelector(".nogat-command-form-status");
    try {
      await navigator.clipboard.writeText(this._line.text);
      status.textContent = this._texts.copied;
    } catch {
      const range = document.createRange();
      range.selectNodeContents(box.querySelector(".nogat-command-form-line-text"));
      const selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = this._texts.copyFailed;
    }
  }

  /** A person's edit: the form updated, the line asked for, then `change`. */
  _edited() {
    this._refresh(false);
    this._emit();
  }

  /** Tell of a person's edit: the call and whether it passes the checks. */
  _emit() {
    const detail = { options: this.options, valid: this.valid };
    this.dispatchEvent(new CustomEvent("change", { bubbles: true, detail }));
  }

  /** The control that has the focus, and its selection. */
  _focused() {
    const active = document.activeElement;
    if (!active || !active.id || !this.contains(active)) return null;
    const kept = { id: active.id, start: null, end: null };
    if (typeof active.selectionStart === "number") {
      kept.start = active.selectionStart;
      kept.end = active.selectionEnd;
    }
    return kept;
  }

  /** Give the focus back to the control drawn in its place. */
  _restore(kept) {
    if (!kept) return;
    const control = document.getElementById(kept.id);
    if (!control || !this.contains(control)) return;
    control.focus({ preventScroll: true });
    if (kept.start !== null && typeof control.setSelectionRange === "function") {
      control.setSelectionRange(kept.start, kept.end);
    }
  }
}

if (!customElements.get("nogat-command-form")) {
  customElements.define("nogat-command-form", NogatCommandForm);
}
