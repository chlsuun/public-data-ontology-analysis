// Offline DOM-adapter checks; this does not open a browser or inspect browser layout.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const folder=path.resolve(process.argv[2]||'analysis/observation-comparison/20260915');
const page=fs.readFileSync(path.join(folder,'index.html'),'utf8');
assert(!page.includes('__DATA__'));assert(!page.includes('__GAPS__'));
const payload=page.match(/<script id="analysis-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const program=page.match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes=new Map([...page.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],{innerHTML:'',textContent:'',value:'',checked:false,listeners:{},addEventListener(kind,fn){this.listeners[kind]=fn;}}]));
nodes.get('analysis-data').textContent=payload;nodes.get('country').value='all';
let savedBlob, clicked=false, anchor;
vm.runInNewContext(program,{document:{getElementById(id){assert(nodes.has(id));return nodes.get(id);},createElement(kind){assert.equal(kind,'a');anchor={click(){clicked=true}};return anchor;}},
  Blob,URL:{createObjectURL(blob){savedBlob=blob;return 'blob:test';},revokeObjectURL(){}},setTimeout(fn){fn();}},{timeout:5000});
const rows=()=>[...nodes.get('rows').innerHTML.matchAll(/<tr\b/g)].length;
assert.equal(rows(),60);assert.equal([...nodes.get('steps').innerHTML.matchAll(/<article/g)].length,8);
nodes.get('country').value='DEU';nodes.get('country').listeners.change();assert.equal(rows(),15);
nodes.get('only-caution').checked=true;nodes.get('only-caution').listeners.change();assert.equal(rows(),4);
assert(nodes.get('rows').innerHTML.includes('620,174'));
nodes.get('country').value='all';nodes.get('country').listeners.change();assert.equal(rows(),5);
nodes.get('country').value='KOR';nodes.get('country').listeners.change();assert.equal(rows(),0);
assert(nodes.get('row-count').textContent.startsWith('0쌍'));
nodes.get('only-caution').checked=false;nodes.get('only-caution').listeners.change();assert.equal(rows(),15);
nodes.get('download').listeners.click();assert(clicked);assert.equal(anchor.download,'population-comparison-KOR.json');
const exported=JSON.parse(await savedBlob.text());assert.equal(exported.length,15);assert(exported.every(r=>r.country==='KOR'));
for(const node of nodes.values()){assert(!node.innerHTML.includes('undefined'));assert(!node.innerHTML.includes('NaN'));}
const renderedMarkup=page.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')+[...nodes.values()].map(n=>n.innerHTML).join('');
for(const m of renderedMarkup.matchAll(/href="([^"]+)"/g)){
 const href=m[1];if(href.startsWith('#')){assert(nodes.has(href.slice(1)));continue;}
 if(/^https?:/.test(href))continue;
 assert(fs.existsSync(path.resolve(folder,href)),`Missing local link: ${href}`);
}
for(const s of JSON.parse(payload).process)assert(fs.existsSync(path.join(folder,s.evidence)));
const result={passed:true,checked_at:new Date().toISOString(),mode:'offline JavaScript DOM adapter; not browser layout verification',
 checks:['60 initial rows','8 process stages','country filter','5 caution pairs','combined filters and zero results','JSON export of selected rows','local evidence links','no undefined or NaN'],
 browser_visual_check:{status:'not_performed',reason:'Browser URL security policy rejected file URL; no alternate browser or local-server workaround attempted'},
 visual_figures:'PNG charts inspected separately from browser'};
fs.writeFileSync(path.join(folder,'ui-validation.json'),JSON.stringify(result,null,2));
console.log(JSON.stringify(result));
