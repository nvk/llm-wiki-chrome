(() => {
  const MARKER_ID = "llm-wiki-browser-collaboration-marker";
  const LISTENER_KEY = "__llmWikiCollaborationMarkerListener";

  function removeMarker() {
    document.getElementById(MARKER_ID)?.remove();
  }

  function addMarker() {
    if (document.getElementById(MARKER_ID) || !document.documentElement) return;
    const host = document.createElement("div");
    host.id = MARKER_ID;
    host.setAttribute("aria-hidden", "true");
    const root = host.attachShadow({mode: "closed"});
    const style = document.createElement("style");
    style.textContent = `
      :host { all: initial; }
      .outline {
        position: fixed;
        inset: 0;
        z-index: 2147483647;
        box-sizing: border-box;
        border: 3px solid #35a36f;
        border-radius: 7px;
        pointer-events: none;
      }
      .label {
        position: fixed;
        top: 10px;
        right: 12px;
        z-index: 2147483647;
        padding: 6px 10px;
        border-radius: 999px;
        background: #17201b;
        color: #f7fff9;
        box-shadow: 0 4px 14px rgb(0 0 0 / 22%);
        font: 700 11px/1.1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        letter-spacing: .08em;
        pointer-events: none;
      }
      .dot { color: #57d494; }
    `;
    const outline = document.createElement("div");
    outline.className = "outline";
    const label = document.createElement("div");
    label.className = "label";
    label.append("LLM WIKI ", Object.assign(document.createElement("span"), {
      className: "dot",
      textContent: "●",
    }), " CONTROLLED");
    root.append(style, outline, label);
    document.documentElement.append(host);
  }

  addMarker();
  if (!globalThis[LISTENER_KEY]) {
    globalThis[LISTENER_KEY] = true;
    chrome.runtime.onMessage.addListener((message) => {
      if (message?.type === "llm-wiki-collaboration-revoke") removeMarker();
    });
  }
})();
