import fs from 'node:fs';
import path from 'node:path';
const ROOT = process.cwd();
const SRC = path.join(ROOT,'src'); const SHARED = path.join(ROOT,'../../libs/shared/ts/src');
const exts=['.tsx','.ts','.jsx','.js','.mjs','.json'];
function resolveSpec(spec, from){
  let base;
  if(spec.startsWith('@/src/')) base=path.join(SRC,spec.slice(6));
  else if(spec.startsWith('@/')) base=path.join(SRC,spec.slice(2));
  else if(spec.startsWith('@shared/')) base=path.join(SHARED,spec.slice(8));
  else if(spec.startsWith('.')) base=path.resolve(path.dirname(from),spec);
  else return null;
  for(const e of ['',...exts]){const p=base+e;if(fs.existsSync(p)&&fs.statSync(p).isFile())return p;}
  for(const e of exts){const p=path.join(base,'index'+e);if(fs.existsSync(p))return p;}
  return null;
}
function imports(file){const s=fs.readFileSync(file,'utf8');const out=[];
 const re=/(?:^|\n)\s*(?:import|export)\s+(type\s+)?(?:[\s\S]*?\s+from\s+)?["']([^"']+)["']/g;let m;
 while((m=re.exec(s))){if(m[1])continue;out.push(m[2]);}
 const re2=/import\(["']([^"']+)["']\)/g; while((m=re2.exec(s))) out.push(m[1]);
 return out;}
const entries=process.argv.slice(2).map(p=>path.resolve(ROOT,p));
const seen=new Map(); for(const e of entries) seen.set(e,null);
const q=[...entries]; const pkgs=new Map();
while(q.length){const f=q.shift(); let imps=[]; try{imps=imports(f);}catch{continue;}
 for(const spec of imps){
  if(spec.startsWith('.')||spec.startsWith('@/')||spec.startsWith('@shared/')){const r=resolveSpec(spec,f); if(r&&!seen.has(r)){seen.set(r,f);q.push(r);} continue;}
  if(spec.startsWith('node:')) continue;
  const name=spec.startsWith('@')?spec.split('/').slice(0,2).join('/'):spec.split('/')[0];
  if(!pkgs.has(name)) pkgs.set(name, new Set());
  pkgs.get(name).add(path.relative(ROOT,f));
 }
}
const rows=[...pkgs.entries()].map(([k,v])=>[k,[...v]]).sort((a,b)=>b[1].length-a[1].length);
for(const [k,v] of rows) console.log(String(v.length).padStart(3), k, '  e.g.', v.slice(0,2).join(', '));
console.log('\napp files scanned',seen.size,'packages',rows.length);
