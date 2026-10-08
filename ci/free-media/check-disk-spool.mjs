import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {mkdtempSync,openSync,closeSync,statSync,rmSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
const root=mkdtempSync(join(tmpdir(),"open-media-spool-"));
const out=join(root,"stdout.bin"),err=join(root,"stderr.bin");
try {
  const fdOut=openSync(out,"w"),fdErr=openSync(err,"w");
  let run;
  try {
    run=spawnSync(process.execPath,["-e","process.stdout.write('x'.repeat(4*1024*1024));process.stderr.write('y'.repeat(2*1024*1024))"],{
      stdio:["ignore",fdOut,fdErr],timeout:30000
    });
  } finally {closeSync(fdOut);closeSync(fdErr)}
  assert.equal(run.error,undefined,String(run.error));
  assert.equal(run.status,0);
  assert.equal(statSync(out).size,4*1024*1024);
  assert.equal(statSync(err).size,2*1024*1024);
  console.log("DISK_BACKED_DIAGNOSTIC_CAPTURE_PASS 6MiB");
}finally{rmSync(root,{recursive:true,force:true})}
