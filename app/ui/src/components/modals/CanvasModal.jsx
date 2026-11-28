import { Fragment, useState } from "react";

import { api } from "../../lib/api.js";
import { NODE_TYPES, PLATFORM_LABELS, platformColor } from "../../config/nodeTypes.js";
import { cloneTheme } from "../../config/theme.js";
import Modal, { Check, useFetch } from "./Modal.jsx";

/**
 * Canvas — what is drawn, and how much of it.
 *
 * **Two modals, two questions.** This one answers *what is on the canvas*: sort, how
 * many nodes, which node types, which platform clusters. `Gravity` (its own title-bar
 * button) answers *how it is arranged*: the force simulation and the label threshold.
 * They are separate because only the second is tuned while watching the graph, so it
 * docks to the right instead of covering the canvas.
 *
 * Everything else — icons, colours, edge widths, node sizes — is a **dev knob** in
 * `config/theme.js`. It is not exposed here on purpose: a control that only ever gets
 * moved once is clutter in a modal that is opened often.
 *
 * Two rules this modal must not break:
 *
 *  - **The platform toggle here is view-only.** It hides clusters from the canvas and
 *    nothing else. `Utilities` is the other thing: it narrows what the *tools* return,
 *    so search and the AI chat see less. They are different operations and must not be
 *    merged.
 *  - **A hidden node is not a deleted node.** `limit` truncates, so the footer states
 *    the real total and offers "show more" rather than pretending the canvas is the
 *    store.
 */

const SORTS = [
  {
    key: "messages",
    label: "Most messages",
    hint: "the biggest threads first",
    note: "Busiest conversations first.",
  },
  {
    key: "recent",
    label: "Most recent",
    hint: "the live ones first",
    note: "Whatever was active last.",
  },
  {
    key: "quiet",
    label: "Quietest",
    hint: "the ones that went silent first",
    note: "The threads that stopped.",
  },
];

const LIMITS = [500, 1000, 2000, 5000, 10000, 20000];

/**
 * The rows of the "Show node types" grid.
 *
 * **Three mutually exclusive states per row**, one radio group each:
 *
 *   all    — merged and single-platform nodes of this kind.
 *   merged — only the cross-platform ones (the `bag:merged` population).
 *   hide   — none of this kind, merged or not.
 *
 * There is no "singles only": the useful axis is everything / the strong
 * cross-platform claims / nothing. And it is a radio group precisely because the
 * states contradict each other — two checkboxes could express "neither", which no
 * reader could interpret.
 *
 * `Correspondent` and `Person` are placeholders: the row exists so the control reads
 * as a complete list, but it is greyed and disabled. Correspondent is the largest drawn
 * population and is deliberately left alone until the other three have been lived with;
 * `Person` has no extractor and no rows — it is a placeholder, and `canon`'s `person`
 * kind is a string fold used by Correspondents, not a graph node type.
 */
const SHOW_ROWS = [
  { type: "Correspondent", label: "Correspondent", placeholder: true },
  { type: "Place", label: "Place" },
  { type: "Product", label: "Product" },
  { type: "Organization", label: "Organization" },
  { type: "Person", label: "Person", placeholder: true },
];

const VISIBILITY_MODES = [
  { value: "all", label: "show all" },
  { value: "merged", label: "merged only" },
  { value: "hide", label: "hide" },
];

/**
 * Is this platform drawn?
 *
 * An empty `platforms` list means "not chosen yet", which is every platform on — so
 * a platform added later appears without the user ticking it. Once the user has
 * toggled anything the list is explicit and is read literally.
 */
function isPlatformOn(chosen, platform, rows) {
  if (!chosen || chosen.length === 0) return true;
  return chosen.includes(platform);
}

