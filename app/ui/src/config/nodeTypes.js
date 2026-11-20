/**
 * Node types the canvas can draw, and how each one looks.
 *
 * **This is the single place a kind is declared.** The canvas reads `drawable`,
 * `shape`, `sizeLadder`, `countKey`, `labelMax`, `edgeWeight`, `glow` and
 * `iconKind` from here rather than testing `node.type === "Thread"` strings, so
 * adding a kind is one entry and no component change (edit 3).
 *
 * `drawable` means "the canvas knows how to draw it", not "the server returns it by
 * default". `tools.DRAWABLE_NODE_TYPES` is the server-side default and is still
 * `Thread` + `Correspondent`; the four entity kinds are drawable here but hold zero
 * rows until body-entity extraction lands, so they are off in `filter.nodeTypes`
 * until someone ticks them.
 *
 * Message and Attachment are listed because `types_present()` reports them and the
 * Canvas modal shows the real counts — but they are not drawable at this node count,
 * and the canvas refuses them rather than trying.
 */

export const NODE_TYPES = {
  Thread: {
    drawable: true,
    shape: "ellipse",
    label: "Thread",
    hint: "one conversation; size = message count",
    // Which letters of the A..F ladder this kind may use, biggest first. Threads
    // skip B so a thread always outranks the correspondent of the same band.
    sizeLadder: ["A", "C", "E"],
    countKey: "message_count",
    labelMax: 34,
    // The field that weights an edge leaving this node. `WITH` stores no count, so
    // the thread's own size is the only signal the canvas has.
    edgeWeight: "message_count",
    // Only threads can be "silent" — a correspondent has no is_self of its own.
    hideWhenSilent: true,
    iconKind: "platform",
  },
  Correspondent: {
    drawable: true,
    shape: "ellipse",
    label: "Correspondent",
    hint: "a person on one platform (not a Person)",
    sizeLadder: ["B", "D", "F"],
    countKey: "thread_count",
    labelMax: 28,
    // Correspondents glow permanently, so they read as a different class of thing
    // against the threads. Selection therefore cannot also be a glow.
    glow: true,
    iconKind: "person",
  },
  // The four extracted kinds draw as the DEFAULT FILLED CIRCLE — no glyph, by
  // decision. `iconKind: null` is what makes that true: `nodeIcon()` returns null,
  // the `icon` class is never added, and the base `node` rule (a filled circle in
  // the platform colour) is what you see. Do not give them a glyph until there is
  // one file per platform colour, the way `PERSON_ICONS` has.
  Person: {
    drawable: true,
    shape: "ellipse",
    label: "Person",
    hint: "a name mentioned in a body — extraction, not ingest",
    sizeLadder: ["D", "E", "F"],
    countKey: "mention_count",
    labelMax: 28,
    glow: true,
    iconKind: null,
  },
  Place: {
    drawable: true,
    shape: "ellipse",
    label: "Place",
    hint: "a location mentioned in a body",
    sizeLadder: ["D", "E", "F"],
    countKey: "mention_count",
    labelMax: 28,
    glow: true,
    iconKind: null,
  },
  Organization: {
    drawable: true,
    shape: "ellipse",
    label: "Organization",
    hint: "a company or body mentioned in a body",
    sizeLadder: ["D", "E", "F"],
    countKey: "mention_count",
    labelMax: 28,
    glow: true,
    iconKind: null,
  },
  Product: {
    drawable: true,
    shape: "ellipse",
    label: "Product",
    hint: "a product or thing mentioned in a body",
    sizeLadder: ["D", "E", "F"],
    countKey: "mention_count",
    labelMax: 28,
    glow: true,
    iconKind: null,
  },
  Message: {
    drawable: false,
    label: "Message",
    hint: "12,499 of them — never drawn, only queried",
  },
  Attachment: {
    drawable: false,
    label: "Attachment",
    hint: "refs only, never bytes",
  },
};

/** The node types the canvas will actually draw, in declaration order. */
export const DRAWABLE_TYPES = Object.entries(NODE_TYPES)
  .filter(([, meta]) => meta.drawable)
  .map(([type]) => type);

/**
 * Platform colours. Fixed, not hashed, so the picture is identical on every load —
 * a graph that recolours itself between visits reads as noise.
 *
 * Chosen to sit inside the black/green palette: each is a desaturated tint that
 * reads at 8px and does not fight the light-blue selection glow.
 */
export const PLATFORM_COLORS = {
  messenger: "#3b6fd4", // medium blue (Facebook)
  telegram: "#3fb6b0", // aqua
  whatsapp: "#4caf50", // green
  linkedin: "#5cc8f0", // light blue
  email: "#d9534f", // red (Hostinger/Gmail both land here)
  gmail: "#d9534f",
  imap: "#d9534f",
  outlook: "#8b5cf6", // purple — its own leg, not a variant of Email
  sms: "#b8912a", // dark yellow
};

