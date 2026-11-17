import { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";

import { api } from "../../lib/api.js";
import { NODE_TYPES, PLATFORM_LABELS, platformColor } from "../../config/nodeTypes.js";
import { cloneTheme, resetTheme } from "../../config/theme.js";
import Modal, { Check, Slider, useFetch } from "./Modal.jsx";

/**
 * Canvas — what is drawn, and how much of it.
 *
 * This modal is deliberately split in two, because the two halves answer different
 * questions and were previously mixed together in one long list:
 *
 *  1. **What is on the canvas** (this modal). Sort, how many nodes, which node types,
 *     which platform clusters. These change *what you are looking at*.
 *  2. **Styling** (a sub-modal). Force simulation and the label zoom threshold. These
 *     change *how it looks*, and are used far less often.
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
  { key: "messages", label: "Most messages", hint: "the biggest threads first" },
  { key: "recent", label: "Most recent", hint: "the live ones first" },
  { key: "quiet", label: "Quietest", hint: "the ones that went silent first" },
];

const LIMITS = [500, 1000, 2000, 5000, 10000, 20000];

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
  onChange,
  onClose,
  onRerunLayout,
  graph,
  onReload,
  platforms,
}) {
  const [draft, setDraft] = useState(() => cloneTheme(theme));
  const [styling, setStyling] = useState(false);
  const types = useFetch(() => api.types(), []);

  // Push every edit straight through. The canvas re-styles; the layout only re-runs
  // when the user asks, because a graph that keeps bobbing looks like a physics toy.
  useEffect(() => {
    onChange(draft);
  }, [draft, onChange]);

  const set = (group, key) => (value) =>
    setDraft((prev) => ({ ...prev, [group]: { ...prev[group], [key]: value } }));

  const toggleType = (type) =>
    setDraft((prev) => {
      const current = prev.filter.nodeTypes;
      const next = current.includes(type)
        ? current.filter((value) => value !== type)
        : [...current, type];
      return { ...prev, filter: { ...prev.filter, nodeTypes: next } };
    });

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

  if (styling) {
    return (
      <StylingModal
        draft={draft}
        setDraft={setDraft}
        set={set}
        onBack={() => setStyling(false)}
        onClose={onClose}
        onRerunLayout={onRerunLayout}
      />
    );
  }

  return (
    <Modal
      title="Canvas"
      onClose={onClose}
      wide
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
          <button onClick={onRerunLayout}>Re-run layout</button>
        </>
      }
    >
      <h2 className="section" style={{ marginTop: 0 }}>Sort — which nodes survive the cutoff</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        The canvas draws a limited number of nodes. Whichever order is chosen decides
        which ones you can never see, so this is a real choice, not a preference.
      </div>
      {SORTS.map((sort) => (
        <Check
          key={sort.key}
          label={sort.label}
          checked={(draft.filter.sort || "messages") === sort.key}
          onChange={() => {
            setDraft((prev) => ({
              ...prev,
              filter: { ...prev.filter, sort: sort.key },
            }));
            onReload?.({ sort: sort.key });
          }}
          hint={sort.hint}
        />
      ))}

      <h2 className="section">How many nodes</h2>
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
              onReload?.({ limit: value });
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

      <h2 className="section">Node types</h2>
      {Object.entries(NODE_TYPES).map(([type, meta]) => {
        const count = types.data?.node_types?.find((entry) => entry.type === type)?.count;
        return (
          <Check
            key={type}
            label={`${meta.label}${count != null ? ` (${count.toLocaleString()})` : ""}${
              meta.drawable ? "" : " — not drawable"
            }`}
            checked={draft.filter.nodeTypes.includes(type)}
            onChange={() => toggleType(type)}
            hint={meta.hint}
          />
        );
      })}

      <h2 className="section">Viewable platforms</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        All on by default. Toggle one off to hide its cluster from the canvas — it stays
        fully searchable, and the AI chat still sees it. This is <em>not</em>{" "}
        <strong>Utilities</strong>, which narrows what the tools return.
      </div>
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
          <span style={{ minWidth: 90 }}>
            {PLATFORM_LABELS[row.platform] || row.platform}
          </span>
          <span className="pager-info">
            {row.built ? `${row.count.toLocaleString()} messages` : "not built yet"}
          </span>
        </label>
      ))}

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
      />

      <div style={{ marginTop: 18 }}>
        <button className="ghost" onClick={() => setStyling(true)}>
          Styling — force and labels
        </button>
      </div>
    </Modal>
  );
}

/**
 * Styling — the sub-modal. Force simulation and the label zoom threshold only.
 *
 * Node sizes, icons, colours and edge widths are deliberately absent: they are dev
 * knobs in `config/theme.js`, and a slider that is moved once is clutter.
 */
function StylingModal({ draft, setDraft, set, onBack, onClose, onRerunLayout }) {
  return (
    <Modal
      title="Styling"
      onClose={onClose}
      footer={
        <>
          <button
            className="ghost"
            onClick={() => {
              setDraft(resetTheme());
              onRerunLayout?.();
            }}
          >
            <RotateCcw size={13} /> Reset to defaults
          </button>
          <span className="spacer" />
          <button className="ghost" onClick={onBack}>
            Back
          </button>
          <button onClick={onRerunLayout}>Re-run layout</button>
        </>
      }
    >
      <h2 className="section" style={{ marginTop: 0 }}>Force — fcose</h2>
      <Slider
        label="nodeRepulsion"
        value={draft.physics.nodeRepulsion}
        min={2000}
        max={60000}
        step={1000}
        onChange={set("physics", "nodeRepulsion")}
        hint="8000 = tight clumps, 40000 = airy"
      />
      <Slider
        label="idealEdgeLength"
        value={draft.physics.idealEdgeLength}
        min={20}
        max={200}
        step={5}
        onChange={set("physics", "idealEdgeLength")}
        hint="40 = dense, 120 = sparse"
      />
      <Slider
        label="gravity"
        value={draft.physics.gravity}
        min={0}
        max={1}
        step={0.05}
        onChange={set("physics", "gravity")}
        hint="0 = drifts apart, 0.5 = pulled into a ball"
      />
      <Slider
        label="nodeSeparation"
        value={draft.physics.nodeSeparation}
        min={10}
        max={200}
        step={5}
        onChange={set("physics", "nodeSeparation")}
        hint="between disconnected components only"
      />
      <Slider
        label="numIter"
        value={draft.physics.numIter}
        min={500}
        max={6000}
        step={250}
        onChange={set("physics", "numIter")}
        hint="1000 = fast and messy, 5000 = slow and settled"
      />
      <Slider
        label="zoomDistance"
        value={draft.physics.zoomDistance}
        min={1}
        max={3}
        step={0.1}
        onChange={set("physics", "zoomDistance")}
        hint="multiplies the post-layout fit zoom"
      />
      <Slider
        label="wheelSensitivity"
        value={draft.physics.wheelSensitivity}
        min={1}
        max={8}
        step={0.2}
        onChange={set("physics", "wheelSensitivity")}
        hint="default 1.0 is genuinely slow"
      />
      <Check
        label="randomize node positions before layout"
        checked={draft.physics.randomize}
        onChange={set("physics", "randomize")}
        hint="mandatory in practice: fresh nodes all start at (0,0) and clicks land wrong"
      />

      <h2 className="section">Labels — a zoom reward</h2>
      <Slider
        label="min-zoomed-font-size"
        value={draft.labels.minZoomedFontSize}
        min={4}
        max={30}
        step={1}
        onChange={set("labels", "minZoomedFontSize")}
        hint="text is hidden when font-size × zoom falls below this"
      />
      <Slider
        label="text-max-width"
        value={draft.labels.maxWidth}
        min={40}
        max={260}
        step={10}
        onChange={set("labels", "maxWidth")}
        hint="px, with text-wrap: wrap"
      />
    </Modal>
  );
}
