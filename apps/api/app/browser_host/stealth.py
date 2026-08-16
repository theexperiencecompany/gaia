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

STEALTH_INIT_SCRIPT = r"""(() => {
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

  // Remove any leaked automation driver properties (Selenium/ChromeDriver artifacts)
  safe(() => {
    const props = Object.getOwnPropertyNames(window).filter(
      (p) => p.startsWith('cdc_') || p.startsWith('$cdc_') || p.startsWith('$chrome_'),
    );
    for (const p of props) { safe(() => { delete window[p]; }); }
  });
})();"""
