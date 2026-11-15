/* Exercise the actual React SkyMap lifecycle with the built-in atlas API. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
async function scenario(kind){
 const effects=[],states=[],errors=[],centers=[],listeners={};let created=0,destroyed=0,remoteScripts=0,recentered=0,options;
 const fakeMap={on(name,fn){listeners[name]=fn;},gotoRaDec(){recentered++;},setFoV(){},setBaseImageLayer(){},destroy(){destroyed++;}};
 const c={URL,URLSearchParams,AbortController,Map,Date,Promise,console,location:{search:''},
  document:{getElementById(){return {};},createElement(){return {};},head:{appendChild(){remoteScripts++;}}},
  setTimeout,clearTimeout,ReactDOM:{createRoot(){return {render(){}};}},
  SkyAtlas:{create(element,opt){options=opt;created++;if(kind==='initialization-error')throw Error('Canvas unavailable');return fakeMap;}}
 };
 c.window=c;c.self=c;vm.createContext(c);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'react.production.min.js'),'utf8'),c);
 c.React={...c.React,useState(v){return [typeof v==='function'?v():v,()=>{}];},useRef(v){return {current:v};},useEffect(fn){effects.push(fn);}};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'htm.js'),'utf8'),c);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'app.js'),'utf8'),c);
 const SkyMap=vm.runInContext('SkyMap',c),ref={current:null};
 SkyMap({mapRef:ref,target:{ra:83,dec:-5},view:{ra:120,dec:-30,fov:120},survey:'dss',onCenter:v=>centers.push(v),onState:s=>states.push(s),onError:e=>errors.push(e)});
 const cleanup=effects[0]();assert.equal(created,1);assert.equal(remoteScripts,0);
 if(kind==='initialization-error'){
  assert.equal(ref.current,null);assert.equal(states.at(-1),'error');assert.match(errors.at(-1),/Canvas unavailable/);
 }else{
  assert.equal(ref.current,fakeMap);
  if(kind==='restored-view'){effects[1]();assert.equal(options.ra,120);assert.equal(options.dec,-30);assert.equal(options.fov,120);assert.equal(recentered,0);}
  if(kind==='ready'){listeners.ready();assert.equal(states.at(-1),'ready');assert.equal(errors.at(-1),'');}
  if(kind==='image-error'){listeners.error(Error('IRSA unavailable'));assert.equal(states.at(-1),'error');assert.equal(errors.at(-1),'IRSA unavailable');}
  if(kind==='cleanup'){
   cleanup();const size=states.length;listeners.ready();listeners.positionChanged({ra:9,dec:2});
   assert.equal(states.length,size);assert.equal(centers.length,1);assert.equal(destroyed,1);assert.equal(ref.current,null);
  }
 }
 if(kind!=='cleanup')cleanup();assert.equal(ref.current,null);console.log('PASS '+kind);
}
(async()=>{for(const kind of ['ready','image-error','initialization-error','cleanup','restored-view'])await scenario(kind);console.log('5 atlas lifecycle integration tests passed.');})().catch(e=>{console.error(e);process.exitCode=1;});
