/**
 * placeholders.ts
 * ----------------
 * Was imported by index.ts (`crawlPlaceholders`, `missingFields`,
 * `extractDefault`, `replaceByShortKey`) but never uploaded — the SDK
 * doesn't compile without it. Implemented fresh against the schema shape
 * converter.py actually emits (verified against converter.py directly,
 * not guessed), which uses TWO distinct placeholder syntaxes:
 *
 *   1. Value placeholders — sit as the value of a key inside `class` or
 *      `body` (and nested body groups): '{{DataType=str, Default=$env.X}}'.
 *      These are what getInputForm()'s fields come from, and what a
 *      filled-in form value replaces.
 *
 *   2. Reference placeholders — single-brace, sit INSIDE a string
 *      elsewhere in the schema and point at a class field by name:
 *      headers.Authorization = "Bearer {authorization}", and the OpenAPI
 *      path template itself, e.g. url = ".../users/{id}". These must be
 *      resolved AFTER the value placeholders are, since they reference
 *      the resolved value, not the placeholder marker.
 *
 * index.ts's original buildSchema() only ever handled (1) — it replaced
 * `{{...}}` markers in class/body but never substituted the resulting
 * values back into `{authorization}`/`{id}`-style references in headers
 * or url. That's a real functional gap on top of this file being
 * missing; index.ts is patched separately to call resolveReferences()
 * after filling class placeholders.
 */

const VALUE_PLACEHOLDER = /^\{\{\s*DataType\s*=\s*(\w+)\s*(?:,\s*Default\s*=\s*(.+?))?\s*\}\}$/;
const REFERENCE_PLACEHOLDER = /\{([\w-]+)\}/g;

export type Section = "class" | "body";

/** One located placeholder: which section, its dot-path within that section, and the raw '{{...}}' string. */
export interface MatchedItem {
  section: Section;
  path: string[]; // e.g. ["address", "street"] for a nested body group; ["CLIENT_ID"] for a top-level field
  raw: string; // the original '{{DataType=..., Default=...}}' string
}

export interface CrawlResult {
  /** "class.email" / "body.address.street" -> MatchedItem. The dot-path IS the FormField.key used by getInputForm/buildSchema. */
  matchedItems: Record<string, MatchedItem>;
  /** Currently identical to matchedItems — kept as a separate param (rather than folded into matchedItems) so
   *  replaceByShortKey's signature matches how index.ts already calls it: (schema, keyValue, key, value). */
  keyValue: Record<string, MatchedItem>;
}

function isValuePlaceholder(v: unknown): v is string {
  return typeof v === "string" && VALUE_PLACEHOLDER.test(v);
}

function walk(node: unknown, section: Section, path: string[], out: Record<string, MatchedItem>): void {
  if (node === null || typeof node !== "object") return;
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const nextPath = [...path, key];
    if (isValuePlaceholder(value)) {
      out[`${section}.${nextPath.join(".")}`] = { section, path: nextPath, raw: value as string };
    } else if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      walk(value, section, nextPath, out);
    }
    // Arrays of primitives/objects inside body aren't emitted by
    // converter.py today (_build_body_payload only ever produces flat
    // or nested-object fields, never arrays) — intentionally not
    // walked here; extend this branch if that changes.
  }
}

/**
 * Finds every value placeholder in schema.class and schema.body (recursing
 * into nested body groups). 'authorization' inside class is included like
 * any other field — buildSchema's own Default=$env. handling is what
 * treats it specially, not this function.
 */
export function crawlPlaceholders(schema: any): CrawlResult {
  const matchedItems: Record<string, MatchedItem> = {};
  if (schema.class) walk(schema.class, "class", [], matchedItems);
  if (schema.body) walk(schema.body, "body", [], matchedItems);
  return { matchedItems, keyValue: matchedItems };
}

/** Dot-path keys present in matchedItems but absent from fieldValues. */
export function missingFields(
  matchedItems: Record<string, MatchedItem>,
  fieldValues: Record<string, unknown>
): string[] {
  return Object.keys(matchedItems).filter((k) => !(k in fieldValues));
}

/**
 * Parses the 'Default=...' portion of a '{{DataType=..., Default=...}}'
 * marker. Returns null if there's no default (field is genuinely
 * required with nothing to fall back on).
 *
 * A default that needs to contain a LITERAL leading '$env.' (not an env
 * lookup) can be escaped with a leading '/' — e.g. 'Default=/$env.literal'
 * — mirroring the escape convention buildSchema() already expects
 * (`rawDefault.startsWith("/")` in index.ts predates this file and is
 * left as-is here, not invented for this port).
 */
export function extractDefault(placeholder: MatchedItem | string): string | null {
  const raw = typeof placeholder === "string" ? placeholder : placeholder.raw;
  const m = VALUE_PLACEHOLDER.exec(raw);
  if (!m || m[2] === undefined) return null;
  return m[2].trim();
}

/**
 * Writes `value` at matchedItems[key]'s location inside `schema`, mutating
 * and returning the same schema object (index.ts calls this repeatedly
 * across one buildSchema() run and expects each call's effect to be
 * visible to the next — mutation is intentional here, unlike dispatcher.ts's
 * hydrate() which deliberately returns a fresh copy for a different reason:
 * hydrate() resolves a LIVE credential inside dispatch() and must never let
 * that resolved token leak into anything held elsewhere; buildSchema()
 * only ever fills placeholders with the caller's own field values before
 * handing the result straight back to that same caller, so there's
 * nothing sensitive to protect from a second reference to the same object).
 */
export function replaceByShortKey(
  schema: any,
  keyValue: Record<string, MatchedItem>,
  key: string,
  value: unknown
): any {
  const item = keyValue[key];
  if (!item) return schema;

  let node = schema[item.section];
  for (let i = 0; i < item.path.length - 1; i++) {
    node = node[item.path[i]];
  }
  node[item.path[item.path.length - 1]] = value;
  return schema;
}

/**
 * Second pass: substitutes single-brace {name} references anywhere in a
 * string — headers.Authorization = "Bearer {authorization}", or the url
 * template itself, e.g. ".../users/{id}" — with the now-resolved value of
 * schema.class[name]. Must run AFTER every class placeholder has already
 * been filled via replaceByShortKey, or {authorization}/{id} would be
 * substituted with the raw unresolved marker string instead of the real
 * value.
 */
export function resolveReferences(value: string, resolvedClass: Record<string, unknown>): string {
  return value.replace(REFERENCE_PLACEHOLDER, (whole, name) => {
    if (!(name in resolvedClass)) return whole; // leave unresolvable refs as-is rather than silently blanking them
    const v = resolvedClass[name];
    return typeof v === "string" ? v : JSON.stringify(v);
  });
}