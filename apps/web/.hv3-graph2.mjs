import fs from 'node:fs';
import path from 'node:path';
const ROOT = process.cwd();
const SRC = path.join(ROOT, 'src');
const SHARED = path.join(ROOT, '../../libs/shared/ts/src');
const exts = ['.tsx','.ts','.jsx','.js','.mjs','.json'];
function resolveSpec(spec, from) {
  let base;
  if (spec.startsWith('@/src/')) base = path.join(SRC, spec.slice(6));
  else if (spec.startsWith('@/')) base = path.join(SRC, spec.slice(2));
  else if (spec.startsWith('@shared/')) base = path.join(SHARED, spec.slice(8));
  else if (spec.startsWith('.')) base = path.resolve(path.dirname(from), spec);
  else return null;
  for (const e of ['', ...exts]) {
    const p = base + e;
    if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  }
  for (const e of exts) { const p = path.join(base, 'index'+e); if (fs.existsSync(p)) return p; }
  return null;
}
function imports(file) {
  const s = fs.readFileSync(file, 'utf8');
  const out = [];
  const re = /(?:^|\n)\s*(?:import|export)\s+(type\s+)?(?:[\s\S]*?\s+from\s+)?["']([^"']+)["']/g;
  let m;
  while ((m = re.exec(s))) { if (m[1]) continue; out.push(m[2]); }
  // also require()
  for (const mm of s.matchAll(/require\(["']([^"']+)["']\)/g)) out.push(mm[1]);
  return out;
}
const targets = { cronstrue:'cronstrue', dompurify:'dompurify', dodo:'dodopayments-checkout', sse:'@microsoft/fetch-event-source', sim:'string-similarity', openapi:'openapi-fetch', events:'events', uuid:'uuid', sileo:'sileo', torph:'torph', numberflow:'@number-flow/react', sentry:'@sentry/nextjs', openui:'@openuidev/react-ui', radix:'@radix-ui/react-dialog', query:'@tanstack/react-query', zustand:'zustand' };
const entries = process.argv.slice(2).map(p => path.resolve(ROOT, p));
const seen = new Map(); // file -> parent
const q = [];
for (const e of entries) { seen.set(e, null); q.push(e); }
const found = {};
while (q.length) {
  const f = q.shift();
  let imps = [];
  try { imps = imports(f); } catch { continue; }
  for (const spec of imps) {
    const pkg = spec.startsWith('@') ? spec.split('/').slice(0,2).join('/') : spec.split('/')[0];
    for (const [k, v] of Object.entries(targets)) {
      if ((pkg === v || pkg.startsWith(v)) && !found[k]) {
        const chain = []; let cur = f;
        while (cur) { chain.push(path.relative(ROOT, cur)); cur = seen.get(cur); }
        found[k] = chain;
      }
    }
    const r = resolveSpec(spec, f);
    if (r && !seen.has(r)) { seen.set(r, f); q.push(r); }
  }
}
for (const [k, chain] of Object.entries(found)) {
  console.log(`\n### ${k}:`);
  console.log('  ' + chain.join('\n  -> '));
}
console.log('\nfiles scanned', seen.size);
