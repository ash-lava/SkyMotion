/* A small real-image atlas used if Aladin/WebGL cannot initialize.
   Geometry exactly matches the TAN WCS in sky_service.py. No external scripts. */
(function (global) {
  'use strict';
  const RAD=Math.PI/180, DEG=180/Math.PI;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const wrap=ra=>((ra%360)+360)%360;
  function pixelToSky(x,y,width,height,view) {
    const scale=2*Math.tan(view.fov*RAD/2)/Math.max(width,height);
    const xi=-(x-width/2)*scale, eta=-(y-height/2)*scale;
    const d=view.dec*RAD, denominator=Math.cos(d)-eta*Math.sin(d);
    return {ra:wrap(view.ra+Math.atan2(xi,denominator)*DEG),
      dec:Math.atan2(Math.sin(d)+eta*Math.cos(d),Math.hypot(denominator,xi))*DEG};
  }
  function skyToPixel(ra,dec,width,height,view) {
    const delta=(ra-view.ra)*RAD,d=dec*RAD,d0=view.dec*RAD;
    const cosc=Math.sin(d0)*Math.sin(d)+Math.cos(d0)*Math.cos(d)*Math.cos(delta);
    if(cosc<=0)return null;
    const xi=Math.cos(d)*Math.sin(delta)/cosc;
    const eta=(Math.cos(d0)*Math.sin(d)-Math.sin(d0)*Math.cos(d)*Math.cos(delta))/cosc;
    const scale=2*Math.tan(view.fov*RAD/2)/Math.max(width,height);
    return [width/2-xi/scale,height/2-eta/scale];
  }
  const surveyKey=value=>({dss:'dss',mass:'mass',wise:'wise','P/DSS2/color':'dss','P/2MASS/color':'mass','P/allWISE/color':'wise'}[value]||'dss');
  class Atlas {
    constructor(element,options={}) {
      this.element=element;this.listeners={};this.view={ra:wrap(options.ra||0),dec:options.dec||0,fov:options.fov||1.4};
      this.survey=surveyKey(options.survey);this.grid=false;this.destroyed=false;this.pointers=new Map();
      element.replaceChildren();element.classList.add('native-atlas');element.tabIndex=0;
      this.image=document.createElement('img');this.image.alt='Real sky survey image';this.image.draggable=false;
      this.image.className='native-sky-image';element.appendChild(this.image);
      this.canvas=document.createElement('canvas');this.canvas.className='native-sky-grid';element.appendChild(this.canvas);
      this.reticle=document.createElement('span');this.reticle.className='native-sky-reticle';this.reticle.setAttribute('aria-hidden','true');element.appendChild(this.reticle);
      this.badge=document.createElement('span');this.badge.className='native-sky-badge';this.badge.textContent='CDS survey image · drag to pan';element.appendChild(this.badge);
      this.bound={pointerdown:e=>this.down(e),pointermove:e=>this.move(e),pointerup:e=>this.up(e),pointercancel:e=>this.up(e),wheel:e=>this.wheel(e),keydown:e=>this.key(e)};
      Object.entries(this.bound).forEach(([name,handler])=>element.addEventListener(name,handler,{passive:false}));
      this.resize=new ResizeObserver(()=>{this.drawGrid();this.schedule();});this.resize.observe(element);
      this.schedule(0);
    }
    on(name,fn){this.listeners[name]=fn;}
    emit(name,value){this.listeners[name]?.(value);}
    schedule(delay=250){clearTimeout(this.timer);this.abort?.abort();this.timer=setTimeout(()=>this.load(),delay);}
    async load(){
      if(this.destroyed)return;
      const rect=this.element.getBoundingClientRect();if(rect.width<1||rect.height<1)return;
      const scale=Math.min(1.5,1280/Math.max(rect.width,rect.height));
      const width=Math.max(64,Math.round(rect.width*scale)),height=Math.max(64,Math.round(rect.height*scale));
      const controller=new AbortController();this.abort=controller;
      const wanted={...this.view},survey=this.survey;
      const params=new URLSearchParams({ra:wanted.ra.toFixed(9),dec:wanted.dec.toFixed(9),fov:wanted.fov.toFixed(7),width,height,survey});
      this.emit('loading');this.badge.textContent='Loading survey image…';
      try{
        const response=await fetch('/api/sky.jpg?'+params,{signal:controller.signal});
        if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.detail?.message||error.detail||`Sky image request failed (${response.status}).`);}
        const blob=await response.blob();if(controller.signal.aborted||this.destroyed)return;
        const url=URL.createObjectURL(blob), decoded=new Image();decoded.src=url;
        try{await decoded.decode();}catch(error){URL.revokeObjectURL(url);throw error;}
        if(controller.signal.aborted||this.destroyed){URL.revokeObjectURL(url);return;}
        const previous=this.url;this.url=url;this.image.src=url;this.image.style.transform='';
        this.image.style.opacity='1';this.element.classList.remove('native-pending');
        if(previous)URL.revokeObjectURL(previous);
        this.shown={...wanted,survey};this.badge.textContent='CDS survey image · drag to pan';
        this.drawGrid();this.emit('ready');
      }catch(error){if(error.name!=='AbortError'&&!controller.signal.aborted&&!this.destroyed){this.image.style.opacity='.15';this.badge.textContent='Survey image unavailable';this.emit('error',error);}}
    }
    getFov(){return [this.view.fov,this.view.fov];}
    gotoRaDec(ra,dec){this.view.ra=wrap(ra);this.view.dec=clamp(dec,-90,90);this.changed();}
    setFoV(fov){this.view.fov=clamp(fov,.01,60);this.changed();}
    setBaseImageLayer(survey){this.survey=surveyKey(survey);this.changed();}
    setCooGrid({enabled}){this.grid=!!enabled;this.drawGrid();}
    retry(){this.schedule(0);}
    changed(){this.element.classList.add('native-pending');this.drawGrid();this.emit('positionChanged',{ra:this.view.ra,dec:this.view.dec});this.schedule();}
    local(e){const r=this.element.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
    down(e){
      if(e.pointerType==='mouse'&&e.button!==0)return;e.preventDefault();this.element.focus({preventScroll:true});
      this.element.setPointerCapture(e.pointerId);this.pointers.set(e.pointerId,this.local(e));
      this.startGesture();
    }
    startGesture(){const points=[...this.pointers.values()];this.gesture={view:{...this.view},points};this.abort?.abort();clearTimeout(this.timer);}
    move(e){
      if(!this.pointers.has(e.pointerId))return;e.preventDefault();this.pointers.set(e.pointerId,this.local(e));
      const points=[...this.pointers.values()],start=this.gesture;if(!start)return;
      const rect=this.element.getBoundingClientRect();
      if(points.length===1&&start.points.length===1){
        const dx=points[0].x-start.points[0].x,dy=points[0].y-start.points[0].y;
        const center=pixelToSky(rect.width/2-dx,rect.height/2-dy,rect.width,rect.height,start.view);
        this.view={...start.view,...center};this.image.style.transform=`translate(${dx}px,${dy}px)`;
      }else if(points.length>=2&&start.points.length>=2){
        const distance=p=>Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);
        const ratio=distance(start.points)/Math.max(1,distance(points));this.view={...start.view,fov:clamp(start.view.fov*ratio,.01,60)};
        this.image.style.transform=`scale(${start.view.fov/this.view.fov})`;
      }
      this.drawGrid();this.emit('positionChanged',{ra:this.view.ra,dec:this.view.dec});
    }
    up(e){if(!this.pointers.has(e.pointerId))return;this.pointers.delete(e.pointerId);if(this.pointers.size)this.startGesture();else{this.gesture=null;this.changed();}}
    wheel(e){e.preventDefault();const old=this.view.fov;this.view.fov=clamp(old*Math.exp(clamp(e.deltaY,-180,180)*.002),.01,60);this.image.style.transform=`scale(${(this.shown?.fov||old)/this.view.fov})`;this.changed();}
    key(e){const r=this.element.getBoundingClientRect(),step=60;let dx=0,dy=0;
      if(e.key==='ArrowLeft')dx=-step;else if(e.key==='ArrowRight')dx=step;else if(e.key==='ArrowUp')dy=-step;else if(e.key==='ArrowDown')dy=step;else if(e.key==='+'||e.key==='='){e.preventDefault();this.setFoV(this.view.fov*.6);return;}else if(e.key==='-'){e.preventDefault();this.setFoV(this.view.fov/ .6);return;}else return;
      e.preventDefault();const center=pixelToSky(r.width/2+dx,r.height/2+dy,r.width,r.height,this.view);this.gotoRaDec(center.ra,center.dec);
    }
    drawGrid(){
      const r=this.element.getBoundingClientRect();if(!r.width||!r.height)return;
      this.canvas.width=Math.round(r.width);this.canvas.height=Math.round(r.height);const ctx=this.canvas.getContext('2d');if(!ctx)return;
      ctx.clearRect(0,0,r.width,r.height);if(!this.grid)return;
      const view=this.view,step=10**Math.floor(Math.log10(view.fov/4)),spacing=step*(view.fov/step>12?2:1);
      ctx.strokeStyle='rgba(223,203,148,.35)';ctx.fillStyle='#dfcb94';ctx.font='10px monospace';ctx.lineWidth=1;
      const draw=(points,label)=>{ctx.beginPath();let last=null,labelled=false;for(const [ra,dec] of points){const p=skyToPixel(ra,dec,r.width,r.height,view);if(!p){last=null;continue;}if(last&&Math.hypot(p[0]-last[0],p[1]-last[1])<r.width/2)ctx.lineTo(...p);else ctx.moveTo(...p);last=p;if(!labelled&&p[0]>25&&p[0]<r.width-70&&p[1]>20&&p[1]<r.height-20){ctx.fillText(label,p[0]+3,p[1]-3);labelled=true;}}ctx.stroke();};
      const raSpan=Math.min(180,view.fov*1.5/Math.max(.1,Math.cos(view.dec*RAD)));
      const raStep=Math.max(spacing,raSpan/24);
      for(let ra=Math.floor((view.ra-raSpan)/raStep)*raStep;ra<=view.ra+raSpan;ra+=raStep){const pts=[];for(let i=0;i<=120;i++)pts.push([ra,clamp(view.dec-view.fov+i*view.fov/60,-90,90)]);draw(pts,wrap(ra).toFixed(2)+'°');}
      for(let dec=Math.ceil(Math.max(-90,view.dec-view.fov)/spacing)*spacing;dec<=Math.min(90,view.dec+view.fov);dec+=spacing){const pts=[];for(let i=0;i<=160;i++)pts.push([view.ra-raSpan+2*raSpan*i/160,dec]);draw(pts,dec.toFixed(2)+'°');}
    }
    destroy(){this.destroyed=true;clearTimeout(this.timer);this.abort?.abort();this.resize.disconnect();Object.entries(this.bound).forEach(([name,handler])=>this.element.removeEventListener(name,handler));if(this.url)URL.revokeObjectURL(this.url);this.element.replaceChildren();this.element.classList.remove('native-atlas');}
  }
  global.SkyAtlas={create:(element,options)=>new Atlas(element,options),pixelToSky,skyToPixel};
})(typeof window==='undefined'?globalThis:window);
