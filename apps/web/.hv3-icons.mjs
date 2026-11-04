import fs from 'node:fs';
import path from 'node:path';
const ROOT=process.cwd(); const SRC=path.join(ROOT,'src'); const SHARED=path.join(ROOT,'../../libs/shared/ts/src');
const exts=['.tsx','.ts','.jsx','.js','.mjs','.json'];
function resolveSpec(spec,from){let base;
 if(spec.startsWith('@/src/'))base=path.join(SRC,spec.slice(6));
 else if(spec.startsWith('@/'))base=path.join(SRC,spec.slice(2));
 else if(spec.startsWith('@shared/'))base=path.join(SHARED,spec.slice(8));
 else if(spec.startsWith('.'))base=path.resolve(path.dirname(from),spec); else return null;
 for(const e of ['',...exts]){const p=base+e;if(fs.existsSync(p)&&fs.statSync(p).isFile())return p;}
 for(const e of exts){const p=path.join(base,'index'+e);if(fs.existsSync(p))return p;} return null;}
const entries=process.argv.slice(2).map(p=>path.resolve(ROOT,p));
const seen=new Set(entries);const q=[...entries];const icons=new Map();
while(q.length){const f=q.shift();let s='';try{s=fs.readFileSync(f,'utf8');}catch{continue}
 for(const m of s.matchAll(/import\s*\{([^}]*)\}\s*from\s*"@icons"/gs)){
   for(const raw of m[1].split(',')){const n=raw.trim().split(/\s+as\s+/)[0].trim(); if(n){if(!icons.has(n))icons.set(n,new Set());icons.get(n).add(path.relative(ROOT,f));}}
 }
 const re=/(?:^|\n)\s*(?:import|export)\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?["']([^"']+)["']/g;let m;
 while((m=re.exec(s))){const spec=m[1];const r=resolveSpec(spec,f);if(r&&!seen.has(r)){seen.add(r);q.push(r);}}
}
console.log('files in landing graph:',seen.size,'distinct @icons:',icons.size);
console.log([...icons.keys()].sort().join(' '));
