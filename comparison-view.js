/* Two-exposure comparisons. Every image is produced from the selected IRSA FITS. */
(() => {
  const {useState,useEffect,useRef}=React;
  const h=htm.bind(React.createElement);
  const match=(a,b)=>[a.wavelength_um,b.wavelength_um,a.bandwidth_um,b.bandwidth_um].every(v=>Number.isFinite(v)&&v>0)&&Math.abs(a.wavelength_um-b.wavelength_um)<=.5*Math.min(a.bandwidth_um,b.bandwidth_um);
  function saveJSON(value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='sphere360-comparison.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  window.ComparisonDialog=function ComparisonDialog({data,initialIndex=0,onClose}){
    const rows=data.observations;
    const [a,setA]=useState(initialIndex),[b,setB]=useState(initialIndex===rows.length-1?0:rows.length-1);
    const [background,setBackground]=useState(true),[result,setResult]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
    const [view,setView]=useState('side'),[phase,setPhase]=useState('a'),[loaded,setLoaded]=useState({}),[imageError,setImageError]=useState('');
    const [finding,setFinding]=useState(false),[findStatus,setFindStatus]=useState('');
    const finder=useRef(null);
    const query=new URLSearchParams({a,b,background}),base=`/api/comparison/${data.key}`;
    const identity=`${data.key}/${a}/${b}/${background}/${retry}`;
    const loadStamp=`${identity}/${view}`;
    useEffect(()=>{
      const controller=new AbortController();setResult(null);setError('');setLoaded({});setImageError('');setPhase('a');
      api(`${base}?${query}`,controller.signal).then(d=>{if(!controller.signal.aborted)setResult(d);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});
      return()=>controller.abort();
    },[data.key,a,b,background,retry]);
    useEffect(()=>()=>finder.current?.abort(),[]);
    useEffect(()=>{setImageError('');setPhase('a');},[view,identity]);
    useEffect(()=>{
      if(view!=='blink'||!result||imageError||loaded.a!==loadStamp||loaded.b!==loadStamp)return;
      const timer=setTimeout(()=>setPhase(v=>v==='a'?'b':'a'),900);return()=>clearTimeout(timer);
    },[view,result,phase,loaded.a,loaded.b,imageError,loadStamp]);
    function select(set,value){finder.current?.abort();setFinding(false);setFindStatus('');set(value);}
    async function findMatch(){
      finder.current?.abort();const controller=new AbortController();finder.current=controller;setFinding(true);setFindStatus('Checking wavelengths…');
      try{
        const reference=await api(`/api/frame-info/${data.key}/${a}`,controller.signal);let best=null,checked=0,failed=0;
        const checkedInfo={[a]:reference};
        for(let i=0;i<rows.length;i++){
          if(controller.signal.aborted)return;
          if(i===a)continue;
          try{
            const info=await api(`/api/frame-info/${data.key}/${i}`,controller.signal);
            checkedInfo[i]=info;
            const days=Math.abs((rows[i].mjd??0)-(rows[a].mjd??0));
            if(rows[a].band===rows[i].band&&match(reference,info)&&(!best||days>best.days))best={index:i,days};
          }catch(e){if(controller.signal.aborted)return;failed++;}
          checked++;if(!controller.signal.aborted)setFindStatus(`Checked ${checked} / ${rows.length-1}${failed?` · ${failed} unavailable`:''}…`);
        }
        if(controller.signal.aborted)return;
        if(!best){
          for(const i of Object.keys(checkedInfo).map(Number))for(const j of Object.keys(checkedInfo).map(Number)){
            if(j<=i||rows[i].band!==rows[j].band||!match(checkedInfo[i],checkedInfo[j]))continue;
            const days=Math.abs((rows[i].mjd??0)-(rows[j].mjd??0));
            if(!best||days>best.days)best={reference:i,index:j,days};
          }
        }
        if(best){if(best.reference!=null)setA(best.reference);setB(best.index);setFindStatus(`${best.reference!=null?'A had no match; selected another pair. ':''}Widest time separation among the checked center-wavelength matches: ${best.days.toFixed(2)} days.${failed?` ${failed} exposures could not be checked.`:''}`);}
        else setFindStatus(`No verified center-wavelength match in this sample.${failed?` ${failed} exposures could not be checked.`:''} Add observations from another date range or try a smaller cutout.`);
      }catch(e){if(!controller.signal.aborted)setFindStatus(e.message);}
      finally{if(finder.current===controller&&!controller.signal.aborted)setFinding(false);}
    }
    function image(which){
      const src=`${base}/image.png?${query}&view=${which}&retry=${retry}`;
      return h`<img key=${`${identity}/${which}`} src=${src} alt=${which==='difference'?'SPHEREx B minus A: gold is positive, blue is negative':which==='mean'?'Mean of the two selected SPHEREx images':`SPHEREx exposure ${which.toUpperCase()}, ${observed(rows[which==='a'?a:b].date)} UTC`} onLoad=${()=>setLoaded(v=>({...v,[which]:loadStamp}))} onError=${()=>setImageError('The comparison image could not load. Retry or choose another pair.')}/>`;
    }
    const selectable=['side','blink',...(result?.arithmetic_available?['difference','mean']:[])];
    const current=selectable.includes(view)?view:'side';
    const wavelengths=entry=>`${entry.wavelength_um?.toFixed(4)||'unknown'} µm${entry.bandwidth_um?` · width ${entry.bandwidth_um.toFixed(4)} µm`:''}`;
    return h`<${Modal} title="Compare exposures" wide=${true} onClose=${onClose}>
      <p>Choose two observations of this patch. A and B use the same contrast limits and common coverage.</p>
      <div className="comparison-selectors input-pair">${[['A',a,setA],['B',b,setB]].map(([label,value,set])=>h`<label key=${label}>Exposure ${label}<select aria-label=${`Comparison exposure ${label}`} value=${value} onChange=${e=>select(set,+e.target.value)}>${rows.map((row,i)=>h`<option key=${i} value=${i}>${i+1}. ${observed(row.date)} · ${row.id}</option>`)}</select></label>`)}</div>
      <div className="comparison-actions"><label className="checkbox-row"><input type="checkbox" checked=${background} onChange=${e=>setBackground(e.target.checked)}/> Remove each image’s median sky level</label><button className="subtle-button" disabled=${finding} onClick=${findMatch}>Find similar wavelength</button>${finding?h`<button className="text-button" onClick=${()=>{finder.current?.abort();setFinding(false);setFindStatus('Wavelength check cancelled.');}}>Cancel check</button>`:null}</div>
      ${findStatus?h`<p className="science-note" role="status">${findStatus}</p>`:null}
      ${error?h`<p role="alert">${error}</p><button className="subtle-button" onClick=${()=>setRetry(v=>v+1)}>Retry comparison</button>`:!result?h`<p className="measurement-loading"><span className="spinner"></span> Loading the two science cutouts…</p>`:h`
        <div className="comparison-summary"><span>A · ${wavelengths(result.a)}</span><span>B · ${wavelengths(result.b)}</span><strong>${result.time_separation_days?.toFixed(2)??'Unknown'} days apart · ${coveragePercent(result.displayed_coverage)} displayed coverage</strong></div>
        ${!result.arithmetic_available?h`<div className="comparison-reasons"><strong>Difference and mean unavailable for this pair</strong><ul>${result.reasons.map((reason,i)=>h`<li key=${i}>${reason}</li>`)}</ul></div>`:h`<p className="science-note">Similar wavelengths verified at the center and each displayed pixel. This is an approximate match; filter responses can still differ.</p>`}
        <div className="comparison-tabs" role="group" aria-label="Comparison view">${[['side','Side by side'],['blink','Blink A / B'],['difference','Difference B − A'],['mean','Mean of A + B']].map(([value,label])=>h`<button key=${value} className=${current===value?'active':''} aria-pressed=${current===value} disabled=${!selectable.includes(value)} onClick=${()=>setView(value)}>${label}</button>`)}</div>
        <div className=${`comparison-images ${current==='side'?'two-images':''}`}>
          ${current==='side'?['a','b'].map(which=>h`<figure key=${which}><figcaption>${which.toUpperCase()} · ${observed(rows[which==='a'?a:b].date)} UTC</figcaption><div className="comparison-image">${image(which)}</div></figure>`):current==='blink'?h`<figure><figcaption aria-live="off">${phase.toUpperCase()} · ${observed(rows[phase==='a'?a:b].date)} UTC</figcaption><div className=${`comparison-image blinking show-${phase}`}><div className="blink-a">${image('a')}</div><div className="blink-b">${image('b')}</div></div></figure>`:h`<figure><figcaption>${current==='difference'?'B − A · gold: B brighter · blue: A brighter · gray: zero':'(A + B) / 2 · moving objects can blur'}</figcaption><div className="comparison-image">${image(current)}</div></figure>`}
        </div>
        ${imageError?h`<p role="alert">${imageError} <button className="subtle-button" onClick=${()=>setRetry(v=>v+1)}>Retry comparison</button></p>`:loaded[current==='difference'||current==='mean'?current:'a']!==loadStamp||((current==='side'||current==='blink')&&loaded.b!==loadStamp)?h`<p role="status" className="science-note">Loading comparison images…</p>`:null}
        <p className="science-note"><span className="missing-swatch" aria-hidden="true"></span> Hatching: no common valid data${result.arithmetic_available?' or wavelengths outside tolerance':''}. ${result.background_removed?'Median sky level removed.':'Original sky levels retained.'} A and B flags retained: ${result.a.flagged_fraction!=null?coveragePercent(result.a.flagged_fraction):'unknown'} / ${result.b.flagged_fraction!=null?coveragePercent(result.b.flagged_fraction):'unknown'}.</p>
        <details className="comparison-details"><summary>Processing and limits</summary><ul>${result.warnings.map((warning,i)=>h`<li key=${i}>${warning}</li>`)}</ul><p>${result.wavelength_rule} ${result.stretch}</p><p>Shared limits: ${result.shared_limits.map(v=>v.toPrecision(5)).join(' to ')} ${result.unit||'native units'}. Difference limits: ${result.difference_limits.map(v=>v.toPrecision(5)).join(' to ')} ${result.unit||'native units'}.</p></details>
        <div className="comparison-downloads"><button className="subtle-button" onClick=${()=>saveJSON(result)}>Save comparison metadata</button>${result.arithmetic_available?h`<a className="subtle-button" href=${`${base}/data.fits?${query}&operation=difference`}>Difference FITS ↓</a><a className="subtle-button" href=${`${base}/data.fits?${query}&operation=mean`}>Mean FITS ↓</a>`:null}<a href=${`/api/cutout/${data.key}/${a}`} target="_blank" rel="noreferrer">Original A ↗</a><a href=${`/api/cutout/${data.key}/${b}`} target="_blank" rel="noreferrer">Original B ↗</a></div>
      `}
    </${Modal}>`;
  };
})();
