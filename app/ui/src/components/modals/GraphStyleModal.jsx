import { Fragment, useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";

import { api } from "../../lib/api.js";
import { NODE_TYPES } from "../../config/nodeTypes.js";
import { cloneTheme, resetTheme } from "../../config/theme.js";
import Modal, { Check, Slider, useFetch } from "./Modal.jsx";

/**
 * Graph Style: force simulation and visuals, live (UI-Cytoscape.md §12).
 *
 * This modal is the visible payoff of keeping every tunable in one config object
 * (`config/theme.js`). It edits a draft and calls `onChange` on every move, so the
 * canvas updates while the slider is dragged.
 *
 * The filter group is **view-only**. Hiding a node type changes what is drawn and
 * nothing else — a hidden toggle must never narrow what an agent can query.
 */
/**
 * The six lettered sizes, editable in place.
 *
 * There are no thresholds here any more: a node's letter is computed per source
 * (`assignBands` in GraphCanvas), so the only thing to tune is how big each letter
 * draws. Which letters a kind may use is fixed in `theme.js` §tiers.
 */
function SizeTable({ sizes, onChange }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "28px 1fr 1fr",
        gap: "4px 8px",
        alignItems: "center",
        fontSize: 11,
        marginBottom: 14,
      }}
    >
      <span className="pager-info">#</span>
      <span className="pager-info">size</span>
      <span className="pager-info">font</span>
      {Object.entries(sizes).map(([letter, row]) => (
        <Fragment key={letter}>
          <span className="pager-info">{letter}</span>
          <input
            type="number"
            value={row.size}
            min={2}
            onChange={(event) => onChange(letter, "size", Number(event.target.value))}
          />
          <input
            type="number"
            value={row.font}
            min={4}
            onChange={(event) => onChange(letter, "font", Number(event.target.value))}
          />
        </Fragment>
      ))}
    </div>
  );
}

export default function GraphStyleModal({ theme, onChange, onClose, onRerunLayout }) {
  const [draft, setDraft] = useState(() => cloneTheme(theme));
  const types = useFetch(() => api.types(), []);

  // Push every edit straight through. The canvas re-styles; the layout only re-runs
  // when the user asks, because a graph that keeps bobbing looks like a physics toy.
  useEffect(() => {
    onChange(draft);
  }, [draft, onChange]);

  const set = (group, key) => (value) =>
    setDraft((prev) => ({ ...prev, [group]: { ...prev[group], [key]: value } }));

  /** Edit one cell of the lettered size table. */
  const setSize = (letter, key, value) =>
    setDraft((prev) => ({
      ...prev,
      tiers: {
        ...prev.tiers,
        sizes: {
          ...prev.tiers.sizes,
          [letter]: { ...prev.tiers.sizes[letter], [key]: value },
        },
      },
    }));

  const toggleType = (type) =>
    setDraft((prev) => {
      const current = prev.filter.nodeTypes;
      const next = current.includes(type)
        ? current.filter((value) => value !== type)
        : [...current, type];
      return { ...prev, filter: { ...prev.filter, nodeTypes: next } };
    });

  return (
    <Modal
      title="Graph Style"
      onClose={onClose}
      wide
      footer={
        <>
          <button
            className="ghost"
            onClick={() => {
              const fresh = resetTheme();
              setDraft(fresh);
              onRerunLayout?.();
            }}
          >
            <RotateCcw size={13} /> Reset to defaults
          </button>
          <span className="spacer" />
          <button className="ghost" onClick={onClose}>
            Close
          </button>
          <button onClick={onRerunLayout}>Re-run layout</button>
        </>
      }
    >
      <h2 className="section" style={{ marginTop: 0 }}>Physics — fcose</h2>
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


      <h2 className="section">Sizes — A to F, computed per source</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        Each source is banded on its own, so a small platform is not flattened by a
        big one. Threads use A / C / E (A is the standout, so they skip B);
        correspondents use B / D / F. The ladders interleave, so a thread always
        outranks the correspondent of the same band. Person, Place, Organization and
        Thing will use D / E / F.
      </div>
      <SizeTable
        sizes={draft.tiers.sizes}
        onChange={(letter, key, value) => setSize(letter, key, value)}
      />

      <h2 className="section">Visual</h2>
      <Check
        label="draw threads as their source icon"
        checked={draft.visual.nodeIcons}
        onChange={set("visual", "nodeIcons")}
        hint="Threads only. Correspondents stay as glowing rounded rects, so the two kinds never look alike."
      />
      <Slider
        label="thread icon size (% of node)"
        value={Math.round(draft.visual.iconScale * 100)}
        min={40}
        max={100}
        step={2}
        onChange={(value) => set("visual", "iconScale")(value / 100)}
        hint="only applies when icons are on"
      />
      <Check
        label="draw correspondents as a person glyph"
        checked={draft.visual.correspondentIcons}
        onChange={set("visual", "correspondentIcons")}
        hint="The glyph replaces the fill; the glow and border stay, in the node's own source colour."
      />
      <Slider
        label="person glyph size (% of node)"
        value={Math.round(draft.visual.correspondentIconScale * 100)}
        min={40}
        max={100}
        step={2}
        onChange={(value) => set("visual", "correspondentIconScale")(value / 100)}
        hint="a person silhouette is narrow, so it needs more than a round glyph"
      />
      <Slider
        label="correspondent glow (shadow-blur)"
        value={draft.visual.correspondentGlow}
        min={0}
        max={40}
        step={1}
        onChange={set("visual", "correspondentGlow")}
        hint="permanent, in the node's own source colour"
      />
      <Slider
        label="correspondent glow opacity"
        value={draft.visual.correspondentGlowOpacity}
        min={0}
        max={1}
        step={0.05}
        onChange={set("visual", "correspondentGlowOpacity")}
      />
      <Slider
        label="selection glow (shadow-blur)"
        value={draft.visual.glowBlur}
        min={0}
        max={60}
        step={2}
        onChange={set("visual", "glowBlur")}
        hint="doubled for the selected node, which is white"
      />
      <Slider
        label="shade jitter within a source"
        value={draft.visual.shadeJitter}
        min={0}
        max={0.4}
        step={0.02}
        onChange={set("visual", "shadeJitter")}
        hint="0 = every node identical, 0.3 = noisy"
      />
      <Slider
        label="background haze"
        value={draft.visual.hazeOpacity}
        min={0}
        max={0.4}
        step={0.01}
        onChange={set("visual", "hazeOpacity")}
      />

      <h2 className="section">Reveal</h2>
      <Check
        label="bloom nodes in ts_utc order on load"
        checked={draft.reveal.enabled}
        onChange={set("reveal", "enabled")}
        hint="highest impact per effort for a demo"
      />
      <Slider
        label="duration (ms)"
        value={draft.reveal.durationMs}
        min={400}
        max={6000}
        step={100}
        onChange={set("reveal", "durationMs")}
      />

      <h2 className="section">Filter — view only</h2>
      <div className="empty" style={{ paddingTop: 0, paddingBottom: 8 }}>
        This changes what is <em>drawn</em>. It never narrows what the AI or MCP can query.
      </div>
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
    </Modal>
  );
}
