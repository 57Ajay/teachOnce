// Teach-Once studio: records DOM events inside the portal frame, the tab video and the mic narration.
(() => {
  const frame = document.getElementById("portal");
  const startBtn = document.getElementById("start");
  const stopBtn = document.getElementById("stop");
  const timerEl = document.getElementById("timer");
  const meterEl = document.getElementById("meter");
  const statusEl = document.getElementById("status");

  let t0 = 0, recording = false, events = [], recorders = [], streams = [], meta = {}, ticker = null;
  let typingSince = new WeakMap(); // field -> when typing started, so a fill is timed at its start

  const now = () => Math.round(performance.now() - t0);
  const { describe, interactive, option } = window.TeachOnceDescribe;
  const status = (s) => (statusEl.textContent = s);
  const once = (el, name) => new Promise((res) => el.addEventListener(name, res, { once: true }));

  function valueOf(el) {
    if (el.type === "password") return "***";
    if (el.tagName === "SELECT") return el.options[el.selectedIndex]?.text || "";
    if (["checkbox", "radio"].includes(el.type)) return el.value;
    return el.value;
  }

  function record(type, el, extra = {}) {
    const win = frame.contentWindow;
    const ts = (type === "change" && typingSince.get(el)) || now();
    typingSince.delete(el);
    events.push({
      ts_ms: ts,
      type,
      url: win.location.pathname + win.location.search,
      target: el ? describe(el) : null,
      viewport: [win.innerWidth, win.innerHeight],
      dpr: win.devicePixelRatio,
      ...extra,
    });
  }

  function attach() {
    const doc = frame.contentDocument;
    if (!doc || doc.__teachOnce) return;
    doc.__teachOnce = true;
    record("navigation", null);
    doc.addEventListener("pointerdown", (e) => option(e.target) && record("click", option(e.target)), true);
    doc.addEventListener("click", (e) => option(e.target) || record("click", interactive(e.target)), true);
    doc.addEventListener("change", (e) => record("change", e.target, { value: valueOf(e.target), checked: !!e.target.checked }), true);
    doc.addEventListener("input", (e) => typingSince.has(e.target) || typingSince.set(e.target, now()), true);
    doc.addEventListener("submit", (e) => record("submit", e.target), true);
    doc.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === "Tab") record("keydown", e.target, { key: e.key });
    }, true);
  }

  function startRecorder(stream, mimeType) {
    const chunks = [];
    const rec = new MediaRecorder(stream, MediaRecorder.isTypeSupported(mimeType) ? { mimeType } : {});
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.start(1000);
    return { rec, chunks, stopped: new Promise((res) => (rec.onstop = res)) };
  }

  function showLevel(stream) {
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    ctx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    const draw = () => {
      if (!recording) return ctx.close();
      analyser.getByteTimeDomainData(data);
      const peak = Math.max(...data.map((v) => Math.abs(v - 128))) / 128;
      meterEl.style.width = `${Math.min(100, peak * 160)}%`;
      requestAnimationFrame(draw);
    };
    draw();
  }

  async function start() {
    status('Pick "This tab" and click Share…');
    let screen, mic = null;
    try {
      screen = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 15 }, audio: false, preferCurrentTab: true, selfBrowserSurface: "include",
      });
    } catch {
      return status("Screen capture was cancelled.");
    }
    try {
      mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      status("No microphone: recording without narration.");
    }
    streams = [screen, mic].filter(Boolean);

    frame.src = "/portal/logout";
    await once(frame, "load");

    const r = frame.getBoundingClientRect();
    const [x, y] = [r.left + frame.clientLeft, r.top + frame.clientTop];
    meta = {
      start_url: "/portal/login",
      started_at: new Date().toISOString(),
      user_agent: navigator.userAgent,
      viewport: [frame.contentWindow.innerWidth, frame.contentWindow.innerHeight],
      frame_rect: { x, y, w: frame.clientWidth, h: frame.clientHeight, inner_w: innerWidth, inner_h: innerHeight },
    };
    events = [];
    typingSince = new WeakMap();
    t0 = performance.now();
    recorders = [startRecorder(screen, "video/webm;codecs=vp9")];
    if (mic) recorders.push(startRecorder(mic, "audio/webm;codecs=opus"));
    recording = true;
    attach();
    if (mic) showLevel(mic);
    screen.getVideoTracks()[0].addEventListener("ended", stop);

    startBtn.disabled = true;
    stopBtn.disabled = false;
    document.body.classList.add("recording");
    ticker = setInterval(() => {
      const s = Math.floor(now() / 1000);
      timerEl.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }, 250);
    status(mic ? "Recording. Do the task and say what you're doing." : "Recording (no narration).");
  }

  async function stop() {
    if (!recording) return;
    recording = false;
    clearInterval(ticker);
    stopBtn.disabled = true;
    document.body.classList.remove("recording");
    recorders.forEach((r) => r.rec.stop());
    await Promise.all(recorders.map((r) => r.stopped));
    streams.forEach((s) => s.getTracks().forEach((t) => t.stop()));

    const form = new FormData();
    form.append("meta", JSON.stringify(meta));
    form.append("events", new Blob([JSON.stringify(events)], { type: "application/json" }), "events.json");
    form.append("screen", new Blob(recorders[0].chunks, { type: "video/webm" }), "screen.webm");
    if (recorders[1]) form.append("mic", new Blob(recorders[1].chunks, { type: "audio/webm" }), "mic.webm");
    status("Uploading and converting…");
    const res = await fetch("/app/api/teach", { method: "POST", body: form });
    if (!res.ok) return status(`Upload failed: ${res.status}`);
    const { rec_id } = await res.json();
    location.href = `/app/teach/${rec_id}`;
  }

  frame.addEventListener("load", () => recording && attach());
  startBtn.addEventListener("click", start);
  stopBtn.addEventListener("click", stop);
})();
