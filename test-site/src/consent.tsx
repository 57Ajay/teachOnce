import { useState } from "react";
import { redesign } from "./redesign";

const KEY = "hire-consent";

function decided() {
  try {
    return localStorage.getItem(KEY) !== null;
  } catch {
    return false;
  }
}

// The redesign's cookie banner: it covers the page until the visitor chooses.
export function ConsentBanner() {
  const [shown, setShown] = useState(() => redesign && !decided());
  if (!shown) return null;
  const choose = (choice: string) => {
    try {
      localStorage.setItem(KEY, choice);
    } catch {}
    setShown(false);
  };
  return (
    <div className="consent-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby="consent-title" className="consent">
        <h2 id="consent-title">We value your privacy</h2>
        <p className="muted">
          We use cookies to keep you signed in, remember your preferences and understand how the workspace is used.
          You can change your choice at any time in Settings.
        </p>
        <div className="consent-actions">
          <button type="button" className="button" onClick={() => choose("necessary")}>Only necessary</button>
          <button type="button" className="button primary" onClick={() => choose("all")}>Accept all cookies</button>
        </div>
      </div>
    </div>
  );
}
