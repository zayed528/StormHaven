// A dropdown that matches the app's theme (rounded liquid-glass button + rounded glass option list), replacing the
// native <select>, whose option list is drawn by the operating system and can't be themed.   Owner: Nandan
// Accessible listbox pattern: the button announces its label + current value; the list is role="listbox".
// Keyboard: Enter / Space / Down opens; Up / Down / Home / End move; Enter selects; Esc / Tab close; typing a letter
// jumps to the next option starting with it.
// Props: label (visible text above), value, options [{ value, label }], onChange(value), placeholder (no value yet).
import React, { useEffect, useId, useRef, useState } from "react";

export default function ThemedSelect({ label, value, options, onChange, placeholder = "—", className = "" }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);            // highlighted option while the list is open
  const root = useRef(null);
  const list = useRef(null);
  const current = options.find((o) => o.value === value);

  // Opening highlights the current value; clicking anywhere else closes.
  useEffect(() => {
    if (!open) return;
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    const away = (e) => { if (!root.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the highlighted option in view in long lists (e.g. 110 circuits).
  useEffect(() => {
    if (open) list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const pick = (i) => { onChange(options[i].value); setOpen(false); };
  const onKey = (e) => {
    if (!open) {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) { e.preventDefault(); setOpen(true); }
      return;
    }
    const last = options.length - 1;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(last, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(last); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(active); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    else if (e.key === "Tab") setOpen(false);
    else if (e.key.length === 1) {               // type-ahead: next option starting with that letter
      const k = e.key.toLowerCase();
      const n = options.findIndex((o, i) => i > active && String(o.label).toLowerCase().startsWith(k));
      const wrap = options.findIndex((o) => String(o.label).toLowerCase().startsWith(k));
      if (n >= 0 || wrap >= 0) setActive(n >= 0 ? n : wrap);
    }
  };

  return (
    <div className={`tsel ${open ? "open" : ""} ${className}`} ref={root}>
      {label && <span className="tsel-label" id={`${id}-label`}>{label}</span>}
      <button type="button" className="tsel-button" aria-haspopup="listbox" aria-expanded={open}
        aria-labelledby={`${label ? `${id}-label ` : ""}${id}-value`} aria-controls={`${id}-list`}
        aria-activedescendant={open ? `${id}-opt-${active}` : undefined}
        onClick={() => setOpen(!open)} onKeyDown={onKey}>
        <span id={`${id}-value`} className="tsel-value">{current ? current.label : placeholder}</span>
        <svg className="tsel-chevron" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none"
          stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
      </button>
      {open && (
        <ul className="tsel-list" role="listbox" id={`${id}-list`} ref={list}
          aria-labelledby={label ? `${id}-label` : undefined} tabIndex={-1}>
          {options.map((o, i) => (
            <li key={o.value} id={`${id}-opt-${i}`} role="option" aria-selected={o.value === value}
              className={`${i === active ? "active" : ""} ${o.value === value ? "selected" : ""}`}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(i)}>
              {o.label}{o.value === value && <span className="tsel-check" aria-hidden="true">✓</span>}
            </li>))}
        </ul>)}
    </div>
  );
}
