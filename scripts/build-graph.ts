import fs from 'node:fs';
import path from 'node:path';

const root = path.join(process.cwd(), 'vault');
const outDir = path.join(process.cwd(), 'public');
const wikilink = /\[\[([^\]|#]+)(?:[\]|#][^\]]*)?\]\]/g;

function walk(dir:string):string[]{
  if(!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir,{withFileTypes:true}).flatMap(entry=>{
    const full=path.join(dir,entry.name);
    return entry.isDirectory()?walk(full):entry.name.endsWith('.md')?[full]:[];
  });
}

const files=walk(root);
const nodes=files.map(file=>{
  const rel=path.relative(root,file).replace(/\\/g,'/');
  const body=fs.readFileSync(file,'utf8');
  const title=(body.match(/^title:\s*(.+)$/m)?.[1]||path.basename(file,'.md')).replace(/^['"]|['"]$/g,'');
  const folder=rel.split('/')[0]||'vault';
  const links=[...body.matchAll(wikilink)].map(m=>m[1].trim());
  return {id:rel,title,folder,path:rel,links,backlinks:0};
});

const byTitle=new Map(nodes.map(n=>[n.title.toLowerCase(),n]));
const byStem=new Map(nodes.map(n=>[path.basename(n.path,'.md').toLowerCase(),n]));
const edges:{source:string;target:string}[]=[];
for(const node of nodes){
  for(const raw of node.links){
    const target=byTitle.get(raw.toLowerCase())||byStem.get(raw.toLowerCase());
    if(target && target.id!==node.id){edges.push({source:node.id,target:target.id});target.backlinks++;}
  }
}
fs.mkdirSync(outDir,{recursive:true});
fs.writeFileSync(path.join(outDir,'graph.json'),JSON.stringify({generatedAt:new Date().toISOString(),nodes,links:edges},null,2));
console.log(`graph: ${nodes.length} nodes, ${edges.length} links`);
