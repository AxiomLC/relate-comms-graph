import { useEffect, useState } from "react";
import { X } from "lucide-react";

/**
 * A plain modal shell. Escape closes, backdrop click closes, body scrolls.
 *
 * `side` docks the panel to the right edge instead of centring it, and narrows it.
 * That is for the Gravity panel: the point of that one is to change the layout while
 * watching the graph, so it must not sit on top of the thing it is changing.
 */
export default function Modal({
  title, onClose, children, footer, wide = false, side = false,
}) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className={`modal-backdrop${side ? " side" : ""}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`modal${wide ? " wide" : ""}${side ? " side" : ""}`}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-head">
          <span className="modal-title">{title}</span>
          <button className="ghost icon" style={{ marginLeft: "auto" }} onClick={onClose}>
            <X size={14} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

/**
 * A labelled slider. The value is shown because a slider without a number is a toy.
 *
 * `hint` is the hover tooltip; `note` is the always-visible one-liner under the
 * control. Both exist because a tooltip is invisible until you already know to look
 * for it, and these are knobs whose effect is not obvious from the name.
 */
export function Slider({ label, value, min, max, step = 1, onChange, hint, note }) {
  return (
    <div className="field" title={hint || ""}>
      <div className="field-row">
        <label>{label}</label>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <span className="value">{value}</span>
      </div>
      {note && <p className="field-note">{note}</p>}
    </div>
  );
}

/** A labelled checkbox. `note` is the always-visible line under it. */
export function Check({ label, checked, onChange, hint, note }) {
  return (
    <div className="field check-field" title={hint || ""}>
      <label className="check">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
        {label}
      </label>
      {note && <p className="field-note">{note}</p>}
    </div>
  );
}

/** A labelled text input, for the few values a slider cannot express. */
export function TextField({
  label, value, onChange, placeholder, hint, note, type = "text", autoComplete,
}) {
  return (
    <div className="field" title={hint || ""}>
      <div className="field-row">
        <label>{label}</label>
        <input
          type={type}
          value={value}
          placeholder={placeholder}
          autoComplete={autoComplete}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      {note && <p className="field-note">{note}</p>}
    </div>
  );
}

/** A small async loader: `useFetch(fn, deps)` -> {data, error, loading}. */
export function useFetch(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    fn()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((error) => {
        if (!cancelled) setState({ data: null, error: error.message, loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
