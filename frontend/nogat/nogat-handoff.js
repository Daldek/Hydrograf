// Nogat GUI kit: the hand-off between GUIs (DEV-15.5, ECO-058).
// A GUI writes and reads `nogat-handoff/1` (Nogat schemas/exchange/handoff-1.schema.json)
// through this module: the file name, the text, the clipboard with its fallback, the file
// download and upload, and the check of a document against a JSON Schema with Polish
// messages. Building the document and the meaning of its payload stay the GUI's.
// Copy this file byte for byte (DEV-15.6); change it in Nogat design/kit/.

/** Names of the GUIs in the cases the labels need. */
export const GUI_NAMES = {
  archiwista: { nominative: "Archiwista", genitive: "Archiwisty", accusative: "Archiwistę" },
  hydrograf: { nominative: "Hydrograf", genitive: "Hydrografa", accusative: "Hydrografa" },
  hydrolog: { nominative: "Hydrolog", genitive: "Hydrologa", accusative: "Hydrologa" },
  obserwator: { nominative: "Obserwator", genitive: "Obserwatora", accusative: "Obserwatora" },
};

/**
 * One case of a GUI's name; the name itself for a GUI the kit does not know.
 *
 * @param {string} name registry name in lower case, e.g. "hydrolog"
 * @param {"nominative"|"genitive"|"accusative"} form the case
 * @returns {string} the name in that case
 */
