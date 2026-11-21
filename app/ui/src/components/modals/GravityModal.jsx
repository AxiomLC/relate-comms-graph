import { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";

import { cloneTheme, resetTheme } from "../../config/theme.js";
import Modal, { Check, Slider } from "./Modal.jsx";

/**
 * Gravity — the force simulation and the label zoom threshold.
 *
 * **Its own modal, docked to the right, and deliberately narrow.** These knobs are
 * tuned by watching the graph, so the panel must not cover it. That is the whole
 * reason this is not a sub-page of Canvas any more: Canvas answers "what is drawn",
 * this answers "how is it arranged", and only the second one is adjusted live.
 *
 * Every control carries a one-line note under it as well as a hover tooltip. A
 * tooltip is invisible until you already know to look, and none of these names
 * explain themselves.
 *
 * Node sizes, icons, colours and edge widths are NOT here: they are dev knobs in
 * `config/theme.js`, and a slider that is moved once is clutter.
 */
export default function GravityModal({ theme, onChange, onClose, onRerunLayout }) {
  const [draft, setDraft] = useState(() => cloneTheme(theme));

  // Push every edit straight through, so the canvas re-styles as the slider moves.
  // The layout does not re-run on its own — a graph that keeps bobbing looks like a
  // physics toy — so the footer has an explicit button.
  useEffect(() => {
    onChange(draft);
  }, [draft, onChange]);

  const set = (group, key) => (value) =>
    setDraft((prev) => ({ ...prev, [group]: { ...prev[group], [key]: value } }));

  return (
    <Modal
      title="Gravity"
      onClose={onClose}
      side
      footer={
        <>
          <button
            className="ghost"
            onClick={() => {
              setDraft(resetTheme());
              onRerunLayout?.();
            }}
          >
            <RotateCcw size={13} /> Reset
          </button>
          <span className="spacer" />
          <button className="primary" onClick={onRerunLayout}>
            Re-run layout
          </button>
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
        hint="how hard nodes push each other apart"
        note="Higher spreads everything out. Lower lets clusters collapse."
      />
      <Slider
        label="idealEdgeLength"
        value={draft.physics.idealEdgeLength}
        min={2}
        max={200}
        step={1}
        onChange={set("physics", "idealEdgeLength")}
        hint="the length an edge wants to be"
        note="The main lever on edge length. Lower pulls the whole picture in. Keep above 2 — below that the spring math degenerates."
      />
      <Check
        label="smart edge length"
        checked={!!draft.physics.smartEdgeLength}
        onChange={set("physics", "smartEdgeLength")}
        hint="adds each bag's size to every edge that crosses it"
        note="On, a cross-platform edge gets hundreds of px of extra length. Off is much tighter."
      />
      <Slider
        label="gravity — inverted: left is stronger"
        value={3 - draft.physics.gravity}
        min={0}
        max={3}
        step={0.05}
        onChange={(value) => set("physics", "gravity")(3 - value)}
        hint="pulls everything toward the middle of the screen"
        note="Display is inverted so strong sits LEFT like the other levers: slider 0 = gravity 3 (strongest), slider 3 = gravity 0 (off). The stored value stays the plain gravity number."
      />
      <Slider
        label="gravityCompound"
        value={draft.physics.gravityCompound}
        min={0.05}
        max={6}
        step={0.05}
        onChange={set("physics", "gravityCompound")}
        hint="squeezes each platform bag toward its own centre"
        note="NEVER 0. At exactly 0 fcose's compound tiling stalls the solver — hang confirmed in the probe. 0.05 floor keeps it alive."
      />
      <Slider
        label="gravityRangeCompound"
        value={draft.physics.gravityRangeCompound}
        min={0.1}
        max={1.1}
        step={0.05}
        onChange={set("physics", "gravityRangeCompound")}
        hint="how far the bag pull reaches"
        note="Measured in bag radii. Range re-centered 2026-11-20: anything past ~1.1 was dead space; useful spread is 0.1-1.1."
      />
      <Slider
        label="nodeSeparation"
        value={draft.physics.nodeSeparation}
        min={10}
        max={200}
        step={5}
        onChange={set("physics", "nodeSeparation")}
        hint="initial spectral spacing only"
        note="Does not space the settled layout. Changing it rarely shows."
      />
      <Slider
        label="numIter"
        value={draft.physics.numIter}
        min={500}
        max={6000}
        step={250}
        onChange={set("physics", "numIter")}
        hint="how long the solver runs"
        note="1000 is fast and messy, 5000 is slow and settled."
      />
      <Slider
        label="zoomDistance"
        value={draft.physics.zoomDistance}
        min={1}
        max={3}
        step={0.1}
        onChange={set("physics", "zoomDistance")}
        hint="multiplies the zoom after the layout fits"
        note="Raise it if the graph lands too small to read."
      />
      <Slider
        label="wheelSensitivity"
        value={draft.physics.wheelSensitivity}
        min={1}
        max={8}
        step={0.2}
        onChange={set("physics", "wheelSensitivity")}
        hint="how fast the wheel zooms"
        note="The default of 1.0 feels broken on a trackpad."
      />
      <Check
        label="randomize before layout"
        checked={draft.physics.randomize}
        onChange={set("physics", "randomize")}
        hint="start nodes at random positions"
        note="Leave on. Fresh nodes all start at (0,0) and clicks land on the wrong one."
      />
      <Check
        label="count labels in the layout box"
        checked={!!draft.physics.nodeDimensionsIncludeLabels}
        onChange={set("physics", "nodeDimensionsIncludeLabels")}
        hint="the solver reserves room for the label"
        note="Off, it places an 18px node and draws a 120px label over its neighbours."
      />

      <h2 className="section">Bags — platforms around the outside</h2>
      <Check
        label="pin bags to a ring"
        checked={!!draft.layout.bagRing}
        onChange={set("layout", "bagRing")}
        hint="place each platform bag on a circle after the layout"
        note="Off, the bags float wherever the solver leaves them and the middle stops meaning anything."
      />
      <Slider
        label="ring spread"
        value={draft.layout.bagRingSpread}
        min={0.5}
        max={2.5}
        step={0.05}
        onChange={set("layout", "bagRingSpread")}
        hint="how wide the circle is"
        note="1.0 packs the bags shoulder to shoulder. Below 1.0 pulls them inward, shortening every bag-bridge edge; below ~0.65 the clusters overlap. Measured: edge length tracks the ring radius exactly."
      />

      <h2 className="section">Labels — a zoom reward</h2>
      <Slider
        label="min-zoomed-font-size"
        value={draft.labels.minZoomedFontSize}
        min={4}
        max={30}
        step={1}
        onChange={set("labels", "minZoomedFontSize")}
        hint="text is hidden below this size on screen"
        note="Labels appear as you zoom in, never on hover."
      />
      <Slider
        label="text-max-width"
        value={draft.labels.maxWidth}
        min={40}
        max={260}
        step={10}
        onChange={set("labels", "maxWidth")}
        hint="how wide a label may grow before wrapping"
        note="Wider labels are easier to read but collide more."
      />
    </Modal>
  );
}
