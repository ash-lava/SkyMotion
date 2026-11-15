const {useState,useEffect}=React,html=htm.bind(React.createElement);
const TARGETS=[['WISE 0855',133.79513,-7.24515,'coldest known brown dwarf, fast mover'],['Barnard’s Star',269.4521,4.6934,'high proper motion'],['Epsilon Indi B',330.84,-56.78,'brown dwarf pair'],['RW Aurigae',76.95,30.4,'variable star'],['R Draconis',248.17,66.755,'variable star']];
const api=async u=>{const r=await fetch(u);let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.detail||`Request failed (${r.status})`);return d};
const day=d=>d?d.slice(0,10):'unknown';
const mjdYear=m=>new Date((m-40587)*864e5).getUTCFullYear();
const jan1=y=>Date.UTC(y,0,1)/864e5+40587;

function Plate({src,fov,stars,onLoad,onError}){
  const t=[];for(let k=0;k<=20;k++){const L=k%5?1.6:3.4,p=k*5;t.push(html`<path key=${k} vectorEffect="non-scaling-stroke" d=${`M${p} 0v${L}M${p} 100v${-L}M0 ${p}h${L}M100 ${p}h${-L}`}/>`)}
  return html`<div className="plate" role="img" aria-label="SPHEREx cutout">
    ${src?html`<img src=${src} alt="" onLoad=${onLoad} onError=${onError}/>`:html`<div className="none">The plate is empty.<br/>Find a target to pull real exposures.</div>`}
    <svg viewBox="0 0 100 100" preserveAspectRatio="none"><g stroke="#d3d5e4" strokeWidth="1" fill="none" opacity=".75">${t}</g>
      <g stroke="#d3d5e4" strokeWidth="1.2" vectorEffect="non-scaling-stroke"><path d="M50 44v4M50 52v4M44 50h4M52 50h4" vectorEffect="non-scaling-stroke"/></g>
      ${(stars?.stars||[]).map(s=>{const fast=s.pm>100;return html`<ellipse key=${s.id} cx=${s.x*100} cy=${s.y*100} rx=${Math.max(1.1,3.3-((s.g??18)-8)*.17)} ry=${Math.max(1.1,3.3-((s.g??18)-8)*.17)} fill="none" stroke=${fast?'#ffcb78':'#d3d5e4'} strokeWidth="1.4" strokeDasharray=${fast?'4 3':''} vectorEffect="non-scaling-stroke"/>`})}
    </svg></div>`;
}

