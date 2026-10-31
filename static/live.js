// Teach-Once live recorder: injected into every page of the browser teach_live.py opens; sends DOM events to Python.
(() => {
  if (window !== window.top) return;
  const { describe, interactive, option } = globalThis.TeachOnceDescribe;
  const typingSince = new WeakMap(); // field -> when typing started, so a fill is timed at its start

  function valueOf(el) {
    if (el.type === "password") return "***";
    if (el.tagName === "SELECT") return el.options[el.selectedIndex]?.text || "";
    return el.value;
  }

  function record(type, el, extra = {}) {
    const ts = (type === "change" && typingSince.get(el)) || Date.now();
    typingSince.delete(el);
    window.__teachOnceEvent({
      ts,
      type,
      url: location.pathname + location.search,
      target: el ? describe(el) : null,
      viewport: [innerWidth, innerHeight],
      dpr: devicePixelRatio,
      ...extra,
    });
  }

  addEventListener("pointerdown", (e) => option(e.target) && record("click", option(e.target)), true);
  addEventListener("click", (e) => option(e.target) || record("click", interactive(e.target)), true);
  addEventListener("change", (e) => record("change", e.target, { value: valueOf(e.target), checked: !!e.target.checked }), true);
  addEventListener("input", (e) => typingSince.has(e.target) || typingSince.set(e.target, Date.now()), true);
  addEventListener("submit", (e) => record("submit", e.target), true);
  addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === "Tab") record("keydown", e.target, { key: e.key });
  }, true);
})();
