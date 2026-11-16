import { useEffect, useState } from "react";
import { X } from "lucide-react";

/** A plain modal shell. Escape closes, backdrop click closes, body scrolls. */
export default function Modal({ title, onClose, children, footer, wide = false }) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true">
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

/** A labelled slider. The value is shown because a slider without a number is a toy. */
export function Slider({ label, value, min, max, step = 1, onChange, hint }) {
  return (
    <div className="field" title={hint || ""}>
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
  );
}

/** A labelled checkbox. */
export function Check({ label, checked, onChange, hint }) {
  return (
    <label className="check" title={hint || ""}>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  );
}

/** A labelled text input, for the few values a slider cannot express. */
export function TextField({ label, value, onChange, placeholder, hint }) {
  return (
    <div className="field" title={hint || ""}>
      <label>{label}</label>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
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