function App(){
  const [q,setQ]=useState(''),[fov,setFov]=useState(3),[band,setBand]=useState('D2'),[view,setView]=useState(null),[obs,setObs]=useState([]),[key,setKey]=useState(''),[total,setTotal]=useState(0),[i,setI]=useState(0);
  const [msg,setMsg]=useState({t:'Name a star or enter coordinates, for example 08h55m10.8s -07d14m42s.'}),[busy,setBusy]=useState(false),[play,setPlay]=useState(false),[speed,setSpeed]=useState(900),[shown,setShown]=useState(-1),[gaia,setGaia]=useState(false),[stars,setStars]=useState(null),[phot,setPhot]=useState([]);
  const qs=v=>new URLSearchParams({ra:v.ra,dec:v.dec,fov:v.fov}).toString();
  const frame=k=>view&&key?`/api/frame/${key}/${k}.png?${qs(view)}`:'';

  async function search(ra,dec,f=fov,b=band){
    setBusy(true);setPlay(false);setPhot([]);setStars(null);setShown(-1);setMsg({t:'Asking the archive which exposures cover this patch…'});
    try{const d=await api('/api/observations?'+new URLSearchParams({ra,dec,fov:f,detector:b,limit:32}));
      setView({ra,dec,fov:f,band:b});setObs(d.observations);setKey(d.key);setTotal(d.total);setI(0);
      setMsg(d.observations.length?{t:`${d.total} exposures cover this patch. Showing ${d.observations.length}, spread across the survey.${d.warnings.length?` ${d.warnings.length} archive collection(s) did not answer.`:''}`}:{t:'No exposures here. Try another detector, or open the field wider.',bad:true});
      history.replaceState(null,'',`?ra=${ra}&dec=${dec}&fov=${f}&band=${b}`);
    }catch(e){setMsg({t:e.message,bad:true})}finally{setBusy(false)}
  }
  async function locate(e){e&&e.preventDefault();const text=q.trim();if(!text)return;setBusy(true);setMsg({t:`Looking up “${text}”…`});
    try{const d=await api('/api/resolve?q='+encodeURIComponent(text));await search(d.ra,d.dec)}catch(x){setMsg({t:x.message,bad:true});setBusy(false)}}
  const pick=t=>{setQ(t[0]);search(t[1],t[2])};
  useEffect(()=>{const p=new URLSearchParams(location.search);if(p.has('ra')&&p.has('dec')){const f=+p.get('fov')||3,b=p.get('band')||'D2';setFov(f);setBand(b);search(+p.get('ra'),+p.get('dec'),f,b)}},[]);
  // Playback waits for the current frame to load, so slow archive fetches never flicker.
  useEffect(()=>{if(!play||shown!==i||!obs.length)return;const t=setTimeout(()=>setI(x=>(x+1)%obs.length),speed);return()=>clearTimeout(t)},[play,shown,i,speed,obs.length]);
  useEffect(()=>{if(!gaia||!key||!view){setStars(null);return}let off=false;api(`/api/overlay/${key}/${i}.json?${qs(view)}`).then(d=>!off&&setStars(d)).catch(e=>!off&&setStars({stars:[],note:e.message}));return()=>{off=true}},[gaia,key,i,view]);
  async function measure(){setBusy(true);setMsg({t:'Measuring up to 18 frames. Each is read from the archive, so this can take minutes.'});
    try{const d=await api(`/api/photometry/${key}?${qs(view)}&max_frames=18`);setPhot(d.measurements.filter(m=>Number.isFinite(m.proxy)));setMsg({t:d.warning})}catch(e){setMsg({t:e.message,bad:true})}finally{setBusy(false)}}

  const o=obs[i],mj=obs.map(x=>x.mjd),have=obs.length>1&&mj.every(Number.isFinite),t0=have?Math.min(...mj):0,t1=have?Math.max(...mj):Math.max(obs.length-1,1);
  const xOf=k=>10+((have?obs[k].mjd:k)-t0)/((t1-t0)||1)*980;
  const years=have?Array.from({length:mjdYear(t1)-mjdYear(t0)+1},(_,k)=>mjdYear(t0)+k).filter(y=>jan1(y)>=t0&&jan1(y)<=t1):[];
  const pv=phot.map(m=>m.proxy),lo=Math.min(...pv),hi=Math.max(...pv),yOf=v=>92-(v-lo)/((hi-lo)||1)*66;
  return html`<div className="app">
    <header className="rail"><h1>SkyMotion</h1><p className="tag">The infrared sky, exposure by exposure. Watch a patch of sky change and catch what moves.</p>
      <h2>Targets to test</h2><ul>${TARGETS.map(t=>html`<li key=${t[0]}><button onClick=${()=>pick(t)}><b>${t[0]}</b><small>${t[3]}</small></button></li>`)}</ul>
</header>
    <main>
      <form className="find" onSubmit=${locate}><input value=${q} onChange=${e=>setQ(e.target.value)} placeholder="Barnard’s Star" aria-label="Target name or coordinates"/>
        <label>Field<select value=${fov} onChange=${e=>{const f=+e.target.value;setFov(f);view&&search(view.ra,view.dec,f,band)}}>${[1,2,3,6,12].map(f=>html`<option key=${f} value=${f}>${f}′ across</option>`)}</select></label>
        <label>Detector<select value=${band} onChange=${e=>{setBand(e.target.value);view&&search(view.ra,view.dec,fov,e.target.value)}}>${['D1','D2','D3','D4','D5','D6','all'].map(b=>html`<option key=${b}>${b}</option>`)}</select></label>
        <button className="go" disabled=${busy}>${busy?'Working…':'Find'}</button></form>
      <p className=${'status'+(msg.bad?' bad':'')} role="status">${msg.t}</p>
      <${Plate} src=${o?frame(i):''} fov=${view?.fov} stars=${gaia?stars:null} onLoad=${()=>setShown(i)} onError=${()=>{setShown(i);setMsg({t:`Frame ${i+1} could not be read from the archive.`,bad:true})}}/>
      <p className="cap">${view?`Ticks mark ${(view.fov/4).toFixed(2)}′ (long) and ${(view.fov/20).toFixed(2)}′ (short) from the edge. Centered on RA ${(+view.ra).toFixed(4)}°, Dec ${(+view.dec).toFixed(4)}°. Each frame is stretched on its own.`:''}${gaia&&stars?(stars.note||` ${stars.stars.length} Gaia stars, moved to this date. Dashed amber moves fast. A mover with no ring is worth a look.`):''}</p>
      <div className="ctl"><button onClick=${()=>setI((i+obs.length-1)%obs.length)} disabled=${!obs.length}>Back</button><button onClick=${()=>setPlay(!play)} disabled=${!obs.length}>${play?'Pause':'Play'}</button><button onClick=${()=>setI((i+1)%obs.length)} disabled=${!obs.length}>Forward</button>
        <label>Pace<select value=${speed} onChange=${e=>setSpeed(+e.target.value)}><option value="1800">Slow</option><option value="900">Steady</option><option value="400">Fast</option></select></label>
        <label><input type="checkbox" checked=${gaia} onChange=${e=>setGaia(e.target.checked)} disabled=${!obs.length}/>Gaia stars</label>
        <button onClick=${measure} disabled=${!obs.length||busy}>Measure brightness</button></div>
      ${obs.length?html`<div style=${{marginTop:30}}><svg className="axis" viewBox="0 0 1000 64" role="group" aria-label="Exposure dates on a shared time axis"><line x1="10" x2="990" y1="34" y2="34" stroke="#2a2650"/>
        ${obs.map((x,k)=>html`<g key=${k}><line x1=${xOf(k)} x2=${xOf(k)} y1=${k===i?10:24} y2="34" stroke=${k===i?'#a08cff':'#d3d5e4'} strokeWidth=${k===i?3:1.2}/><rect className="hit" x=${xOf(k)-7} y="6" width="14" height="34" onClick=${()=>{setPlay(false);setI(k)}}><title>${day(x.date)}</title></rect></g>`)}
        ${years.map(y=>html`<g key=${y}><line x1=${xOf0(jan1(y),t0,t1)} x2=${xOf0(jan1(y),t0,t1)} y1="36" y2="44" stroke="#8f91ab"/><text x=${xOf0(jan1(y),t0,t1)} y="60" textAnchor="middle">${y}</text></g>`)}</svg>
        ${phot.length?html`<svg className="axis" viewBox="0 0 1000 100" style=${{marginTop:6}} role="img" aria-label="Brightness proxy over time"><polyline fill="none" stroke="#d3d5e4" strokeWidth="1.4" points=${phot.map(m=>`${xOf(m.index)},${yOf(m.proxy)}`).join(' ')}/>${phot.map(m=>html`<circle key=${m.index} cx=${xOf(m.index)} cy=${yOf(m.proxy)} r=${m.index===i?5:3} fill=${m.index===i?'#a08cff':'#d3d5e4'}/>`)}<text x="12" y="14">uncalibrated brightness, same time axis</text></svg>`:null}</div>`:null}
    </main>
    <aside className="ledger"><dl>
      <dt>Exposure</dt><dd>${o?`${i+1} of ${obs.length}`:'none loaded'}</dd>
      <dt>Taken</dt><dd>${o?day(o.date):'-'}</dd>
      <dt>Detector</dt><dd>${o?o.band.replace('SPHEREx-',''):'-'}</dd>
      <dt>Wavelength</dt><dd>${o&&o.em_min?`${(o.em_min*1e6).toFixed(2)} to ${(o.em_max*1e6).toFixed(2)} µm`:'-'}</dd>
      <dt>Release</dt><dd>${o?o.collection.replace('spherex_','').toUpperCase():'-'}</dd>
      <dt>Newest in this sample</dt><dd>${obs.length?day(obs.map(x=>x.date).filter(Boolean).sort().pop()):'-'}</dd></dl>
      <p style=${{marginTop:30}}>SPHEREx reads a different wavelength at each spot on its detector, so two frames can differ because of colour, not because anything changed. Compare frames from the same detector.</p><p className="credit">Images: NASA/IPAC Infrared Science Archive, SPHEREx. Stars: ESA Gaia DR3. Names: SIMBAD, CDS. An independent project, not an official NASA product.</p></aside></div>`;
}
const xOf0=(m,t0,t1)=>10+(m-t0)/((t1-t0)||1)*980;
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
