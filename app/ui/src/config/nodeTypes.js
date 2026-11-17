/**
 * Node types the canvas can draw, and how each one looks.
 *
 * The canvas draws Thread and Correspondent only (UI-Cytoscape.md §3). Message and
 * Attachment are listed because `types_present()` reports them and the Canvas
 * modal shows the real counts — but they are not drawable at this node count, and
 * the canvas refuses them rather than trying.
 */

export const NODE_TYPES = {
  Thread: {
    drawable: true,
    shape: "ellipse",
    label: "Thread",
    hint: "one conversation; size = message count",
  },
  Correspondent: {
    drawable: true,
    shape: "round-rectangle",
    label: "Correspondent",
    hint: "a person on one platform (not a Person)",
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
 * Correspondents use `PERSON_ICONS` below, so the two kinds never look alike.
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
 * Person glyphs, one per platform colour, for Correspondent nodes.
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
