// Describes DOM elements the way Teach-Once locates them. Used by the teach studio and, injected, by heal.
globalThis.TeachOnceDescribe = (() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 120);
  const INTERACTIVE = "a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], " +
    "[role=checkbox], [role=radio], [role=switch], [role=combobox], [role=textbox], [role=tab], [role=menuitem]";

  function role(el) {
    if (el.getAttribute("role")) return el.getAttribute("role");
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (tag === "a" && el.hasAttribute("href")) return "link";
    if (tag === "button") return "button";
    if (tag === "select") return el.multiple ? "listbox" : "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "tr") return "row";
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "input") {
      if (["checkbox", "radio"].includes(type)) return type;
      if (["submit", "button", "reset", "image"].includes(type)) return "button";
      if (["text", "email", "tel", "search", "url"].includes(type)) return "textbox";
      if (type === "number") return "spinbutton";
    }
    return "";
  }

  function labelText(el) {
    const doc = el.ownerDocument;
    if (el.id) {
      const label = doc.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label) return clean(label.innerText);
    }
    const wrap = el.closest("label");
    return wrap ? clean(wrap.innerText) : "";
  }

  function accessibleName(el) {
    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));
    const by = el.getAttribute("aria-labelledby");
    if (by) return clean(by.split(/\s+/).map((id) => el.ownerDocument.getElementById(id)?.innerText).join(" "));
    const label = labelText(el);
    if (label) return label;
    const tag = el.tagName.toLowerCase();
    if (["a", "button", "tr", "td", "th"].includes(tag) || /^h[1-6]$/.test(tag)) return clean(el.innerText);
    if (tag === "input" && ["submit", "button"].includes(el.type)) return clean(el.value);
    return clean(el.getAttribute("placeholder") || el.getAttribute("title"));
  }

  function cssPath(el) {
    const doc = el.ownerDocument;
    if (el.id && doc.querySelectorAll(`#${CSS.escape(el.id)}`).length === 1) return `#${CSS.escape(el.id)}`;
    const parts = [];
    for (let node = el; node && node.nodeType === 1 && node !== doc.body; node = node.parentElement) {
      let part = node.tagName.toLowerCase();
      if (node.id) part = `#${CSS.escape(node.id)}`;
      else {
        const same = [...(node.parentElement?.children || [])].filter((c) => c.tagName === node.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      const selector = parts.join(" > ");
      if (doc.querySelectorAll(selector).length === 1) return selector;
    }
    return parts.join(" > ");
  }

  function xpath(el) {
    const parts = [];
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const same = [...(node.parentElement?.children || [])].filter((c) => c.tagName === node.tagName);
      parts.unshift(node.tagName.toLowerCase() + (same.length > 1 ? `[${same.indexOf(node) + 1}]` : ""));
    }
    return "/" + parts.join("/");
  }

  function describe(el) {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      role: role(el),
      accessible_name: accessibleName(el),
      label_text: labelText(el),
      placeholder: el.getAttribute("placeholder") || "",
      text: clean(el.innerText),
      id: el.id || "",
      name: el.getAttribute("name") || "",
      css: cssPath(el),
      xpath: xpath(el),
      bbox: [r.left, r.top, r.right, r.bottom].map(Math.round),
    };
  }

  function visible(el) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  }

  // Like describe(), but the box is in page coordinates (what a full-page screenshot shows).
  function describeOnPage(el) {
    const d = describe(el);
    d.bbox = [d.bbox[0] + scrollX, d.bbox[1] + scrollY, d.bbox[2] + scrollX, d.bbox[3] + scrollY];
    return d;
  }

  // Interactive elements on the whole page (plus `extra`, e.g. table cells to read from), numbered. Kept for byRef().
  function candidates(extra = "") {
    const els = [...document.querySelectorAll(INTERACTIVE + (extra ? ", " + extra : ""))].filter(visible);
    globalThis.__teachOnceRefs = els;
    return els.map((el, ref) => ({ ref, ...describeOnPage(el) }));
  }

  function byRef(ref) {
    const el = globalThis.__teachOnceRefs?.[ref];
    return el ? describeOnPage(el) : null;
  }

  // The interactive element under a page-coordinate point (scrolls it into view first).
  function atPoint(x, y) {
    scrollTo(0, Math.max(0, y - innerHeight / 2));
    const hits = document.elementsFromPoint(x - scrollX, y - scrollY);
    for (const hit of hits) {
      const el = hit.closest(INTERACTIVE) || (hit.tagName === "LABEL" && hit.control);
      if (el) return describeOnPage(el);
    }
    return null;
  }

  return { clean, describe, candidates, byRef, atPoint };
})();