export function guiName(name, form) {
  const known = GUI_NAMES[name];
  if (known) return known[form];
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** The labels and messages of a hand-off, in Polish (DEV-15.2). */
export const TEXTS = {
  copyTo: (name) => `Kopiuj do ${guiName(name, "genitive")}`,
  file: "Plik przekazania",
  loadFrom: (name) => `Wczytaj z ${guiName(name, "genitive")}`,
  openFile: "Plik przekazania…",
  paste: "Wklej ze schowka",
  open: (name) => `Otwórz ${guiName(name, "accusative")}`,
  copied: "Skopiowano przekazanie do schowka.",
  copyByHand: "Przeglądarka nie pozwoliła skopiować: tekst przekazania jest zaznaczony, naciśnij Ctrl+C.",
  saved: (fileName) => `Zapisano plik „${fileName}”.`,
  pasteByHand: "Przeglądarka nie pozwoliła odczytać schowka: wklej tekst przekazania w pole (Ctrl+V).",
  notJson: (detail) => `To nie jest tekst JSON (${detail}).`,
  notHandoff: "To nie jest przekazanie nogat-handoff/1.",
  problem: (path, message) => (path ? `${path}: ${message}` : message),
  keywords: {
    type: (p) => `oczekiwano: ${p.expected.map((t) => TYPE_NAMES[t] || t).join(" lub ")}`,
    required: (p) => `brak pola „${p.property}”`,
    additionalProperties: (p) => `nieznane pole „${p.property}”`,
    propertyNames: (p) => `niedozwolona nazwa pola „${p.property}”`,
    const: (p) => `oczekiwano ${JSON.stringify(p.value)}`,
    enum: (p) => `wartość spoza listy: ${p.allowed.map((v) => JSON.stringify(v)).join(", ")}`,
    minimum: (p) => `musi być ≥ ${p.limit}`,
    maximum: (p) => `musi być ≤ ${p.limit}`,
    exclusiveMinimum: (p) => `musi być > ${p.limit}`,
    exclusiveMaximum: (p) => `musi być < ${p.limit}`,
    multipleOf: (p) => `musi być wielokrotnością ${p.limit}`,
    minLength: (p) => `za krótkie: co najmniej ${p.limit} znaków`,
    maxLength: (p) => `za długie: najwyżej ${p.limit} znaków`,
    pattern: (p) => `niezgodne ze wzorem ${p.pattern}`,
    minItems: (p) => `za mało elementów: co najmniej ${p.limit}`,
    maxItems: (p) => `za dużo elementów: najwyżej ${p.limit}`,
    uniqueItems: () => "elementy się powtarzają",
    minProperties: (p) => `za mało pól: co najmniej ${p.limit}`,
    maxProperties: (p) => `za dużo pól: najwyżej ${p.limit}`,
    dependentRequired: (p) => `pole „${p.property}” wymaga pola „${p.missing}”`,
    anyOf: () => "nie pasuje do żadnego z dopuszczalnych wariantów",
    oneOf: (p) => `pasuje do ${p.count} wariantów zamiast dokładnie jednego`,
    not: () => "wartość niedozwolona",
    false: () => "pole niedozwolone",
  },
};

const TYPE_NAMES = {
  object: "obiekt",
  array: "lista",
  string: "tekst",
  number: "liczba",
  integer: "liczba całkowita",
  boolean: "prawda lub fałsz",
  null: "brak wartości",
};

/**
 * The file name of a hand-off: "<subject>.handoff.json". Characters a file name cannot hold
 * (\ / : * ? " < > | and control characters) become "-", runs of white space one space,
 * and an empty subject becomes the producer's name.
 *
 * @param {string} subject the document's `subject`
 * @param {string} producer registry name of the producing tool, e.g. "hydrograf"
 * @returns {string} the file name
 */
export function fileName(subject, producer) {
  const base = String(subject ?? "")
    // eslint-disable-next-line no-control-regex
    .replace(/[\\/:*?"<>|\u0000-\u001f\u007f]+/g, "-")
    .replace(/\s+/g, " ")
    .trim();
  return `${base || producer}.handoff.json`;
}

/**
 * The text of a hand-off: JSON indented by two spaces with a final newline.
 *
 * @param {object} doc the document
 * @returns {string} the text
 */
export function documentText(doc) {
  return `${JSON.stringify(doc, null, 2)}\n`;
}

/**
 * Put a text on the clipboard. Where the Clipboard API is missing (a plain-HTTP address
 * other than localhost) or refused, the text goes into `field`, which is shown and
 * selected so the person presses Ctrl+C.
 *
 * @param {string} text the text
 * @param {HTMLTextAreaElement} [field] the fallback field; without it the failure is thrown
 * @returns {Promise<"clipboard"|"field">} where the text went
 */
export async function copyText(text, field) {
  if (globalThis.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return "clipboard";
    } catch (error) {
      if (!field) throw error;
    }
  } else if (!field) {
    throw new Error("clipboard unavailable");
  }
  field.value = text;
  field.hidden = false;
  field.readOnly = true;
  field.focus();
  field.select();
  return "field";
}

/**
 * Save a text as a file through a temporary link.
 *
 * @param {string} text the content
 * @param {string} name the file name
 * @param {string} [type] the media type
 */
export function saveText(text, name, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/**
 * Download a hand-off as "<subject>.handoff.json".
 *
 * @param {object} doc the document
 * @returns {string} the file name
 */
export function downloadHandoff(doc) {
  const name = fileName(doc.subject, doc.producer?.tool || "nogat");
  saveText(documentText(doc), name);
  return name;
}

/**
 * Copy a hand-off to the clipboard (see copyText).
 *
 * @param {object} doc the document
 * @param {HTMLTextAreaElement} [field] the fallback field
 * @returns {Promise<"clipboard"|"field">} where the text went
 */
export function copyHandoff(doc, field) {
  return copyText(documentText(doc), field);
}

/**
 * The text of a file the person picked.
 *
 * @param {Blob} file the file
 * @returns {Promise<string>} its text
 */
export function readFile(file) {
  return file.text();
}

/**
 * The text on the clipboard, or null when the browser refuses (the GUI then offers a
 * field to paste into).
 *
 * @returns {Promise<string|null>} the text
 */
export async function readClipboard() {
  if (!globalThis.isSecureContext || !navigator.clipboard?.readText) return null;
  try {
    return await navigator.clipboard.readText();
  } catch {
    return null;
  }
}

/**
 * Parse a hand-off and check it against the envelope schema (the GUI's copy of
 * handoff-1.schema.json). The payload is the GUI's to check, against its owner's schema
 * (`validate`).
 *
 * @param {string} text the text of a file or the clipboard
 * @param {object} envelope the envelope schema
 * @returns {{doc: object|null, problems: Array<{path: string, keyword: string, message: string}>}}
 *   the document when it parses, and every problem with a Polish message
 */
export function readHandoff(text, envelope) {
  let doc;
  try {
    doc = JSON.parse(text);
  } catch (error) {
    return { doc: null, problems: [{ path: "", keyword: "json", message: TEXTS.notJson(error.message) }] };
  }
  if (doc === null || typeof doc !== "object" || doc.schema !== "nogat-handoff/1") {
    return { doc: null, problems: [{ path: "", keyword: "schema", message: TEXTS.notHandoff }] };
  }
  return { doc, problems: validate(doc, envelope) };
}

/**
 * Check a value against a JSON Schema (draft 2020-12): type, const, enum, the number,
 * string, array and object keywords, allOf, anyOf, oneOf, not, if/then/else and local
 * `$ref`s ("#/$defs/…"). Annotations and `format` are not checked.
 *
 * @param {*} value the value
 * @param {object|boolean} schema the schema
 * @returns {Array<{path: string, keyword: string, params: object, message: string}>} the
 *   problems, each with a JSON Pointer to the value and a Polish message; empty when valid
 */
export function validate(value, schema) {
  const problems = [];
  check(value, schema, "", schema, problems);
  return problems.map((p) => ({ ...p, message: TEXTS.keywords[p.keyword](p.params) }));
}

function check(value, schema, path, root, out) {
  if (schema === true) return;
  if (schema === false) {
    out.push({ path, keyword: "false", params: {} });
    return;
  }
  if (schema.$ref !== undefined) check(value, resolve(root, schema.$ref), path, root, out);
  if (schema.type !== undefined) {
    const expected = [].concat(schema.type);
    if (!expected.some((t) => isType(value, t))) {
      out.push({ path, keyword: "type", params: { expected } });
      return;
    }
  }
  if ("const" in schema && !equal(value, schema.const)) {
    out.push({ path, keyword: "const", params: { value: schema.const } });
  }
  if (schema.enum !== undefined && !schema.enum.some((v) => equal(value, v))) {
    out.push({ path, keyword: "enum", params: { allowed: schema.enum } });
  }
  if (typeof value === "number") checkNumber(value, schema, path, out);
  if (typeof value === "string") checkString(value, schema, path, out);
  if (Array.isArray(value)) checkArray(value, schema, path, root, out);
  else if (value !== null && typeof value === "object") checkObject(value, schema, path, root, out);
  for (const sub of schema.allOf ?? []) check(value, sub, path, root, out);
  if (schema.anyOf !== undefined && !schema.anyOf.some((sub) => passes(value, sub, path, root))) {
    out.push({ path, keyword: "anyOf", params: {} });
  }
  if (schema.oneOf !== undefined) {
    const count = schema.oneOf.filter((sub) => passes(value, sub, path, root)).length;
    if (count !== 1) out.push({ path, keyword: "oneOf", params: { count } });
  }
  if (schema.not !== undefined && passes(value, schema.not, path, root)) {
    out.push({ path, keyword: "not", params: {} });
  }
  if (schema.if !== undefined) {
    const branch = passes(value, schema.if, path, root) ? schema.then : schema.else;
    if (branch !== undefined) check(value, branch, path, root, out);
  }
}

function checkNumber(value, schema, path, out) {
  const bound = (keyword, fails) => {
    if (schema[keyword] !== undefined && fails(schema[keyword])) {
      out.push({ path, keyword, params: { limit: schema[keyword] } });
    }
  };
  bound("minimum", (limit) => value < limit);
  bound("maximum", (limit) => value > limit);
  bound("exclusiveMinimum", (limit) => value <= limit);
  bound("exclusiveMaximum", (limit) => value >= limit);
  bound("multipleOf", (limit) => !Number.isInteger(value / limit));
}

function checkString(value, schema, path, out) {
  const length = [...value].length;
  if (schema.minLength !== undefined && length < schema.minLength) {
    out.push({ path, keyword: "minLength", params: { limit: schema.minLength } });
  }
  if (schema.maxLength !== undefined && length > schema.maxLength) {
    out.push({ path, keyword: "maxLength", params: { limit: schema.maxLength } });
  }
  if (schema.pattern !== undefined && !new RegExp(schema.pattern, "u").test(value)) {
    out.push({ path, keyword: "pattern", params: { pattern: schema.pattern } });
  }
}

function checkArray(value, schema, path, root, out) {
  if (schema.minItems !== undefined && value.length < schema.minItems) {
    out.push({ path, keyword: "minItems", params: { limit: schema.minItems } });
  }
  if (schema.maxItems !== undefined && value.length > schema.maxItems) {
    out.push({ path, keyword: "maxItems", params: { limit: schema.maxItems } });
  }
  if (schema.uniqueItems && value.some((v, i) => value.slice(i + 1).some((w) => equal(v, w)))) {
    out.push({ path, keyword: "uniqueItems", params: {} });
  }
  const prefix = schema.prefixItems ?? [];
  value.forEach((item, i) => {
    const sub = i < prefix.length ? prefix[i] : schema.items;
    if (sub !== undefined) check(item, sub, `${path}/${i}`, root, out);
  });
}

function checkObject(value, schema, path, root, out) {
  const keys = Object.keys(value);
  if (schema.minProperties !== undefined && keys.length < schema.minProperties) {
    out.push({ path, keyword: "minProperties", params: { limit: schema.minProperties } });
  }
  if (schema.maxProperties !== undefined && keys.length > schema.maxProperties) {
    out.push({ path, keyword: "maxProperties", params: { limit: schema.maxProperties } });
  }
  for (const property of schema.required ?? []) {
    if (!(property in value)) out.push({ path, keyword: "required", params: { property } });
  }
  for (const [property, needs] of Object.entries(schema.dependentRequired ?? {})) {
    if (!(property in value)) continue;
    for (const missing of needs) {
      if (!(missing in value)) {
        out.push({ path, keyword: "dependentRequired", params: { property, missing } });
      }
    }
  }
  const properties = schema.properties ?? {};
  const patterns = Object.entries(schema.patternProperties ?? {}).map(([p, s]) => [new RegExp(p, "u"), s]);
  for (const key of keys) {
    const at = `${path}/${pointerToken(key)}`;
    if (schema.propertyNames !== undefined && !passes(key, schema.propertyNames, at, root)) {
      out.push({ path: at, keyword: "propertyNames", params: { property: key } });
    }
    let matched = false;
    if (Object.hasOwn(properties, key)) {
      matched = true;
      check(value[key], properties[key], at, root, out);
    }
    for (const [regex, sub] of patterns) {
      if (regex.test(key)) {
        matched = true;
        check(value[key], sub, at, root, out);
      }
    }
    if (!matched && schema.additionalProperties !== undefined) {
      if (schema.additionalProperties === false) {
        out.push({ path: at, keyword: "additionalProperties", params: { property: key } });
      } else {
        check(value[key], schema.additionalProperties, at, root, out);
      }
    }
  }
}

function passes(value, schema, path, root) {
  const out = [];
  check(value, schema, path, root, out);
  return out.length === 0;
}

function resolve(root, ref) {
  if (!ref.startsWith("#")) throw new Error(`only local $ref is supported: ${ref}`);
  let node = root;
  for (const token of ref.slice(1).split("/").slice(1)) {
    node = node?.[token.replaceAll("~1", "/").replaceAll("~0", "~")];
  }
  if (node === undefined) throw new Error(`$ref not found: ${ref}`);
  return node;
}

function pointerToken(key) {
  return key.replaceAll("~", "~0").replaceAll("/", "~1");
}

function isType(value, type) {
  switch (type) {
    case "null":
      return value === null;
    case "array":
      return Array.isArray(value);
    case "object":
      return value !== null && typeof value === "object" && !Array.isArray(value);
    case "integer":
      return Number.isInteger(value);
    default:
      return typeof value === type;
  }
}

function equal(a, b) {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((k) => Object.hasOwn(b, k) && equal(a[k], b[k]));
}
