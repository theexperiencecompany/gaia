"""Stealth init script for the CDP-driven headless Chromium.

The launch flags already neutralise the automation-controlled signal (browser-use's
CHROME_DEFAULT_ARGS ships --disable-blink-features=AutomationControlled and
no --enable-automation). What flags cannot fix is the JS-visible fingerprint of
a bare headless browser — a missing window.chrome, empty navigator.plugins,
a truthy navigator.webdriver, headless WebGL vendor strings. This script patches
those; app/patches/browser_use_stealth_patch.py registers it on every page
browser-use drives, so it runs before the page's own scripts on every navigation.

The per-user values (hardware, GPU, canvas and audio noise) come from one seed,
so the same person always presents the same device and different people do not
all present one.
"""

_STEALTH_TEMPLATE = r"""(() => {
  const safe = (fn) => { try { fn(); } catch (_) {} };

  // navigator.webdriver -> false, what a browser no automation drives reports
  safe(() => {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: () => false,
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

  // ── Per-user device, seeded ────────────────────────────────────────────────
  // Every value below derives from a seed for the GAIA user. Randomising per call
  // would be worse than nothing: a real browser returns the SAME values every
  // time, so a fingerprint that moves is itself a bot signal; and one fixed value
  // for every user makes them all the same suspicious device.
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

  const pick = (salt, options) => options[Math.floor(rngFor(salt)() * options.length)];

  // navigator.hardwareConcurrency / deviceMemory: common real-machine values.
  safe(() => {
    const cores = pick(11, [4, 8, 8, 12, 16]);
    Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', { get: () => cores, configurable: true });
  });
  safe(() => {
    const memory = pick(12, [4, 8, 8, 16]);
    Object.defineProperty(Navigator.prototype, 'deviceMemory', { get: () => memory, configurable: true });
  });

  // WebGL vendor/renderer: a common real GPU in place of the headless SwiftShader one.
  safe(() => {
    const [vendor, renderer] = pick(13, [
      ['Google Inc. (Intel)', 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)'],
      ['Google Inc. (Intel)', 'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)'],
      ['Google Inc. (NVIDIA)', 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)'],
      ['Google Inc. (AMD)', 'ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)'],
    ]);
    const patchGetParameter = (proto) => {
      const orig = proto.getParameter;
      proto.getParameter = function (parameter) {
        // UNMASKED_VENDOR_WEBGL = 0x9245, UNMASKED_RENDERER_WEBGL = 0x9246
        if (parameter === 0x9245) return vendor;
        if (parameter === 0x9246) return renderer;
        return orig.call(this, parameter);
      };
    };
    if (window.WebGLRenderingContext) patchGetParameter(WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) patchGetParameter(WebGL2RenderingContext.prototype);
  });

  // Canvas: nudge a handful of pixels' low bits of what is READ BACK. Invisible
  // to a human, but it moves the hash a scraper-detector keys on. Only a copy is
  // ever changed, so the page's own canvas stays exactly as it drew it and the
  // same drawing always reads back the same; every export path agrees.
  safe(() => {
    const jitter = (data) => {
      const rnd = rngFor(1);
      for (let i = 0; i < data.length; i += 4 * 977) {
        data[i] = Math.max(0, Math.min(255, data[i] + (rnd() < 0.5 ? -1 : 1)));
      }
    };
    const hookImageData = (proto) => {
      const orig = proto.getImageData;
      proto.getImageData = function (...args) {
        const result = orig.apply(this, args);
        safe(() => jitter(result.data));
        return result;
      };
      return orig;
    };
    const readHtml = hookImageData(CanvasRenderingContext2D.prototype);
    const readOffscreen = window.OffscreenCanvasRenderingContext2D
      ? hookImageData(OffscreenCanvasRenderingContext2D.prototype)
      : null;

    // A jittered copy of a 2D canvas, or null when it has no 2D pixels to read.
    const jitteredCopy = (canvas, read, blank) => {
      const ctx = canvas.getContext('2d');
      if (!ctx || !canvas.width || !canvas.height) return null;
      const img = read.call(ctx, 0, 0, canvas.width, canvas.height);
      jitter(img.data);
      const copy = blank(canvas.width, canvas.height);
      copy.getContext('2d').putImageData(img, 0, 0);
      return copy;
    };
    const htmlBlank = (width, height) => {
      const copy = document.createElement('canvas');
      copy.width = width;
      copy.height = height;
      return copy;
    };
    const hookExport = (proto, name, read, blank) => {
      const orig = proto[name];
      proto[name] = function (...args) {
        let copy = null;
        safe(() => { copy = jitteredCopy(this, read, blank); });
        return orig.apply(copy || this, args);
      };
    };
    hookExport(HTMLCanvasElement.prototype, 'toDataURL', readHtml, htmlBlank);
    hookExport(HTMLCanvasElement.prototype, 'toBlob', readHtml, htmlBlank);
    if (window.OffscreenCanvas && readOffscreen) {
      hookExport(OffscreenCanvas.prototype, 'convertToBlob', readOffscreen, (w, h) => new OffscreenCanvas(w, h));
    }
  });

  // AudioContext: the same idea on the audio fingerprint's float samples.
  // getChannelData returns the buffer's own storage, so each channel is nudged
  // once; nudging on every read would compound into audible noise.
  safe(() => {
    const nudged = new WeakMap();
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function (channel, ...rest) {
      const data = origGetChannelData.call(this, channel, ...rest);
      safe(() => {
        const channels = nudged.get(this) || new Set();
        nudged.set(this, channels);
        if (channels.has(channel)) return;
        channels.add(channel);
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
    """Return the init script with this user's fingerprint seed baked in."""
    return _STEALTH_TEMPLATE.replace("__FINGERPRINT_SEED__", str(int(seed)))
