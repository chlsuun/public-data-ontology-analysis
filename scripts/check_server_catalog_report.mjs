// Exercise the generated report's controls without starting a network listener.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const path=process.argv[2];
const page=fs.readFileSync(path,'utf8');
const payload=page.match(/<script type="application\/json" id="reportData">([\s\S]*?)<\/script>/)[1];
const program=page.match(/<script>([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(payload);
const nodes=new Map([...page.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],{
  innerHTML:'',textContent:'',value:'',listeners:{},
  addEventListener(kind,fn){this.listeners[kind]=fn},
  scrollIntoView(){this.scrolled=true}
}]));
nodes.get('reportData').textContent=payload;
nodes.get('scope').value='all';nodes.get('sort').value='rows';
vm.runInNewContext(program,{document:{getElementById(id){assert(nodes.has(id),'Unknown DOM target: '+id);return nodes.get(id)}},URL,console},{timeout:5000});
const body=()=>nodes.get('portals').innerHTML;
const rows=()=>[...body().matchAll(/<tr\b/g)].length;
const expectedDomestic=data.sources.filter(s=>s.country==='대한민국').length;
assert.equal(rows(),data.sources.length);
nodes.get('scope').value='kr';nodes.get('scope').listeners.change();
assert.equal(rows(),expectedDomestic);
nodes.get('search').value='KOSIS';nodes.get('search').listeners.input();
assert.equal(rows(),1);assert.match(body(),/data-source="kosis"/);
nodes.get('search').value='';nodes.get('scope').value='foreign';nodes.get('scope').listeners.change();
assert.equal(rows(),data.sources.length-expectedDomestic);
nodes.get('scope').value='all';nodes.get('sort').value='score';nodes.get('sort').listeners.change();
assert.equal(rows(),data.sources.length);
const expectedFirst=[...data.sources].sort((a,b)=>(b.metrics.metadata_documentation_score_0_10??-1)-(a.metrics.metadata_documentation_score_0_10??-1))[0].id;
assert.equal(body().match(/data-source="([^"]+)"/)[1],expectedFirst);
for(const id of ['kosis','worldbank','finland']){
  nodes.get('portals').listeners.click({target:{closest(){return {dataset:{source:id}}}}});
  assert(nodes.get('detailTitle').textContent.includes(data.sources.find(s=>s.id===id).name));
  assert(nodes.get('selectedDetail').scrolled);
  assert(!nodes.get('detail').innerHTML.includes('undefined'));
  assert(!nodes.get('detail').innerHTML.includes('NaN'));
}
const result={passed:true,mode:'generated HTML with DOM adapter; no screenshot or live-browser claim',
  sources:data.sources.length,domestic:expectedDomestic,foreign:data.sources.length-expectedDomestic,
  checks:['initial table','domestic filter','foreign filter','KOSIS search','score sort','populated source detail','database-series source detail','empty source detail','all DOM targets exist','no undefined/NaN detail values']};
console.log(JSON.stringify(result));
