import fs from 'node:fs';
import path from 'node:path';

function latestDaily(){
  const dir=path.join(process.cwd(),'vault','50-daily');
  if(!fs.existsSync(dir)) return {name:'No daily brief',content:'No daily note exists yet.'};
  const files=fs.readdirSync(dir).filter(f=>f.endsWith('.md')).sort().reverse();
  const name=files[0];
  return name?{name:name.replace('.md',''),content:fs.readFileSync(path.join(dir,name),'utf8')}:{name:'No daily brief',content:'No daily note exists yet.'};
}

export default function Today(){
  const note=latestDaily();
  const clean=note.content.replace(/^---[\s\S]*?---\s*/,'');
  return <main style={{maxWidth:820,margin:'0 auto',padding:'40px 22px 80px',display:'block'}}>
    <a href="/" style={{color:'#9aa3b5',textDecoration:'none'}}>← Command Center</a>
    <p style={{marginTop:34,color:'#8795ff',textTransform:'uppercase',letterSpacing:'.12em',fontSize:12}}>Daily brief</p>
    <h1>{note.name}</h1>
    <article style={{whiteSpace:'pre-wrap',lineHeight:1.75,color:'#d8deeb',marginTop:28}}>{clean}</article>
  </main>;
}
