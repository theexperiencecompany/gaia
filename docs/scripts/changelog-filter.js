(function () {
  var APPS = ["api", "web", "desktop", "mobile", "bots", "cli"];
  var APP_LABELS = { api: "Api", web: "Web", desktop: "Desktop", mobile: "Mobile", bots: "Bots", cli: "Cli" };
  var APP_PATTERNS = {
    api: /^[\u200b\s]*api\s+v/i,
    web: /^[\u200b\s]*web\s+v/i,
    desktop: /^[\u200b\s]*desktop\s+v/i,
    mobile: /^[\u200b\s]*mobile\s+v/i,
    bots: /^[\u200b\s]*bots\s+v/i,
    cli: /^[\u200b\s]*cli\s+v/i,
  };

  function getApp(h1Text) {
    for (var app in APP_PATTERNS) {
      if (APP_PATTERNS[app].test(h1Text)) return app;
    }
    return null;
  }

  function isChangelogPage() {
    // Only run the interactive filter bar on the main release notes page.
    // Sub-pages (e.g. /release-notes/api) use a React component for filtering.
    var path = window.location.pathname.replace(/\/$/, "");
    return path.endsWith("/release-notes") || path === "/release-notes";
  }

  function getBgColor() {
    var isDark = document.documentElement.classList.contains("dark");
    return isDark ? "#111111" : "#ffffff";
  }

  // --- TOC scroll highlighter ---
  var scrollRaf = null;
  var scrollHandler = null;

  function startTocHighlighter() {
    if (scrollHandler) return;
    scrollHandler = function () {
      if (scrollRaf) return;
      scrollRaf = requestAnimationFrame(function () {
        scrollRaf = null;
        syncTocHighlight();
      });
    };
    window.addEventListener("scroll", scrollHandler, { passive: true });
    syncTocHighlight();
  }

  function stopTocHighlighter() {
    if (scrollHandler) {
      window.removeEventListener("scroll", scrollHandler);
      scrollHandler = null;
    }
    if (scrollRaf) { cancelAnimationFrame(scrollRaf); scrollRaf = null; }
    // Reset inline TOC link styles so Mintlify takes back over
    document.querySelectorAll(".toc-item a").forEach(function (a) {
      a.style.color = "";
      a.style.borderLeftColor = "";
      a.style.fontWeight = "";
      a.style.opacity = "";
    });
  }

  function syncTocHighlight() {
    var OFFSET = 96; // below sticky navbar
    var visible = Array.from(document.querySelectorAll(".update-container"))
      .filter(function (c) { return c.style.display !== "none"; });

    var active = null;
    for (var i = 0; i < visible.length; i++) {
      if (visible[i].getBoundingClientRect().top <= OFFSET) {
        active = visible[i];
      } else {
        break;
      }
    }
    if (!active && visible.length) active = visible[0];

    document.querySelectorAll(".toc-item a").forEach(function (a) {
      var isActive = active && a.getAttribute("href") === "#" + active.id;
      a.style.color = isActive ? "#00bbff" : "";
      a.style.borderLeftColor = isActive ? "#00bbff" : "";
      a.style.fontWeight = isActive ? "500" : "";
    });
  }

  // --- cleanup ---
  function removeExisting() {
    var bar = document.getElementById("cl-filter-bar");
    if (bar) bar.remove();
    document.querySelectorAll("[data-cl-app]").forEach(function (el) {
      var parent = el.parentElement;
      while (el.firstChild) parent.insertBefore(el.firstChild, el);
      parent.removeChild(el);
    });
    document.querySelectorAll(".update-container").forEach(function (el) {
      el.style.display = "";
    });
    document.querySelectorAll(".toc-item").forEach(function (el) {
      el.style.display = "";
    });
    stopTocHighlighter();
  }

  function init() {
    if (!isChangelogPage()) return;
    removeExisting();

    var proseDivs = document.querySelectorAll("div.prose-sm");
    if (!proseDivs.length) return;

    var anyTagged = false;

    proseDivs.forEach(function (div) {
      var elChildren = Array.from(div.children);
      var h2Positions = [];

      elChildren.forEach(function (el, i) {
        if (el.tagName === "H2") {
          var app = getApp(el.textContent);
          if (app) h2Positions.push({ index: i, app: app });
        }
      });

      if (h2Positions.length === 0) return;
      anyTagged = true;

      for (var i = h2Positions.length - 1; i >= 0; i--) {
        var start = h2Positions[i].index;
        var end = i + 1 < h2Positions.length ? h2Positions[i + 1].index : elChildren.length;
        var app = h2Positions[i].app;

        var wrapper = document.createElement("div");
        wrapper.setAttribute("data-cl-app", app);
        div.insertBefore(wrapper, elChildren[start]);
        for (var j = start; j < end; j++) wrapper.appendChild(elChildren[j]);
      }
    });

    if (!anyTagged) return;

    // --- Filter bar ---
    var bar = document.createElement("div");
    bar.id = "cl-filter-bar";
    var bg = getBgColor();
    bar.style.cssText =
      "display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:28px;" +
      "padding:10px 0;background:" + bg + ";";

    var active = "all";

    // Label
    var label = document.createElement("span");
    label.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-right:5px;margin-top:-2px"><path d="M2 5h20"/><path d="M6 12h12"/><path d="M9 19h6"/></svg>Filter by app';
    label.style.cssText =
      "font-size:14px;font-weight:500;opacity:0.45;white-space:nowrap;margin-right:4px;";
    bar.appendChild(label);

    var pillsWrap = document.createElement("div");
    pillsWrap.style.cssText = "display:flex;align-items:center;flex-wrap:wrap;gap:6px;flex:1;";
    bar.appendChild(pillsWrap);

    // Clear button
    var clearBtn = document.createElement("button");
    clearBtn.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:middle;margin-right:5px;margin-top:-1px"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>Clear filters';
    clearBtn.style.cssText =
      "margin-left:8px;padding:7px 12px;border-radius:10px;font-size:13px;font-weight:500;" +
      "cursor:pointer;border:none;background:rgba(128,128,128,0.15);opacity:0.6;" +
      "font-family:inherit;line-height:1.4;white-space:nowrap;" +
      "transition:opacity 120ms ease;display:none;";
    clearBtn.addEventListener("mouseenter", function () { this.style.opacity = "1"; });
    clearBtn.addEventListener("mouseleave", function () { this.style.opacity = "0.6"; });
    clearBtn.addEventListener("click", function () { applyFilter("all"); });
    bar.appendChild(clearBtn);

    function styleBtn(btn, isActive) {
      btn.style.backgroundColor = isActive ? "#00bbff" : "rgba(128,128,128,0.15)";
      btn.style.color = isActive ? "#fff" : "";
    }

    function applyFilter(filter) {
      active = filter;

      pillsWrap.querySelectorAll("button").forEach(function (btn) {
        styleBtn(btn, btn.getAttribute("data-cl-key") === filter);
      });

      clearBtn.style.display = filter === "all" ? "none" : "";

      document.querySelectorAll("[data-cl-app]").forEach(function (section) {
        var app = section.getAttribute("data-cl-app");
        section.style.display = (filter === "all" || filter === app) ? "" : "none";
      });

      document.querySelectorAll(".update-container").forEach(function (container) {
        var appSections = container.querySelectorAll("[data-cl-app]");
        var isLegacy = appSections.length === 0;
        var hide = filter !== "all" && (
          isLegacy
            ? filter !== "api" && filter !== "web"
            : !Array.from(appSections).some(function (s) { return s.style.display !== "none"; })
        );

        container.style.display = hide ? "none" : "";

        // Hide irrelevant TOC items
        var id = container.id;
        if (id) {
          var tocLink = document.querySelector('.toc-item a[href="#' + id + '"]');
          if (tocLink) {
            tocLink.closest(".toc-item").style.display = hide ? "none" : "";
          }
        }
      });

      // Fix first-visible release headline top margin
      var firstHeadline = true;
      document.querySelectorAll(".update-container").forEach(function (container) {
        if (container.style.display === "none") return;
        var prose = container.querySelector("div.prose-sm");
        if (!prose) return;
        var h1 = prose.querySelector("h1");
        if (!h1) return;
        h1.style.marginTop = firstHeadline ? "0" : "";
        firstHeadline = false;
      });

      startTocHighlighter();
    }

    function createPill(label, key) {
      var btn = document.createElement("button");
      btn.textContent = label;
      btn.setAttribute("data-cl-key", key);
      btn.style.cssText =
        "padding:5px 14px;border-radius:9999px;font-size:14px;font-weight:500;" +
        "cursor:pointer;border:none;transition:all 120ms ease;" +
        "font-family:inherit;line-height:1.4;";
      styleBtn(btn, false);
      btn.addEventListener("click", function () { applyFilter(active === key ? "all" : key); });
      return btn;
    }

    APPS.forEach(function (app) { pillsWrap.appendChild(createPill(APP_LABELS[app], app)); });
    applyFilter("all");

    var firstProse = proseDivs[0];
    var insertTarget = firstProse;
    for (var p = firstProse.parentElement; p && p !== document.body; p = p.parentElement) {
      if (p.children.length > 1) { insertTarget = p; break; }
      insertTarget = p;
    }
    insertTarget.parentElement.insertBefore(bar, insertTarget);
  }

  function tryInit() {
    var tries = 0;
    var interval = setInterval(function () {
      tries++;
      if (document.querySelector("div.prose-sm")) {
        clearInterval(interval);
        init();
      } else if (tries > 30) {
        clearInterval(interval);
      }
    }, 200);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryInit);
  } else {
    tryInit();
  }

  var lastPath = location.pathname;
  new MutationObserver(function () {
    if (location.pathname !== lastPath) {
      lastPath = location.pathname;
      setTimeout(tryInit, 100);
    }
  }).observe(document.body, { childList: true, subtree: true });
})();
