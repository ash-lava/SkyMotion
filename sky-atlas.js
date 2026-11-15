/* A small real-image atlas using the server’s live IRSA survey-tile renderer.
   Geometry matches local TAN and wide Hammer-Aitoff server rendering. No external scripts. */
(function (global) {
  'use strict';
  const RAD=Math.PI/180, DEG=180/Math.PI;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const wrap=ra=>((ra%360)+360)%360;
  const overviewScale=(width,height,view)=>Math.min(width/(4*Math.SQRT2),height/(2*Math.SQRT2))*360/view.fov;
  function pixelToSky(x,y,width,height,view) {
    if(view.fov>60){
      const scale=overviewScale(width,height,view),px=-(x-width/2)/scale,py=-(y-height/2)/scale;
      if(px*px/8+py*py/2>1+1e-12)return null;
      const z=Math.sqrt(Math.max(0,1-(px/4)**2-(py/2)**2));
      const lon=2*Math.atan2(z*px,2*(2*z*z-1)),lat=Math.asin(clamp(z*py,-1,1)),d=view.dec*RAD;
      const a=Math.cos(lat)*Math.cos(lon),b=Math.cos(lat)*Math.sin(lon),c=Math.sin(lat);
      return {ra:wrap(view.ra+Math.atan2(b,Math.cos(d)*a-Math.sin(d)*c)*DEG),dec:Math.asin(clamp(Math.sin(d)*a+Math.cos(d)*c,-1,1))*DEG};
    }
    const scale=2*Math.tan(view.fov*RAD/2)/Math.max(width,height);
    const xi=-(x-width/2)*scale, eta=-(y-height/2)*scale;
    const d=view.dec*RAD, denominator=Math.cos(d)-eta*Math.sin(d);
    return {ra:wrap(view.ra+Math.atan2(xi,denominator)*DEG),
      dec:Math.atan2(Math.sin(d)+eta*Math.cos(d),Math.hypot(denominator,xi))*DEG};
  }
  function skyToPixel(ra,dec,width,height,view) {
    const delta=(ra-view.ra)*RAD,d=dec*RAD,d0=view.dec*RAD;
    if(view.fov>60){
      const a=Math.cos(d0)*Math.cos(d)*Math.cos(delta)+Math.sin(d0)*Math.sin(d),b=Math.cos(d)*Math.sin(delta);
      const c=Math.cos(d0)*Math.sin(d)-Math.sin(d0)*Math.cos(d)*Math.cos(delta);
      const lon=Math.atan2(b,a),lat=Math.asin(clamp(c,-1,1)),den=Math.sqrt(1+Math.cos(lat)*Math.cos(lon/2));
      const scale=overviewScale(width,height,view);
      return [width/2-2*Math.SQRT2*Math.cos(lat)*Math.sin(lon/2)/den*scale,height/2-Math.SQRT2*Math.sin(lat)/den*scale];
    }
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
      this.element=element;this.listeners={};this.view={ra:wrap(options.ra||0),dec:clamp(options.dec||0,-90,90),fov:clamp(options.fov||6,.01,360)};
      this.survey=surveyKey(options.survey);this.grid=false;this.destroyed=false;this.pointers=new Map();
      element.replaceChildren();element.classList.add('native-atlas');element.tabIndex=0;
      this.image=document.createElement('img');this.image.alt='Real sky survey image';this.image.draggable=false;
      this.image.className='native-sky-image';element.appendChild(this.image);
      this.canvas=document.createElement('canvas');this.canvas.className='native-sky-grid';element.appendChild(this.canvas);
      this.reticle=document.createElement('span');this.reticle.className='native-sky-reticle';this.reticle.setAttribute('aria-hidden','true');element.appendChild(this.reticle);
      this.marker=document.createElement('span');this.marker.className='native-sky-selection';this.marker.style.display='none';element.appendChild(this.marker);
      this.badge=document.createElement('span');this.badge.className='native-sky-badge';this.badge.textContent='IRSA survey image · drag to pan';element.appendChild(this.badge);
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
        this.shown={...wanted,survey};this.badge.textContent='IRSA survey image · drag to pan';
        this.drawGrid();this.emit('ready');
      }catch(error){if(error.name!=='AbortError'&&!controller.signal.aborted&&!this.destroyed){this.image.style.opacity='.15';this.badge.textContent='Survey image unavailable';this.emit('error',error);}}
    }
    getFov(){return [this.view.fov,this.view.fov];}
    gotoRaDec(ra,dec){this.view.ra=wrap(ra);this.view.dec=clamp(dec,-90,90);this.changed();}
    setFoV(fov){this.view.fov=clamp(fov,.01,360);this.changed();}
    setSelection(selection){this.selection=selection;this.marker.textContent=selection?.name||'Selected patch';this.drawSelection();}
    drawSelection(){
      const r=this.element.getBoundingClientRect(),s=this.selection;
      const p=s&&skyToPixel(s.ra,s.dec,r.width,r.height,this.view);
      if(!p||p[0]<0||p[0]>r.width||p[1]<0||p[1]>r.height){this.marker.style.display='none';return;}
      this.marker.style.display='block';this.marker.style.left=p[0]+'px';this.marker.style.top=p[1]+'px';
    }
    setBaseImageLayer(survey){this.survey=surveyKey(survey);this.changed();}
    setCooGrid({enabled}){this.grid=!!enabled;this.drawGrid();}
    retry(){this.schedule(0);}
    changed(){this.element.classList.add('native-pending');this.drawGrid();this.emit('positionChanged',{...this.view});this.schedule();}
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
        if(!center)return;
        this.view={...start.view,...center};this.image.style.transform=`translate(${dx}px,${dy}px)`;
      }else if(points.length>=2&&start.points.length>=2){
        const distance=p=>Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);
        const ratio=distance(start.points)/Math.max(1,distance(points));this.view={...start.view,fov:clamp(start.view.fov*ratio,.01,360)};
        this.image.style.transform=`scale(${start.view.fov/this.view.fov})`;
      }
      this.drawGrid();this.emit('positionChanged',{...this.view});
    }
    up(e){if(!this.pointers.has(e.pointerId))return;this.pointers.delete(e.pointerId);if(this.pointers.size)this.startGesture();else{this.gesture=null;this.changed();}}
    wheel(e){e.preventDefault();const old=this.view.fov;this.view.fov=clamp(old*Math.exp(clamp(e.deltaY,-180,180)*.002),.01,360);this.image.style.transform=`scale(${(this.shown?.fov||old)/this.view.fov})`;this.changed();}
    key(e){const r=this.element.getBoundingClientRect(),step=60;let dx=0,dy=0;
      if(e.key==='ArrowLeft')dx=-step;else if(e.key==='ArrowRight')dx=step;else if(e.key==='ArrowUp')dy=-step;else if(e.key==='ArrowDown')dy=step;else if(e.key==='+'||e.key==='='){e.preventDefault();this.setFoV(this.view.fov*.6);return;}else if(e.key==='-'){e.preventDefault();this.setFoV(this.view.fov/ .6);return;}else return;
      e.preventDefault();const center=pixelToSky(r.width/2+dx,r.height/2+dy,r.width,r.height,this.view);if(center)this.gotoRaDec(center.ra,center.dec);
    }
    drawGrid(){
      this.drawSelection();
      const r=this.element.getBoundingClientRect();if(!r.width||!r.height)return;
      this.canvas.width=Math.round(r.width);this.canvas.height=Math.round(r.height);const ctx=this.canvas.getContext('2d');if(!ctx)return;
      ctx.clearRect(0,0,r.width,r.height);if(!this.grid)return;
      const view=this.view,step=10**Math.floor(Math.log10(view.fov/4)),spacing=view.fov>60?30:step*(view.fov/step>12?2:1);
      ctx.strokeStyle='rgba(223,203,148,.35)';ctx.fillStyle='#dfcb94';ctx.font='10px monospace';ctx.lineWidth=1;
      const draw=(points,label)=>{ctx.beginPath();let last=null,labelled=false;for(const [ra,dec] of points){const p=skyToPixel(ra,dec,r.width,r.height,view);if(!p){last=null;continue;}if(last&&Math.hypot(p[0]-last[0],p[1]-last[1])<r.width/2)ctx.lineTo(...p);else ctx.moveTo(...p);last=p;if(!labelled&&p[0]>25&&p[0]<r.width-70&&p[1]>20&&p[1]<r.height-20){ctx.fillText(label,p[0]+3,p[1]-3);labelled=true;}}ctx.stroke();};
      if(view.fov>60){
        for(let ra=0;ra<360;ra+=30){const pts=[];for(let dec=-90;dec<=90;dec+=2)pts.push([ra,dec]);draw(pts,ra+'°');}
        for(let dec=-60;dec<=60;dec+=30){const pts=[];for(let ra=0;ra<=360;ra+=2)pts.push([ra,dec]);draw(pts,dec+'°');}
        return;
      }
      const raSpan=Math.min(180,view.fov*1.5/Math.max(.1,Math.cos(view.dec*RAD)));
      const raStep=Math.max(spacing,raSpan/24);
      for(let ra=Math.floor((view.ra-raSpan)/raStep)*raStep;ra<=view.ra+raSpan;ra+=raStep){const pts=[];for(let i=0;i<=120;i++)pts.push([ra,clamp(view.dec-view.fov+i*view.fov/60,-90,90)]);draw(pts,wrap(ra).toFixed(2)+'°');}
      for(let dec=Math.ceil(Math.max(-90,view.dec-view.fov)/spacing)*spacing;dec<=Math.min(90,view.dec+view.fov);dec+=spacing){const pts=[];for(let i=0;i<=160;i++)pts.push([view.ra-raSpan+2*raSpan*i/160,dec]);draw(pts,dec.toFixed(2)+'°');}
    }
    destroy(){this.destroyed=true;clearTimeout(this.timer);this.abort?.abort();this.resize.disconnect();Object.entries(this.bound).forEach(([name,handler])=>this.element.removeEventListener(name,handler));if(this.url)URL.revokeObjectURL(this.url);this.element.replaceChildren();this.element.classList.remove('native-atlas');}
  }
  global.SkyAtlas={create:(element,options)=>new Atlas(element,options),pixelToSky,skyToPixel};
})(typeof window==='undefined'?globalThis:window);
