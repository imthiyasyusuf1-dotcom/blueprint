/* Blueprint engine worker: runs the Python engine in Pyodide, off the main thread.
   Messages in:  {type: 'run', id, pid, capacity, region, params}
                 {type: 'pdf', id, data}
   Messages out: {type: 'progress', id, step}  step = python | engine | solve | pdf
                 {type: 'result', id, json} | {type: 'pdf', id, bytes} | {type: 'error', id, message} */
/* Loaded as a module worker: Pyodide 314 does not support classic workers. */

var PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/';
var SITE = new URL('../', self.location.href).href;
var py = null;
var enginePromise = null;
var pdfPromise = null;
var queue = Promise.resolve();

function post(msg) { self.postMessage(msg); }

async function ensurePython(id) {
  if (py) return py;
  post({ type: 'progress', id: id, step: 'python' });
  var mod;
  try {
    mod = await import(PYODIDE_URL + 'pyodide.mjs');
  } catch (e) {
    throw new Error('NET: Python could not be downloaded. Check your connection and try again.');
  }
  try {
    py = await mod.loadPyodide({ indexURL: PYODIDE_URL });
  } catch (e) {
    throw new Error('NET: Python could not be started (' + (e && e.message ? e.message : e) + ').');
  }
  return py;
}

async function fetchOk(url, as) {
  var r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error('Could not load ' + url.replace(SITE, '') + ' (' + r.status + ')');
  return as === 'bytes' ? new Uint8Array(await r.arrayBuffer()) : r.text();
}

function mkdirs(path) {
  var parts = path.split('/').slice(0, -1), cur = '';
  parts.forEach(function (p) {
    if (!p) return;
    cur += '/' + p;
    try { py.FS.mkdir(cur); } catch (e) { /* exists */ }
  });
}

async function ensureEngine(id) {
  await ensurePython(id);
  if (!enginePromise) {
    enginePromise = (async function () {
      post({ type: 'progress', id: id, step: 'engine' });
      var man = JSON.parse(await fetchOk(SITE + 'py/manifest.json'));
      var texts = await Promise.all(man.files.map(function (f) { return fetchOk(SITE + 'py/' + f.path); }));
      man.files.forEach(function (f, i) {
        var p = '/bp/' + f.path;
        mkdirs(p);
        py.FS.writeFile(p, texts[i]);
      });
      await py.loadPackage('micropip');
      py.runPython([
        'import sys, json, math, ast, importlib',
        'sys.path.insert(0, "/bp")',
        'def _bp_clean(o):',
        '    if isinstance(o, dict): return {str(k): _bp_clean(v) for k, v in o.items()}',
        '    if isinstance(o, (list, tuple)): return [_bp_clean(v) for v in o]',
        '    if o is None or isinstance(o, (bool, str, int)): return o',
        '    if isinstance(o, float): return o if math.isfinite(o) else None',
        '    if hasattr(o, "item"): return _bp_clean(o.item())',
        '    return str(o)',
        'async def _bp_deps(pid):',
        '    """Install third party imports a process model needs (for example iapws)."""',
        '    import micropip',
        '    src = open(f"/bp/engine/processes/{pid}.py").read()',
        '    names = set()',
        '    for node in ast.walk(ast.parse(src)):',
        '        if isinstance(node, ast.Import): names.update(a.name.split(".")[0] for a in node.names)',
        '        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module: names.add(node.module.split(".")[0])',
        '    for n in sorted(names):',
        '        if n in sys.stdlib_module_names or n == "engine": continue',
        '        try: importlib.import_module(n)',
        '        except ImportError: await micropip.install(n)'
      ].join('\n'));
    })();
    enginePromise.catch(function () { enginePromise = null; });
  }
  return enginePromise;
}

async function run(msg) {
  await ensureEngine(msg.id);
  post({ type: 'progress', id: msg.id, step: 'solve' });
  await py.runPythonAsync('await _bp_deps(' + JSON.stringify(msg.pid) + ')');
  py.globals.set('BP_ARGS', JSON.stringify({ pid: msg.pid, capacity: msg.capacity, region: msg.region, params: msg.params || {} }));
  var t0 = performance.now();
  var out = py.runPython([
    'from engine import registry',
    '_a = json.loads(BP_ARGS)',
    '_r = registry.run(_a["pid"], capacity_tpd=_a["capacity"], region=_a["region"], **_a["params"])',
    'json.dumps(_bp_clean(_r), allow_nan=False)'
  ].join('\n'));
  post({ type: 'result', id: msg.id, json: out, ms: Math.round(performance.now() - t0) });
}

async function ensurePdf(id) {
  await ensureEngine(id);
  if (!pdfPromise) {
    pdfPromise = (async function () {
      var man = JSON.parse(await fetchOk(SITE + 'py/manifest.json'));
      var fonts = man.fonts || ['Inter-Regular.ttf', 'Inter-SemiBold.ttf', 'Inter-Bold.ttf'];
      var bytes = await Promise.all(fonts.map(function (f) { return fetchOk(SITE + 'fonts/' + f, 'bytes'); }));
      fonts.forEach(function (f, i) { mkdirs('/bp/fonts/' + f); py.FS.writeFile('/bp/fonts/' + f, bytes[i]); });
      await py.runPythonAsync('import micropip\nawait micropip.install("fpdf2")\nimport build_pdf');
    })();
    pdfPromise.catch(function () { pdfPromise = null; });
  }
  return pdfPromise;
}

async function pdf(msg) {
  post({ type: 'progress', id: msg.id, step: 'pdf' });
  await ensurePdf(msg.id);
  py.globals.set('BP_DATA', msg.data);
  var proxy = py.runPython('build_pdf.build(json.loads(BP_DATA), "/bp/fonts")');
  var bytes = proxy.toJs();
  if (proxy.destroy) proxy.destroy();
  self.postMessage({ type: 'pdf', id: msg.id, bytes: bytes }, [bytes.buffer]);
}

function cleanError(e) {
  var s = String((e && e.message) || e || 'Unknown error');
  var lines = s.trim().split('\n').filter(Boolean);
  var last = lines[lines.length - 1];
  if (/^NET: /.test(s)) return s;
  // engine errors written for people (ValueError with a sentence) pass through; internal failures get a plain message
  var m = last.match(/^(\w*(?:Error|Exception)):\s*(.*)$/);
  if (m && m[1] === 'ValueError' && m[2].length > 12 && /\s/.test(m[2])) return m[2].replace(/[.\s]*$/, '.');
  return 'The flowsheet did not converge for these inputs.';
}

self.onmessage = function (ev) {
  var msg = ev.data || {};
  queue = queue.then(function () {
    return (msg.type === 'pdf' ? pdf(msg) : run(msg)).catch(function (e) {
      post({ type: 'error', id: msg.id, message: cleanError(e), detail: String(e && e.message || e) });
    });
  });
};
