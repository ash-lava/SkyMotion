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
 await test('Initial React render, challenge targets plus M101, and disabled empty playback',async()=>{const ui=setup();assert.match(ui.text(),/Find a target/);assert.equal(ui.nodes().filter(n=>n.props.className?.startsWith('target-row')).length,6);assert.equal(ui.button('Play observations').props.disabled,true);ui.cleanup();});
 await test('Correct Epsilon Indi B target and wider cutout',async()=>{const ui=setup();const item=ui.nodes().find(n=>n.props.className?.startsWith('target-row')&&JSON.stringify(n.props.children).includes('Epsilon Indi B'));item.props.onClick();await ui.settle();assert.equal(ui.field('Cutout size').props.value,6);assert.match(ui.text(),/331.04415/);ui.cleanup();});
 await test('Exposure load, metadata rendering, next frame and playback wait',async()=>{const ui=setup();ui.setResponder(normal);await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/3 of 3 exposures/);await ui.imageLoaded();await ui.click('Play observations');assert.ok([...ui.timers.values()].some(t=>t.ms===1000));await ui.click('Next exposure');assert.equal(ui.field('Exposure number').props.value,1);assert.ok(![...ui.timers.values()].some(t=>t.ms===1000));await ui.imageLoaded();ui.cleanup();});
 await test('All archive failures render retry state, not empty-results state',async()=>{const ui=setup();ui.setResponder(()=>response({detail:'SPHEREx temporarily unreachable'},503));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/Couldn’t load observations/);assert.doesNotMatch(ui.text(),/No observations found/);assert.ok(ui.button('Retry archive'));ui.cleanup();});
 await test('No observations render a true empty state',async()=>{const ui=setup();ui.setResponder(()=>response(sequence('a'.repeat(24),0)));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/No observations found/);assert.equal(ui.button('Play observations').props.disabled,true);ui.cleanup();});
 await test('Frame errors stop playback and provide retry',async()=>{const ui=setup();ui.setResponder(url=>url.startsWith('/api/frame/')?response({detail:'Test cutout unavailable'},502):normal(url));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/Test cutout unavailable/);assert.equal(ui.button('Play observations').props.disabled,true);assert.ok(ui.button('Retry frame'));ui.cleanup();});
 await test('Changing detector clears old observations',async()=>{const ui=setup();ui.setResponder(normal);await ui.click('Load SPHEREx exposures');await ui.change('SPHEREx detector','D4');assert.equal(ui.field('SPHEREx detector').props.value,'D4');assert.equal(ui.button('Play observations').props.disabled,true);assert.doesNotMatch(ui.text(),/3 of 3 exposures/);ui.cleanup();});
 await test('Late results cannot overwrite a newly selected target',async()=>{const ui=setup();let finish;ui.setResponder(()=>new Promise(r=>finish=r));await ui.click('Load SPHEREx exposures');const item=ui.nodes().find(n=>n.props.className?.startsWith('target-row')&&JSON.stringify(n.props.children).includes('WISE 0855'));item.props.onClick();await ui.settle();finish(response(sequence()));await ui.settle();assert.match(ui.text(),/WISE 0855/);assert.doesNotMatch(ui.text(),/3 of 3 exposures/);assert.equal(ui.field('Cutout size').props.value,12);ui.cleanup();});
 await test('Shared URLs restore controls and auto-load requested sequence',async()=>{const ui=setup('?ra=133.7951292&dec=-7.2451472&fov=12&band=D3&layer=wise&mode=sequence');await ui.settle();assert.equal(ui.field('SPHEREx detector').props.value,'D3');assert.equal(ui.field('Sky survey').props.value,'wise');assert.ok(ui.calls.some(url=>url.includes('ra=133.7951292')&&url.includes('detector=D3')));ui.cleanup();});
 await test('Invalid URL coordinates fall back to M101',async()=>{const ui=setup('?ra=999&dec=100&fov=0&band=oops');assert.match(ui.text(),/Pinwheel Galaxy/);assert.equal(ui.field('Cutout size').props.value,6);ui.cleanup();});
 await test('Structured archive errors show the message rather than a generic status',async()=>{const ui=setup();ui.setResponder(()=>response({detail:{code:'SPHEREX_UNAVAILABLE',message:'Both IRSA search services need a retry.'}},503));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/Both IRSA search services need a retry/);assert.doesNotMatch(ui.text(),/\[object Object\]/);ui.cleanup();});
 await test('TAP recovery keeps playback usable with a compact warning and real release label',async()=>{const ui=setup();ui.setResponder(url=>url.startsWith('/api/observations')?response({...sequence(),search_method:'TAP',warnings:['TAP combines wide and deep products.'],observations:sequence().observations.map(o=>({...o,collection:'spherex_qr3'}))}):normal(url));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/An alternate IRSA search supplied these images/);assert.match(ui.text(),/Archive connection details/);assert.match(ui.text(),/TAP combines wide and deep products/);assert.match(ui.text(),/\/ QR3/);const notice=ui.nodes().find(n=>n.props.className?.startsWith('notice '));assert.match(notice.props.className,/notice-warning/);await ui.imageLoaded();assert.equal(ui.button('Play observations').props.disabled,false);ui.cleanup();});
 await test('Empty fallback results retain connection details',async()=>{const ui=setup();ui.setResponder(()=>response({...sequence('a'.repeat(24),0),search_method:'TAP',warnings:['Only the field center was searched.']}));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/No observations found/);assert.match(ui.text(),/Only the field center was searched/);assert.equal(ui.button('Play observations').props.disabled,true);ui.cleanup();});
 await test('Default page starts a live M101 search without a saved sample',async()=>{const ui=setup();await ui.settle();assert.ok(ui.calls.some(u=>u.startsWith('/api/observations?')&&u.includes('ra=210.80227')&&u.includes('dec=54.34895')));assert.ok(!ui.calls.some(u=>u.includes('/data/')));ui.cleanup();});
 await test('Atlas remains an explicit optional mode',async()=>{const ui=setup('?mode=atlas');await ui.settle();assert.ok(!ui.calls.some(u=>u.startsWith('/api/observations?')));ui.cleanup();});
 await test('Limited live samples disclose the lower-bound count and scope',async()=>{const ui=setup('?mode=atlas');ui.setResponder(url=>url.startsWith('/api/observations')?response({...sequence(),sampling_limited:true,total_lower_bound:true,warnings:['Live request reached MAXREC.']}):normal(url));await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/3 of at least 3 exposures/);assert.match(ui.text(),/Limited sample from IRSA/);ui.cleanup();});
 await test('Atlas URLs restore a map view independently of the selected SPHEREx target',async()=>{
  const ui=setup('?mode=atlas&ra=210.8&dec=54.3&atlas_ra=359.99&atlas_dec=-80&atlas_fov=180');
  const map=ui.nodes().find(n=>n.type?.name==='SkyMap');assert.equal(map.props.view.ra,359.99);assert.equal(map.props.view.dec,-80);assert.equal(map.props.view.fov,180);assert.equal(map.props.target.ra,210.8);ui.cleanup();
 });
 await test('Changing a suggested target preserves the atlas zoom',async()=>{
  const ui=setup('?mode=atlas');ui.nodes().find(n=>n.type?.name==='SkyMap').props.onCenter({ra:2,dec:3,fov:120});await ui.settle();
  ui.nodes().find(n=>n.props.className?.startsWith('target-row')&&JSON.stringify(n.props.children).includes('Barnard')).props.onClick();await ui.settle();
  const map=ui.nodes().find(n=>n.type?.name==='SkyMap');assert.equal(map.props.view.fov,120);assert.equal(map.props.target.ra,269.4521);ui.cleanup();
 });
 await test('Sharing a freely panned atlas retains its center and zoom',async()=>{
  const ui=setup('?mode=atlas');ui.nodes().find(n=>n.type?.name==='SkyMap').props.onCenter({ra:.25,dec:-42,fov:3});await ui.settle();await ui.nodes().find(n=>n.props.className==='share-button').props.onClick();await ui.settle();
  const p=new URL(ui.context.location.href).searchParams;assert.equal(p.get('atlas_ra'),'0.25');assert.equal(p.get('atlas_dec'),'-42');assert.equal(p.get('atlas_fov'),'3');assert.equal(p.get('ra'),'210.80227');ui.cleanup();
 });
 await test('Any valid coordinate pair opens the atlas without an exposure query',async()=>{
  const ui=setup('?mode=atlas');ui.nodes().find(n=>n.type==='button'&&JSON.stringify(n.props.children).includes('SPHEREx sequence')).props.onClick();await ui.settle();
  await ui.change('Right ascension in degrees','12.345');await ui.change('Declination in degrees','-90');
  ui.nodes().find(n=>n.type==='form'&&n.props.onSubmit?.name==='applyCoordinates').props.onSubmit({preventDefault(){}});await ui.settle();
  const map=ui.nodes().find(n=>n.type?.name==='SkyMap');assert.equal(map.props.target.ra,12.345);assert.equal(map.props.target.dec,-90);assert.equal(map.props.view.fov,6);assert.ok(!ui.calls.some(u=>u.startsWith('/api/observations?')));ui.cleanup();
 });
 await test('Selecting a panned position preserves its surrounding map field',async()=>{
  const ui=setup('?mode=atlas');ui.nodes().find(n=>n.type?.name==='SkyMap').props.onCenter({ra:45.6,dec:12.3,fov:120});await ui.settle();
  ui.nodes().find(n=>n.props.className==='search-area').props.onClick();await ui.settle();
  const map=ui.nodes().find(n=>n.type?.name==='SkyMap');assert.equal(map.props.target.ra,45.6);assert.equal(map.props.view.fov,120);ui.cleanup();
 });
 await test('An all-sky atlas view does not enlarge the SPHEREx science cutout',async()=>{
  const ui=setup('?mode=atlas&atlas_fov=360');ui.setResponder(normal);await ui.click('Load SPHEREx exposures');
  const call=ui.calls.find(u=>u.startsWith('/api/observations?'));assert.equal(new URL(call,'https://example.test').searchParams.get('fov'),'6');ui.cleanup();
 });
 await test('Coverage filter keeps immutable source indices for frames and overlays',async()=>{
  const ui=setup('?mode=atlas');const values=[1,.76,.98];ui.setResponder(url=>url.startsWith('/api/frame-info/')?response({coverage:values[Number(url.split('/').at(-1))],wavelength_um:1.2}):normal(url));
  await ui.click('Load SPHEREx exposures');await ui.imageLoaded();await ui.change('Exposure coverage','good');
  assert.match(ui.text(),/2 of 3 exposures/);await ui.click('Next exposure');
  assert.ok(ui.calls.some(u=>u.endsWith('/2.png')));ui.nodes().find(n=>n.type==='input'&&n.props.type==='checkbox').props.onChange({target:{checked:true}});await ui.settle();assert.ok(ui.calls.some(u=>u.endsWith('/2.json')));assert.match(ui.byType('img').props.alt,/03 Jan 2026/);
  await ui.imageLoaded();await ui.change('Exposure coverage','all');assert.equal(ui.field('Exposure number').props.value,2);ui.cleanup();
 });
 await test('Coverage excludes unverified frames and preserves all-frame recovery',async()=>{
  const ui=setup('?mode=atlas');ui.setResponder(url=>url.startsWith('/api/frame-info/')?(url.endsWith('/1')?response({detail:'Unavailable'},502):response({coverage:.8})):normal(url));
  await ui.click('Load SPHEREx exposures');await ui.change('Exposure coverage','good');
  assert.match(ui.text(),/No frames meet this coverage filter/);assert.match(ui.text(),/1 exposures could not be checked/);
  assert.equal(ui.button('Play observations').props.disabled,true);await ui.click('Show all frames');assert.match(ui.text(),/3 of 3 exposures/);ui.cleanup();
 });
 await test('Cancelled coverage checks cannot overwrite a changed detector',async()=>{
  const ui=setup('?mode=atlas');let finish;ui.setResponder(url=>url.startsWith('/api/frame-info/')?new Promise(resolve=>finish=resolve):normal(url));
  await ui.click('Load SPHEREx exposures');await ui.change('Exposure coverage','good');
  assert.equal(ui.button('Play observations').props.disabled,true);await ui.change('SPHEREx detector','D4');
  finish(response({coverage:1}));await ui.settle();assert.doesNotMatch(ui.text(),/3 of 3 exposures/);assert.equal(ui.field('SPHEREx detector').props.value,'D4');ui.cleanup();
 });
 await test('Missing-data legend distinguishes coverage from flag quality',async()=>{
  const ui=setup('?mode=atlas');ui.setResponder(url=>url.startsWith('/api/frame-info/')?response({coverage:.7599555,flagged_fraction:1}):normal(url));
  await ui.click('Load SPHEREx exposures');assert.match(ui.text(),/76.0% valid pixels/);assert.match(ui.text(),/Hatching: no valid data/);ui.cleanup();
 });
 console.log(`${passed} frontend state tests passed (no browser rendering).`);
})().catch(err=>{console.error(err);process.exitCode=1;});