export default function CanvasModal({
  theme,
  onClose,
  onApply,
  graph,
  platforms,
}) {
  const [draft, setDraft] = useState(() => cloneTheme(theme));
  const types = useFetch(() => api.types(), []);

  // **Nothing here is pushed live.** The draft is local until "Re-run layout" is
  // pressed, and then `onApply` saves it, fetches the slice it describes and re-solves
  // — the Gravity modal's model exactly. An edit to the draft never touches `theme`, so
  // it cannot trigger a rebuild or a fetch on its own.
  const apply = () => {
    onApply?.(draft);
    // **Stays open**, like the Gravity modal. Re-running the layout is something you
    // watch happen; closing the panel hid the result and forced a reopen to adjust
    // again.
  };

  const set = (group, key) => (value) =>
    setDraft((prev) => ({ ...prev, [group]: { ...prev[group], [key]: value } }));

  /** Set one kind's three-way state. Radio, so this replaces rather than merges. */
  const setVisibility = (type, mode) =>
    setDraft((prev) => ({
      ...prev,
      filter: {
        ...prev.filter,
        nodeVisibility: { ...prev.filter.nodeVisibility, [type]: mode },
      },
    }));

  /**
   * Toggle one platform, materialising the "all on" default first.
   *
   * `platforms: []` means "not chosen yet", which reads as every platform on. The
   * first click therefore has to expand that into an explicit list, or turning one
   * off would turn everything else off with it.
   */
  const togglePlatform = (platform) =>
    setDraft((prev) => {
      const all = (platforms?.rows || []).map((row) => row.platform);
      const current = prev.filter.platforms.length ? prev.filter.platforms : all;
      const next = current.includes(platform)
        ? current.filter((value) => value !== platform)
        : [...current, platform];
      return { ...prev, filter: { ...prev.filter, platforms: next } };
    });

  const shown = graph?.counts?.nodes ?? 0;
  const total = graph?.total ?? shown;
  const hidden = Math.max(0, total - shown);

  return (
    <Modal
      title="Canvas"
      onClose={onClose}
      side
      footer={
        <>
          <span className="pager-info">
            {shown.toLocaleString()} of {total.toLocaleString()} nodes
            {hidden > 0 ? ` · ${hidden.toLocaleString()} hidden` : ""}
          </span>
          <span className="spacer" />
          <button className="ghost" onClick={onClose}>
            Close
          </button>
          <button className="primary" onClick={apply}>
            Re-run layout
          </button>
        </>
      }
    >
      <h2 className="section" style={{ marginTop: 0 }}>Shortened graph view</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        Sort and view only:
      </div>
      {/* **Horizontal.** These sort with `filter.sort`; they are one exclusive choice of
          three, so they belong side by side like the `How many nodes` limits below —
          three stacked rows wasted the width the sidebar already has. */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
        {SORTS.map((sort) => (
          <button
            key={sort.key}
            className={(draft.filter.sort || "messages") === sort.key ? "active" : "ghost"}
            title={sort.hint}
            onClick={() => {
              setDraft((prev) => ({
                ...prev,
                filter: { ...prev.filter, sort: sort.key },
              }));
            }}
          >
            {sort.label}
          </button>
        ))}
      </div>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 6 }}>
        {SORTS.map((s) => s.note).join("  ·  ")}
      </div>

      <h2 className="section">How many nodes</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        Viewable graph; but full graph still searchable.
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
        {LIMITS.map((value) => (
          <button
            key={value}
            className={(draft.filter.limit || 2000) === value ? "active" : "ghost"}
            onClick={() => {
              setDraft((prev) => ({
                ...prev,
                filter: { ...prev.filter, limit: value },
              }));
            }}
          >
            {value.toLocaleString()}
          </button>
        ))}
      </div>
      {hidden > 0 && (
        <div className="empty" style={{ paddingTop: 0 }}>
          {hidden.toLocaleString()} nodes are not drawn. Raise the number above, or
          change the sort, to reach them. Search and the AI chat always see the whole
          store — this cutoff is the canvas only.
        </div>
      )}

      <h2 className="section">Show node types</h2>
      {/* One radio group per row. The three states are one population described three
          ways, so they cannot be multi-selected: "hide" plus "merged only" is not a
          preference, it is a contradiction. */}
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        Merged nodes are the ones spanning platforms — they live in the central bag.
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 76px 76px 56px",
          gap: "2px 6px",
          alignItems: "center",
        }}
      >
        <span />
        {VISIBILITY_MODES.map((mode) => (
          <span
            key={mode.value}
            className="empty"
            style={{ textAlign: "center", paddingBottom: 2 }}
          >
            {mode.label}
          </span>
        ))}
        {SHOW_ROWS.map(({ type, label, placeholder }) => {
          const count = types.data?.node_types?.find((entry) => entry.type === type)?.count;
          const current = placeholder
            ? "all"
            : draft.filter.nodeVisibility?.[type] || "all";
          return (
            <Fragment key={type}>
              <span
                style={{
                  opacity: placeholder ? 0.4 : 1,
                  cursor: placeholder ? "not-allowed" : "default",
                }}
                title={placeholder ? "Placeholder — not wired" : NODE_TYPES[type]?.hint}
              >
                {label}
                {count != null ? ` (${count.toLocaleString()})` : ""}
                {placeholder ? " — placeholder" : ""}
              </span>
              {VISIBILITY_MODES.map((mode) => (
                <input
                  key={mode.value}
                  type="radio"
                  name={`visibility-${type}`}
                  disabled={!!placeholder}
                  checked={!placeholder && current === mode.value}
                  onChange={() => setVisibility(type, mode.value)}
                  style={{ justifySelf: "center" }}
                />
              ))}
            </Fragment>
          );
        })}
      </div>

      <h2 className="section">Viewable platforms</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        All on by default. Not <strong>Utilities</strong>, which narrows what the tools
        return.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 10px" }}>
        {(platforms?.rows || []).map((row) => (
          <label key={row.platform} className="check" style={{ marginBottom: 6 }}>
            <input
              type="checkbox"
              checked={isPlatformOn(draft.filter.platforms, row.platform, platforms?.rows)}
              onChange={() => togglePlatform(row.platform)}
            />
            <span
              className="legend-swatch"
              style={{ background: platformColor(row.platform), marginRight: 2 }}
            />
            <span>{PLATFORM_LABELS[row.platform] || row.platform}</span>
          </label>
        ))}
      </div>

      <h2 className="section">Threads you never spoke in</h2>
      <Check
        label="Hide threads where the owner never sent a message"
        checked={!!draft.filter.hideSilent}
        onChange={(value) =>
          setDraft((prev) => ({
            ...prev,
            filter: { ...prev.filter, hideSilent: value },
          }))
        }
        hint="View only. A thread you never replied in is often a broadcast or a group you were added to — hidden here, still searchable."
        note="A thread you never replied in is usually a broadcast or a group you were added to."
      />

      <h2 className="section">Threads nobody replied to</h2>
      <Check
        label="Hide threads where only the owner sent messages"
        checked={!!draft.filter.hideBroadcast}
        onChange={(value) =>
          setDraft((prev) => ({
            ...prev,
            filter: { ...prev.filter, hideBroadcast: value },
          }))
        }
        hint="View only. A cold-email campaign with no replies lands in one thread, so 30 recipients can look like a 30-message conversation. Hidden here, still searchable."
        note="A thread where nobody but you spoke is an outbound campaign, not a conversation."
      />
    </Modal>
  );
}
