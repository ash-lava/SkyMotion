/* Fallback geometry and fetch lifecycle tests; no browser or network required. */
const assert=require('node:assert/strict');
require('./sky-atlas.js');
const {pixelToSky,skyToPixel}=global.SkyAtlas;
let count=0;
function check(name,fn){fn();count++;console.log('PASS '+name);}
check('TAN center is exact',()=>{const v={ra:359.98,dec:-70,fov:8};const p=pixelToSky(600,400,1200,800,v);assert.ok(Math.abs(p.ra-v.ra)<1e-9);assert.ok(Math.abs(p.dec-v.dec)<1e-9);});
check('RA increases leftward and Dec upward',()=>{const v={ra:100,dec:0,fov:2};assert.ok(pixelToSky(100,400,1200,800,v).ra>100);assert.ok(pixelToSky(600,100,1200,800,v).dec>0);});
check('Projection round trips through RA wrap and polar fields',()=>{for(const dec of [-89.99,-70,0,70,89.99])for(const ra of [.001,359.999])for(const fov of [.01,1.4,60]){const v={ra,dec,fov};for(const [x,y] of [[100,100],[1199,799],[600,400],[1,700]]){const world=pixelToSky(x,y,1200,800,v);const back=skyToPixel(world.ra,world.dec,1200,800,v);assert.ok(Math.abs(back[0]-x)<1e-5);assert.ok(Math.abs(back[1]-y)<1e-5);}}});
check('Largest image dimension has requested angular field',()=>{const v={ra:90,dec:0,fov:25};const a=pixelToSky(0,200,1000,400,v),b=pixelToSky(1000,200,1000,400,v);assert.ok(Math.abs(a.ra-b.ra-25)<1e-9);});
check('Opposite hemisphere is excluded',()=>assert.equal(skyToPixel(180,0,1000,500,{ra:0,dec:0,fov:1}),null));
const tick=()=>new Promise(r=>setImmediate(r));
class Element{constructor(){this.style={};this.children=[];this.classList={add(){},remove(){}};this.handlers={};}appendChild(el){this.children.push(el);}replaceChildren(){this.children=[];}setAttribute(){}addEventListener(n,f){this.handlers[n]=f;}removeEventListener(n){delete this.handlers[n];}getBoundingClientRect(){return {left:0,top:0,width:1000,height:700};}getContext(){return {clearRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillText(){}};}focus(){}setPointerCapture(){}}
global.document={createElement:()=>new Element()};global.ResizeObserver=class{observe(){}disconnect(){}};global.Image=class{async decode(){}};
(async()=>{
 let calls=[],responses=[],ready=0,error='';global.fetch=async(url,{signal})=>{calls.push(String(url));return responses.shift()(signal);};
 const el=new Element(),atlas=SkyAtlas.create(el,{ra:83.8,dec:-5.3,fov:1.4,survey:'P/DSS2/color'});clearTimeout(atlas.timer);
 atlas.on('ready',()=>ready++);atlas.on('error',e=>error=e.message);
 responses.push(()=>new Response(new Blob(['test image'],{type:'image/jpeg'})));await atlas.load();
 check('Fallback loads through same-origin API',()=>{assert.match(calls[0],/^\/api\/sky.jpg\?/);assert.equal(ready,1);assert.ok(Math.abs(atlas.shown.ra-83.8)<1e-9);assert.equal(atlas.survey,'dss');});
 responses.push(()=>new Response(JSON.stringify({detail:{message:'Both survey mirrors unavailable'}}),{status:503}));await atlas.load();
 check('Structured upstream errors reach the UI',()=>assert.equal(error,'Both survey mirrors unavailable'));
 let finish;responses.push(()=>new Promise(resolve=>finish=resolve));const oldLoad=atlas.load();atlas.gotoRaDec(120,30);clearTimeout(atlas.timer);finish(new Response(new Blob(['old frame'])));await oldLoad;
 check('Cancelled images cannot replace the current sky patch',()=>{assert.equal(atlas.view.ra,120);assert.ok(Math.abs(atlas.shown.ra-83.8)<1e-9);assert.equal(ready,1);});
 atlas.setFoV(180);clearTimeout(atlas.timer);check('Fallback zoom is bounded to a usable TAN field',()=>assert.equal(atlas.getFov()[0],60));
 atlas.destroy();check('Cleanup releases the atlas and its events',()=>{assert.equal(el.children.length,0);assert.equal(Object.keys(el.handlers).length,0);});
 console.log(`${count} atlas tests passed (mock image responses; no live service claim).`);
})().catch(error=>{console.error(error);process.exitCode=1;});
