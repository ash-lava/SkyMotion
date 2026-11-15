/* Exercise the actual React SkyMap loader with fake Aladin and local atlas APIs. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
async function scenario(kind){
 const effects=[],states=[],errors=[];let fallback=0,aladin=0;
 const fakeMap={on(){},gotoRaDec(){},setFoV(){},setBaseImageLayer(){},destroy(){}};
 const c={console:{warn(){}},URL,URLSearchParams,AbortController,Map,Date,Promise,location:{search:''},
  document:{getElementById(){return {};},createElement(){return {};},head:{appendChild(script){queueMicrotask(()=>script.onerror());}}},
  setTimeout(){return 1;},clearTimeout(){},ReactDOM:{createRoot(){return {render(){}};}},
  SkyAtlas:{create(){fallback++;return fakeMap;}},
  fakeAladin(){aladin++;if(kind==='constructor-failure')throw Error('WebGL failed');return fakeMap;}
 };
 c.window=c;c.self=c;vm.createContext(c);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'react.production.min.js'),'utf8'),c);
 c.React={...c.React,useState(v){return [typeof v==='function'?v():v,()=>{}];},useRef(v){return {current:v};},useEffect(fn){effects.push(fn);}};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'htm.js'),'utf8'),c);
 if(kind==='lexical-global')vm.runInContext('const A={init:Promise.resolve(),aladin:fakeAladin};',c);
 if(kind==='constructor-failure')c.A={init:Promise.resolve(),aladin:c.fakeAladin};
 if(kind==='wasm-failure')c.A={init:Promise.reject(Error('WASM blocked')),aladin:c.fakeAladin};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'app.js'),'utf8'),c);
 const SkyMap=vm.runInContext('SkyMap',c),ref={current:null};
 SkyMap({mapRef:ref,target:{ra:83,dec:-5},survey:'dss',onCenter(){},onState:s=>states.push(s),onError:e=>errors.push(e)});
 const cleanup=effects[0]();for(let i=0;i<4;i++)await new Promise(r=>setImmediate(r));
 assert.equal(ref.current,fakeMap);
 if(kind==='lexical-global'){assert.equal(c.A,undefined);assert.equal(aladin,1);assert.equal(fallback,0);assert.ok(states.includes('ready'));}
 else assert.equal(fallback,1);
 cleanup();assert.equal(ref.current,null);console.log('PASS '+kind);
}
(async()=>{for(const kind of ['lexical-global','script-blocked','wasm-failure','constructor-failure'])await scenario(kind);console.log('4 map loader integration tests passed.');})().catch(e=>{console.error(e);process.exitCode=1;});