/**
 * Platform icons, one per platform, served from `app/static/icons/`.
 *
 * These are solid silhouettes recoloured to the platform's own colour, normalised
 * to a 24x24 viewBox so they all draw at the same weight. Used for **Threads**.
 * Correspondents and Persons use `PERSON_ICONS` below, so the two kinds never look
 * alike.
 *
 * Icons are the only node look — there is no circle mode.
 */
export const PLATFORM_ICONS = {
  messenger: "/static/icons/messenger.svg",
  telegram: "/static/icons/telegram.svg",
  whatsapp: "/static/icons/whatsapp.svg",
  linkedin: "/static/icons/linkedin.svg",
  email: "/static/icons/email.svg",
  gmail: "/static/icons/email.svg",
  imap: "/static/icons/email.svg",
  outlook: "/static/icons/outlook.svg",
  sms: "/static/icons/sms.svg",
};

export function platformIcon(platform) {
  return PLATFORM_ICONS[String(platform || "").toLowerCase()] || null;
}

/**
 * Person glyphs, one per platform colour, for Correspondent and Person nodes.
 *
 * Same silhouette as the source's own icon set — a solid fill baked into the file,
 * because Cytoscape cannot tint a `background-image`. Platforms that share a colour
 * (email / gmail / imap) share a file; Outlook has its own, in its own colour.
 */
export const PERSON_ICONS = {
  messenger: "/static/icons/person-messenger.svg",
  telegram: "/static/icons/person-telegram.svg",
  whatsapp: "/static/icons/person-whatsapp.svg",
  linkedin: "/static/icons/person-linkedin.svg",
  email: "/static/icons/person-email.svg",
  gmail: "/static/icons/person-email.svg",
  imap: "/static/icons/person-email.svg",
  outlook: "/static/icons/person-outlook.svg",
  sms: "/static/icons/person-sms.svg",
};

export function personIcon(platform) {
  return PERSON_ICONS[String(platform || "").toLowerCase()] || null;
}

/**
 * The glyph for one node, chosen by its KIND and then its platform.
 *
 * Only two kinds have glyphs today: a Thread draws its platform's glyph, a
 * Correspondent draws the person glyph. **`Person` / `Place` / `Organization` /
 * `Product` deliberately have none** — `iconKind: null` — so they draw as the base
 * filled circle. A glyph cannot be tinted at runtime, so each one would need a file
 * per platform colour the way `PERSON_ICONS` does; until then, a circle is the
 * honest look.
 */
export function nodeIcon(type, platform) {
  const kind = NODE_TYPES[type]?.iconKind;
  if (kind === "platform") return platformIcon(platform);
  if (kind === "person") return personIcon(platform);
  return null;
}

/**
 * The kind class for a node, or null.
 *
 * A thread is not a kind — its glyph already says which platform it is — so it gets
 * no class. A kind with a glyph carries `person`; the four extracted kinds carry
 * nothing, because they have no glyph and the class exists only to pick one.
 */
export function kindClass(type) {
  const kind = NODE_TYPES[type]?.iconKind;
  return kind && kind !== "platform" ? kind : null;
}

const FALLBACK_COLOR = "#6b7a90";

export function platformColor(platform) {
  return PLATFORM_COLORS[String(platform || "").toLowerCase()] || FALLBACK_COLOR;
}

/**
 * Human label for a platform key — the ONLY place the two spellings meet.
 *
 * The store key is `messenger` and must stay that way: it is part of every
 * `Message.key` (`platform:chat_id:message_id`), so renaming it would orphan every
 * existing row. The UI says **Facebook Messenger** — never bare "Messenger", which
 * reads as "a message" next to a Message node.
 *
 * The four email keys collapse to one label because they are one platform to a
 * reader; the store keeps them apart because the adapters differ.
 */
export const PLATFORM_LABELS = {
  messenger: "Fcbk Mssgr",
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  linkedin: "LinkedIn",
  email: "Email",
  gmail: "Email",
  imap: "Email",
  outlook: "Outlook",
  sms: "SMS",
};

export function platformLabel(platform) {
  const key = String(platform || "").toLowerCase();
  if (!key) return "unknown";
  return PLATFORM_LABELS[key] || key;
}

/**
 * Placeholder accounts are by design (TECHREADME.md §5): one `Facebook user` spans
 * 31 Facebook Messenger threads. A viewer must render it as a spam account, not as
 * a contact.
 */
const PLACEHOLDER_NAMES = new Set([
  "facebook user",
  "linkedin member",
  "instagram user",
  "unknown",
  "you",
]);

export function isPlaceholder(name) {
  return PLACEHOLDER_NAMES.has(String(name || "").trim().toLowerCase());
}

/** Truncate a label upstream so the graph and the Viewer agree on the string. */
export function truncateLabel(text, max = 42) {
  const value = String(text ?? "").trim();
  if (value.length <= max) return value;
  return value.slice(0, max - 1).trimEnd() + "…";
}
