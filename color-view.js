/* Live three-band SPHEREx composites, with explicit dates and no filled pixels. */
(() => {
  const {useState,useEffect,useRef}=React,h=htm.bind(React.createElement);
  const labels=['red','green','blue'];
  function closest(results){
    let best=null;
    for(let r=0;r<results.red.observations.length;r++)for(let g=0;g<results.green.observations.length;g++)for(let b=0;b<results.blue.observations.length;b++){
      const values=[results.red.observations[r].mjd,results.green.observations[g].mjd,results.blue.observations[b].mjd];
      if(!values.every(Number.isFinite))continue;
      const span=Math.max(...values)-Math.min(...values);
      if(!best||span<best.span)best={red:r,green:g,blue:b,span};
    }
    return best;
  }
  window.ColorDialog=function ColorDialog({target,fov,start='',end='',onClose}){
    const [detectors,setDetectors]=useState({red:'D6',green:'D3',blue:'D1'}),[results,setResults]=useState({}),[indices,setIndices]=useState({red:0,green:0,blue:0});
    const [busy,setBusy]=useState(false),[progress,setProgress]=useState(''),[errors,setErrors]=useState({}),[building,setBuilding]=useState(false),[error,setError]=useState('');
    const [allowMixed,setAllowMixed]=useState(false),[built,setBuilt]=useState(null),[imageLoaded,setImageLoaded]=useState(false),[imageError,setImageError]=useState('');
    const controller=useRef(null),builder=useRef(null);
    useEffect(()=>()=>{controller.current?.abort();builder.current?.abort();},[]);
    function reset(){builder.current?.abort();setBuilding(false);setBuilt(null);setError('');setImageError('');setImageLoaded(false);}
    async function search(){
      controller.current?.abort();reset();const request=new AbortController();controller.current=request;
      setBusy(true);setResults({});setErrors({});setProgress('Searching IRSA for three channels…');
      const found={},failures={};let next=0,completed=0;
      async function worker(){
        while(next<labels.length&&!request.signal.aborted){
          const channel=labels[next++],params=new URLSearchParams({ra:target.ra,dec:target.dec,fov,detector:detectors[channel],limit:16});
          if(start)params.set('start',start);if(end)params.set('end',end);
          try{
            const result=await api(`/api/observations?${params}`,request.signal);
            if(request.signal.aborted)return;
            if(!result.observations.length)throw Error('No observations returned. Try another detector or date range.');
            found[channel]=result;setResults({...found});
          }catch(e){if(request.signal.aborted)return;failures[channel]=e.message;setErrors({...failures});}
          completed++;if(!request.signal.aborted)setProgress(`Searched ${completed} / 3 channels.`);
        }
      }
      await Promise.all([worker(),worker()]);
      if(request.signal.aborted)return;
      if(labels.every(label=>found[label])){
        const selected=closest(found);
        setIndices(selected?{red:selected.red,green:selected.green,blue:selected.blue}:{red:0,green:0,blue:0});
        setProgress('Selected the closest observation dates in these returned samples. Check the dates before building.');
      }
      setBusy(false);
    }
    const selected=labels.map(label=>results[label]?.observations[indices[label]]),available=selected.every(Boolean);
    const times=selected.map(row=>row?.mjd),known=available&&times.every(Number.isFinite),span=known?Math.max(...times)-Math.min(...times):null;
    async function build(){
      reset();const request=new AbortController();builder.current=request;setBuilding(true);
      const params=new URLSearchParams({allow_mixed_dates:allowMixed});
      labels.forEach(label=>{params.set(`${label}_key`,results[label].key);params.set(`${label}_index`,indices[label]);});
      try{
        const info=await api(`/api/color?${params}`,request.signal);
        if(!request.signal.aborted)setBuilt({info,params:params.toString()});
      }catch(e){if(!request.signal.aborted)setError(e.message);}
      finally{if(builder.current===request&&!request.signal.aborted)setBuilding(false);}
    }
    function save(){const url=URL.createObjectURL(new Blob([JSON.stringify(built.info,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='sphere360-color.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    return h`<${Modal} title="SPHEREx infrared color" wide=${true} onClose=${onClose}>
      <p>Three real infrared exposures, assigned to red, green and blue. These are false colors: infrared light is invisible to our eyes.</p><p className="science-note">${target.name} · ${fov}′ field · ${start||'Any start date'} through ${end||'any end date'} (UTC). Change the observation dates in the search panel to narrow this window.</p>
      <div className="color-selectors">${labels.map(label=>h`<section key=${label}><h3>${label[0].toUpperCase()+label.slice(1)} channel</h3><label>Infrared detector<select aria-label=${`${label} channel detector`} value=${detectors[label]} disabled=${busy} onChange=${e=>{reset();setResults({});setErrors({});setProgress('');setDetectors(v=>({...v,[label]:e.target.value}));}}>${Object.entries(DETECTORS).map(([key,value])=>h`<option key=${key} value=${key}>${key} · ${value}</option>`)}</select></label>${results[label]?h`<label>Exposure<select aria-label=${`${label} channel exposure`} value=${indices[label]} disabled=${busy} onChange=${e=>{reset();setIndices(v=>({...v,[label]:+e.target.value}));}}>${results[label].observations.map((row,index)=>h`<option key=${index} value=${index}>${observed(row.date)} UTC · ${row.id}</option>`)}</select></label><p className="science-note">${results[label].observations.length} returned${results[label].sampling_limited?' · limited sample':''}</p>`:null}${errors[label]?h`<p role="alert">${errors[label]}</p>`:null}</section>`)}</div>
      <div className="comparison-actions"><button className="subtle-button" disabled=${busy||building} onClick=${search}>${busy?'Finding color channels…':'Find color channels'}</button>${busy?h`<button className="text-button" onClick=${()=>{controller.current?.abort();setBusy(false);setProgress('Search cancelled.');}}>Cancel search</button>`:null}<span className="science-note" role="status">${progress}</span></div>
      ${available?h`<div className="color-build"><p>${known?`Selected channels span ${span.toFixed(2)} days.`:'Observation times are unavailable.'} ${span>1?'Motion and variability can create colored features. This will combine different dates.':'The channels may still have different observation times.'}</p><label className="checkbox-row"><input aria-label="Allow mixed color dates" type="checkbox" checked=${allowMixed} onChange=${e=>{reset();setAllowMixed(e.target.checked);}}/> Allow channels more than one day apart</label><button className="subtle-button" disabled=${busy||building||!known||span>1&&!allowMixed} onClick=${build}>${building?'Loading science images…':'Build color image'}</button></div>`:null}
      ${error?h`<p role="alert">${error}</p>`:null}
      ${built?h`<figure className="color-result"><figcaption>Assigned infrared color · ${coveragePercent(built.info.coverage)} common valid coverage · ${built.info.time_span_days.toFixed(2)} days across channels</figcaption><div className="comparison-image"><img src=${`/api/color/image.png?${built.params}`} alt=${`False-color SPHEREx composite of ${target.name} from three real infrared exposures`} onLoad=${()=>setImageLoaded(true)} onError=${()=>setImageError('The color image could not load. Build the image again to retry.')}/></div>${!imageLoaded&&!imageError?h`<p role="status">Loading color image…</p>`:null}${imageError?h`<p role="alert">${imageError}</p>`:null}<p className="science-note"><span className="missing-swatch" aria-hidden="true"></span> Hatching: at least one channel has no finite science data. No filled pixels.</p><dl className="color-provenance">${labels.map(label=>{const channel=built.info.channels[label];return h`<div key=${label}><dt>${label[0].toUpperCase()+label.slice(1)} · ${channel.band}</dt><dd>${channel.wavelength_um?.toFixed(4)||'Unknown'} µm · ${observed(channel.date)} UTC · <a href=${`/api/cutout/${channel.key}/${channel.source_index}`} target="_blank" rel="noreferrer">Original FITS ↗</a></dd></div>`;})}</dl><details className="comparison-details"><summary>How the colors were made</summary><p>${built.info.stretch}</p><ul>${built.info.warnings.map((warning,i)=>h`<li key=${i}>${warning}</li>`)}</ul></details><div className="comparison-downloads"><a className="subtle-button" href=${`/api/color/image.png?${built.params}`} download="sphere360-infrared-color.png">Save color PNG ↓</a><button className="subtle-button" onClick=${save}>Save channel metadata</button></div></figure>`:null}
    </${Modal}>`;
  };
})();
