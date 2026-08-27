"""Stealth init script for the CDP-driven headless Chromium.

The launch flags already neutralise the automation-controlled signal (browser-use's
``CHROME_DEFAULT_ARGS`` ships ``--disable-blink-features=AutomationControlled`` and
no ``--enable-automation``). What flags cannot fix is the JS-visible fingerprint of
a bare headless browser — a missing ``window.chrome``, empty ``navigator.plugins``,
a truthy ``navigator.webdriver``, headless WebGL vendor strings. This script patches
those, applied to every page via ``Page.addScriptToEvaluateOnNewDocument`` so it runs
before the page's own scripts on every navigation.

Note: it is applied per page target at context creation. A page that browser-use
opens later in the same context via ``window.open`` would not be covered without a
``Target.setAutoAttach`` hook; single-page tasks (the norm) are covered.
"""

_STEALTH_TEMPLATE = r"""(() => {
  const safe = (fn) => { try { fn(); } catch (_) {} };

  // navigator.webdriver -> undefined
  safe(() => {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: () => undefined,
      configurable: true,
    });
  });

  // navigator.plugins / mimeTypes -> realistic non-empty
  safe(() => {
    const mimeTypeData = [
      { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
      { type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
    ];
    const pluginData = [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    ];

    const makeMimeType = (data) => Object.create(MimeType.prototype, {
      type: { value: data.type, enumerable: true },
      suffixes: { value: data.suffixes, enumerable: true },
      description: { value: data.description, enumerable: true },
      enabledPlugin: { value: null, enumerable: true },
    });

    const mimeTypes = mimeTypeData.map(makeMimeType);
    const mimeTypeArray = Object.create(MimeTypeArray.prototype, {
      length: { value: mimeTypes.length, enumerable: true },
      item: { value: (i) => mimeTypes[i] ?? null },
      namedItem: { value: (name) => mimeTypes.find((m) => m.type === name) ?? null },
    });
    mimeTypes.forEach((m, i) => { mimeTypeArray[i] = m; mimeTypeArray[m.type] = m; });

    const plugins = pluginData.map((data) => {
      const plugin = Object.create(Plugin.prototype, {
        name: { value: data.name, enumerable: true },
        filename: { value: data.filename, enumerable: true },
        description: { value: data.description, enumerable: true },
        length: { value: 1, enumerable: true },
      });
      const mt = mimeTypes[0];
      plugin[0] = mt;
      plugin.item = (i) => (i === 0 ? mt : null);
      plugin.namedItem = (name) => (name === mt.type ? mt : null);
      return plugin;
    });
    const pluginArray = Object.create(PluginArray.prototype, {
      length: { value: plugins.length, enumerable: true },
      item: { value: (i) => plugins[i] ?? null },
      namedItem: { value: (name) => plugins.find((p) => p.name === name) ?? null },
      refresh: { value: () => {} },
    });
    plugins.forEach((p, i) => { pluginArray[i] = p; pluginArray[p.name] = p; });

    Object.defineProperty(Navigator.prototype, 'plugins', { get: () => pluginArray, configurable: true });
    Object.defineProperty(Navigator.prototype, 'mimeTypes', { get: () => mimeTypeArray, configurable: true });
  });

  // navigator.languages
  safe(() => {
    Object.defineProperty(Navigator.prototype, 'languages', {
      get: () => ['en-US', 'en'],
      configurable: true,
    });
  });

  // navigator.hardwareConcurrency / deviceMemory
  safe(() => {
    Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', { get: () => 8, configurable: true });
  });
  safe(() => {
    Object.defineProperty(Navigator.prototype, 'deviceMemory', { get: () => 8, configurable: true });
  });

  // window.chrome.runtime — headless Chromium exposes window.chrome but not the
  // runtime object a real Chrome tab has. Redefining window.chrome itself throws
  // when it is non-configurable, so assign onto the existing object instead.
  safe(() => {
    if (typeof window.chrome === 'undefined') {
      Object.defineProperty(window, 'chrome', {
        value: {}, writable: true, enumerable: true, configurable: true,
      });
    }
    if (!window.chrome.runtime) {
      window.chrome.runtime = {
        connect: () => {},
        sendMessage: () => {},
        onMessage: { addListener: () => {}, removeListener: () => {} },
        id: undefined,
      };
    }
    if (!window.chrome.csi) window.chrome.csi = () => {};
    if (!window.chrome.loadTimes) window.chrome.loadTimes = () => {};
  });

  // navigator.permissions.query -> notifications should not "denied"/throw
  safe(() => {
    const origQuery = Permissions.prototype.query;
    Permissions.prototype.query = function (parameters) {
      if (parameters && parameters.name === 'notifications') {
        return Promise.resolve(
          Object.setPrototypeOf(
            { state: Notification.permission === 'default' ? 'prompt' : Notification.permission, onchange: null },
            PermissionStatus.prototype,
          ),
        );
      }
      return origQuery.call(this, parameters);
    };
  });

  // WebGL vendor/renderer spoofing
  safe(() => {
    const patchGetParameter = (proto) => {
      const orig = proto.getParameter;
      proto.getParameter = function (parameter) {
        // UNMASKED_VENDOR_WEBGL = 0x9245, UNMASKED_RENDERER_WEBGL = 0x9246
        if (parameter === 0x9245) return 'Intel Inc.';
        if (parameter === 0x9246) return 'Intel Iris OpenGL Engine';
        return orig.call(this, parameter);
      };
    };
    if (window.WebGLRenderingContext) patchGetParameter(WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) patchGetParameter(WebGL2RenderingContext.prototype);
  });


  // ── Fingerprint noise, seeded per user ────────────────────────────────────
  // Canvas/audio readback is near-unique per machine, so a bare headless
  // browser is identifiable by it. These hooks perturb the values — but
  // deterministically, from a seed derived from the GAIA user. Randomising per
  // call would be worse than nothing: a real browser returns the SAME values
  // every time, so a fingerprint that moves is itself a bot signal.
  const __seed = __FINGERPRINT_SEED__;

  // mulberry32 — small, fast, and stable for a given seed.
  const rngFor = (salt) => {
    let a = (__seed ^ salt) >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  };

  // Canvas: nudge a handful of pixels' low bits. Invisible to a human, but it
  // moves the hash a scraper-detector keys on.
  safe(() => {
    const jitter = (data, rnd) => {
      for (let i = 0; i < data.length; i += 4 * 977) {
        data[i] = Math.max(0, Math.min(255, data[i] + (rnd() < 0.5 ? -1 : 1)));
      }
    };
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function (...args) {
      const result = origGetImageData.apply(this, args);
      safe(() => jitter(result.data, rngFor(1)));
      return result;
    };
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function (...args) {
      safe(() => {
        const ctx = this.getContext('2d');
        if (!ctx || !this.width || !this.height) return;
        const img = origGetImageData.call(ctx, 0, 0, this.width, this.height);
        jitter(img.data, rngFor(2));
        ctx.putImageData(img, 0, 0);
      });
      return origToDataURL.apply(this, args);
    };
  });

  // AudioContext: the same idea on the audio fingerprint's float samples.
  safe(() => {
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function (...args) {
      const data = origGetChannelData.apply(this, args);
      safe(() => {
        const rnd = rngFor(3);
        for (let i = 0; i < data.length; i += 1229) {
          data[i] = data[i] + (rnd() - 0.5) * 1e-7;
        }
      });
      return data;
    };
  });

  // Remove any leaked automation driver properties (Selenium/ChromeDriver artifacts)
  safe(() => {
    const props = Object.getOwnPropertyNames(window).filter(
      (p) => p.startsWith('cdc_') || p.startsWith('$cdc_') || p.startsWith('$chrome_'),
    );
    for (const p of props) { safe(() => { delete window[p]; }); }
  });
})();"""


def build_stealth_script(seed: int) -> str:
    """The init script with this user's fingerprint seed baked in."""
    return _STEALTH_TEMPLATE.replace("__FINGERPRINT_SEED__", str(int(seed)))
