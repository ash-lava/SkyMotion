/* SkyMotion / React 18 + htm. No Node build required. */
const {useState, useEffect, useRef} = React;
const html = htm.bind(React.createElement);
const ICONS = {
  search: 'M21 21l-5-5M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15',
  arrow: 'M5 12h14M13 6l6 6-6 6', plus: 'M12 5v14M5 12h14', minus: 'M5 12h14',
  cross: 'M6 6l12 12M6 18L18 6', target: 'M12 2v4M12 18v4M2 12h4M18 12h4M19 12a7 7 0 1 0-14 0 7 7 0 0 0 14 0',
  layers: 'M12 3L2 8l10 5 10-5-10-5M2 12l10 5 10-5M2 16l10 5 10-5',
  share: 'M10 14l4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0',
  info: 'M12 11v6M12 7h.01M22 12a10 10 0 1 0-20 0 10 10 0 0 0 20 0',
  back: 'M6 5v14M18 5l-9 7 9 7V5', next: 'M18 5v14M6 5l9 7-9 7V5',
  play: 'M8 4l12 8-12 8V4', pause: 'M8 5v14M16 5v14',
  refresh: 'M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-2l2 2M4 17l2 2a7 7 0 0 0 12-2',
  globe: 'M22 12a10 10 0 1 0-20 0 10 10 0 0 0 20 0M2 12h20M12 2c-6 5-6 15 0 20M12 2c6 5 6 15 0 20',
  grid: 'M3 3h18v18H3V3M3 9h18M3 15h18M9 3v18M15 3v18',
  menu: 'M4 6h16M4 12h16M4 18h16', star: 'M12 2l2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2',
  download: 'M12 3v12M7 10l5 5 5-5M4 16v5h16v-5'
};
function Icon({name, size=18}) {
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d=${ICONS[name] || ICONS.star}/></svg>`;
}
const M101 = {name:'Pinwheel Galaxy',ra:210.80227,dec:54.34895,type:'Spiral galaxy · live IRSA',tag:'M101',fov:6};
const TARGETS = [M101,
  {name: 'Barnard’s Star', ra:269.4521, dec:4.6934, type:'High proper motion', tag:'01', fov:12},
  {name: 'Epsilon Indi B', ra:331.0441466, dec:-56.7828442, type:'Brown dwarf pair', tag:'02', fov:6},
  {name: 'WISE 0855', ra:133.7951292, dec:-7.2451472, type:'Cold brown dwarf', tag:'03', fov:12},
  {name: 'RW Aurigae', ra:76.9565260, dec:30.4014382, type:'Variable star', tag:'04'},
  {name: 'R Draconis', ra:248.1676075, dec:66.7549842, type:'Variable star', tag:'05'}
];
const SURVEYS = {
  dss: {id:'P/DSS2/color', label:'DSS · Optical color', short:'DSS2 color', credit:'DSS / STScI · IRSA'},
  mass: {id:'P/2MASS/color', label:'2MASS · Near-infrared', short:'2MASS infrared', credit:'2MASS / UMass / IPAC · IRSA'},
  wise: {id:'P/allWISE/color', label:'WISE · Infrared color', short:'AllWISE infrared', credit:'WISE / NASA / JPL / UCLA · IRSA'}
};
const DETECTORS = {D1:'0.75–1.1 µm',D2:'1.1–1.6 µm',D3:'1.6–2.4 µm',D4:'2.4–3.8 µm',D5:'3.8–4.4 µm',D6:'4.4–5.0 µm'};
const date = d => d ? new Date(d).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'}) : 'Date unavailable';
const observed = d => d ? `${date(d)} · ${new Date(d).toLocaleTimeString('en-GB',{hour12:false,timeZone:'UTC'})}` : 'Date unavailable';
const MIN_COVERAGE=.95;
const coveragePercent = value => value>=1?'100%':value>=.9995?'>99.9%':`${(value*100).toFixed(1)}%`;
const coords = t => `${t.ra.toFixed(5)}°, ${t.dec >= 0 ? '+' : ''}${t.dec.toFixed(5)}°`;
function errorMessage(payload, fallback) {
  return typeof payload.detail === 'string' ? payload.detail : payload.detail?.message || fallback;
}
function archiveDetails(warnings) {
  if (!warnings?.length) return null;
  return html`<details className="archive-details"><summary>Archive connection details</summary><ul>${warnings.map((warning,k)=>html`<li key=${k}>${warning}</li>`)}</ul></details>`;
}
async function api(url, signal) {
  const response = await fetch(url, {signal});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(payload, `Request failed (${response.status}). Please retry.`));
  return payload;
}
function initialState() {
  const p = new URLSearchParams(location.search), ra = Number(p.get('ra')), dec = Number(p.get('dec'));
  const valid = p.has('ra') && p.has('dec') && Number.isFinite(ra) && Number.isFinite(dec) && ra>=0 && ra<360 && dec>=-90 && dec<=90;
  const target=valid ? {name:'Selected sky patch',ra,dec,type:'Shared coordinates'} : M101;
  const ar=Number(p.get('atlas_ra')),ad=Number(p.get('atlas_dec')),af=Number(p.get('atlas_fov'));
  const atlasValid=p.has('atlas_ra')&&p.has('atlas_dec')&&Number.isFinite(ar)&&Number.isFinite(ad)&&ar>=0&&ar<360&&ad>=-90&&ad<=90;
  return {target,view:{ra:atlasValid?ar:target.ra,dec:atlasValid?ad:target.dec,fov:Number.isFinite(af)&&af>=.01&&af<=360?af:6},
    fov:[1,2,3,6,12].includes(+p.get('fov')) ? +p.get('fov') : (valid ? 3 : 6),
    band:DETECTORS[p.get('band')] ? p.get('band') : 'D2',
    survey:SURVEYS[p.get('layer')] ? p.get('layer') : 'dss',
    auto:valid ? p.get('mode')==='sequence' : !p.has('ra')&&!p.has('dec')&&p.get('mode')!=='atlas'&&!p.has('atlas')};
}
function SkyMap({mapRef,target,view={ra:target.ra,dec:target.dec,fov:6},survey,grid=false,onCenter,onState,onError}) {
  const priorTarget=useRef(target);
  useEffect(()=>{
    let cancelled=false,active=null;
    onError('');onState('loading');
    try{
      const map=window.SkyAtlas.create(document.getElementById('sky-map'),{
        ra:view.ra,dec:view.dec,fov:view.fov,survey:SURVEYS[survey].id});
      active=map;mapRef.current=map;
      map.on('positionChanged',position=>{if(!cancelled)onCenter(position);});
      map.on('loading',()=>{if(!cancelled&&!map.shown)onState('loading');});
      map.on('ready',()=>{if(!cancelled){onError('');onState('ready');}});
      map.on('error',error=>{if(!cancelled){onError(error.message);onState('error');}});
      onCenter({...view});
    }catch(error){onError('The map could not start: '+error.message);onState('error');}
    return()=>{cancelled=true;active?.destroy();mapRef.current=null;};
  },[]);
  useEffect(()=>{
    if(mapRef.current){
      if(priorTarget.current!==target)mapRef.current.gotoRaDec(target.ra,target.dec);
      mapRef.current.setSelection?.(target);
    }
    priorTarget.current=target;
  },[target]);
  useEffect(()=>{mapRef.current?.setCooGrid?.({enabled:grid});},[grid]);
  useEffect(()=>{if(mapRef.current)mapRef.current.setBaseImageLayer(SURVEYS[survey].id);},[survey]);
  return html`<div id="sky-map" role="region" aria-label="Interactive sky map. Drag to pan and scroll to zoom."/>`;
}
function Modal({title,onClose,children}) {
  const ref=useRef();
  useEffect(()=>{const before=document.activeElement;ref.current.showModal();return()=>{ref.current?.close();before?.focus();};},[]);
  return html`<dialog ref=${ref} className="modal" onCancel=${onClose} onClick=${e=>{if(e.target===ref.current)onClose();}}>
    <div className="modal-head"><h2>${title}</h2><button className="icon-button" aria-label="Close dialog" onClick=${onClose}><${Icon} name="cross"/></button></div>${children}
  </dialog>`;
}
function App() {
  const [initial]=useState(initialState);
  const [target,setTarget]=useState(initial.target),[query,setQuery]=useState(''),[fov,setFov]=useState(initial.fov),[band,setBand]=useState(initial.band);
  const [raInput,setRaInput]=useState(initial.target.ra.toFixed(6)),[decInput,setDecInput]=useState(initial.target.dec.toFixed(6));
  const [center,setCenter]=useState(initial.view),[survey,setSurvey]=useState(initial.survey),[mapState,setMapState]=useState('loading'),[mapError,setMapError]=useState('');
  const [panel,setPanel]=useState(false),[about,setAbout]=useState(false),[grid,setGrid]=useState(false),[toast,setToast]=useState('');
  const [mode,setMode]=useState(initial.auto?'sequence':'atlas'),[busy,setBusy]=useState(false),[resolving,setResolving]=useState(false),[status,setStatus]=useState(null);
  const [data,setData]=useState(null),[index,setIndex]=useState(0),[playing,setPlaying]=useState(false),[speed,setSpeed]=useState(1000);
  const [frame,setFrame]=useState(null),[frameError,setFrameError]=useState(''),[frameBusy,setFrameBusy]=useState(false),[retry,setRetry]=useState(0),[ready,setReady]=useState(-1);
  const [coverageMode,setCoverageMode]=useState('all'),[coverageInfo,setCoverageInfo]=useState({}),[coverageScan,setCoverageScan]=useState(null);
  const coverageRef=useRef(null);
  const [info,setInfo]=useState(null),[gaia,setGaia]=useState(false),[stars,setStars]=useState(null),[gaiaError,setGaiaError]=useState('');
  const [phot,setPhot]=useState(null),[measuring,setMeasuring]=useState(false),[photOpen,setPhotOpen]=useState(false),[notesOpen,setNotesOpen]=useState(false);
  const mapRef=useRef(null), searchRef=useRef(null), resolveRef=useRef(null), blobs=useRef(new Map()), photoRef=useRef(null);
  const allObs=data?.observations || [];
  const visibleIndices=allObs.map((_,i)=>i).filter(i=>coverageMode==='all'||Number.isFinite(coverageInfo[i]?.coverage)&&coverageInfo[i].coverage>=MIN_COVERAGE);
  const obs=visibleIndices.map(i=>({...allObs[i],sourceIndex:i})),o=obs[index],sourceIndex=o?.sourceIndex??0;
  const frameMatches=frame?.index===sourceIndex&&frame?.key===data?.key;
  const releases = [...new Set(obs.map(row=>row.collection.replace('spherex_', '').replace('_deep', '').toUpperCase()))];
  const selectedMoved = Math.abs(((center.ra-target.ra+540)%360)-180)>.0001 || Math.abs(center.dec-target.dec)>.0001;

  function resetCoverage(){coverageRef.current?.abort();coverageRef.current=null;setCoverageMode('all');setCoverageInfo({});setCoverageScan(null);}
  function clearSequence() {
    resetCoverage();
    searchRef.current?.abort(); photoRef.current?.abort();
    setBusy(false);setPlaying(false);setData(null);setFrame(null);setInfo(null);setStars(null);setPhot(null);setPhotOpen(false);setNotesOpen(false);setMeasuring(false);setStatus(null);setFrameError('');
    blobs.current.forEach(url=>URL.revokeObjectURL(url));blobs.current.clear();
  }
  function choose(t) {
    resolveRef.current?.abort();setResolving(false);clearSequence();setTarget(t);setCenter(v=>({...v,ra:t.ra,dec:t.dec}));
    setRaInput(t.ra.toFixed(6));setDecInput(t.dec.toFixed(6));if(t.fov)setFov(t.fov);setQuery('');setPanel(false);
  }
  function updateURL(t=target, display=mode) {
    const p=new URLSearchParams({ra:t.ra,dec:t.dec,fov,band,layer:survey,mode:display,atlas_ra:center.ra,atlas_dec:center.dec,atlas_fov:center.fov});
    history.replaceState(null,'',`?${p}`);
    return location.href;
  }
  async function locate(e) {
    e.preventDefault();if(!query.trim()) return;
    resolveRef.current?.abort();const controller=new AbortController();resolveRef.current=controller;
    setResolving(true);setStatus(null);
    try {const d=await api('/api/resolve?q='+encodeURIComponent(query.trim()),controller.signal);if(!controller.signal.aborted)choose({name:query.trim(),ra:d.ra,dec:d.dec,type:'Search result'});}
    catch(err){if(err.name!=='AbortError')setStatus({error:true,text:err.message});}
    finally{if(resolveRef.current===controller)setResolving(false);}
  }
  function applyCoordinates(e) {
    e.preventDefault();const ra=Number(raInput),dec=Number(decInput);
    if(!raInput.trim()||!decInput.trim()||!Number.isFinite(ra)||!Number.isFinite(dec)||ra<0||ra>=360||dec< -90||dec>90) {
      setStatus({error:true,text:'Enter RA from 0 to 359.999° and Dec from −90 to +90°.'});return;
    }
    choose({name:'Selected sky patch',ra,dec,type:'ICRS coordinates'});setMode('atlas');
  }
  async function changeCoverage(value){
    setPlaying(false);
    coverageRef.current?.abort();
    if(value==='all'){setCoverageMode('all');setCoverageScan(null);setIndex(sourceIndex);return;}
    if(!data)return;
    const controller=new AbortController();coverageRef.current=controller;
    const results={...coverageInfo};let failed=0;
    setCoverageScan({running:true,checked:0,total:allObs.length,failed:0});
    for(let i=0;i<allObs.length;i++){
      if(controller.signal.aborted)return;
      if(!Number.isFinite(results[i]?.coverage)){
        try{
          const value=await api(`/api/frame-info/${data.key}/${i}`,controller.signal);
          if(!Number.isFinite(value.coverage))throw Error('Coverage unavailable');
          results[i]=value;
        }catch(error){if(controller.signal.aborted)return;failed++;}
      }
      if(controller.signal.aborted)return;
      setCoverageInfo({...results});setCoverageScan({running:true,checked:i+1,total:allObs.length,failed});
    }
    if(controller.signal.aborted)return;
    const included=allObs.map((_,i)=>i).filter(i=>Number.isFinite(results[i]?.coverage)&&results[i].coverage>=MIN_COVERAGE);
    setCoverageMode('good');setIndex(Math.max(0,included.indexOf(sourceIndex)));
    setCoverageScan({running:false,checked:allObs.length,total:allObs.length,failed});
  }
  async function loadExposures(refresh=false) {
    resetCoverage();
    searchRef.current?.abort();const controller=new AbortController();searchRef.current=controller;
    photoRef.current?.abort();setPhotOpen(false);setMeasuring(false);setPlaying(false);setBusy(true);setPanel(false);setStatus(null);setIndex(0);setData(null);setFrame(null);setInfo(null);setPhot(null);setFrameError('');setMode('sequence');
    blobs.current.forEach(url=>URL.revokeObjectURL(url));blobs.current.clear();
    updateURL(target,'sequence');
    try {
      const d=await api('/api/observations?'+new URLSearchParams({ra:target.ra,dec:target.dec,fov,detector:band,limit:24,refresh}),controller.signal);
      if(controller.signal.aborted)return;
      setData(d);
      if(!d.observations.length)setStatus({text:'No matching exposures were returned by the available search. Try another detector or sky patch.',empty:true,details:d.warnings});
      else if(d.warnings.length)setStatus({text:d.sampling_limited&&!d.search_method?.includes('TAP')?'Showing a limited live IRSA sample. More exposures may exist; this is not the full survey history.':d.search_method?.includes('TAP')?'An alternate IRSA search supplied these images. Some archive results may be missing.':'Some archive collections are unavailable. This sequence may be incomplete.',warning:true,details:d.warnings});
    } catch(err) {if(err.name!=='AbortError')setStatus({error:true,text:err.message});}
    finally {if(searchRef.current===controller)setBusy(false);}
  }
  useEffect(()=>{if(initial.auto)loadExposures();return()=>{coverageRef.current?.abort();searchRef.current?.abort();resolveRef.current?.abort();photoRef.current?.abort();blobs.current.forEach(url=>URL.revokeObjectURL(url));};},[]);
  useEffect(()=>{
    if(!data || !obs.length)return;
    const controller=new AbortController(), identity=`${data.key}/${sourceIndex}`;
    setFrameBusy(true);setFrameError('');setReady(-1);setInfo(null);setStars(null);
    async function run() {
      try {
        let url=blobs.current.get(identity);
        if(!url) {
          const response=await fetch(`/api/frame/${identity}.png`,{signal:controller.signal,cache:'no-store'});
          if(!response.ok){const d=await response.json().catch(()=>({}));throw Error(errorMessage(d,'This exposure could not be loaded.'));}
          const blob=await response.blob();if(controller.signal.aborted)return;
          url=URL.createObjectURL(blob);blobs.current.set(identity,url);
        }
        if(controller.signal.aborted)return;
        setFrame({url,index:sourceIndex,key:data.key});
        api(`/api/frame-info/${identity}`,controller.signal).then(d=>{if(!controller.signal.aborted){setInfo(d);setCoverageInfo(prior=>({...prior,[sourceIndex]:d}));}}).catch(()=>{});
      } catch(err){if(err.name!=='AbortError'){setFrameError(err.message);setPlaying(false);setFrameBusy(false);}}
    }
    run();return()=>controller.abort();
  },[data,sourceIndex,retry]);
  useEffect(()=>{
    if(!playing||ready!==sourceIndex||!frameMatches||frameError||!!coverageScan?.running||obs.length<2)return;
    const timer=setTimeout(()=>setIndex(i=>(i+1)%obs.length),speed);
    return()=>clearTimeout(timer);
  },[playing,ready,index,sourceIndex,speed,frameMatches,frameError,obs.length,coverageScan?.running]);
  useEffect(()=>{
    setStars(null);setGaiaError('');if(!gaia||!data||!obs.length)return;
    const controller=new AbortController();
    api(`/api/overlay/${data.key}/${sourceIndex}.json`,controller.signal).then(d=>{if(!controller.signal.aborted)setStars(d);}).catch(e=>{if(e.name!=='AbortError')setGaiaError(e.message);});
    return()=>controller.abort();
  },[gaia,data,sourceIndex]);
  useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(''),3200);return()=>clearTimeout(timer);},[toast]);
  useEffect(()=>{
    function key(e) {
      if(mode!=='sequence'||obs.length<1||!!coverageScan?.running||about||photOpen||notesOpen||/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName))return;
      if(e.code==='Space'){e.preventDefault();if(obs.length>1)setPlaying(v=>!v);}
      if(e.code==='ArrowRight'){e.preventDefault();setPlaying(false);setIndex(i=>(i+1)%obs.length);}
      if(e.code==='ArrowLeft'){e.preventDefault();setPlaying(false);setIndex(i=>(i+obs.length-1)%obs.length);}
    }
    window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
  },[mode,obs.length,about,photOpen,notesOpen,coverageScan?.running]);
  function move(direction){setPlaying(false);setIndex(i=>(i+direction+obs.length)%obs.length);}
  function zoom(factor){if(mapRef.current)mapRef.current.setFoV(Math.min(360,Math.max(.01,mapRef.current.getFov()[0]*factor)));}
  function toggleGrid(){setGrid(v=>!v);}
  async function share(){const url=updateURL();try{await navigator.clipboard.writeText(url);setToast('Link copied. Same patch, same settings.');}catch{setToast('The address bar now contains your shareable link.');}}
  async function measure(){
    setPhotOpen(true);if(phot||measuring)return;
    photoRef.current?.abort();const controller=new AbortController();photoRef.current=controller;setMeasuring(true);
    try{const d=await api(`/api/photometry/${data.key}?max_frames=12`,controller.signal);if(!controller.signal.aborted)setPhot(d);}
    catch(e){if(e.name!=='AbortError')setPhot({error:e.message});}finally{if(photoRef.current===controller)setMeasuring(false);}
  }
  function downloadMetadata(){
    const rows=allObs.map(({id,date,band,collection,em_min,em_max,exptime},i)=>({id,date,band,collection,em_min,em_max,exptime,source_index:i,coverage:coverageInfo[i]?.coverage??null,displayed:visibleIndices.includes(i)}));
    const blob=new Blob([JSON.stringify({target,fov_arcmin:fov,search_method:data.search_method||'SIA2',queried_at:data.queried_at,sampling_limited:!!data.sampling_limited,total_lower_bound:!!data.total_lower_bound,coverage_filter:coverageMode==='good'?{minimum_valid_fraction:MIN_COVERAGE,unverified_excluded:coverageScan?.failed||0}:null,displayed_source_indices:visibleIndices,missing_pixels:'Transparent pixels have no finite science data; display hatching is not astronomical signal.',observations:rows},null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='skymotion-observations.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
  }

  return html`<div className=${`app ${mode==='sequence'?'sequence-mode':''} ${allObs.length?'has-observations':''}`}>
    <header className="topbar">
      <a className="brand" href="/" aria-label="SkyMotion home"><span className="brand-mark"><${Icon} name="star" size=${25}/></span><span>SkyMotion<span className="brand-period">.</span></span></a>
      <span className="topbar-note">THE SKY, OVER TIME</span>
      <div className="topbar-right"><span className="archive-badge"><span className=${`status-dot ${status?.error?'warning':''}`}></span>SPHEREx <span className="muted">/ ${releases.length ? releases.join(' + ') : 'IRSA'}</span></span>
      <button className="text-button about-button" onClick=${()=>setAbout(true)}><${Icon} name="info" size=${16}/> About the data</button>
      <button className="share-button" onClick=${share}><${Icon} name="share" size=${15}/> Share patch</button>
      <button className="icon-button mobile-menu" aria-label="Toggle search panel" aria-expanded=${panel} onClick=${()=>setPanel(v=>!v)}><${Icon} name=${panel?'cross':'menu'}/></button></div>
    </header>
    <main className="workspace">
      ${mode==='atlas'?html`<${SkyMap} mapRef=${mapRef} target=${target} view=${center} grid=${grid} survey=${survey} onCenter=${setCenter} onState=${setMapState} onError=${setMapError}/>`:null}
      <div className="map-shade"></div>
      ${mode==='atlas'&&mapState!=='ready' ? html`<div className="map-message" role="status"><${Icon} name=${mapState==='error'?'layers':'star'} size=${26}/><strong>${mapState==='error'?'The survey image couldn’t load':mapState==='slow'?'The sky survey is taking a little longer':'Opening the sky atlas'}</strong><p>${mapState==='error'?(mapError||'The survey service did not respond. Retry the map below.'):'Loading real survey imagery. You can choose a target while it arrives.'}</p>${mapState==='error'||mapState==='slow'?html`<button className="subtle-button" onClick=${()=>{setMapError('');setMapState('loading');if(mapRef.current?.retry)mapRef.current.retry();else location.reload();}}>Retry map</button>`:html`<span className="loading-line"></span>`}</div>`:null}
      <aside className=${`explorer panel ${panel?'is-open':''}`} aria-label="Find and select a sky patch">
        <div className="explorer-intro"><span className="eyebrow">AN OPEN SKY EXPLORER</span><h1>A sky that never<br/>stands still.</h1><p>Find a patch. Look closer. Watch it change.</p></div>
        <form className="search-box" onSubmit=${locate}><${Icon} name="search" size=${18}/><input aria-label="Search object or coordinates" value=${query} onChange=${e=>setQuery(e.target.value)} placeholder="Object name or RA, Dec"/><button aria-label="Find target" disabled=${resolving}>${resolving?html`<span className="spinner"></span>`:html`<${Icon} name="arrow" size=${18}/>`}</button></form>
        <div className="selected-target"><div><span className="eyebrow">SPHEREx PATCH</span><h2>${target.name}</h2><span className="coordinate-text">${coords(target)}</span></div><button className="icon-button" title="Recenter map" aria-label="Recenter on selected target" onClick=${()=>mapRef.current?.gotoRaDec(target.ra,target.dec)}><${Icon} name="target"/></button></div>
        <details className="coordinate-details" open=${mode==='atlas'}><summary>Go to any RA / Dec <span>+</span></summary><form onSubmit=${applyCoordinates}><div className="input-pair"><label>RA · degrees<input aria-label="Right ascension in degrees" inputMode="decimal" value=${raInput} onChange=${e=>setRaInput(e.target.value)}/></label><label>Dec · degrees<input aria-label="Declination in degrees" inputMode="decimal" value=${decInput} onChange=${e=>setDecInput(e.target.value)}/></label></div><button className="subtle-button">Go to coordinates <${Icon} name="arrow" size=${14}/></button></form></details>
        <details className="target-presets" open=${mode!=='atlas'}><summary className="section-label"><span className="eyebrow">SUGGESTED PLACES</span><span className="muted">${TARGETS.length} places <span className="target-disclosure">⌄</span></span></summary><div className="target-list">
          ${TARGETS.map(t=>html`<button key=${t.name} className=${`target-row ${target.name===t.name?'active':''}`} onClick=${()=>choose(t)}><span className="target-number">${t.tag}</span><span><strong>${t.name}</strong><small>${t.type}</small></span><${Icon} name="arrow" size=${15}/></button>`)}
        </div></details>
        <div className="observation-settings"><div className="input-pair"><label>SPHEREx cutout<select aria-label="Cutout size" value=${fov} onChange=${e=>{clearSequence();setFov(+e.target.value);}}>${[1,2,3,6,12].map(v=>html`<option key=${v} value=${v}>${v} arcmin</option>`)}</select></label><label>SPHEREx detector<select aria-label="SPHEREx detector" value=${band} onChange=${e=>{clearSequence();setBand(e.target.value);}}>${Object.keys(DETECTORS).map(b=>html`<option key=${b} value=${b}>${b} · ${DETECTORS[b]}</option>`)}</select></label></div>
        <button className="primary-button" disabled=${busy||resolving} onClick=${()=>loadExposures()}><span>${busy?'Finding exposures…':'Load SPHEREx exposures'}</span>${busy?html`<span className="spinner"></span>`:html`<${Icon} name="arrow" size=${18}/>`}</button>
        <p className="quiet-note">Real infrared observations from NASA / IPAC.</p></div>
      </aside>
      <div className="map-top-controls"><div className="view-switch" role="group" aria-label="Viewer mode"><button className=${mode==='atlas'?'active':''} onClick=${()=>{setMode('atlas');setPlaying(false);}}>Sky atlas</button><button className=${mode==='sequence'?'active':''} onClick=${()=>setMode('sequence')}>SPHEREx sequence ${obs.length?html`<span>${obs.length}</span>`:null}</button></div>
      <label className="survey-select"><${Icon} name="layers" size=${16}/><span className="sr-only">Sky survey</span><select aria-label="Sky survey" value=${survey} onChange=${e=>setSurvey(e.target.value)}>${Object.entries(SURVEYS).map(([k,s])=>html`<option key=${k} value=${k}>${s.label}</option>`)}</select></label></div>
      ${mode==='atlas'?html`<div className="atlas-center">${selectedMoved?html`<button className="search-area" onClick=${()=>choose({name:'Selected sky patch',ra:center.ra,dec:center.dec,type:'Map selection'})}>Use this sky position <${Icon} name="plus" size=${13}/></button>`:null}</div>`:null}
      ${mode==='atlas'?html`<div className="map-title"><span className="eyebrow">${SURVEYS[survey].short} / REFERENCE ATLAS</span><h2>${center.fov>=360?'Entire sky':selectedMoved?'Sky atlas':target.name}</h2><p>${coords(center)} <span>ICRS</span> <span className="atlas-field">${center.fov>=360?'All sky':center.fov>60?'Wide view':`${center.fov<1?center.fov.toFixed(3):center.fov.toFixed(1)}° field`}</span></p></div>`:null}
      ${mode==='atlas'?html`<div className="map-tools"><span className="north-label">N <span>↑</span></span><button className="map-tool all-sky-button" aria-label="View entire sky" title="View entire sky" onClick=${()=>mapRef.current?.setFoV(360)}><${Icon} name="globe" size=${16}/><span>All sky</span></button><div className="tool-stack"><button aria-label="Zoom in" title="Zoom in" disabled=${!mapRef.current} onClick=${()=>zoom(.6)}><${Icon} name="plus"/></button><button aria-label="Zoom out" title="Zoom out" disabled=${!mapRef.current} onClick=${()=>zoom(1.6)}><${Icon} name="minus"/></button></div><button className=${`map-tool ${grid?'active':''}`} aria-pressed=${grid} aria-label="Toggle coordinate grid" title="Coordinate grid" disabled=${!mapRef.current} onClick=${toggleGrid}><${Icon} name="grid"/></button><button className="map-tool" aria-label="Return to selected patch" title="Center selected patch" onClick=${()=>mapRef.current?.gotoRaDec(target.ra,target.dec)}><${Icon} name="target"/></button></div>`:null}
      ${mode==='sequence'?html`<section className="sequence-stage" aria-label="SPHEREx observation viewer">
        ${busy?html`<div className="sequence-placeholder"><span className="spinner large"></span><span className="eyebrow">NASA / IPAC INFRARED SCIENCE ARCHIVE</span><h2>Finding this patch in time.</h2><p>Looking for ${band} observations covering ${target.name}.<br/>Archive requests can take a minute or two.</p><button className="subtle-button" onClick=${()=>{searchRef.current?.abort();setBusy(false);setStatus(null);setMode('atlas');}}>Back to the atlas</button></div>`:
        obs.length?html`<div className="frame-layout"><div className="frame-heading"><div><span className="eyebrow">SPHEREx / ${band} / ${fov}′ FIELD</span><h2>${target.name}</h2></div><span className="frame-number">${String(index+1).padStart(2,'0')}<span> / ${String(obs.length).padStart(2,'0')}</span></span></div>
          <div className="science-frame">
            ${frameMatches?html`<img src=${frame.url} alt=${`SPHEREx infrared exposure of ${target.name}, ${observed(o.date)} UTC`} onLoad=${()=>{setReady(sourceIndex);setFrameBusy(false);}} onError=${()=>{setFrameError('The image could not be decoded. Retry this frame.');setFrameBusy(false);setPlaying(false);}}/>`:null}
            ${gaia&&frameMatches&&stars?html`<svg className="gaia-overlay" viewBox="0 0 100 100">${stars.stars.map(s=>html`<circle key=${s.id} cx=${s.x*100} cy=${s.y*100} r="1.5" fill="none" stroke="#e2cd8d" strokeWidth=".22" strokeDasharray=${s.pm>100?'1 .7':null}><title>Gaia ${s.id}; proper motion ${s.pm.toFixed(0)} mas/yr</title></circle>`)}</svg>`:null}
            <div className="frame-crosshair"></div><span className="frame-north">N ↑<br/>E ←</span><span className="frame-scale">${fov} arcmin</span>
            ${frameBusy&&!frameError?html`<div className="frame-loading"><span className="spinner"></span><span>Loading exposure ${index+1}…</span></div>`:null}
            ${frameError?html`<div className="frame-error" role="alert"><${Icon} name="info" size=${24}/><p>${frameError}</p><button className="subtle-button" onClick=${()=>{blobs.current.delete(`${data.key}/${sourceIndex}`);setRetry(v=>v+1);}}>Retry frame</button><button className="text-button" onClick=${()=>move(1)} disabled=${obs.length<2}>Skip to next exposure</button></div>`:null}
          </div>
          <div className="frame-caption"><span>${observed(o.date)} <span className="muted">UTC</span></span><span>North up · same sky grid</span></div><div className="coverage-legend" role="status"><span className="missing-swatch" aria-hidden="true"></span><span>${info?.coverage!=null?`${coveragePercent(info.coverage)} valid pixels · `:''}Hatching: no valid data</span></div><button className="mobile-notes text-button" onClick=${()=>{setPlaying(false);setNotesOpen(true);}}>Exposure notes & Gaia <${Icon} name="info" size=${13}/></button>
        </div>`:coverageMode==='good'&&allObs.length?html`<div className="sequence-placeholder"><${Icon} name="layers" size=${30}/><h2>No frames meet this coverage filter.</h2><p>No verified exposure has at least 95% valid pixels in this cutout.${coverageScan?.failed?` ${coverageScan.failed} exposures could not be checked.`:''}</p><button className="primary-button" onClick=${()=>changeCoverage('all')}>Show all frames</button><p>A smaller SPHEREx cutout may have better coverage.</p></div>`:html`<div className="sequence-placeholder"><${Icon} name="layers" size=${30}/><span className="eyebrow">A DIFFERENT VIEW OF TIME</span><h2>${status?.empty?'No exposures in this patch.':status?.error?'The archive couldn’t connect.':'See what changes.'}</h2><p>${status?.text||'Load infrared exposures of your selected patch, then step through them or press play.'}</p>${archiveDetails(status?.details)}<button className="primary-button" onClick=${()=>loadExposures(true)}>${status?.error?'Retry archive':'Load SPHEREx exposures'}<${Icon} name="arrow" size=${17}/></button><button className="text-button" onClick=${()=>setMode('atlas')}>Return to sky atlas</button></div>`}
        ${obs.length?html`<aside className="exposure-info panel"><span className="eyebrow">EXPOSURE NOTES</span><dl><dt>Observed · UTC</dt><dd>${observed(o.date)}</dd><dt>Detector</dt><dd>${band} <span>${DETECTORS[band]}</span></dd><dt>Wavelength at center</dt><dd>${info?.wavelength_um?`${info.wavelength_um.toFixed(3)} µm`:'Not available'}</dd><dt>Release</dt><dd>${o.collection.replace('spherex_','').toUpperCase()}</dd><dt>Flagged pixels</dt><dd>${info?.flagged_fraction!=null?`${(info.flagged_fraction*100).toFixed(1)}%`:'Not available'}</dd><dt>Patch covered</dt><dd>${info?coveragePercent(info.coverage):'…'}</dd></dl>
          <label className="checkbox-row"><input type="checkbox" checked=${gaia} onChange=${e=>setGaia(e.target.checked)}/> Gaia DR3 overlay</label>
          ${gaiaError?html`<p className="inline-warning">${gaiaError}</p>`:null}
          <p className="science-note">Brightness and wavelength can vary between exposures. The same detector is not the same spectral channel.</p>
          <button className="text-button" onClick=${measure}>Brightness proxy <${Icon} name="arrow" size=${14}/></button><button className="text-button" onClick=${downloadMetadata}>Save metadata <${Icon} name="download" size=${14}/></button>
        </aside>`:null}
      </section>`:null}
      ${status && (mode==='atlas'||obs.length>0)?html`<div className=${`notice ${status.error?'notice-error':status.warning?'notice-warning':''}`} role="status"><${Icon} name="info" size=${17}/><div className="notice-copy"><span>${status.text}</span>${archiveDetails(status.details)}</div><button aria-label="Dismiss message" onClick=${()=>setStatus(null)}><${Icon} name="cross" size=${15}/></button></div>`:null}
      <section className="timeline panel" aria-label="Observation playback">
        <div className="timeline-header"><span className="eyebrow"><span className="tiny-star">+</span> OBSERVATION TIMELINE</span><span className="timeline-count">${allObs.length?`${obs.length} of ${data.total_lower_bound?'at least ':''}${data.total} exposures · ${band}`:'SPHEREx · near-infrared'}</span></div>
        ${mode==='sequence'&&allObs.length?html`<div className="coverage-controls"><label>Coverage<select aria-label="Exposure coverage" value=${coverageScan?.running?'checking':coverageMode} onChange=${e=>changeCoverage(e.target.value)}><option value="all">All frames</option><option value="good" disabled=${!!coverageScan?.running}>At least 95% covered</option>${coverageScan?.running?html`<option value="checking" disabled>Checking coverage…</option>`:null}</select></label><span role="status">${coverageScan?.running?`Checking ${coverageScan.checked} / ${coverageScan.total}…`:coverageMode==='good'?`${obs.length}/${allObs.length} included${coverageScan?.failed?` · ${coverageScan.failed} unverified`:''}`:'Partial frames remain available'}</span></div>`:null}
        <div className="timeline-main"><div className="play-controls"><button className="icon-button" aria-label="Previous exposure" disabled=${!obs.length||!!coverageScan?.running} onClick=${()=>{setMode('sequence');move(-1);}}><${Icon} name="back" size=${17}/></button><button className="play-button" aria-label=${playing?'Pause playback':'Play observations'} disabled=${obs.length<2||!!frameError||!!coverageScan?.running} onClick=${()=>{setMode('sequence');setPlaying(v=>!v);}}><${Icon} name=${playing?'pause':'play'} size=${20}/></button><button className="icon-button" aria-label="Next exposure" disabled=${!obs.length||!!coverageScan?.running} onClick=${()=>{setMode('sequence');move(1);}}><${Icon} name="next" size=${17}/></button></div>
        <div className="timeline-track">${obs.length?html`<input className="exposure-slider" aria-label="Exposure number" type="range" min="0" max=${Math.max(0,obs.length-1)} value=${index} disabled=${!!coverageScan?.running} onChange=${e=>{setPlaying(false);setMode('sequence');setIndex(+e.target.value);}}/><div className="timeline-dates"><span>${date(obs[0].date)}</span><span>${obs.length===1?'One available exposure':`${index+1} / ${obs.length}`}</span><span>${date(obs[obs.length-1].date)}</span></div>`:html`<div className="empty-track"><span></span><p>${busy?'Searching the archive…':'Choose a patch, then load its history.'}</p></div>`}</div>
        <label className="pace"><span>Playback</span><select aria-label="Playback speed" value=${speed} onChange=${e=>setSpeed(+e.target.value)}><option value="1800">Slow</option><option value="1000">Steady</option><option value="450">Fast</option></select></label></div>
        <div className="timeline-foot"><span>${obs.length?'Aligned frames · independent intensity stretch · use ← → to step':'Drag to explore the map. Scroll to zoom. The atlas is a reference, not a time series.'}</span>${obs.length?html`<button className="text-button" onClick=${()=>loadExposures(true)} disabled=${busy}><${Icon} name="refresh" size=${12}/> Refresh archive</button>`:null}</div>
      </section>
      <footer className="map-credit"><span>${mode==='atlas'?SURVEYS[survey].credit:'SPHEREx · NASA / JPL / Caltech · IRSA'}</span><button onClick=${()=>setAbout(true)}>Data & credits</button></footer>
      ${toast?html`<div className="toast" role="status">${toast}</div>`:null}
    </main>
    ${about?html`<${Modal} title="A real sky. A changing sky." onClose=${()=>setAbout(false)}><p>SkyMotion lets you explore a sky survey and compare infrared observations from NASA’s SPHEREx mission.</p><div className="about-section"><h3>The colorful atlas</h3><p>DSS, 2MASS, and WISE are real astronomical surveys served from NASA/IPAC IRSA’s public survey mirror and displayed in the built-in atlas. Their color composites combine telescope bands; they are reference maps, not SPHEREx frames or a view of how the sky looks to your eyes.</p></div><div className="about-section"><h3>The SPHEREx sequence</h3><p>Each grayscale frame comes from an IRSA FITS science image. Exposures are resampled onto one north-up, east-left coordinate grid. Playback waits for the current frame to load.</p><p>Frames use independent intensity stretches. Wavelength, detector noise, flagged pixels, and PSF changes can imitate variability. Compare metadata before interpreting changes. Hatched areas have no valid science data. The coverage filter keeps frames with at least 95% finite pixels; it does not reject quality flags. Flag percentages count any nonzero flag; these pixels are not automatically rejected.</p></div><div className="about-section"><h3>Looking for motion</h3><p>Start with the five challenge targets, choose a detector, and load exposures. Use the arrow keys to step through. Gaia rings use approximate linear proper motion; missing rings do not establish a new discovery. Suggested target coordinates are finding positions, not date-propagated ephemerides. Fast-moving targets open a wider cutout to include their more recent positions.</p></div><p className="credit-line">Independent NASA Space Apps project. Not an official NASA product.<br/>Data: NASA / JPL / Caltech / IPAC, STScI, UMass, UCLA, ESA Gaia. Reference surveys: CDS HiPS via IRSA. Name lookup: CDS Sesame.</p><div className="about-links"><a href="https://irsa.ipac.caltech.edu/Missions/spherex.html" target="_blank" rel="noreferrer">SPHEREx at IRSA ↗</a><a href="https://irsa.ipac.caltech.edu/data/hips/list" target="_blank" rel="noreferrer">IRSA survey images ↗</a></div></${Modal}>`:null}
    ${notesOpen&&o?html`<${Modal} title="Exposure notes" onClose=${()=>setNotesOpen(false)}><p>${observed(o.date)} UTC · ${band} · ${o.collection.replace('spherex_','').toUpperCase()}</p><p>Valid pixels in patch: ${info?.coverage!=null?coveragePercent(info.coverage):'not available'}<br/>Hatching marks missing data.</p><p>Center wavelength: ${info?.wavelength_um?`${info.wavelength_um.toFixed(3)} µm`:'not available'}<br/>Flagged pixels: ${info?.flagged_fraction!=null?`${(info.flagged_fraction*100).toFixed(1)}%`:'not available'}</p><label className="checkbox-row"><input type="checkbox" checked=${gaia} onChange=${e=>setGaia(e.target.checked)}/> Gaia DR3 overlay</label>${gaiaError?html`<p>${gaiaError}</p>`:null}<p className="science-note">Each frame has its own intensity stretch. Wavelength, PSF, and flagged pixels can imitate changes. Compare metadata before interpreting variability.</p><button className="subtle-button" onClick=${()=>{setNotesOpen(false);measure();}}>Measure brightness proxy</button><button className="text-button" style=${{marginLeft:14}} onClick=${downloadMetadata}>Save metadata</button></${Modal}>`:null}
    ${photOpen?html`<${Modal} title="Exploratory brightness" onClose=${()=>setPhotOpen(false)}>${coverageMode==='good'?html`<p className="science-note">These measurements sample the original returned sequence. The coverage filter controls playback.</p>`:null}${measuring?html`<p className="measurement-loading"><span className="spinner"></span> Measuring up to 12 exposures. This can take several minutes.</p>`:phot?.error?html`<p role="alert">${phot.error}</p>`:phot?html`<p>${phot.warning}</p><div className="measurement-table"><table><thead><tr><th>Date · UTC</th><th>Center µm</th><th>Brightness proxy</th></tr></thead><tbody>${phot.measurements.map(m=>html`<tr key=${m.index}><td>${date(m.date)}</td><td>${m.wavelength_um?.toFixed(3)||'—'}</td><td>${Number.isFinite(m.proxy)?m.proxy.toPrecision(5):'Unavailable'}</td></tr>`)}</tbody></table>${!phot.measurements.length?html`<p>No usable aperture measurements in these frames.</p>`:null}</div>`:null}</${Modal}>`:null}
  </div>`;
}
ReactDOM.createRoot(document.getElementById('root')).render(html`<${App}/>`);
