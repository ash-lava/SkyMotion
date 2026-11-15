/* React/htm state regression harness. Does not substitute for browser layout tests.
   Run with Node 20+: node test_frontend.cjs */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path'),root=__dirname;
const pause=()=>new Promise(r=>setImmediate(r));
function setup(search='') {
  let hook=0,states=[],refs=[],effects=[],pending=[],dirty=false,rootElement,tree;
  let handlers={},calls=[],timers=new Map(),nextTimer=0;
  let responder=async url=>new Response(JSON.stringify({detail:'Fixture missing: '+url}),{status:500});
  const context={console,URL,URLSearchParams,AbortController,Blob,Response,Map,Date,Promise,DOMException,
    location:{search,href:'https://example.test/'+search,reload(){}},history:{replaceState(a,b,url){context.location.href='https://example.test/'+url;}},navigator:{clipboard:{async writeText(){}}},
    document:{getElementById(){return {};},activeElement:{focus(){}},createElement(){return {click(){}}}},
    setTimeout(fn,ms){let n=++nextTimer;timers.set(n,{fn,ms});return n;},clearTimeout(n){timers.delete(n);},
    fetch:async(url,options={})=>{calls.push(String(url));const response=await responder(String(url),options);if(options.signal?.aborted)throw new DOMException('Aborted','AbortError');return response;}
  };
  context.self=context;context.window=context;context.addEventListener=(name,fn)=>handlers[name]=fn;context.removeEventListener=(name)=>delete handlers[name];
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'react.production.min.js'),'utf8'),context);
  const react=context.React;
  context.React={...react,
    useState(initial){const n=hook++;if(!(n in states))states[n]=typeof initial==='function'?initial():initial;return [states[n],v=>{states[n]=typeof v==='function'?v(states[n]):v;dirty=true;}];},
    useRef(value){const n=hook++;return refs[n]||(refs[n]={current:value});},
    useEffect(fn,deps){const n=hook++,prior=effects[n];if(!prior||deps.some((v,i)=>v!==prior.deps[i])){effects[n]={deps,cleanup:prior?.cleanup};pending.push(()=>{effects[n].cleanup?.();effects[n].cleanup=fn();});}}
  };
  context.ReactDOM={createRoot(){return {render(el){rootElement=el;}};}};
  vm.runInContext(fs.readFileSync(path.join(root,'htm.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),context);
  function render(){hook=0;dirty=false;tree=rootElement.type();const run=pending;pending=[];run.forEach(fn=>fn());return tree;}
  async function settle(){for(let i=0;i<10;i++){if(dirty||!tree)render();await pause();}if(dirty)render();}
  function flatten(node,out=[]){if(Array.isArray(node))node.forEach(n=>flatten(n,out));else if(node&&typeof node==='object'&&node.props){out.push(node);flatten(node.props.children,out);}return out;}
  function text(node){if(node==null||typeof node==='boolean')return '';if(Array.isArray(node))return node.map(text).join('');if(typeof node==='object')return text(node.props?.children);return String(node);}
  function find(predicate){const node=flatten(tree).find(predicate);assert.ok(node,'Element not found');return node;}
  const ui={settle,render,calls,context,timers,text:()=>text(tree),nodes:()=>flatten(tree),setResponder(fn){responder=fn;},
    button(name){return find(n=>n.type==='button'&&(n.props['aria-label']===name||text(n)===name));},
    field(name){return find(n=>(n.type==='input'||n.type==='select')&&n.props['aria-label']===name);},
    byType(type){return find(n=>n.type===type);},
    async click(name){ui.button(name).props.onClick();await settle();},
    async change(name,value){ui.field(name).props.onChange({target:{value}});await settle();},
    async imageLoaded(){ui.byType('img').props.onLoad();await settle();},
    cleanup(){effects.forEach(e=>e?.cleanup?.());timers.clear();}
  };render();return ui;
}
const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const sequence=(key='a'.repeat(24),n=3)=>({key,total:n,warnings:[],observations:Array.from({length:n},(_,i)=>({id:String(i),mjd:61000+i,date:`2026-01-0${i+1}T00:00:00Z`,band:'SPHEREx-D2',collection:'spherex_dr1'}))});
function normal(url){if(url.startsWith('/api/observations'))return response(sequence());if(url.startsWith('/api/frame-info'))return response({coverage:1,wavelength_um:1.23,flagged_fraction:0});if(url.startsWith('/api/frame/'))return new Response(new Blob(['fixture'],{type:'image/png'}));if(url.startsWith('/api/overlay'))return response({stars:[]});return response({detail:'fixture error'},503);}
(async()=>{
 let passed=0;
 async function test(name,fn){await fn();passed++;console.log('PASS '+name);}
 await test('Initial React render, five target presets, and disabled empty playback',async()=>{const ui=setup();assert.match(ui.text(),/A sky that never/);assert.equal(ui.nodes().filter(n=>n.props.className?.startsWith('target-row')).length,5);assert.equal(ui.button('Play observations').props.disabled,true);ui.cleanup();});
 await test('Correct Epsilon Indi B target and wider cutout',async()=>{const ui=setup();const item=ui.nodes().find(n=>n.props.className?.startsWith('target-row')&&JSON.stringify(n.props.children).includes('Epsilon Indi B'));item.props.onClick();await ui.settle();assert.equal(ui.field('Cutout size').props.value,6);assert.match(ui.text(),/331.04415/);ui.cleanup();});
 await test('Exposure load, metadata rendering, next frame and playback wait',async()=>{const ui=setup();ui.setResponder(normal);await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/3 of 3 exposures/);await ui.imageLoaded();await ui.click('Play observations');assert.ok([...ui.timers.values()].some(t=>t.ms===1000));await ui.click('Next exposure');assert.equal(ui.field('Exposure number').props.value,1);assert.ok(![...ui.timers.values()].some(t=>t.ms===1000));await ui.imageLoaded();ui.cleanup();});
 await test('All archive failures render retry state, not empty-results state',async()=>{const ui=setup();ui.setResponder(()=>response({detail:'SPHEREx temporarily unreachable'},503));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/archive couldn’t connect/);assert.doesNotMatch(ui.text(),/No exposures in this patch/);assert.ok(ui.button('Retry archive'));ui.cleanup();});
 await test('No observations render a true empty state',async()=>{const ui=setup();ui.setResponder(()=>response(sequence('a'.repeat(24),0)));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/No exposures in this patch/);assert.equal(ui.button('Play observations').props.disabled,true);ui.cleanup();});
 await test('Frame errors stop playback and provide retry',async()=>{const ui=setup();ui.setResponder(url=>url.startsWith('/api/frame/')?response({detail:'Test cutout unavailable'},502):normal(url));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/Test cutout unavailable/);assert.equal(ui.button('Play observations').props.disabled,true);assert.ok(ui.button('Retry frame'));ui.cleanup();});
 await test('Changing detector clears old observations',async()=>{const ui=setup();ui.setResponder(normal);await ui.click('Load SPHEREx exposures');await ui.change('SPHEREx detector','D4');assert.equal(ui.field('SPHEREx detector').props.value,'D4');assert.equal(ui.button('Play observations').props.disabled,true);assert.doesNotMatch(ui.text(),/3 of 3 exposures/);ui.cleanup();});
 await test('Late results cannot overwrite a newly selected target',async()=>{const ui=setup();let finish;ui.setResponder(()=>new Promise(r=>finish=r));await ui.click('Load SPHEREx exposures');const item=ui.nodes().find(n=>n.props.className?.startsWith('target-row')&&JSON.stringify(n.props.children).includes('WISE 0855'));item.props.onClick();await ui.settle();finish(response(sequence()));await ui.settle();assert.match(ui.text(),/WISE 0855/);assert.doesNotMatch(ui.text(),/3 of 3 exposures/);assert.equal(ui.field('Cutout size').props.value,12);ui.cleanup();});
 await test('Shared URLs restore controls and auto-load requested sequence',async()=>{const ui=setup('?ra=133.7951292&dec=-7.2451472&fov=12&band=D3&layer=wise&mode=sequence');await ui.settle();assert.equal(ui.field('SPHEREx detector').props.value,'D3');assert.equal(ui.field('Sky survey').props.value,'wise');assert.ok(ui.calls.some(url=>url.includes('ra=133.7951292')&&url.includes('detector=D3')));ui.cleanup();});
 await test('Invalid URL coordinates fall back to Orion',async()=>{const ui=setup('?ra=999&dec=100&fov=0&band=oops');assert.match(ui.text(),/Orion Nebula/);assert.equal(ui.field('Cutout size').props.value,3);ui.cleanup();});
 await test('Structured archive errors show the message rather than a generic status',async()=>{const ui=setup();ui.setResponder(()=>response({detail:{code:'SPHEREX_UNAVAILABLE',message:'Both IRSA search services need a retry.'}},503));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/Both IRSA search services need a retry/);assert.doesNotMatch(ui.text(),/\[object Object\]/);ui.cleanup();});
 await test('TAP recovery keeps playback usable with a compact warning and real release label',async()=>{const ui=setup();ui.setResponder(url=>url.startsWith('/api/observations')?response({...sequence(),search_method:'TAP',warnings:['TAP combines wide and deep products.'],observations:sequence().observations.map(o=>({...o,collection:'spherex_qr3'}))}):normal(url));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/An alternate IRSA search supplied these images/);assert.match(ui.text(),/Archive connection details/);assert.match(ui.text(),/TAP combines wide and deep products/);assert.match(ui.text(),/\/ QR3/);const notice=ui.nodes().find(n=>n.props.className?.startsWith('notice '));assert.match(notice.props.className,/notice-warning/);await ui.imageLoaded();assert.equal(ui.button('Play observations').props.disabled,false);ui.cleanup();});
 await test('Empty fallback results retain connection details',async()=>{const ui=setup();ui.setResponder(()=>response({...sequence('a'.repeat(24),0),search_method:'TAP',warnings:['Only the field center was searched.']}));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/No exposures in this patch/);assert.match(ui.text(),/Only the field center was searched/);assert.equal(ui.button('Play observations').props.disabled,true);ui.cleanup();});
 console.log(`${passed} frontend state tests passed (no browser rendering).`);
})().catch(err=>{console.error(err);process.exitCode=1;});
