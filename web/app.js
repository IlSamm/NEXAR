/* NEXAR: frontend responsive. Ogni numero in modalità reale deriva dalla API autenticata. */
(()=>{
'use strict';
const $=id=>document.getElementById(id);
const demo=new URLSearchParams(location.search).get('demo')==='1';
const titles={
 home:['Panoramica','Il tuo PC sotto controllo, ovunque tu sia.'],
 energy:['Consumi','Quanto assorbe il PC dalla presa, componente per componente.'],
 lights:['Luci','Colori e luminosità dei LED.'],
 cooling:['Ventole','Temperature e profili di raffreddamento.'],
 power:['Accensione','Spegni, riavvia, sospendi o programma.'],
 screen:['Schermo','Guarda il PC da lontano, chiudi finestre bloccate, volume e avvisi dell’AI.'],
 gaming:['Gaming','I tuoi giochi, il PC pronto a giocare e le statistiche di ogni partita.'],
 optimize:['Ottimizza','Pulizia, programmi pesanti, file grandi, dischi e rete.'],
 links:['Collegamenti','Programmi trovati e collegati da soli.'],
 settings:['Impostazioni','AI ECO, energia, Telegram e registro.'],
 more:['Altro','Schermo, consumi, accensione, collegamenti e impostazioni.'],
};
let key=sessionStorage.getItem('pc_eco_key')||'';
const initialHash=location.hash.match(/^#access=([A-Za-z0-9_-]{28,})$/);
if(initialHash&&(location.hostname==='127.0.0.1'||location.hostname==='localhost')){
 key=initialHash[1];sessionStorage.setItem('pc_eco_key',key);
 history.replaceState(null,'',location.pathname+location.search);
}
// Mini App: Telegram passa i dati firmati nell'hash (#tgWebAppData=...); il server ne verifica la firma.
const tgHash=new URLSearchParams(location.hash.slice(1)).get('tgWebAppData');
if(tgHash){sessionStorage.setItem('pc_eco_tg',tgHash);history.replaceState(null,'',location.pathname+location.search);}
const tgInit=tgHash||sessionStorage.getItem('pc_eco_tg')||'';
if(tgInit){
 document.documentElement.classList.add('in-telegram');
 const sc=document.createElement('script');sc.src='https://telegram.org/js/telegram-web-app.js';
 sc.onload=()=>{const w=window.Telegram?.WebApp;if(!w)return;w.ready();w.expand();
  try{w.setHeaderColor('#0b0e14');w.setBackgroundColor('#090b0f');w.setBottomBarColor?.('#0b0e14');}catch(e){}
  try{w.disableVerticalSwipes?.();}catch(e){}   // scorrendo in cima la dashboard non si chiude più per sbaglio
  try{w.BackButton.onClick(()=>{if(typeof RC!=='undefined'&&RC.on){rcClose();return;}navigate('home');});}catch(e){}
  tgApp=w;syncTelegram();};
 document.head.append(sc);
}
let tgApp=null;let current=null,busy=false,rgbTouched=false,schedKind='shutdown';
const hist={cpu:[],gpu:[],power:[],ram:[],fan:[]};let curView='home';
const COMP={cpu:'#38bdf8',gpu:'#a78bfa',board:'#94a3b8',ram:'#2dd4bf',disks:'#fbbf24',cooling:'#34d399',rgb:'#f472b6',usb:'#fb923c',monitor:'#e2e8f0'};
const statusDemo={connected:true,version:'1.0.0',update:new URLSearchParams(location.search).has('upd')?{supported:true,available:true,latest:'1.0.31',checked_at:'2026-11-03T21:10:00'}:{supported:true,available:false,checked_at:'2026-11-03T21:10:00'},mode:'gaming',fans_level:'max',fans_levels_ready:true,cpu:12,cpu_temp:46,gpu:6,gpu_temp:38,gpu_watts:24,ram:34,ram_used:10.9,ram_total:31.1,eco_cpu_max_percent:90,
 fans:[{name:'CPU Fan',rpm:930,ctl:'/lpc/demo/control/0'},{name:'System Fan #1',rpm:0,ctl:'/lpc/demo/control/1'},{name:'System Fan #2',rpm:740,ctl:'/lpc/demo/control/2'},{name:'System Fan #3',rpm:750,ctl:'/lpc/demo/control/3'},{name:'Pump Fan',rpm:2400,ctl:'/lpc/demo/control/4'}],fans_manual_ready:true,fans_custom:{'/lpc/demo/control/2':45},
 rgb_enabled:true,fans_enabled:true,auto_enabled:true,processes:{codex:true,claude:false},telegram_enabled:true,rgb_color:'#ff0000',rgb_brightness:100,
 rgb_palette:['#ffffff','#ff0000','#ff8a00','#ffd400','#2cff5a','#00e5ff','#1f6bff','#8a3cff','#ff3cc8'],
 hardware:{cpu:'AMD Ryzen 7 9800X3D',gpu:'NVIDIA GeForce RTX 3060 Ti',motherboard:'MSI MAG B850 TOMAHAWK MAX WIFI',cooler:'ARCTIC Liquid Freezer II 240'},
 power:{items:[{key:'cpu',name:'Processore',watts:26.6,source:'misurato',detail:'24 W nel chip + regolatori'},{key:'gpu',name:'Scheda video',watts:24,source:'misurato',detail:'scheda intera'},
  {key:'board',name:'Scheda madre',watts:14,source:'stimato',detail:'chipset, rete, audio, Wi-Fi'},{key:'ram',name:'Memoria RAM',watts:3.5,source:'stimato',detail:'2 moduli'},
  {key:'disks',name:'Dischi',watts:9.4,source:'stimato',detail:'2 HDD + 3 NVMe'},{key:'cooling',name:'Ventole e pompa',watts:5.3,source:'stimato',detail:'5 ventole + pompa AIO'},
  {key:'rgb',name:'LED RGB',watts:1.5,source:'stimato',detail:'40 LED'},{key:'usb',name:'Periferiche USB',watts:6,source:'stimato',detail:'mouse, tastiera'}],
  dc:90.3,total:103,loss:12.7,efficiency:.877,psu_load:12,psu_watts:750,psu_class:'gold',amps:.5,va:116,pf:.89,voltage:230,low:93,high:113,margin:10,monitor_on:false,monitor_watts:0},
 energy:{today_kwh:1.42,month_kwh:12.3,price_eur_kwh:.3,today_cost:.43,month_cost:3.69,forecast_kwh:74,forecast_cost:22.2},
 pc:{uptime_s:11200,pending:null,hibernate:false,net:{name:'Ethernet 2',desc:'Realtek PCIe 5GbE',mac:'34:5A:60:77:D4:8D',ip:'192.168.0.128',broadcast:'192.168.0.255',wol_magic:true,wol_shutdown:true}},
 integrations:[{key:'rgb',name:'OpenRGB',level:'ok',detail:'ECO spegne tutti i LED'},{key:'fans',name:'Fan Control',level:'ok',detail:'Profili NEXAR'}],jobs:{}};

/* ---------- utilità ---------- */
const nf=(v,d=0)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const pct=v=>typeof v==='number'?Math.round(v)+'%':'—';
const deg=v=>typeof v==='number'?Math.round(v)+' °C':'—';
const eur=v=>typeof v==='number'?v.toLocaleString('it-IT',{style:'currency',currency:'EUR'}):'—';
const kwh=(v,d=2)=>typeof v==='number'?nf(v,d)+' kWh':'—';
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function icon(name){const s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('class','i');const u=document.createElementNS('http://www.w3.org/2000/svg','use');u.setAttribute('href','#i-'+name);s.append(u);return s;}
function duration(s){const m=Math.floor(s/60),h=Math.floor(m/60);return h>=24?`${Math.floor(h/24)} g ${h%24} h`:h?`${h} h ${m%60} min`:`${m} min`;}
function notify(txt,error=false){
 // Tutti gli avvisi compaiono in alto, nello stile dell'isola (niente più in basso).
 try{tgApp?.HapticFeedback?.notificationOccurred(error?'error':'success');}catch(e){}
 let s=String(txt||'').trim();const bad=error||/^⚠/.test(s),ok=!bad&&/^✓/.test(s);s=s.replace(/^(✓|⚠)\uFE0F?\s*/,'');if(!s)return;
 if(s==='Operazione avviata'&&document.querySelector('.isl,.lqc,.lq'))return;   // c'è già l'animazione che lo mostra
 const live=[...$('nt-stack').children].find(x=>x._txt===s&&!x._closed);if(live){live._h.pop();live._h.later(bad?6000:4200);return;}
 const [title,sub]=noteSplit(s);
 const h=topNote({title,sub,kind:bad?'err':ok?'ok':'',col:bad?NT_COL.err:ok?NT_COL.ok:NT_COL.info,ico:bad?'alert':ok?'check':'info',ms:bad?6000:4200});
 h.el._txt=s;
}
const NT_COL={ok:'#34d399',err:'#f87171',info:'#60a5fa',upd:'#a78bfa'};
function noteSplit(s){
 const parts=s.split(' · ');if(parts.length>1)return [parts[0],parts.slice(1).join(' · ')];
 const i=s.indexOf(': ');if(s.length>52&&i>3&&i<48)return [s.slice(0,i),s.slice(i+2)];
 return [s,''];
}
function topNote(o={}){
 // Pillola nera che scende dall'alto e si allarga col contenuto; può avere pulsanti e una barra di avanzamento.
 const stack=$('nt-stack'),still=matchMedia('(prefers-reduced-motion: reduce)').matches;
 stack.classList.toggle('below-isl',!!document.querySelector('.isl'));
 const n=el('div','nt');n.style.setProperty('--c',o.col||NT_COL.info);
 const ico=el('span','nt-ico');const ring=document.createElementNS('http://www.w3.org/2000/svg','svg');ring.setAttribute('class','nt-ring');ring.setAttribute('viewBox','0 0 40 40');
 ring.innerHTML='<circle class="nt-tr" cx="20" cy="20" r="18" pathLength="100"/><circle class="nt-ar" cx="20" cy="20" r="18" pathLength="100"/>';ico.append(ring,icon(o.ico||'check'));
 const arc=ring.querySelector('.nt-ar');
 const txt=el('div','nt-txt');const t1=el('b','',o.title||'');const t2=el('small','',o.sub||'');t2.hidden=!o.sub;txt.append(t1,t2);
 const act=el('div','nt-act');act.hidden=true;
 const bar=el('div','nt-bar');const bi=el('i');bar.append(bi);
 const inner=el('div','nt-in');inner.append(ico,txt,act);n.append(inner,bar);
 stack.append(n);while(stack.children.length>3)stack.firstElementChild.remove();
 let timer=0,kind=o.kind||'';
 const flip=fn=>{const a=n.getBoundingClientRect();fn();if(still||!n._shown)return;const b=n.getBoundingClientRect();
  if(Math.abs(a.width-b.width)<1&&Math.abs(a.height-b.height)<1)return;
  n.animate([{width:a.width+'px',height:a.height+'px'},{width:b.width+'px',height:b.height+'px'}],{duration:480,easing:EASE.spring});};
 const h={el:n,
  set(p){flip(()=>{
   if(p.title!=null)t1.textContent=p.title;if(p.sub!=null){t2.textContent=p.sub;t2.hidden=!p.sub;}
   if(p.col)n.style.setProperty('--c',p.col);if(p.ico)ico.querySelector('.i').replaceWith(icon(p.ico));
   if(p.kind!==undefined)kind=p.kind;n.className='nt'+(kind?' '+kind:'')+(n.classList.contains('busy')?' busy':'')+(n.classList.contains('indet')?' indet':'');
   if(p.actions!==undefined){act.replaceChildren(...(p.actions||[]).map(a=>{const b=el('button','nt-btn'+(a.primary?' primary':''),a.label);b.type='button';
     b.addEventListener('click',e=>{e.stopPropagation();a.run(h);});return b;}));act.hidden=!(p.actions||[]).length;}
   if(p.progress!==undefined){const on=p.progress!=null;n.classList.toggle('busy',on);n.classList.toggle('indet',on&&p.progress<0);
    if(on&&p.progress>=0){const v=Math.min(1,p.progress)*100;bi.style.width=v.toFixed(1)+'%';arc.style.strokeDasharray=`${v.toFixed(1)} 100`;}}
  });if(p.ms!==undefined)h.later(p.ms);return h;},
  later(ms){clearTimeout(timer);n._ms=ms;if(ms)timer=setTimeout(close,ms);},
  pop(){if(!still)ico.animate([{transform:'scale(.7)'},{transform:'scale(1.15)'},{transform:'scale(1)'}],{duration:560,easing:EASE.spring});},
  close(){return close();}};
 async function close(){if(n._closed)return;n._closed=true;clearTimeout(timer);
  if(!still){inner.animate([{opacity:1},{opacity:0}],{duration:140,fill:'forwards'});bar.style.opacity=0;const r=n.getBoundingClientRect();
   await n.animate([{width:r.width+'px',height:r.height+'px',opacity:1},{width:'48px',height:'48px',opacity:1,offset:.55},{width:'48px',height:'0px',opacity:0,marginTop:'-8px'}],
    {duration:560,easing:EASE.io,fill:'forwards'}).finished.catch(()=>{});}
  n.remove();}
 n._h=h;
 n.addEventListener('click',()=>{if(!o.sticky)close();});
 n.addEventListener('pointerenter',()=>clearTimeout(timer));
 n.addEventListener('pointerleave',()=>{if(!o.sticky&&!n._closed&&n._ms)h.later(n._ms);});
 h.set({actions:o.actions||[],progress:o.progress===undefined?null:o.progress});
 if(!still){const r=n.getBoundingClientRect();
  n.animate([{width:'48px',height:'48px',opacity:0,transform:'translateY(-18px) scale(.8)'},{width:'48px',height:'48px',opacity:1,transform:'none',offset:.22},{width:r.width+'px',height:r.height+'px',opacity:1,transform:'none'}],
   {duration:700,easing:EASE.spring});
  inner.animate([{opacity:0,filter:'blur(6px)',transform:'scale(.96)'},{opacity:0,offset:.32},{opacity:1,filter:'blur(0)',transform:'none'}],{duration:620,easing:'ease-out'});
  ico.animate([{transform:'scale(.4) rotate(-30deg)'},{transform:'scale(.4) rotate(-30deg)',offset:.3},{transform:'none'}],{duration:760,easing:EASE.spring});}
 n._shown=true;
 if(!o.sticky)h.later(o.ms||4200);
 return h;
}
function loginScreen(show){$('auth-screen').hidden=!show;$('app-shell').hidden=show;if(show)hideSplash();}
async function req(path,method='GET',data){
 const headers=tgInit?{'X-TG-Init-Data':tgInit}:{'X-PC-ECO-Key':key};if(data!==undefined)headers['Content-Type']='application/json';
 const ctrl=new AbortController();const t=setTimeout(()=>ctrl.abort(),15000);
 try{
  const r=await fetch(path,{method,headers,body:data===undefined?undefined:JSON.stringify(data),signal:ctrl.signal,cache:'no-store'});
  if(r.status===401&&tgInit)throw new Error('Questo account Telegram non è abbinato al PC.');
  if(r.status===401){sessionStorage.removeItem('pc_eco_key');key='';loginScreen(true);throw new Error('Chiave di accesso non valida.');}
  const obj=await r.json();if(!r.ok)throw new Error(obj.detail||'Errore di comunicazione');return obj;
 }finally{clearTimeout(t);}
}
async function post(path,body){
 if(demo){notify('Anteprima: comando non attivo.');return;}
 try{const r=await req(path,'POST',body);notify('✓ '+r.message);await refresh();}catch(ex){notify('⚠ '+ex.message,true);}
}
function choose(title,text,options,{ico='fan',danger=false}={}){
 // Finestra con più scelte (es. ventole spente: pompa al minimo / tutto spento). Restituisce il value scelto o ''.
 const d=$('confirm'),box=d.querySelector('.sheet-actions'),saved=[...box.children];
 $('confirm-title').textContent=title;$('confirm-text').textContent=text;
 $('confirm-ico').className='sheet-ico'+(danger?'':' calm');$('confirm-ico').replaceChildren(icon(ico));
 box.classList.add('stacked');box.replaceChildren(...options.map(o=>{const b=el('button','btn'+(o.cls?' '+o.cls:''),o.label);b.value=o.value;return b;}));
 d.returnValue='';d.showModal();
 return new Promise(res=>d.addEventListener('close',()=>{box.classList.remove('stacked');box.replaceChildren(...saved);res(d.returnValue);},{once:true}));
}
function ask(title,text,{danger=true,ico='power',yes='Conferma'}={}){
 const d=$('confirm');$('confirm-title').textContent=title;$('confirm-text').textContent=text;
 $('confirm-ico').className='sheet-ico'+(danger?'':' calm');$('confirm-ico').replaceChildren(icon(ico));
 $('confirm-yes').textContent=yes;$('confirm-yes').classList.toggle('danger',danger);
 if(!d.showModal)return Promise.resolve(confirm(title+'\n'+text));
 d.returnValue='';d.showModal();
 return new Promise(res=>d.addEventListener('close',()=>res(d.returnValue==='yes'),{once:true}));
}
function navigate(view){
 if(!titles[view])return;
 if(view==='settings'){if(!demo){loadSettings();loadEvents();}loadEco();}
 if(view==='lights')loadRgbDevices();
 if(view==='optimize')loadOptimize();
 if(view==='gaming')loadGaming(false,true);
 if(view==='energy')loadStats();
 if(view==='power')loadApps();
 if(view==='screen'){loadScreen();loadRemote();}
 if(view!=='screen'&&scrLiveOn)scrLive(false);
 const tab=['power','screen','links','settings','energy','lights'].includes(view)&&!document.querySelector(`.tabbar [data-view="${view}"]`)?'more':view;
 document.querySelectorAll('.rail-nav [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
 document.querySelectorAll('.tabbar [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===tab));
 document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+view));
 if(curView!==view)pageScan();curView=view;setZone();syncTelegram();
 document.querySelectorAll('.page.active .tabs').forEach(inkTabs);
 $('page-title').textContent=titles[view][0];$('page-desc').textContent=view==='home'?greeting():titles[view][1];
 window.scrollTo({top:0});
}
function setBar(id,v,max=100){const p=typeof v==='number'?Math.max(0,Math.min(100,v/max*100)):0;$(id).style.width=p+'%';
 const r=$(id).closest('.gstat')?.querySelector('.gr-f');if(r)r.style.strokeDasharray=`${p.toFixed(1)} 100`;}
function ringSvg(cls){
 const s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('viewBox','0 0 48 48');s.setAttribute('class',cls);s.setAttribute('aria-hidden','true');
 ['gr-t','gr-f'].forEach(c=>{const ci=document.createElementNS('http://www.w3.org/2000/svg','circle');ci.setAttribute('cx','24');ci.setAttribute('cy','24');ci.setAttribute('r','20');
  ci.setAttribute('pathLength','100');ci.setAttribute('class',c);s.append(ci);});
 return s;
}
document.querySelectorAll('.gstat').forEach(g=>{const ico=g.querySelector('.tile-ico');const w=el('span','gring');w.append(ringSvg('gr'),...ico.childNodes);ico.replaceWith(w);});
function chart(id,series,max,unit){
 const W=760,H=150,box=$(id);
 const all=series.flatMap(s=>s.data);
 const top=max||Math.max(10,...all)*1.15;
 const path=data=>(data.length>1?data:[0,0]).map((v,i,a)=>[i*W/(a.length-1),H-4-Math.min(1,Math.max(0,v/top))*(H-10)]).map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
 const body=series.map((s,i)=>{const d=path(s.data);return `<linearGradient id="g-${id}-${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity="${i?0:.25}"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient>
  <path d="${d} L${W},${H} L0,${H} Z" fill="url(#g-${id}-${i})"/><path d="${d}" stroke="${s.color}" stroke-width="2.4" fill="none" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;}).join('');
 box.innerHTML=`<div class="chart-scale"><span>${Math.round(top)}${unit}</span><span>${Math.round(top/2)}${unit}</span><span>0${unit}</span></div>
 <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><g class="gridlines"><line x1="0" y1="2" x2="${W}" y2="2"/><line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}"/><line x1="0" y1="${H-2}" x2="${W}" y2="${H-2}"/></g>${body}</svg>`;
}
function areaBg(id,data){
 // Curva morbida dei watt sul fondo delle schede grandi (colore preso dalla scheda: currentColor).
 const box=$(id);if(!box)return;const pts=data.length>1?data:[0,0];const top=Math.max(80,...pts)*1.3,W=600,H=160;
 const P=pts.map((v,i)=>[i*W/(pts.length-1),H-8-Math.min(1,Math.max(0,v/top))*(H-24)]);
 let d=`M${P[0][0]},${P[0][1]}`;
 for(let i=0;i<P.length-1;i++){const p0=P[i-1]||P[i],p1=P[i],p2=P[i+1],p3=P[i+2]||p2;
  d+=` C${(p1[0]+(p2[0]-p0[0])/6).toFixed(1)},${(p1[1]+(p2[1]-p0[1])/6).toFixed(1)} ${(p2[0]-(p3[0]-p1[0])/6).toFixed(1)},${(p2[1]-(p3[1]-p1[1])/6).toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;}
 const g='ab-'+id;
 box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><defs><linearGradient id="${g}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".32"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>`+
  `<path d="${d} L${W},${H} L0,${H} Z" fill="url(#${g})"/><path d="${d}" fill="none" stroke="currentColor" stroke-width="2" stroke-opacity=".8" vector-effect="non-scaling-stroke"/>`+
  `<circle cx="${P[P.length-1][0]}" cy="${P[P.length-1][1]}" r="4" fill="currentColor" class="ab-dot"/></svg>`;
}
function push(arr,v){if(typeof v==='number'){arr.push(v);if(arr.length>60)arr.shift();}}

/* ---------- rendering ---------- */
function render(s){
 current=s;
 modeFx(s.mode);
 const eco=s.mode==='eco';
 document.querySelectorAll('.mode-opt').forEach(b=>b.classList.toggle('selected',b.classList.contains(s.mode)));
 $('mode-desc').textContent=eco?`Turbo spento, CPU al ${s.eco_cpu_max_percent??'—'}%, dischi e USB a risparmio, monitor spento dopo ${Math.round((s.monitor_timeout_seconds||60)/60)} min`
  :s.mode==='gaming'?'Turbo al massimo, CPU sempre pronta, monitor mai spento':'Piano energetico originale di Windows';
 const mp=$('mode-pill');mp.className='mode-pill '+(s.mode||'normal');mp.querySelector('span').textContent={eco:'AI ECO',gaming:'Gaming'}[s.mode]||'Normale';
 // Componenti
 const p=s.power||{};const w=k=>(p.items||[]).find(i=>i.key===k)?.watts;
 countUp($('cpu-val'),s.cpu,pct);countUp($('gpu-val'),s.gpu,pct);countUp($('ram-val'),s.ram,pct);
 [['cpu-temp',s.cpu_temp,80],['gpu-temp',s.gpu_temp,78]].forEach(([id,v,hot])=>{$(id).textContent=deg(v);$(id).classList.toggle('hot',v>=hot);});
 $('cpu-sub').textContent=typeof w('cpu')==='number'?`${nf(w('cpu'))} W · ${p.items.find(i=>i.key==='cpu').source}`:'consumo —';
 $('gpu-sub').textContent=typeof w('gpu')==='number'?`${nf(w('gpu'))} W · ${p.items.find(i=>i.key==='gpu').source}`:'consumo —';
 $('ram-detail').textContent=typeof s.ram_used==='number'?`${nf(s.ram_used,1)} di ${nf(s.ram_total,0)} GB`:'—';
 $('ram-sub').textContent=typeof w('ram')==='number'?`~${nf(w('ram'),1)} W`:'—';
 const hw=s.hardware||{};
 $('cpu-name').textContent=(hw.cpu||'—').replace(/^AMD |^Intel\(R\) /,'');$('gpu-name').textContent=(hw.gpu||'—').replace(/^NVIDIA GeForce /,'');
 $('hw-mb').textContent=hw.motherboard||'—';$('hw-cpu-name').textContent=hw.cpu||'—';$('hw-gpu-name').textContent=hw.gpu||'—';$('hw-cooler').textContent=hw.cooler||'—';
 ['cpu','gpu','ram'].forEach(n=>setBar(n+'-bar',s[n]));
 const caseFans=(s.fans||[]).filter(f=>/system fan/i.test(f.name)&&f.rpm>0);
 const avg=caseFans.length?Math.round(caseFans.reduce((a,f)=>a+f.rpm,0)/caseFans.length):null;
 countUp($('fan-val'),avg||null,v=>typeof v==='number'?Math.round(v)+' RPM':'—');setBar('fan-bar',avg,1800);
 const fs=$('fan-spin');if(fs){fs.style.animationDuration=avg?Math.max(.35,Math.min(4,900/avg)).toFixed(2)+'s':'0s';fs.classList.toggle('still',!avg);}
 renderHomeHero(s);
 $('hw-cpu').textContent=deg(s.cpu_temp);$('hw-gpu').textContent=deg(s.gpu_temp);
 [['cpu',s.cpu_temp,80],['gpu',s.gpu_temp,78]].forEach(([k,v,hot])=>{const a=$(`hw-${k}-arc`);if(!a)return;
  a.style.strokeDasharray=`${typeof v==='number'?Math.min(75,Math.max(0,v)/100*75).toFixed(1):0} 100`;$('tg-'+k).classList.toggle('hot',v>=hot);
  const col=!(v>0)?'#475569':v<60?'#34d399':v<hot-5?'#fbbf24':'#f87171';a.style.stroke=col;a.style.filter=`drop-shadow(0 0 6px ${col})`;});
 // Agenti e automazione
 [['codex',s.processes?.codex],['claude',s.processes?.claude]].forEach(([n,on])=>{$(n+'-state').textContent=on?'Al lavoro':'Chiuso';$(n+'-dot').classList.toggle('off',!on);});
 $('auto-toggle').setAttribute('aria-checked',s.auto_enabled?'true':'false');
 $('auto-note').textContent=s.auto_enabled?'AI ECO parte da sola quando lavorano':'Spenta: cambi modalità solo a mano';
 // Luci e ventole
 ['rgb-eco','rgb-normal','rgb-apply-all','q-rgb-off','q-rgb-on'].forEach(id=>$(id).disabled=!s.rgb_enabled);
 ['fans-eco','fans-normal','q-fans-eco','q-fans-normal'].forEach(id=>$(id).disabled=!s.fans_enabled);
 ['fans-off','fans-max'].forEach(id=>$(id).disabled=!s.fans_enabled||!s.fans_levels_ready);
 ['off','eco','normal','max'].forEach(l=>$('fans-'+l).classList.toggle('selected',s.fans_level===l));
 const upgrade=s.fans_enabled&&!s.remote&&(!s.fans_levels_ready||s.fans_profiles_outdated);$('fans-upgrade').hidden=!upgrade;
 $('fans-upgrade-title').textContent=s.fans_levels_ready?'Nuovo Massimo: tutte le ventole al 100%':'Nuovi profili Spente e Massimo';
 const fanN=(s.fans||[]).filter(f=>f.rpm>0).length;
 $('cool-title').textContent=!s.fans_enabled?'Gestione del BIOS':{off:'Ventole spente',eco:'Profilo silenzioso',max:'Tutte al massimo'}[s.fans_level]||'Profilo normale';
 $('cool-sub').textContent=fanN?`${fanN} ventole in funzione${avg?` · media ${avg} RPM`:''} · CPU ${deg(s.cpu_temp)} · GPU ${deg(s.gpu_temp)}`:'Nessuna ventola rilevata: collega i sensori in Collegamenti';
 $('cool-hero').dataset.level=s.fans_enabled?(s.fans_level||'normal'):'bios';
 $('rgb-title').textContent=!s.rgb_enabled?'OpenRGB non collegato':s.rgb_off?'LED spenti':'LED accesi';
 $('fan-profile').textContent=!s.fans_enabled?'Gestione BIOS':{off:'Ventole spente',eco:'Profilo silenzioso',max:'Al massimo'}[s.fans_level]||'Profilo normale';
 $('rgb-label').textContent=!s.rgb_enabled?'OpenRGB non collegato':(s.rgb_off?'LED spenti: scegli un colore per riaccenderli':'Colore e luminosità per tutti i dispositivi');
 if(!rgbTouched&&s.rgb_color){$('rgb-color').value=s.rgb_color;$('rgb-bright').value=s.rgb_brightness??100;$('rgb-bright-val').textContent=$('rgb-bright').value+'%';}
 renderPalette(s.rgb_palette||[]);
 paintOrb(s.rgb_off);
 renderFans(s.fans||[]);
 // Telegram e connessione
 const bot=s.telegram_bot||{};
 $('telegram-indicator').textContent=bot.error?'Bot non raggiungibile':s.telegram_enabled?`Collegato a @${bot.username||'bot'} · solo il tuo account`:bot.username?`@${bot.username}: invia il codice /pair`:'Non collegato';
 $('tg-error').hidden=!bot.error;$('tg-error').textContent=bot.error||'';
 $('tg-bot-link').hidden=!bot.username;if(bot.username){$('tg-bot-link').textContent='@'+bot.username;$('tg-bot-link').href='https://t.me/'+bot.username;}
 const ok=!!s.connected;$('conn-dot').classList.toggle('off',!ok);$('conn-text').textContent=ok?'PC connesso':'Non connesso';
 document.querySelectorAll('.local-only').forEach(e=>e.hidden=!!s.remote);
 renderPower(s.power,s.energy);
 renderPc(s.pc||{});
 push(hist.cpu,s.cpu);push(hist.gpu,s.gpu);push(hist.power,s.power?.total);push(hist.ram,s.ram);push(hist.fan,avg??0);
 spark('cpu-val',hist.cpu,100,COMP.cpu);spark('gpu-val',hist.gpu,100,COMP.gpu);spark('ram-val',hist.ram,100,COMP.ram);spark('fan-val',hist.fan,1800,COMP.cooling);setZone();
 chart('chart-load',[{data:hist.cpu,color:COMP.cpu},{data:hist.gpu,color:COMP.gpu}],100,'%');
 chart('chart-power',[{data:hist.power,color:'#34d399'}],0,' W');
 areaBg('hm-chart',hist.power);areaBg('e-chart',hist.power);
 renderLinks(s.integrations||[],s.jobs||{});
 renderUpdate(s.version,s.update||{},s.jobs?.update);
 watchOptimizeJobs(s.jobs||{});
 renderGamingLive(s);
 // Schede delle zone in Home: dati di Ottimizza e libreria giochi letti una volta all'avvio.
 if(!render.zones){render.zones=true;loadOptimize(true);loadGaming();}
 renderZones();
 hideSplash();
}
function renderUpdate(version,u,job){
 if(version){$('app-version').textContent='v'+version;$('upd-version').textContent='v'+version;}
 const running=job?.state==='running'||['downloading','installing','restarting'].includes(u.status);
 $('upd-install').hidden=!u.available;$('upd-install').disabled=running;
 $('upd-install').textContent=running?'Aggiornamento in corso…':`Aggiorna a ${u.latest||''}`;
 if(running&&!demo){if(!updNote||updNote.el._closed)updNote=topNote({sticky:true,ico:'download',col:NT_COL.upd,kind:'upd',title:'Aggiornamento in corso',progress:-1});if(!updPoll)pollUpdate();}
 else updateOffer(u);
 if(u.updated&&!updWelcomed(version)&&Date.now()/1000-u.updated.at<900)
  setTimeout(()=>{topNote({ico:'check',col:NT_COL.ok,kind:'ok',title:`NEXAR aggiornata a ${version}`,sub:`Da ${u.updated.from}: le novità sono già attive`,ms:5600}).pop();},900);
 $('upd-text').textContent=!u.supported?'Disponibili solo nell\'app installata':u.status==='error'?u.message
  :u.available?`Nuova versione ${u.latest} pronta`:u.checked_at?`Aggiornato · controllato ${u.checked_at.slice(11,16)}`:'Controllo al primo avvio';
}
/* ---------- aggiornamenti: avviso in alto; scarica e installa solo quando lo chiedi tu ---------- */
let updNote=null,updPoll=0,updT0=0,updLater='';
try{updLater=sessionStorage.getItem('nexar_upd_later')||'';}catch(e){}
function updWelcomed(version){try{if(sessionStorage.getItem('nexar_upd_welcome')===version)return true;sessionStorage.setItem('nexar_upd_welcome',version);}catch(e){}return false;}
function updateOffer(u){
 if(!u?.available||!u.supported||updLater===u.latest||(updNote&&!updNote.el._closed))return;
 updNote=topNote({sticky:true,ico:'download',col:NT_COL.upd,kind:'upd',title:`NEXAR ${u.latest} è pronta`,sub:'Nuova versione disponibile',
  actions:[{label:'Più tardi',run:h=>{updLater=u.latest;try{sessionStorage.setItem('nexar_upd_later',u.latest);}catch(e){}h.close();updNote=null;}},
           {label:'Aggiorna',primary:true,run:()=>startUpdate()}]});
}
async function startUpdate(){
 const u=current?.update||{};updLater='';
 if(!updNote||updNote.el._closed)updNote=topNote({sticky:true,ico:'download',col:NT_COL.upd,kind:'upd',title:'Aggiornamento'});
 updNote.set({ico:'download',col:NT_COL.upd,kind:'upd',title:`Scarico NEXAR ${u.latest||''}`,sub:'Preparo il download…',actions:[],progress:0});updNote._stage='';updT0=0;
 if(demo){demoUpdate(u.latest||'1.0.31');return;}
 try{await req('/api/update/install','POST',{});}catch(ex){updFail(ex.message);return;}
 pollUpdate();
}
function updFail(msg){
 clearTimeout(updPoll);updPoll=0;
 updNote?.set({kind:'upd err',col:NT_COL.err,ico:'alert',title:'Aggiornamento non riuscito',sub:String(msg||'').slice(0,110),progress:null,
  actions:[{label:'Chiudi',run:h=>{h.close();updNote=null;}},{label:'Riprova',primary:true,run:()=>startUpdate()}]});
}
function updStage(u,job){
 if(!updNote)return false;
 if(u.status==='error'||job?.state==='error'){updFail(u.message||job?.message);return false;}
 if(u.status==='downloading'){
  const p=u.progress||{},done=p.done||0,tot=p.total||0,now=performance.now();if(!updT0&&done)updT0=now-200;
  const speed=updT0?done/Math.max(.2,(now-updT0)/1000):0;
  updNote.set({title:`Scarico NEXAR ${u.latest||''}`+(tot?` · ${Math.floor(done/tot*100)}%`:''),
   sub:tot?`${bytes(done)} di ${bytes(tot)}`+(speed?` · ${bytes(speed)}/s`:''):'Download in corso…',progress:tot?done/tot:-1});
  return true;}
 if(u.status==='installing'){updNote.set({title:'Installo l’aggiornamento',sub:'Controllo i file scaricati…',progress:-1});return true;}
 if(u.status==='restarting'&&updNote._stage!=='restart'){updNote._stage='restart';
  updNote.set({ico:'check',col:NT_COL.ok,title:'NEXAR si riavvia',sub:'Torna tra qualche secondo con la nuova versione',progress:1});updNote.pop();}
 return true;
}
async function pollUpdate(){
 clearTimeout(updPoll);const was=current?.version;
 try{const r=await req('/api/update');
  if(updNote?._stage==='restart'&&r.update.current!==was){location.reload();return;}   // il server è tornato con la nuova versione
  if(!updStage(r.update,r.job)&&updNote?._stage!=='restart'){updPoll=0;return;}}
 catch(e){/* server spento mentre si sostituisce: si riprova */}
 updPoll=setTimeout(pollUpdate,updNote?._stage==='restart'?1500:350);
}
function demoUpdate(v){
 const tot=29.5*1048576,t0=performance.now();updT0=t0;
 const step=()=>{const k=Math.min(1,(performance.now()-t0)/4200);
  if(k<1){updStage({status:'downloading',latest:v,progress:{done:tot*k,total:tot}});setTimeout(step,300);return;}
  updStage({status:'installing'});setTimeout(()=>{updStage({status:'restarting'});setTimeout(()=>{updNote?.close();updNote=null;},3200);},1400);};
 step();
}
let splashGone=false;
function hideSplash(){
 if(splashGone)return;splashGone=true;
 setTimeout(()=>{$('splash').classList.add('gone');setTimeout(()=>$('splash').remove(),600);},Math.max(0,(tgInit?700:2100)-performance.now()));   // il tempo di vedere la N dipinta
}
function renderFans(fans){
 const box=$('fan-list');
 const spinning=fans.filter(f=>f.rpm>0),empty=fans.length-spinning.length;
 const free=$('fan-free');free.hidden=!empty;free.textContent=`${empty} connettori liberi`;
 if(!spinning.length){box._map=null;box.replaceChildren(el('p','muted',fans.length?'Ventole ferme in questo momento.':'Nessun RPM disponibile: collega i sensori in Collegamenti.'));return;}
 if(!box._map){box._map=new Map();box.replaceChildren();}
 const seen=new Set();
 spinning.forEach((f,i)=>{
  const pump=/pump/i.test(f.name),max=pump?3000:1800,pct=Math.min(100,f.rpm/max*100);seen.add(f.name);
  let c=box._map.get(f.name);
  if(!c){c=el('div','fan2'+(pump?' pump':''));c.style.setProperty('--i',i);c.tabIndex=0;c.setAttribute('role','button');
   c.addEventListener('click',()=>openFan(c._f));c.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openFan(c._f);}});
   c.innerHTML=`<div class="f2-dial"><svg viewBox="0 0 60 60"><circle class="f2-track" cx="30" cy="30" r="26" pathLength="100"/><circle class="f2-fill" cx="30" cy="30" r="26" pathLength="100"/></svg><svg class="i f2-spin"><use href="#i-fan"/></svg></div><div class="f2-txt"><small></small><b></b></div>`;
   c.querySelector('small').textContent=f.name.replace('CPU Fan','Radiatore').replace('Pump Fan','Pompa').replace('System Fan','Ventola case');
   box._map.set(f.name,c);box.append(c);}
  c._f=f;const cu=(current?.fans_custom||{})[f.ctl],cv=cu&&typeof cu==='object';c.classList.toggle('custom',cu!=null);
  c.setAttribute('aria-label',`${FAN_NICE(f.name)}: ${f.rpm} RPM${cv?`, con curva sulla ${cu.src.toUpperCase()}`:cu!=null?`, fissa al ${cu}%`:''}. Apri per regolarla`);
  let tag=c.querySelector('.f2-tag');if(cu!=null){if(!tag){tag=el('span','f2-tag');c.append(tag);}tag.textContent=cv?'Curva':cu+'%';tag.classList.toggle('cv',cv);}else tag?.remove();
  c.querySelector('b').innerHTML=`${f.rpm}<em>RPM</em>`;
  if(fanSheet.f?.ctl===f.ctl){fanSheetLive(f);if(fanSheet.mode==='curve'&&fanSheet.drag<0)fanCurveDraw();}
  c.querySelector('.f2-fill').style.strokeDasharray=`${pct.toFixed(1)} 100`;
  c.querySelector('.f2-spin').style.animationDuration=Math.max(.3,Math.min(4,900/f.rpm)).toFixed(2)+'s';
 });
 [...box._map].forEach(([k,c])=>{if(!seen.has(k)){c.remove();box._map.delete(k);}});
}
/* ---------- una ventola alla volta: scheda con regolazione manuale ---------- */
const FAN_NICE=n=>String(n||'Ventola').replace('CPU Fan','Radiatore').replace('Pump Fan','Pompa AIO').replace('System Fan','Ventola case');
const fanSheet={f:null,mode:'auto',val:50,src:'cpu',pts:null,drag:-1};
const FAN_CURVES={quiet:[[40,20],[60,35],[72,55],[85,100]],bal:[[35,30],[55,45],[70,70],[80,100]],perf:[[30,45],[50,60],[65,85],[75,100]]};
function fanSheetLive(f){
 fanSheet.f=f;const pump=/pump/i.test(f.name),pct=Math.min(100,f.rpm/(pump?3000:1800)*100);
 $('fs-rpm').textContent=f.rpm;$('fs-arc').style.strokeDasharray=`${pct.toFixed(1)} 100`;
 $('fs-spin').style.animationDuration=f.rpm>0?Math.max(.25,Math.min(4,900/f.rpm)).toFixed(2)+'s':'0s';
 $('fan-sheet').classList.toggle('still',!f.rpm);
}
function fanSheetMode(m){
 fanSheet.mode=m;document.querySelectorAll('#fs-modes button').forEach(b=>b.classList.toggle('selected',b.dataset.m===m));
 $('fs-manual').classList.toggle('off',m!=='manual');$('fs-manual').hidden=m==='curve';$('fs-curve').hidden=m!=='curve';$('fs-auto').hidden=m!=='auto';
 if(m==='curve')fanCurveDraw();fanSheetSafe();
}
/* curva: velocità secondo la temperatura di CPU o GPU, eseguita da Fan Control */
const CV={x0:34,x1:310,y0:10,y1:156,t0:20,t1:100};
const cvX=t=>CV.x0+(t-CV.t0)/(CV.t1-CV.t0)*(CV.x1-CV.x0),cvY=d=>CV.y0+(100-d)/100*(CV.y1-CV.y0);
function cvDuty(pts,t){if(t<=pts[0][0])return pts[0][1];for(let i=1;i<pts.length;i++){const[a,b]=[pts[i-1],pts[i]];if(t<=b[0])return a[1]+(b[1]-a[1])*(t-a[0])/(b[0]-a[0]);}return pts[pts.length-1][1];}
const fanIsPump=()=>/pump/i.test(fanSheet.f?.name||'');
function fanCurveSet(pts){const min=fanIsPump()?40:0;fanSheet.pts=pts.map(([t,d])=>[t,Math.max(min,d)]);
 for(let i=1;i<fanSheet.pts.length;i++)fanSheet.pts[i][1]=Math.max(fanSheet.pts[i][1],fanSheet.pts[i-1][1]);fanCurveDraw();fanSheetSafe();}
function fanCurveNow(){const t=fanSheet.src==='gpu'?current?.gpu_temp:current?.cpu_temp;return typeof t==='number'?t:null;}
function fanCurveDraw(){
 const g=$('fs-graph'),P=fanSheet.pts;if(!P)return;const ns='http://www.w3.org/2000/svg';
 const mk=(tag,a,cls)=>{const n=document.createElementNS(ns,tag);for(const k in a)n.setAttribute(k,a[k]);if(cls)n.setAttribute('class',cls);return n;};
 if(!g._init){g._init=true;g.replaceChildren();
  const defs=mk('defs',{});defs.innerHTML='<linearGradient id="fs-cv-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22d3ee" stop-opacity=".42"/><stop offset="1" stop-color="#22d3ee" stop-opacity="0"/></linearGradient>';g.append(defs);
  g.append(mk('rect',{x:cvX(CV.t0),y:CV.y0,width:cvX(100)-cvX(CV.t0),height:CV.y1-CV.y0,rx:8},'cv-bg'));
  g.append(mk('rect',{x:cvX(80),y:CV.y0,width:cvX(100)-cvX(80),height:CV.y1-CV.y0},'cv-hot'));
  [40,60,80].forEach(t=>{g.append(mk('line',{x1:cvX(t),x2:cvX(t),y1:CV.y0,y2:CV.y1},'cv-grid'));const l=mk('text',{x:cvX(t),y:CV.y1+17,'text-anchor':'middle'},'cv-lab');l.textContent=t+'°';g.append(l);});
  [25,50,75].forEach(d=>{g.append(mk('line',{x1:CV.x0,x2:CV.x1,y1:cvY(d),y2:cvY(d)},'cv-grid'));});
  [0,50,100].forEach(d=>{const l=mk('text',{x:CV.x0-7,y:cvY(d)+4,'text-anchor':'end'},'cv-lab');l.textContent=d+'%';g.append(l);});
  g.append(mk('path',{d:''},'cv-area'));g.append(mk('path',{d:''},'cv-line'));
  g.append(mk('line',{x1:0,x2:0,y1:CV.y0,y2:CV.y1},'cv-now'));g.append(mk('circle',{r:5,cx:0,cy:0},'cv-now-dot'));
  g._pts=[];
 }
 while(g._pts.length>P.length)g._pts.pop().remove();
 while(g._pts.length<P.length){const i=g._pts.length,h=mk('g',{tabindex:0,role:'slider'},'cv-pt');h.append(mk('circle',{r:16},'cv-hit'),mk('circle',{r:7.5},'cv-dot'));
  h.addEventListener('pointerdown',e=>{e.preventDefault();fanSheet.drag=i;g.setPointerCapture(e.pointerId);h.classList.add('drag');});
  h.addEventListener('keydown',e=>{const k={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,1],ArrowDown:[0,-1]}[e.key];if(!k)return;e.preventDefault();const p=fanSheet.pts[i];fanCurveMove(i,p[0]+k[0],p[1]+k[1]*(e.shiftKey?10:2));});
  g.append(h);g._pts.push(h);}
 const xy=P.map(([t,d])=>[cvX(t),cvY(d)]),line=`M${cvX(CV.t0)},${xy[0][1]} `+xy.map(p=>'L'+p.join(',')).join(' ')+` L${cvX(100)},${xy[xy.length-1][1]}`;
 g.querySelector('.cv-line').setAttribute('d',line);g.querySelector('.cv-area').setAttribute('d',line+` L${cvX(100)},${CV.y1} L${cvX(CV.t0)},${CV.y1} Z`);
 P.forEach(([t,d],i)=>{const h=g._pts[i];h.setAttribute('transform',`translate(${cvX(t)},${cvY(d)})`);h.setAttribute('aria-label',`Punto ${i+1}: ${t} gradi, ${d}%`);});
 const now=fanCurveNow(),nl=g.querySelector('.cv-now'),nd=g.querySelector('.cv-now-dot');
 if(now==null){nl.classList.add('gone');nd.classList.add('gone');$('fs-cv-now').textContent='temperatura —';}
 else{const t=Math.max(CV.t0,Math.min(100,now)),d=cvDuty(P,t);nl.classList.remove('gone');nd.classList.remove('gone');
  nl.setAttribute('x1',cvX(t));nl.setAttribute('x2',cvX(t));nd.setAttribute('cx',cvX(t));nd.setAttribute('cy',cvY(d));
  $('fs-cv-now').innerHTML=`<b>${Math.round(now)}°</b> → <b>${Math.round(d)}%</b> ora`;}
 document.querySelectorAll('#fs-src button').forEach(b=>b.classList.toggle('selected',b.dataset.s===fanSheet.src));
 document.querySelectorAll('#fs-cpresets button').forEach(b=>b.classList.toggle('selected',JSON.stringify(FAN_CURVES[b.dataset.c].map(([t,d])=>[t,Math.max(fanIsPump()?40:0,d)]))===JSON.stringify(P)));
}
function fanCurveMove(i,t,d){
 const P=fanSheet.pts,min=fanIsPump()?40:0,lo=i?P[i-1]:null,hi=P[i+1];
 t=Math.round(Math.max(lo?lo[0]+3:CV.t0,Math.min(hi?hi[0]-3:100,t)));d=Math.round(Math.max(lo?lo[1]:min,Math.min(hi?hi[1]:100,d)));
 P[i]=[t,d];fanCurveDraw();fanSheetSafe();
}
function fanSheetSafe(){
 const ap=$('fs-apply'),bad=fanSheet.mode==='curve'&&fanSheet.pts&&cvDuty(fanSheet.pts,80)<50;
 ap.disabled=!!bad&&!!current?.fans_manual_ready;
 $('fs-cnote').textContent=bad?'Troppo lenta quando scalda: a 80 °C serve almeno il 50%. Alza l\'ultimo punto.'
  :fanIsPump()?'La pompa non scende sotto il 40%.':'Trascina i punti. Fan Control la segue da solo, anche a NEXAR chiusa.';
 $('fs-cnote').classList.toggle('bad',!!bad);
}
$('fs-graph').addEventListener('pointermove',e=>{
 if(fanSheet.drag<0)return;const g=$('fs-graph'),m=g.getScreenCTM();if(!m)return;
 const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(m.inverse());
 fanCurveMove(fanSheet.drag,CV.t0+(p.x-CV.x0)/(CV.x1-CV.x0)*(CV.t1-CV.t0),100-(p.y-CV.y0)/(CV.y1-CV.y0)*100);
});
const cvEnd=()=>{if(fanSheet.drag<0)return;fanSheet.drag=-1;document.querySelectorAll('.cv-pt.drag').forEach(h=>h.classList.remove('drag'));};
$('fs-graph').addEventListener('pointerup',cvEnd);$('fs-graph').addEventListener('pointercancel',cvEnd);
document.querySelectorAll('#fs-src button').forEach(b=>b.addEventListener('click',()=>{fanSheet.src=b.dataset.s;fanCurveDraw();}));
document.querySelectorAll('#fs-cpresets button').forEach(b=>b.addEventListener('click',()=>fanCurveSet(FAN_CURVES[b.dataset.c])));
function fanSheetVal(v){
 const pump=/pump/i.test(fanSheet.f?.name||''),min=pump?40:0;v=Math.max(min,Math.min(100,Math.round(v)));fanSheet.val=v;
 const r=$('fs-range');r.min=min;r.value=v;r.style.setProperty('--v',((v-min)/(100-min)*100).toFixed(1)+'%');
 $('fs-pct').textContent=v;$('fan-sheet').style.setProperty('--fv',v);
 document.querySelectorAll('#fs-presets button').forEach(b=>{const p=+b.dataset.p;b.disabled=p<min;b.classList.toggle('selected',p===v);});
 $('fs-note').textContent=pump?'La pompa non scende sotto il 40%: tiene freddo il processore.'
  :v===0?'Ferma: se CPU o GPU arrivano a 75 °C torna normale da sola.':v<30?'Molto lenta: se CPU o GPU arrivano a 75 °C torna normale da sola.':'';
}
function openFan(f){
 if(!f)return;const d=$('fan-sheet'),cu=(current?.fans_custom||{})[f.ctl],ready=!!current?.fans_manual_ready,enabled=current?.fans_enabled!==false;
 $('fs-name').textContent=FAN_NICE(f.name);
 $('fs-kind').textContent=/pump/i.test(f.name)?'Pompa del liquido':/cpu/i.test(f.name)?'Radiatore del processore':/system/i.test(f.name)?'Ventola del case':'Ventola';
 const cv=cu&&typeof cu==='object';
 $('fs-mode').textContent=cv?`curva sulla ${cu.src.toUpperCase()}`:cu!=null?`fissa al ${cu}%`:'segue il profilo';
 fanSheetLive(f);fanSheet.src=cv?cu.src:(/gpu/i.test(f.name)?'gpu':'cpu');fanCurveSet(cv?cu.pts.map(p=>[...p]):FAN_CURVES.bal);
 fanSheetVal(typeof cu==='number'?cu:(/pump/i.test(f.name)?60:50));fanSheetMode(cv?'curve':cu!=null?'manual':'auto');
 $('fs-ctl').hidden=!ready||!enabled||!f.ctl;$('fs-setup').hidden=ready&&enabled;
 $('fs-setup-text').textContent=!enabled?'La gestione delle ventole non è collegata: attivala da Collegamenti (serve Fan Control).'
  :current?.remote?'Per regolare ogni ventola a mano serve una conferma da amministratore, una volta sola: falla dalla app sul PC.'
  :'Per regolare ogni ventola a mano serve una conferma da amministratore, una volta sola: rifaccio i profili di Fan Control e aggiungo quello manuale.';
 const ap=$('fs-apply');ap.hidden=!enabled||(!ready&&!!current?.remote);ap.textContent=ready?'Applica':'Attiva regolazione';
 if(!d.open)d.showModal();
}
function closeFan(){const d=$('fan-sheet');if(d.open)d.close();fanSheet.f=null;}
document.querySelectorAll('#fs-modes button').forEach(b=>b.addEventListener('click',()=>fanSheetMode(b.dataset.m)));
$('fs-range').addEventListener('input',e=>{fanSheetVal(+e.target.value);if(fanSheet.mode!=='manual')fanSheetMode('manual');});
document.querySelectorAll('#fs-presets button').forEach(b=>b.addEventListener('click',()=>{fanSheetVal(+b.dataset.p);fanSheetMode('manual');}));
$('fs-close').addEventListener('click',closeFan);$('fs-cancel').addEventListener('click',closeFan);
$('fan-sheet').addEventListener('close',()=>{fanSheet.f=null;});
$('fan-sheet').addEventListener('click',e=>{if(e.target===e.currentTarget)closeFan();});   // clic fuori dalla scheda
$('fs-apply').addEventListener('click',async()=>{
 const f=fanSheet.f;if(!f)return;
 if(!current?.fans_manual_ready){closeFan();post('/api/fans/setup',{});return;}
 const percent=fanSheet.mode==='manual'?fanSheet.val:null,curve=fanSheet.mode==='curve'?{src:fanSheet.src,pts:fanSheet.pts.map(p=>[...p])}:null;closeFan();
 if(demo){current.fans_custom[f.ctl]=curve||percent;if(curve==null&&percent==null)delete current.fans_custom[f.ctl];
  notify(`✓ ${FAN_NICE(f.name)}: `+(curve?`curva sulla ${curve.src.toUpperCase()}`:percent==null?'torna al profilo':`${percent}% fisso`));return;}
 post('/api/fans/one',{id:f.ctl,percent,curve});
});
const COMP_ICON={cpu:'cpu',gpu:'gpu',board:'grid',ram:'ram',disks:'disk',cooling:'fan',rgb:'bulb',usb:'plug',monitor:'monitor',loss:'bolt'};
let donutPick=null;
function renderDonut(items,total){
 const svg=$('e-stack');if(!svg)return;const tot=items.reduce((a,i)=>a+i.watts,0)||1;let at=0;
 if(!svg._segs){svg.innerHTML='<circle class="dn-track" cx="100" cy="100" r="78" pathLength="100"/>';svg._segs=new Map();}
 const seen=new Set();
 const show=i=>{$('e-donut-sub').textContent=i?i.name:'Totale';$('e-donut-top').textContent=i?nf(i.watts/tot*100,0)+'%':Math.round(total)+' W';
  $('e-donut-w').textContent=i?`${i.source==='misurato'?'':'~'}${nf(i.watts,i.watts<10?1:0)} W`:`${items.length} voci`;};
 items.forEach(i=>{const len=i.watts/tot*100;if(len<.3){at+=len;return;}seen.add(i.key);
  let c=svg._segs.get(i.key);
  if(!c){c=document.createElementNS('http://www.w3.org/2000/svg','circle');
   ['cx','cy'].forEach(k=>c.setAttribute(k,100));c.setAttribute('r',78);c.setAttribute('pathLength',100);c.setAttribute('class','dn-seg'+(i.key==='loss'?' loss':''));
   c.style.stroke=COMP[i.key]||'#64748b';c.style.strokeDasharray='0 100';c.style.strokeDashoffset=(-at).toFixed(2);
   c.addEventListener('pointerenter',()=>{donutPick=i.key;show(c._item);svg.classList.add('picking');c.classList.add('on');});
   c.addEventListener('pointerleave',()=>{donutPick=null;show(null);svg.classList.remove('picking');c.classList.remove('on');});
   svg.append(c);svg._segs.set(i.key,c);void c.getBoundingClientRect();}
  c._item=i;c.style.strokeDasharray=`${Math.max(.1,len-.8).toFixed(2)} ${(100-len+.8).toFixed(2)}`;c.style.strokeDashoffset=(-at).toFixed(2);at+=len;});
 svg._segs.forEach((c,k)=>{if(!seen.has(k)){c.remove();svg._segs.delete(k);}});
 show(donutPick?items.find(x=>x.key===donutPick):null);
}
function renderPower(p,e){
 const fill=$('gauge-fill');
 if(!p||typeof p.total!=='number'){countUp($('g-watts'),null,()=>'—');$('e-watts').textContent='—';fill.style.strokeDasharray='0 100';}
 else{
  // Arco di 270° (75 su 100): scala fino al 60% dell'alimentatore, oltre un PC da scrivania non va quasi mai.
  const scale=Math.max(300,(p.psu_watts||750)*.6);
  fill.style.strokeDasharray=`${Math.min(75,p.total/scale*75).toFixed(1)} 100`;
  countUp($('g-watts'),p.total,v=>Math.round(v));$('g-amps').textContent=`${nf(p.amps,2)} A · ${p.voltage} V`;
  $('e-watts').textContent=Math.round(p.total);
  $('e-range').textContent=`Tra ${p.low} e ${p.high} W (±${p.margin}%)`+(p.monitor_watts?(p.monitor_on?' · monitor incluso':' · monitor spento'):' · monitor escluso');
  $('e-amps').textContent=nf(p.amps,2)+' A';$('e-volts').textContent=`a ${p.voltage} V`;
  $('e-psu').textContent=nf(p.psu_load,0)+'%';$('e-eff').textContent=`efficienza ${nf(p.efficiency*100,0)}% · ${p.psu_watts} W`;
  $('e-va').textContent=nf(p.va,0)+' VA';$('e-pf').textContent=`fattore di potenza ${nf(p.pf,2)}`;
  const measured=(p.items||[]).filter(i=>i.source==='misurato').reduce((a,i)=>a+i.watts,0);
  $('e-measured').textContent=Math.round(measured/p.total*100)+'%';
  const all=[...(p.items||[])].sort((a,b)=>b.watts-a.watts).concat([{key:'loss',name:'Perdite alimentatore',watts:p.loss,source:'calcolato',detail:`calore dell'alimentatore`}]);
  renderDonut(all,p.total);
  const list=$('e-list');if(!list._rows){list._rows=new Map();list.replaceChildren();}
  all.forEach((i,n)=>{
   const c=COMP[i.key]||'#64748b',share=i.watts/p.total*100;
   let row=list._rows.get(i.key);
   if(!row){row=el('div','brk2');row.style.setProperty('--c',c);row.style.setProperty('--i',n);
    const ico=el('span','b2-ico');ico.append(icon(COMP_ICON[i.key]||'bolt'));
    const txt=el('div','b2-txt');const name=el('b','',i.name);name.append(el('em',i.source==='misurato'?'m':'',i.source));txt.append(name,el('small','b2-d',''));
    const bar=el('div','b2-bar');bar.append(el('i'));txt.append(bar);
    const val=el('div','b2-val');val.append(el('strong'),el('small'));
    row.append(ico,txt,val);list._rows.set(i.key,row);}
   row.querySelector('.b2-d').textContent=i.detail||'';
   row.querySelector('.b2-bar i').style.width=Math.max(2,share).toFixed(1)+'%';
   row.querySelector('.b2-val strong').textContent=(i.source==='misurato'?'':'~')+nf(i.watts,i.watts<10?1:0)+' W';
   row.querySelector('.b2-val small').textContent=nf(share,0)+'%';
   list.append(row);   // riordina per consumo senza ricreare
  });
  list._rows.forEach((r,k)=>{if(!all.some(x=>x.key===k)){r.remove();list._rows.delete(k);}});
 }
 if(e){
  $('h-today').textContent=kwh(e.today_kwh);$('h-today-cost').textContent=eur(e.today_cost);
  $('h-month').textContent=kwh(e.month_kwh,1);$('h-month-cost').textContent=eur(e.month_cost);
  $('h-forecast').textContent=e.forecast_kwh?kwh(e.forecast_kwh,0):'—';$('h-forecast-cost').textContent=e.forecast_cost?eur(e.forecast_cost):'dal 2° giorno';
  $('e-today').textContent=kwh(e.today_kwh);$('e-today-cost').textContent=eur(e.today_cost);
  $('e-month').textContent=kwh(e.month_kwh,1);$('e-month-cost').textContent=eur(e.month_cost);
  $('e-forecast').textContent=e.forecast_kwh?kwh(e.forecast_kwh,0):'—';$('e-forecast-cost').textContent=e.forecast_cost?eur(e.forecast_cost):'disponibile dal secondo giorno';
 }
}
function renderPc(pc){
 $('pw-uptime').textContent=typeof pc.uptime_s==='number'?`da ${duration(pc.uptime_s)}`:'—';
 $('pw-hibernate').hidden=!pc.hibernate;
 const plan=pc.pending,box=$('pw-pending');box.hidden=!plan;
 $('pw-hero').classList.toggle('armed',!!plan);$('pw-title').textContent=plan?(plan.label||'Programmato'):'PC acceso';
 if(plan){
  $('pw-pending-title').textContent=plan.label+(plan.started?' in corso':' programmato');
  $('pw-pending-sub').textContent=plan.after_ai?(plan.idle_since?'Codex e Claude chiusi: tra meno di 2 minuti':'Quando Codex e Claude hanno finito'):`tra ${plan.seconds_left<90?plan.seconds_left+' s':duration(plan.seconds_left)}`;
 }
 const n=pc.net;
 const setStep=(id,ok)=>{$(id).classList.toggle('ok',ok===true);$(id).classList.toggle('bad',ok===false);};
 setStep('wol-net',!!n);
 $('wol-net-text').textContent=n?`${n.desc} · ${n.mac} · ${n.ip}`:'Nessuna scheda via cavo collegata: il Wi-Fi quasi mai accende un PC spento.';
 const winOk=!!n&&n.wol_magic!==false&&n.wol_shutdown!==false;setStep('wol-win',n?winOk:null);
 $('wol-win-text').textContent=!n?'—':winOk?'Attivo, anche da spento':'Da attivare (una conferma da amministratore)';
 $('wol-enable').hidden=!n||winOk||!!current?.remote;
 $('wol-phone').textContent=n?`Alternativa senza Umbrel: un'app Wake-on-LAN sul telefono collegato al Wi-Fi di casa, con MAC ${n.mac} e indirizzo ${n.broadcast}.`:'';
}

/* ---------- collegamenti ---------- */
const LINK_ICONS={rgb:'bulb',fans:'fan',sensors:'temp',gpu:'gpu',ai:'bot',tunnel:'send',autostart:'power'};
const LINK_COL={rgb:'#f472b6',fans:'#34d399',sensors:'#fbbf24',gpu:'#a78bfa',ai:'#60a5fa',tunnel:'#22d3ee',autostart:'#94a3b8'};
const LEVELS={ok:['Collegato','on'],warn:['Da completare','warn'],missing:['Mancante','err']};
const seenJobs={};
function linkAction(r,jobs){
 const job=name=>({running:jobs[name]?.state==='running'});
 if(r.install)return {label:'Installa',primary:true,...job('install-'+r.key),run:()=>post('/api/install',{key:r.key})};
 if(r.key==='fans'&&r.level==='warn')return {label:'Configura',primary:true,...job('fans-setup'),run:()=>post('/api/fans/setup',{})};
 if((r.key==='sensors'||r.key==='rgb')&&r.level==='warn')return {label:'Collega',primary:true,...job('discover'),run:()=>post('/api/discover',{})};
 if(r.key==='fans')return {label:'Apri Fan Control',run:()=>post('/api/fancontrol/open',{})};
 if(r.key==='autostart')return {label:r.level==='ok'?'Disattiva':'Attiva',run:()=>post('/api/autostart',{enabled:r.level!=='ok'})};
 return null;
}
function renderLinks(items,jobs){
 const todo=items.filter(r=>r.level!=='ok').length;const badge=$('links-badge');badge.hidden=!todo;badge.textContent=todo;
 $('more-links').textContent=todo?`${todo} da completare`:'Tutto collegato';
 $('links-refresh').disabled=jobs.discover?.state==='running';
 // Avvisa una volta sola quando un lavoro in background termina.
 Object.entries(jobs).forEach(([name,j])=>{if(j.state!=='running'&&seenJobs[name]!==undefined&&seenJobs[name]!==j.at)notify((j.state==='ok'?'✓ ':'⚠ ')+j.message,j.state!=='ok');seenJobs[name]=j.at;});
 if(!items.length)return;
 const okN=items.length-todo;$('links-count').textContent=`${okN}/${items.length}`;
 $('links-ring').style.strokeDasharray=`${(okN/items.length*100).toFixed(1)} 100`;
 $('links-title').textContent=todo?(todo===1?'1 collegamento da completare':`${todo} collegamenti da completare`):'Tutto collegato';
 $('links-hero').classList.toggle('todo',!!todo);
 const box=$('links-list');const sig=JSON.stringify([items,jobs,current?.remote]);if(box._sig===sig)return;const first=!box._sig;box._sig=sig;box.replaceChildren();box.classList.toggle('fresh',first);
 items.forEach((r,i)=>{
  const [word,cls]=LEVELS[r.level]||LEVELS.missing;
  const card=el('article','lcard '+cls);card.style.setProperty('--lc',LINK_COL[r.key]||'#38bdf8');card.style.setProperty('--i',i);
  const head=el('div','lc-head');const ico=el('span','lc-ico');ico.append(icon(LINK_ICONS[r.key]||'link'));
  const st=el('span','lc-state '+cls);st.append(el('i'),document.createTextNode(word));head.append(ico,st);
  card.append(head,el('b','lc-name',r.name),el('small','lc-detail',r.detail));
  const a=current?.remote?null:linkAction(r,jobs);
  if(a){const b=el('button','btn small '+(a.primary?'primary':'glass'),a.running?'In corso…':a.label);b.type='button';b.disabled=!!a.running;b.addEventListener('click',a.run);card.append(b);}
  box.append(card);
 });
}

/* ---------- luci ---------- */
let palette=[],paletteEditing=false;
const bright=()=>Number.parseInt($('rgb-bright').value,10);
function renderPalette(list){
 if(JSON.stringify(list)===JSON.stringify(palette))return;
 palette=list;const box=$('rgb-swatches');box.replaceChildren();
 palette.forEach(col=>{
  const b=el('button','swatch');b.type='button';b.dataset.color=col;b.style.background=col;b.title=col.toUpperCase();b.setAttribute('aria-label','Colore '+col);
  b.addEventListener('click',()=>{
   if(paletteEditing){savePalette(palette.filter(c=>c!==col),'Colore tolto');return;}
   $('rgb-color').value=col;rgbTouched=true;paintOrb(false);applyColor(col);
  });
  box.append(b);
 });
 paintOrb(current?.rgb_off);
}
async function savePalette(list,msg){
 if(demo){renderPalette(list);notify('Anteprima: '+msg.toLowerCase()+' solo qui.');return;}
 try{const r=await req('/api/rgb/palette','POST',{colors:list});renderPalette(r.palette);notify('✓ '+msg);}catch(ex){notify('⚠ '+ex.message,true);}
}
$('palette-save').addEventListener('click',()=>{
 const c=$('rgb-color').value.toLowerCase();
 if(palette.includes(c)){notify('Questo colore è già salvato.');return;}
 if(palette.length>=18){notify('Massimo 18 colori: togline uno con Modifica.',true);return;}
 savePalette([...palette,c],'Colore salvato');
});
$('palette-edit').addEventListener('click',()=>{
 paletteEditing=!paletteEditing;$('rgb-swatches').classList.toggle('editing',paletteEditing);
 $('palette-edit').classList.toggle('active',paletteEditing);$('palette-edit').textContent=paletteEditing?'Fatto':'Modifica';
 if(paletteEditing)notify('Tocca un colore per toglierlo.');
});
function paintOrb(off){
 const c=$('rgb-color').value;const orb=$('rgb-orb');orb.style.setProperty('--orb',c);orb.style.opacity=off?1:(.35+.65*bright()/100);orb.classList.toggle('off',!!off&&!rgbTouched);
 $('rgb-hex').textContent=c.toUpperCase();
 const hero=$('rgb-hero');hero.style.setProperty('--hc',off&&!rgbTouched?'#475569':c);hero.classList.toggle('off',!!off&&!rgbTouched);
 $('rgb-bright').style.setProperty('--rc',c);$('rgb-color').closest('.color-input').style.setProperty('--rc',c);
 document.querySelectorAll('.swatch').forEach(s=>s.classList.toggle('selected',s.dataset.color===c));
}
async function applyColor(color,device){
 if(demo){notify('Anteprima: comando non attivo.');return;}
 try{const r=await req('/api/rgb/color','POST',{color,brightness:bright(),device:device||null});notify('✓ '+r.message);rgbTouched=false;if(!device)loadRgbDevices();await refresh();}
 catch(ex){notify('⚠ '+ex.message,true);}
}
async function loadRgbDevices(){
 const box=$('rgb-devices');
 if(demo){box.replaceChildren(el('p','muted','Anteprima: dispositivi non disponibili.'));return;}
 if((!key&&!tgInit)||!current?.rgb_enabled){box.replaceChildren(el('p','muted','OpenRGB non collegato: vedi Collegamenti.'));return;}
 try{
  const data=await req('/api/rgb/devices');box.replaceChildren();
  data.devices.forEach((d,i)=>{
   const row=el('div','rgb-dev2');const col=d.color||$('rgb-color').value;row.style.setProperty('--dc',col);row.style.setProperty('--i',i);
   const strip=el('div','led-strip');for(let k=0;k<Math.max(4,Math.min(16,d.leds||6));k++){const dot=el('i');dot.style.setProperty('--k',k);strip.append(dot);}
   const t=el('div','rd-txt');t.append(el('b','',d.name),el('small','',d.leds?`circa ${d.leds} LED`:'periferica'),strip);
   const sw=el('label','rd-color');const c=el('input');c.type='color';c.value=col;c.setAttribute('aria-label','Colore '+d.name);sw.append(c);
   c.addEventListener('input',()=>row.style.setProperty('--dc',c.value));
   const b=el('button','icon-btn rd-apply');b.type='button';b.title='Applica a '+d.name;b.setAttribute('aria-label',b.title);b.append(icon('check'));
   b.addEventListener('click',()=>applyColor(c.value,d.key));
   row.append(t,sw,b);box.append(row);
  });
  (current?.rgb_excluded||[]).forEach(n=>box.append(el('p','fineprint',`${n}: lasciata al firmware della scheda madre (effetto del BIOS), non si spegne con AI ECO.`)));
 }catch(ex){box.replaceChildren(el('p','muted','Dispositivi non disponibili: '+ex.message));}
}
$('rgb-color').addEventListener('input',()=>{rgbTouched=true;paintOrb(false);});
$('rgb-bright').addEventListener('input',()=>{rgbTouched=true;$('rgb-bright-val').textContent=$('rgb-bright').value+'%';paintOrb(false);});
$('rgb-apply-all').addEventListener('click',()=>applyColor($('rgb-color').value));
$('rgb-reload').addEventListener('click',loadRgbDevices);

/* ---------- accensione ---------- */
const POWER_ASK={
 shutdown:['Spegnere il PC?','Codex, Claude e i programmi aperti verranno chiusi. Hai 30 secondi per annullare.','Spegni'],
 restart:['Riavviare il PC?','I programmi aperti verranno chiusi. Hai 30 secondi per annullare.','Riavvia'],
 sleep:['Mettere in sospensione?','Il PC consuma 2–5 W e si risveglia con mouse, tastiera o Wake-on-LAN.','Sospendi'],
 hibernate:['Ibernare il PC?','Salva tutto su disco e si spegne del tutto.','Iberna'],
};
async function powerAction(kind,minutes=0,afterAi=false){
 if(demo){notify('Anteprima: comando non attivo.');return;}
 if(kind==='cancel'){post('/api/power',{action:'cancel'});return;}
 if(!minutes&&!afterAi&&POWER_ASK[kind]){const [t,x,y]=POWER_ASK[kind];if(!await ask(t,x,{danger:kind!=='sleep',ico:{sleep:'moon',restart:'restart',hibernate:'disk'}[kind]||'power',yes:y}))return;}
 post('/api/power',{action:kind,minutes,after_ai:afterAi});
}
document.querySelectorAll('[data-power]').forEach(b=>b.addEventListener('click',()=>powerAction(b.dataset.power)));
document.querySelectorAll('#sched-kind button').forEach(b=>b.addEventListener('click',()=>{schedKind=b.dataset.kind;document.querySelectorAll('#sched-kind button').forEach(x=>x.classList.toggle('selected',x===b));}));
document.querySelectorAll('#sched-chips button').forEach(b=>b.addEventListener('click',()=>powerAction(schedKind,Number(b.dataset.minutes))));
$('sched-ai').addEventListener('click',()=>powerAction(schedKind,0,true));
$('wol-enable').addEventListener('click',()=>post('/api/power/wol',{}));
$('relay-show').addEventListener('click',async()=>{
 if(demo){notify('Anteprima: non disponibile.');return;}
 try{const r=await req('/api/power/relay');$('relay-text').textContent=r.compose;$('relay-box').hidden=false;}catch(ex){notify('⚠ '+ex.message,true);}
});
$('relay-copy').addEventListener('click',async()=>{
 try{await navigator.clipboard.writeText($('relay-text').textContent);notify('Configurazione copiata.');}catch(e){notify('Seleziona il testo e copialo a mano.',true);}
});

/* ---------- azioni ---------- */
async function refresh(){
 if(demo){render(statusDemo);return;}if(!key&&!tgInit)return;
 try{render(await req('/api/status'));}
 catch(ex){hideSplash();if(tgInit)notify('⚠ '+ex.message,true);$('conn-dot').classList.add('off');$('conn-text').textContent='PC non raggiungibile';}
}
async function action(name,src){
 if(['eco','normal','gaming'].includes(name))return modeSwitch(name,src);
 if(busy)return;if(demo){notify('Anteprima: i controlli non sono collegati al PC.');return;}
 if(!key&&!tgInit){loginScreen(true);return;}
 const map={eco:['/api/mode',{mode:'eco'}],normal:['/api/mode',{mode:'normal'}],gaming:['/api/mode',{mode:'gaming'}],screen:['/api/screen',{}],
  'rgb-eco':['/api/rgb',{profile:'eco'}],'rgb-normal':['/api/rgb',{profile:'normal'}]};
 ['off','eco','normal','max'].forEach(l=>map['fans-'+l]=['/api/fans',{profile:l}]);
 if(!map[name])return;
 if(name==='fans-off'){
  const pick=await choose('Spegnere tutte le ventole?','Case, radiatore e scheda video si fermano. La pompa AIO la tengo al minimo? Se CPU o GPU arrivano a 75 °C tornano normali da sole.',
   [{value:'pump',label:'Sì, pompa al minimo',cls:'primary'},{value:'all',label:'No, spegni anche la pompa',cls:'danger'},{value:'no',label:'Annulla'}],{danger:true});
  if(pick!=='pump'&&pick!=='all')return;
  map['fans-off']=['/api/fans',{profile:'off',keep_pump:pick==='pump'}];
 }
 if(name==='screen'&&!await ask('Spegnere il monitor?','Il PC continua a lavorare; il monitor si riaccende muovendo il mouse.',{danger:false,ico:'monitor',yes:'Spegni monitor'}))return;
 busy=true;try{const r=await req(map[name][0],'POST',map[name][1]);notify('✓ '+r.message);await refresh();}catch(ex){notify('⚠ '+ex.message,true);}finally{busy=false;}
}
async function toggleAuto(){
 if(demo){notify('Interruttore dimostrativo.');return;}if(!current||busy)return;
 busy=true;try{const r=await req('/api/auto','POST',{enabled:!current.auto_enabled});notify('✓ '+r.message);await refresh();}catch(ex){notify('⚠ '+ex.message,true);}finally{busy=false;}
}
const FIELDS={'cfg-delay':'restore_delay_seconds','cfg-cpu-alert':'cpu_temp_alert','cfg-gpu-alert':'gpu_temp_alert',
 'cfg-price':'energy_price_cents','cfg-psu':'psu_watts','cfg-monitor-w':'monitor_watts','cfg-extra':'extra_watts'};
async function loadSettings(){
 if((!key&&!tgInit)||demo)return;
 try{
  const s=await req('/api/settings');
  Object.entries(FIELDS).forEach(([id,f])=>$(id).value=s[f]);$('cfg-psu-class').value=s.psu_class;$('cfg-gaming-fans').value=s.gaming_fans;$('cfg-anim').value=s.anim_style||'liquid';$('cfg-alerts').checked=s.alerts_enabled;
 }catch(ex){notify('Impostazioni: '+ex.message,true);}
}
async function loadEvents(){
 if((!key&&!tgInit)||demo)return;
 try{
  const data=await req('/api/events');const box=$('events-list');box.replaceChildren();
  if(!data.events?.length){box.append(el('p','muted','Nessun evento dall’avvio del programma.'));return;}
  data.events.slice(0,30).forEach(item=>{const row=el('div','event');row.append(el('time','',(item.at||'—').replace('T',' ').slice(5,16)),el('span','',item.message||''));box.append(row);});
 }catch(ex){notify('Registro: '+ex.message,true);}
}
$('tg-pair-start').addEventListener('click',async()=>{
 if(demo){notify('Anteprima: configurazione non disponibile.');return;}
 const token=$('bot-token').value.trim();if(!token){notify('Inserisci il token fornito da @BotFather.',true);return;}
 $('tg-pair-start').disabled=true;
 try{
  const r=await req('/api/telegram/pair','POST',{token});
  $('tg-pair-name').textContent='@'+r.bot_username;$('tg-pair-command').textContent='/pair '+r.code;$('tg-pair-code').hidden=false;$('bot-token').value='';
  notify('Bot verificato. Invia il codice su Telegram.');
 }catch(ex){notify('Telegram: '+ex.message,true);}finally{$('tg-pair-start').disabled=false;}
});
$('tg-pair-copy').addEventListener('click',async()=>{
 try{await navigator.clipboard.writeText($('tg-pair-command').textContent);notify('Codice copiato.');}catch(e){notify('Seleziona il codice e copialo su Telegram.');}
});
$('login-form').addEventListener('submit',async e=>{
 e.preventDefault();const pass=$('key-input').value.trim();if(pass.length<28){$('login-error').textContent='Chiave troppo corta.';return;}
 key=pass;try{const s=await req('/api/status');sessionStorage.setItem('pc_eco_key',key);$('login-error').textContent='';$('key-input').value='';loginScreen(false);render(s);}catch(ex){$('login-error').textContent=ex.message;}
});
$('refresh-events').addEventListener('click',loadEvents);
/* ---------- ottimizza ---------- */
const bytes=b=>{if(typeof b!=='number')return '—';const u=['B','KB','MB','GB','TB'];let i=0;while(b>=1024&&i<4){b/=1024;i++;}return (i<2?Math.round(b):b.toFixed(1).replace('.',','))+' '+u[i];};
let optData=null,procData=null,procSort='by_cpu',optTab='clean',autoScanned=false;const optSeen={};
const OPT_JOBS=['optimize-scan','optimize-clean','trim','optimize-large','optimize-health','optimize-net'];
const QUICK_STEPS=['File temporanei','Cache dei giochi','Anteprime delle immagini','Rapporti di errore','Cache dei browser','Cache DNS','Nuova analisi'];
const CLEAN_ICO={temp:'clean',shader:'game',thumbs:'palette',crash:'x',browser:'link',wintemp:'grid',wupdate:'refresh',recycle:'disk'};
const KIND_ICO=k=>/^(mp4|mkv|avi|mov|wmv|webm)$/.test(k)?['🎬','#a78bfa']:/^(zip|rar|7z|tar|gz)$/.test(k)?['📦','#fbbf24']:/^(iso|vmdk|vhd|vhdx|img|ova)$/.test(k)?['💽','#38bdf8']:/^(exe|msi)$/.test(k)?['⚙️','#fb923c']:['📄','#94a3b8'];
let cleanSteps=null,cleanEst=0;
function quickProgress(running,result,state){
 // Mentre la pulizia lavora: vortice con i passi e il contatore; alla fine spunta e spazio liberato.
 if(running){if(!cfx.box)cleanStart(cleanSteps||QUICK_STEPS,cleanEst);return;}
 cleanFinish(result||'',state!=='error');
}
function watchOptimizeJobs(jobs){
 // A fine analisi/pulizia/ricerca ricarica la pagina (se aperta) e aggiorna la scheda in Home.
 const scan=jobs['optimize-scan']?.state==='running',clean=jobs['optimize-clean']?.state==='running';
 $('opt-scan').disabled=scan||clean;$('opt-quick').disabled=scan||clean;$('opt-quick-label').textContent=clean?'Ottimizzo…':'Ottimizza ora';
 $('opt-health').classList.toggle('scanning',scan||clean);$('opt-run').disabled=clean||!selectedKeys().length;
 [['optimize-large','opt-large-scan','Cerco…','Cerca'],['optimize-health','opt-health-btn','Controllo…','Controlla'],['optimize-net','opt-net-btn','Provo…','Prova la rete']].forEach(([j,id,on,off])=>{
  const b=$(id),r=jobs[j]?.state==='running';b.disabled=r;b.lastChild.textContent=r?on:off;});
 if(optSeen.quick&&!clean&&jobs['optimize-clean'])quickProgress(false,jobs['optimize-clean'].message,jobs['optimize-clean'].state);
 if(clean&&optSeen.quick)quickProgress(true);
 let reload=false;
 OPT_JOBS.forEach(n=>{const j=jobs[n];if(!j)return;if(j.state!=='running'&&optSeen[n]!==undefined&&optSeen[n]!==j.at)reload=true;optSeen[n]=j.at;});
 if(!clean)optSeen.quick=false;
 if(reload)loadOptimize(true);
}
function selectedKeys(){return [...document.querySelectorAll('#opt-clean input:checked')].map(c=>c.value);}
function updateSelected(){
 const items=optData?.report?.items||[];const keys=selectedKeys();
 const tot=items.filter(i=>keys.includes(i.key)).reduce((a,i)=>a+i.bytes,0);
 $('opt-selected').textContent=keys.length?`Selezionati: ${bytes(tot)}`:'Niente selezionato';$('opt-run').disabled=!keys.length;
}
const DEMO_OPT={report:{total:6.1e9,at:'2026-11-04T08:30:00',items:[
  {key:'temp',name:'File temporanei',desc:'Cartella Temp',bytes:1.2e9,files:3496,admin:false,permanent:false,note:''},
  {key:'shader',name:'Cache shader dei giochi',desc:'DirectX, NVIDIA e AMD',bytes:2.3e9,files:390,admin:false,permanent:false,note:''},
  {key:'browser',name:'Cache dei browser',desc:'Edge, Chrome, Brave, Opera',bytes:4.1e8,files:2100,admin:false,permanent:false,note:'chiudi i browser'},
  {key:'wupdate',name:'Aggiornamenti di Windows scaricati',desc:'Già installati',bytes:8e8,files:120,admin:true,permanent:false,note:''},
  {key:'recycle',name:'Cestino',desc:'Svuota il cestino',bytes:2.4e9,files:42,admin:false,permanent:true,note:''}]},
 disks:[{drive:'C:',total:5e11,used:4.7e11,free:3e10,percent:94},{drive:'D:',total:1e12,used:3e11,free:7e11,percent:30}],
 memory:{percent:51,used:1.6e10,total:3.2e10,top:[]},
 startup:[{id:'a',name:'Discord',scope:'utente',enabled:true,admin:false},{id:'b',name:'Steam',scope:'utente',enabled:false,admin:false},{id:'c',name:'OneDrive',scope:'utente',enabled:true,admin:false}],
 history:[{at:Date.now()/1000-3600,freed:2.1e9,kind:'rapida'},{at:Date.now()/1000-86400*6,freed:3.4e9,kind:'automatica'}],freed_total:1.24e10,auto:true,auto_last:Date.now()/1000-86400*6,auto_next:Date.now()/1000+86400,
 large:{files:[{path:'C:/x/a.vmdk',name:'Debian 10.x 64-bit.vmdk',folder:'C:\\Users\\samue\\Documents\\Virtual Machines',bytes:1.6e10,mtime:1720000000,kind:'vmdk'},
  {path:'C:/x/b.mp4',name:'Clip partita.mp4',folder:'C:\\Users\\samue\\Videos',bytes:2.2e9,mtime:1760000000,kind:'mp4'}],total:1.82e10,count:2,at:Date.now()/1000},
 health:{at:Date.now()/1000,disks:[{name:'Sabrent',media:'SSD',bus:'NVMe',health:'Healthy',size:1.02e12,ok:true,temp:41,wear:3},{name:'WDC WD10EARS',media:'Disco',bus:'SATA',health:'Healthy',size:1e12,ok:true}]},
 net:{at:Date.now()/1000,router:{host:'192.168.0.1',ms:1,loss:0},internet:{host:'1.1.1.1',ms:21,loss:0},google:{host:'8.8.8.8',ms:22,loss:0},dns_ms:35,quality:'ottima'},
 net_auto:true,net_history:Array.from({length:72},(_,i)=>{const at=Date.now()/1000-(71-i)*7200,hr=new Date(at*1000).getHours(),eve=hr>=20&&hr<=23;
  return {at,ms:i===40?null:Math.round(18+Math.sin(i*1.7)*3+(eve?14:0)+(i===55?95:0)),router:1,dns:30,q:i===40?'offline':'ottima',auto:true};})};
const DEMO_PROC={cpu_total:14,ram:{used:1.6e10,total:3.2e10,percent:51},count:312,
 by_cpu:[{name:'chrome.exe',cpu:6.2,bytes:1.9e9,count:24,closable:true},{name:'Discord.exe',cpu:2.1,bytes:6e8,count:6,closable:true},{name:'svchost.exe',cpu:1.3,bytes:1.6e9,count:80,closable:false}],
 by_ram:[{name:'ChatGPT.exe',cpu:.4,bytes:2.6e9,count:9,closable:true},{name:'chrome.exe',cpu:6.2,bytes:1.9e9,count:24,closable:true},{name:'svchost.exe',cpu:1.3,bytes:1.6e9,count:80,closable:false}]};
async function loadOptimize(quiet=false){
 if(demo){renderOptimize(DEMO_OPT);return;}
 try{
  const d=await req('/api/optimize');renderOptimize(d);
  // Prima apertura senza analisi: la fa da sola (solo lettura, 10-25 s).
  if(!d.report&&!autoScanned&&current?.jobs?.['optimize-scan']?.state!=='running'){autoScanned=true;req('/api/optimize/scan','POST',{}).catch(()=>{});}
 }catch(ex){if(!quiet)notify('Ottimizza: '+ex.message,true);}
}
function healthScore(d){
 // Punteggio semplice e spiegabile: ogni problema toglie punti e diventa un consiglio.
 let score=100;const tips=[];const rep=d.report;const c=(d.disks||[]).find(x=>/^C/i.test(x.drive))||(d.disks||[])[0];
 if(rep){const gb=rep.total/2**30;if(gb>=0.5){score-=Math.min(25,Math.round(gb*4));tips.push(['clean',`${bytes(rep.total)} di file inutili da pulire`,'clean']);}}
 else tips.push(['refresh','Sto misurando i file inutili…','clean']);
 if(c){const free=c.free/c.total;if(free<0.1){score-=30;tips.push(['disk',`Disco ${c.drive} quasi pieno: ${bytes(c.free)} liberi`,'large']);}
  else if(free<0.2){score-=15;tips.push(['disk',`Disco ${c.drive} con poco spazio (${bytes(c.free)} liberi)`,'large']);}}
 const on=(d.startup||[]).filter(i=>i.enabled).length;if(on>8){score-=Math.min(20,(on-8)*2);tips.push(['power',`${on} programmi partono con Windows`,'startup']);}
 const ram=d.memory?.percent||0;if(ram>80){score-=15;tips.push(['ram',`RAM al ${Math.round(ram)}%: chiudi qualche programma`,'apps']);}else if(ram>65)score-=6;
 const bad=(d.health?.disks||[]).filter(x=>!x.ok);if(bad.length){score-=25;tips.unshift(['disk',`Disco da controllare: ${bad[0].name}`,'disks']);}
 const up=current?.pc?.uptime_s||0;if(up>7*86400){score-=5;tips.push(['restart',`Acceso da ${Math.floor(up/86400)} giorni: un riavvio rinfresca Windows`,'']);}
 if(d.net?.quality==='lenta'){score-=5;tips.push(['wave','Rete lenta: guarda la scheda Rete','net']);}
 return {score:Math.max(0,Math.min(100,score)),tips:tips.slice(0,4),c,on,ram};
}
function optTabGo(name){const b=document.querySelector(`#opt-tabs [data-panel="${name}"]`);if(b)b.click();}
function renderOptimize(d){
 optData=d;
 const h=healthScore(d);
 countUp($('opt-score'),h.score,v=>Math.round(v));$('opt-score-ring').style.strokeDasharray=`${h.score} 100`;
 scoreTicks(h.score);
 $('opt-score-label').textContent=h.score>=85?'Ottimo':h.score>=65?'Buono':'Da migliorare';
 $('opt-health').className='health'+(h.score<65?' low':h.score<85?' mid':'')+($('opt-health').classList.contains('scanning')?' scanning':'');
 swapIn($('opt-title'),!d.report?'Controllo il PC…':h.score>=85?'Il PC è in ottima forma':h.score>=65?'Va bene, ma si può fare meglio':'Il PC ha bisogno di una pulita');
 $('opt-tips').replaceChildren(...(h.tips.length?h.tips.map(([ic,t,go])=>{const li=el('li');li.append(icon(ic),document.createTextNode(t));
  if(go){li.classList.add('link');li.addEventListener('click',()=>optTabGo(go));}return li;}):[(()=>{const li=el('li','ok');li.append(icon('check'),document.createTextNode('Tutto in ordine'));return li;})()]));
 countUp($('opt-freed'),d.freed_total||0,v=>bytes(v));
 const last=(d.history||[])[0];$('opt-auto-lbl').textContent=d.auto?'Pulizia automatica attiva':'Pulizia automatica spenta';$('opt-freed-sub').textContent=last?`Ultima ${ago(last.at)}`:'Mai fatta';
 renderChecks(d,h);
 $('tb-clean').textContent=d.report?bytes(d.report.total):'';$('tb-startup').textContent=h.on||'';$('tb-large').textContent=d.large?.count||'';
 renderClean(d);renderStartup(d.startup||[]);renderDisks(d);renderLarge(d.large);renderNet(d.net);renderNetHist(d);renderOptHistory(d);
 renderZones();
}
function scoreTicks(score){
 // 48 tacche intorno all'anello del punteggio: si accendono fino al valore, come un quadrante.
 const svg=$('opt-health').querySelector('svg');let g=svg.querySelector('.ticks');
 if(!g){g=document.createElementNS('http://www.w3.org/2000/svg','g');g.setAttribute('class','ticks');
  for(let i=0;i<48;i++){const a=i/48*Math.PI*2,l=document.createElementNS('http://www.w3.org/2000/svg','line');
   l.setAttribute('x1',60+Math.cos(a)*57.5);l.setAttribute('y1',60+Math.sin(a)*57.5);l.setAttribute('x2',60+Math.cos(a)*(i%4?59.5:61));l.setAttribute('y2',60+Math.sin(a)*(i%4?59.5:61));
   l.style.transitionDelay=(i*12)+'ms';g.append(l);}
  svg.append(g);}
 [...g.children].forEach((l,i)=>l.classList.toggle('on',i<Math.round(score/100*48)));
}
function renderChecks(d,h){
 // Controllo salute: sei voci con stato colorato; toccandole si apre la scheda giusta.
 const rep=d.report,c=h.c,free=c?c.free/c.total:null,hd=d.health?.disks,net=d.net,GB=2**30;
 const items=[
  ['clean','File inutili',rep?bytes(rep.total):'…',!rep?'none':rep.total<.5*GB?'ok':rep.total<3*GB?'warn':'bad',rep?(rep.total<.5*GB?'Già pulito':'Si possono pulire'):'Analisi in corso','clean'],
  ['disk','Disco C',c?bytes(c.free)+' liberi':'—',free==null?'none':free>=.2?'ok':free>=.1?'warn':'bad',free==null?'—':`${Math.round(free*100)}% libero su ${bytes(c.total)}`,'large'],
  ['power','Avvio di Windows',(d.startup||[]).length?`${h.on} app`:'—',!(d.startup||[]).length?'none':h.on<=8?'ok':h.on<=14?'warn':'bad',h.on<=8?'Avvio leggero':'Si può alleggerire','startup'],
  ['ram','Memoria',d.memory?Math.round(h.ram)+'% in uso':'—',!d.memory?'none':h.ram<=65?'ok':h.ram<=80?'warn':'bad',d.memory?.total?`${bytes(d.memory.used)} di ${bytes(d.memory.total)}`:'—','apps'],
  ['check','Salute dischi',hd?`${hd.filter(x=>x.ok).length} su ${hd.length} ok`:'Non controllata',hd?(hd.every(x=>x.ok)?'ok':'bad'):'none',hd?(hd.every(x=>x.ok)?'Tutti in salute':'Un disco va controllato'):'Tocca per controllare','disks'],
  ['wave','Rete',net?.internet?.ms!=null?net.internet.ms+' ms':'Non provata',!net?'none':['ottima','buona'].includes(net.quality)?'ok':net.quality==='lenta'?'warn':'bad',net?`Connessione ${net.quality}`:'Tocca per provare','net']];
 const LBL={ok:'OK',warn:'Attenzione',bad:'Da sistemare',none:'Da fare'};
 $('opt-side-free').textContent=rep?bytes(rep.total):'…';
 const box=$('opt-checks');box.replaceChildren();
 const fill={clean:rep?Math.min(100,rep.total/(5*GB)*100):0,large:c?100-Math.round(free*100):0,startup:Math.min(100,(h.on||0)/20*100),apps:h.ram||0,
  disks:hd?hd.filter(x=>x.ok).length/hd.length*100:0,net:net?.internet?.ms!=null?Math.min(100,net.internet.ms):0};
 items.forEach(([ic,name,val,s,sub,go])=>{const b=el('button','chk s-'+s);b.type='button';const i=el('span','chk-ico');const ring=ringSvg('cr');
  ring.querySelector('.gr-f').style.strokeDasharray=`${(fill[go]||0).toFixed(1)} 100`;i.append(ring,icon(ic));
  const t=el('div');t.append(el('small','',name),el('b','',val),el('span','',sub));b.append(i,t,el('em','',LBL[s]));
  b.addEventListener('click',()=>{optTabGo(go);$('opt-tabs').scrollIntoView({block:'start',behavior:'smooth'});});box.append(b);});
 const todo=items.filter(x=>x[3]==='warn'||x[3]==='bad').length;
 $('opt-lead').textContent=!rep?'Analizzo file, dischi, avvio e memoria…':(todo?`${todo} ${todo>1?'controlli':'controllo'} su ${items.length} da sistemare`:'Tutti i controlli sono a posto')+` · analisi delle ${rep.at.slice(11,16)}`;
}
function ago2(ts){const d=(ts-Date.now()/1000)/86400;return d<=0?'a breve':d<1?'oggi':d<2?'domani':`tra ${Math.round(d)} giorni`;}
function renderClean(d){
 const box=$('opt-clean');const rep=d.report;if(!rep)return;
 box.replaceChildren();
 $('opt-clean-sub').textContent=`${bytes(rep.total)} recuperabili · analisi delle ${rep.at.slice(11,16)}`;
 const max=Math.max(1,...rep.items.map(i=>i.bytes));
 rep.items.forEach((i,k)=>{
  const row=el('label','clean-row'+(i.bytes?'':' empty'));row.style.setProperty('--i',k);const cb=el('input');cb.type='checkbox';cb.value=i.key;
  const blocked=(i.admin&&current?.remote)||i.note.startsWith('chiudi');
  cb.checked=i.bytes>0&&!i.permanent&&!i.admin&&!blocked;cb.disabled=!i.bytes||blocked;cb.addEventListener('change',updateSelected);
  const ico=el('span','clean-ico');ico.append(icon(CLEAN_ICO[i.key]||'clean'));
  const t=el('div');const name=el('b','',i.name);
  if(i.permanent)name.append(el('em','pill warn','definitivo'));if(i.admin)name.append(el('em','pill admin','🛡 admin'));
  const bar=el('div','bar mini');const f=el('span');f.style.width=(i.bytes/max*100)+'%';bar.append(f);
  t.append(name,el('small','',i.note||i.desc),bar);row.append(cb,ico,t,el('strong','',i.bytes?bytes(i.bytes):'pulito'));box.append(row);
 });
 updateSelected();
 $('opt-auto').setAttribute('aria-checked',d.auto?'true':'false');
 $('opt-auto-sub').textContent=d.auto?(d.auto_next?`Prossima ${ago2(d.auto_next)}: solo file temporanei e cache`:'Parte alla prossima occasione tranquilla'):'Una volta a settimana, quando il PC è tranquillo';
}
function renderOptHistory(d){
 const box=$('opt-history');const list=d.history||[];box.replaceChildren();
 if(!list.length){box.append(el('p','muted','Ancora nessuna pulizia.'));return;}
 const KIND={rapida:['bolt','Ottimizza ora'],manuale:['clean','Pulizia scelta'],automatica:['clock','Automatica']};
 list.slice(0,8).forEach(h=>{const r=el('div','oh-row');const k=KIND[h.kind]||KIND.manuale;const ic=el('span','oh-ico');ic.append(icon(k[0]));
  const t=el('div');t.append(el('b','',k[1]),el('small','',new Date(h.at*1000).toLocaleString('it-IT',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})));
  r.append(ic,t,el('strong','',h.freed?'+'+bytes(h.freed):'già pulito'));box.append(r);});
}
function renderStartup(items){
 const st=$('opt-startup');const keep=st.scrollTop;st.replaceChildren();
 requestAnimationFrame(()=>{st.scrollTop=keep;});
 $('opt-startup-sub').textContent=`${items.filter(i=>i.enabled).length} attivi su ${items.length}: meno programmi = Windows parte prima`;
 items.forEach(i=>{
  const row=el('div','startup-row');const ic=el('span','app-ico',initials(i.name));ic.style.setProperty('--h',hue(i.name));
  const t=el('div');t.append(el('b','',i.name),el('small','',i.scope+(i.admin?' · serve admin':'')));
  const tg=el('button','toggle');tg.type='button';tg.setAttribute('role','switch');tg.setAttribute('aria-checked',i.enabled?'true':'false');tg.setAttribute('aria-label','Avvio di '+i.name);tg.append(el('span'));
  tg.disabled=i.admin&&!!current?.remote;
  tg.addEventListener('click',async e=>{e.stopPropagation();if(demo){notify('Anteprima: comando non attivo.');return;}
   if(tg.dataset.busy)return;tg.dataset.busy='1';tg.disabled=true;const want=!i.enabled;
   tg.setAttribute('aria-checked',want?'true':'false');   // si vede subito sulla riga premuta
   try{const r=await req('/api/optimize/startup','POST',{id:i.id,enabled:want});i.enabled=want;notify('✓ '+r.message);
    $('opt-startup-sub').textContent=`${items.filter(x=>x.enabled).length} attivi su ${items.length}: meno programmi = Windows parte prima`;}
   catch(ex){tg.setAttribute('aria-checked',i.enabled?'true':'false');notify('⚠ '+ex.message,true);}
   finally{delete tg.dataset.busy;tg.disabled=i.admin&&!!current?.remote;}});
  row.dataset.id=i.id;row.append(ic,t,tg);st.append(row);
 });
}
function renderDisks(d){
 const dk=$('opt-disks');dk.replaceChildren();
 (d.disks||[]).forEach(x=>{const c=el('div','disk'+(x.free<0.1*x.total?' low':''));const top=el('div','disk-top');top.append(el('b','',x.drive),el('small','',`${bytes(x.free)} liberi su ${bytes(x.total)}`));
  const bar=el('div','bar');const f=el('span');f.style.width=x.percent+'%';bar.append(f);c.append(top,bar);dk.append(c);});
 const hl=$('opt-health-list');const hd=d.health;if(!hd)return;hl.replaceChildren();
 $('opt-health-sub').textContent=`Controllato ${ago(hd.at)} alle ${new Date(hd.at*1000).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})}`;
 hd.disks.forEach(x=>{const r=el('div','hd-row'+(x.ok?'':' bad'));const ic=el('span','hd-ico');ic.append(icon(x.ok?'check':'x'));
  const t=el('div');t.append(el('b','',x.name),el('small','',[x.media,x.bus,x.size?bytes(x.size):''].filter(Boolean).join(' · ')));
  const chips=el('div','hd-chips');chips.append(el('span',x.ok?'ok':'bad',x.ok?'In salute':x.health||'Da controllare'));
  if(x.temp!=null)chips.append(el('span','',x.temp+' °C'));if(x.wear!=null)chips.append(el('span','',`usura ${x.wear}%`));
  r.append(ic,t,chips);hl.append(r);});
}
function renderLarge(L){
 const box=$('opt-large');if(!L)return;box.replaceChildren();
 $('opt-large-sub').textContent=L.count?`${L.count} file oltre 300 MB · ${bytes(L.total)} in tutto · ricerca ${ago(L.at)}`+(L.partial?' (parziale)':''):'Nessun file oltre 300 MB nelle cartelle personali';
 const max=Math.max(1,...L.files.map(f=>f.bytes));const local=!current?.remote&&!demo;
 L.files.forEach((f,k)=>{
  const r=el('div','lf-row');r.style.setProperty('--i',k);const [emo,col]=KIND_ICO(f.kind);const ic=el('span','lf-ico',emo);ic.style.setProperty('--c',col);
  const t=el('div');t.append(el('b','',f.name),el('small','',f.folder.replace(/^C:\\Users\\[^\\]+\\/i,'').replace(/\\/g,' › ')+' · '+new Date(f.mtime*1000).toLocaleDateString('it-IT',{month:'short',year:'numeric'})));
  const bar=el('div','bar mini');const fl=el('span');fl.style.width=(f.bytes/max*100)+'%';bar.append(fl);t.append(bar);
  const acts=el('div','lf-acts');acts.append(el('strong','',bytes(f.bytes)));
  if(local){
   const o=el('button','icon-btn small');o.type='button';o.title='Apri la cartella';o.setAttribute('aria-label',o.title);o.append(icon('link'));
   o.addEventListener('click',()=>post('/api/optimize/large/reveal',{path:f.path}));
   const del=el('button','icon-btn small danger');del.type='button';del.title='Sposta nel Cestino';del.setAttribute('aria-label',del.title);del.append(icon('x'));
   del.addEventListener('click',async()=>{if(!await ask('Spostare nel Cestino?',`${f.name} (${bytes(f.bytes)}). Potrai recuperarlo dal Cestino finché non lo svuoti.`,{ico:'clean',yes:'Sposta nel Cestino'}))return;
    try{const res=await req('/api/optimize/large/recycle','POST',{path:f.path});notify('✓ '+res.message);r.classList.add('gone');setTimeout(()=>loadOptimize(true),400);}catch(ex){notify('⚠ '+ex.message,true);}});
   acts.append(o,del);
  }
  r.append(ic,t,acts);box.append(r);
 });
}
let netRunning=false,netTimers=[],netStart=0;
function netScene(){
 // Durante la prova: PC → Router → Internet, con i pacchetti che viaggiano e ogni tappa che risponde.
 const box=$('opt-net');box.replaceChildren();netTimers.forEach(clearTimeout);netTimers=[];
 const sc=el('div','net-scene');
 const node=(cls,ic,label)=>{const n=el('div','nn '+cls);const c=el('span','nn-core');c.append(icon(ic));n.append(el('i','nn-ping'),c,el('small','',label),el('b','nn-ms','…'));return n;};
 const link=()=>{const l=el('div','nlink');for(let i=0;i<4;i++){const p=el('i');p.style.setProperty('--d',(i*.32)+'s');l.append(p);}return l;};
 const pc=node('pc','monitor','Il tuo PC'),rt=node('router','wave','Router'),web=node('web','link','Internet'),dns=node('dns','search','DNS');
 pc.classList.add('on');pc.querySelector('.nn-ms').textContent='pronto';
 sc.append(pc,link(),rt,link(),web,link(),dns);
 const st=el('p','net-status','Misuro quanto ci mette il PC a raggiungere il router…');
 box.append(sc,st);
 [[rt,'Router raggiunto: ora misuro la strada verso internet…'],[web,'Internet raggiunto: misuro quanto ci mette a trovare un sito…'],[dns,'Quasi fatto: preparo il risultato…']].forEach(([n,t],i)=>netTimers.push(setTimeout(()=>{
  n.classList.add('on');n.querySelector('.nn-ms').textContent='risponde';sc.querySelectorAll('.nlink')[i].classList.add('on');st.textContent=t;},900+i*1100)));
}
let netIsl=null;
function islandNet(){
 // Isola in alto durante la prova: onde radar, catena PC → Router → Internet → DNS che si accende, poi il risultato.
 const st=animStyle();if(calm.matches||st==='off')return null;
 document.querySelectorAll('.isl').forEach(x=>x.remove());
 const is=el('div','isl ni');const rad=el('div','ni-rad');rad.append(el('i'),el('i'),el('i'),icon('wave'));
 const okI=icon('check');okI.classList.add('ni-ok');rad.append(okI);
 const mid=el('div','ni-mid');const t1=el('b','','Prova della rete');const tBox=el('div','ni-sub');let t2=el('small','','Raggiungo il router di casa…');tBox.append(t2);
 const chain=el('div','ni-chain');const line=el('div','ni-line');const lf=el('i');line.append(lf,el('b'));
 const nodes=['PC','Router','Internet','DNS'].map((l,i)=>{const n=el('span','ni-node'+(i?'':' on'));n.append(el('i'),el('em','',l));return n;});
 chain.append(line,...nodes);mid.append(t1,tBox,chain);is.append(rad,mid);document.body.append(is);
 const W=islandW(410),H=100;
 is.animate([{opacity:0,transform:'translate(-50%,-14px) scale(.9)'},{opacity:1,transform:'translate(-50%,0)'}],{duration:320,easing:EASE.out,fill:'forwards'});
 is.animate([{width:'130px',height:'40px'},{width:'130px',height:'40px',offset:.25},{width:W+'px',height:H+'px'}],{duration:760,easing:EASE.spring,fill:'forwards'});
 rad.animate([{opacity:0,transform:'scale(.3)'},{opacity:0,offset:.35},{opacity:1,transform:'none'}],{duration:760,easing:EASE.spring,fill:'forwards'});
 mid.animate([{opacity:0,transform:'translateX(-10px)'},{opacity:0,offset:.45},{opacity:1,transform:'none'}],{duration:760,easing:EASE.out,fill:'forwards'});
 const say=text=>{const old=t2;t2=el('small','',text);tBox.append(t2);
  old.animate([{transform:'none',opacity:1},{transform:'translateY(-14px)',opacity:0}],{duration:300,easing:EASE.io,fill:'forwards'}).finished.then(()=>old.remove()).catch(()=>{});
  t2.animate([{transform:'translateY(14px)',opacity:0},{transform:'none',opacity:1}],{duration:420,easing:EASE.spring});};
 const reach=k=>{nodes.forEach((n,i)=>n.classList.toggle('on',i<=k));lf.style.width=(k/3*100)+'%';};
 const timers=[[1,'Router raggiunto · misuro la strada verso internet…'],[2,'Internet raggiunto · quanto ci mette a trovare un sito…'],[3,'Quasi fatto · preparo il risultato…']]
  .map(([k,t],i)=>setTimeout(()=>{reach(k);say(t);},900+i*1100));
 let closed=false;
 const close=async()=>{if(closed)return;closed=true;timers.forEach(clearTimeout);if(netIsl===h)netIsl=null;
  [rad,mid].forEach(x=>x.animate([{opacity:1},{opacity:0}],{duration:160,fill:'forwards'}));const r=is.getBoundingClientRect();
  await is.animate([{width:r.width+'px',height:r.height+'px'},{width:'130px',height:'40px'}],{duration:420,easing:EASE.spring,fill:'forwards'}).finished.catch(()=>{});
  await is.animate([{opacity:1},{opacity:0,transform:'translate(-50%,-12px) scale(.9)'}],{duration:240,fill:'forwards'}).finished.catch(()=>{});is.remove();};
 const safety=setTimeout(close,40000);
 const h={close,finish(n){
  timers.forEach(clearTimeout);clearTimeout(safety);reach(3);
  const q={ottima:['Ottima','q-ok'],buona:['Buona','q-mid'],lenta:['Lenta','q-low'],offline:['Non connesso','q-bad']}[n?.quality]||['Fatto','q-mid'];
  is.classList.add('done',q[1]);const ms=n?.internet?.ms;
  t1.textContent=ms!=null?`${Math.round(ms)} ms · ${q[0]}`:q[0];
  say(n?.router?.ms!=null?`Router ${Math.round(n.router.ms)} ms · DNS ${n.dns_ms!=null?Math.round(n.dns_ms)+' ms':'—'}`:'Internet non raggiungibile');
  rad.animate([{transform:'scale(1)'},{transform:'scale(1.15)'},{transform:'scale(1)'}],{duration:600,easing:EASE.spring});
  is.addEventListener('click',close);setTimeout(close,4200);}};
 netIsl=h;return h;
}
function netRun(){
 netRunning=true;netStart=Date.now()/1000-2;netScene();netIsl?.close();islandNet();
 if(demo){netTimers.push(setTimeout(()=>{netRunning=true;renderNet({...DEMO_OPT.net,at:Date.now()/1000});},4300));return;}
 post('/api/optimize/net',{});
}
function renderNetHist(d){
 // Andamento: tempo verso internet di ogni prova (manuali e automatiche), con fascia del "solito" e punti rossi se cade.
 const h=(d.net_history||[]).slice(-72),svg=$('nh-chart'),ok=h.filter(r=>r.ms!=null);
 $('net-auto').setAttribute('aria-checked',d.net_auto?'true':'false');
 $('nh-auto-txt').textContent=d.net_auto?'Prova ogni ora · avviso se peggiora':'Prova automatica spenta';
 $('net-hist').classList.toggle('empty',h.length<2);
 if(h.length<2){svg.replaceChildren();$('nh-stats').replaceChildren();$('nh-axis').replaceChildren();
  $('nh-sub').textContent=d.net_auto?'Le prove automatiche arrivano una volta all\'ora: qui vedrai come va la rete nei giorni.':'Ogni prova finisce qui.';return;}
 const vals=ok.map(r=>r.ms).sort((a,b)=>a-b),med=vals[Math.floor(vals.length/2)]??0,max=Math.max(40,...vals)*1.15,W=600,H=150;
 const t0=h[0].at,t1=h[h.length-1].at||t0+1,X=t=>(t-t0)/Math.max(1,t1-t0)*W,Y=v=>H-6-(v/max)*(H-16);
 const ns='http://www.w3.org/2000/svg',mk=(t,a)=>{const e=document.createElementNS(ns,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
 // punti tondi anche con il grafico stirato: linea lunga zero con estremi arrotondati
 const dot=(x,y,c)=>mk('line',{x1:x,x2:x,y1:y,y2:y,class:'nh-dot '+c});
 svg.replaceChildren();
 const defs=mk('defs',{});defs.innerHTML='<linearGradient id="nh-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#38bdf8" stop-opacity=".35"/><stop offset="1" stop-color="#38bdf8" stop-opacity="0"/></linearGradient>';svg.append(defs);
 svg.append(mk('line',{x1:0,x2:W,y1:Y(med),y2:Y(med),class:'nh-med'}));
 let path='',started=false;h.forEach(r=>{if(r.ms==null){started=false;return;}path+=(started?'L':'M')+X(r.at).toFixed(1)+','+Y(r.ms).toFixed(1)+' ';started=true;});
 const segs=path.trim().split(/(?=M)/);
 segs.forEach(sg=>{const pts=sg.slice(1).trim().split(' L').map(p=>p.split(',').map(Number));if(!pts.length||!pts[0].length)return;
  svg.append(mk('path',{d:sg+` L${pts[pts.length-1][0]},${H} L${pts[0][0]},${H} Z`,class:'nh-area'}));svg.append(mk('path',{d:sg,class:'nh-line'}));});
 h.forEach(r=>{if(r.ms==null)svg.append(mk('rect',{x:X(r.at)-2,y:0,width:4,height:H,class:'nh-off'}));
  else if(r.ms>=Math.max(80,med*3))svg.append(dot(X(r.at),Y(r.ms),'nh-bad'));});
 const last=ok[ok.length-1];if(last)svg.append(dot(X(last.at),Y(last.ms),'nh-last-o'),dot(X(last.at),Y(last.ms),'nh-last'));
 const off=h.length-ok.length,avg=ok.length?Math.round(ok.reduce((a,r)=>a+r.ms,0)/ok.length):null;
 const st=[['Di solito',med+' ms'],['Media',avg!=null?avg+' ms':'—'],['Peggiore',vals.length?vals[vals.length-1]+' ms':'—'],['Senza rete',off?`${off} ${off>1?'volte':'volta'}`:'mai']];
 $('nh-stats').replaceChildren(...st.map(([k,v])=>{const c=el('div','nh-st');c.append(el('small','',k),el('b','',v));return c;}));
 $('nh-sub').textContent=`${h.length} prove dal ${new Date(t0*1000).toLocaleDateString('it-IT',{day:'numeric',month:'short'})} · la linea tratteggiata è il tuo solito`;
 const fmt=t=>{const dt=new Date(t*1000),days=(t1-t0)/86400;return days>1.5?dt.toLocaleDateString('it-IT',{weekday:'short',day:'numeric'}):dt.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});};
 $('nh-axis').replaceChildren(...[t0,(t0+t1)/2,t1].map(t=>el('span','',fmt(t))));
}
function latPos(ms){return ms==null?1:Math.min(1,Math.sqrt(ms/150));}
function renderNet(n){
 const box=$('opt-net');if(!n)return;
 if(netRunning&&!(n.at>netStart))return;   // prova in corso: si aspetta il risultato nuovo
 const animate=netRunning;netRunning=false;netTimers.forEach(clearTimeout);netTimers=[];box.replaceChildren();
 if(animate)netIsl?.finish(n);
 const Q={ottima:['Ottima','ok'],buona:['Buona','mid'],lenta:['Lenta','low'],offline:['Non connesso','low']}[n.quality]||['—',''];
 $('opt-net-sub').textContent=`Prova ${ago(n.at)} alle ${new Date(n.at*1000).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})}`;
 // tachimetro: la lancetta va dal verde (pochi ms) al rosso (tanti ms)
 const wrap=el('div','net-result '+Q[1]);const sp=el('div','speedo');
 const NS='http://www.w3.org/2000/svg',mk=(t,a)=>{const e=document.createElementNS(NS,t);Object.entries(a).forEach(([k,v])=>e.setAttribute(k,v));return e;};
 const svg=mk('svg',{viewBox:'0 0 200 116','aria-hidden':'true'});
 const defs=mk('defs',{});const gr=mk('linearGradient',{id:'speedo-g',x1:'0',y1:'0',x2:'1',y2:'0'});
 [['0','#34d399'],['.55','#fbbf24'],['1','#f87171']].forEach(([o,c])=>gr.append(mk('stop',{offset:o,'stop-color':c})));defs.append(gr);svg.append(defs);
 svg.append(mk('path',{d:'M20 100 A80 80 0 0 1 180 100',class:'sp-track'}),mk('path',{d:'M20 100 A80 80 0 0 1 180 100',class:'sp-arc',pathLength:'100'}));
 for(let i=0;i<=20;i++){const a=Math.PI*(1-i/20),r1=i%5?66:62;svg.append(mk('line',{x1:100+Math.cos(a)*r1,y1:100-Math.sin(a)*r1,x2:100+Math.cos(a)*70,y2:100-Math.sin(a)*70,class:'sp-tick'}));}
 const needle=mk('g',{class:'sp-needle'});needle.append(mk('line',{x1:100,y1:100,x2:100,y2:34}),mk('circle',{cx:100,cy:100,r:6}));svg.append(needle);
 const ms=n.internet?.ms;const deg=-90+180*latPos(ms);
 needle.style.transform=`rotate(${animate?-90:deg}deg)`;
 const mid=el('div','sp-mid');const val=el('b','',ms!=null?'0':'—');mid.append(val,el('small','',ms!=null?'ms verso internet':'internet non raggiungibile'),el('span','sp-q',Q[0]));
 sp.append(svg,mid);wrap.append(sp);
 const hops=el('div','net-hops');
 [['wave','Router di casa',n.router,10],['link','Internet',n.internet,60],['search','Google',n.google,60],['clock','DNS',{ms:n.dns_ms,host:'tempo per trovare un sito'},80]].forEach(([ic,label,x,good],i)=>{
  if(!x)return;const c=el('div','hop');c.style.setProperty('--i',i);const ii=el('span','hop-ico');ii.append(icon(ic));
  const t=el('div');const b=el('b','',x.ms!=null?'0 ms':'—');t.append(el('small','',label),b,el('span','',x.loss?`${x.loss}% pacchetti persi`:(x.host||'')));
  const bar=el('div','bar');const f=el('span');f.className=x.ms==null||x.ms>good*1.5?'bad':x.ms>good*.6?'mid':'';bar.append(f);t.append(bar);c.append(ii,t);hops.append(c);
  const w=(x.ms==null?100:Math.min(100,x.ms/(good*2)*100));
  if(animate){setTimeout(()=>{f.style.width=w+'%';if(x.ms!=null){b._v=0;countUp(b,x.ms,v=>Math.round(v)+' ms');}},250+i*120);}
  else{f.style.width=w+'%';if(x.ms!=null)b.textContent=x.ms+' ms';}
 });
 wrap.append(hops);box.append(wrap);
 if(animate){requestAnimationFrame(()=>requestAnimationFrame(()=>{needle.style.transform=`rotate(${deg}deg)`;}));
  if(ms!=null){val._v=0;countUp(val,ms,v=>Math.round(v));}wrap.classList.add('fresh');}
 else if(ms!=null)val.textContent=ms;
}
async function loadProcs(){
 if(demo){renderProcs(DEMO_PROC);return;}
 try{renderProcs(await req('/api/optimize/processes'));}catch(ex){}
}
function renderProcs(d){
 procData=d;const box=$('opt-apps');box.replaceChildren();
 $('opt-cpu-now').textContent=pct(d.cpu_total);setBar('opt-cpu-bar',d.cpu_total);
 $('opt-ram-now').textContent=`${pct(d.ram.percent)} · ${bytes(d.ram.used)}`;setBar('opt-ram-bar',d.ram.percent);
 $('opt-apps-sub').textContent=`${d.count} processi aperti · aggiornato ogni 4 secondi`;
 const list=d[procSort]||[];const max=Math.max(.1,...list.map(a=>procSort==='by_cpu'?a.cpu:a.bytes));
 list.forEach(a=>{
  const r=el('div','proc-row');const ic=el('span','app-ico',initials(a.name.replace(/\.exe$/i,'')));ic.style.setProperty('--h',hue(a.name));
  const t=el('div');t.append(el('b','',a.name.replace(/\.exe$/i,'')),el('small','',`${a.count>1?a.count+' processi · ':''}CPU ${nf(a.cpu,1)}% · ${bytes(a.bytes)}`));
  const bar=el('div','bar mini');const f=el('span');f.style.width=((procSort==='by_cpu'?a.cpu:a.bytes)/max*100)+'%';bar.append(f);t.append(bar);
  const v=el('strong','',procSort==='by_cpu'?nf(a.cpu,1)+'%':bytes(a.bytes));
  const btn=el('button','btn small'+(a.closable?'':' ghost'),a.closable?'Chiudi':'Sistema');btn.type='button';btn.disabled=!a.closable;
  btn.addEventListener('click',async()=>{if(!await ask(`Chiudere ${a.name.replace(/\.exe$/i,'')}?`,'Come premere la X: se c\'è lavoro non salvato il programma te lo chiede.',{ico:'x',yes:'Chiudi'}))return;
   if(demo){notify('Anteprima: comando non attivo.');return;}
   try{const res=await req('/api/optimize/close','POST',{name:a.name});notify('✓ '+res.message);setTimeout(loadProcs,800);}catch(ex){notify('⚠ '+ex.message,true);}});
  r.append(ic,t,v,btn);box.append(r);
 });
}
setInterval(()=>{if(!document.hidden&&optTab==='apps'&&$('page-optimize').classList.contains('active'))loadProcs();},4000);
function renderZones(){
 // Schede delle due zone in Home: lo stato in breve e un pulsante per l'azione principale.
 const d=optData;
 if(d){const h=healthScore(d);countUp($('zc-opt-score'),h.score,v=>Math.round(v));$('zc-opt-ring').style.strokeDasharray=`${h.score} 100`;
  $('zc-opt').classList.toggle('low',h.score<65);$('zc-opt').classList.toggle('mid',h.score>=65&&h.score<85);
  $('zc-opt-title').textContent=h.score>=85?'PC in ottima forma':h.score>=65?'Si può migliorare':'Da sistemare';
  $('zc-opt-sub').textContent=d.report?`${bytes(d.report.total)} da liberare · ${h.on} app all’avvio`:'Analisi in corso…';}
 const g=gameData,b=current?.boost||{};
 const ses=b.session,run=b.running,last=(g?.games||[]).find(x=>!x.hidden&&x.last);
 const title=b.active&&(ses?.game||run)?(ses?.game||run.name):last?last.name:'I tuoi giochi';
 $('zc-gaming-title').textContent=title;
 $('zc-gaming-sub').textContent=b.active?(ses?`In gioco da ${duration(ses.elapsed)}`:'Gaming attivo'):last?`Ultima partita ${ago(last.last)} · ${(g.games||[]).filter(x=>!x.hidden).length} giochi`:'Libreria, Gaming automatico e partite';
 $('zc-gaming').classList.toggle('live',!!b.active);
 const btn=$('zc-gaming-btn');btn.querySelector('span').textContent=b.active?'Apri':last?'Gioca':'Apri';btn.dataset.gid=!b.active&&last?last.id:'';
 const gid=(b.active&&(ses?.gid||run?.id))||last?.id||'';const art=$('zc-gaming-art');
 if(art.dataset.gid!==gid){art.dataset.gid=gid;art.style.backgroundImage='';art.style.setProperty('--h',hue(gid||'x'));
  if(gid.startsWith('steam-'))coverUrl(gid,'hero').then(u=>{if(u&&art.dataset.gid===gid)art.style.backgroundImage=`url("${u}")`;});}
}
document.querySelectorAll('#opt-tabs button').forEach(b=>b.addEventListener('click',()=>{
 optTab=b.dataset.panel;
 document.querySelectorAll('#opt-tabs button').forEach(x=>x.classList.toggle('selected',x===b));
 document.querySelectorAll('.opt-panel').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.panel);
 if(optTab==='apps')loadProcs();
 inkTabs($('opt-tabs'));
 b.scrollIntoView({block:'nearest',inline:'center',behavior:'smooth'});
}));
document.querySelectorAll('.ostat[data-go]').forEach(b=>b.addEventListener('click',()=>{optTabGo(b.dataset.go);$('opt-tabs').scrollIntoView({block:'start',behavior:'smooth'});}));
document.querySelectorAll('#apps-sort button').forEach(b=>b.addEventListener('click',()=>{procSort=b.dataset.sort;
 document.querySelectorAll('#apps-sort button').forEach(x=>x.classList.toggle('selected',x===b));if(procData)renderProcs(procData);}));
$('opt-scan').addEventListener('click',()=>post('/api/optimize/scan',{}));
async function quickOptimize(){
 const est=optData?.report?.items?.filter(i=>['temp','shader','thumbs','crash','browser'].includes(i.key)).reduce((a,i)=>a+i.bytes,0);
 if(!await ask('Ottimizzare adesso?',`Pulisco file temporanei, cache dei giochi, anteprime, rapporti di errore e cache dei browser chiusi${est?' (circa '+bytes(est)+')':''}, poi svuoto la cache DNS. Cestino e documenti non vengono toccati.`,{danger:false,ico:'clean',yes:'Ottimizza'}))return;
 cleanSteps=QUICK_STEPS;cleanEst=est||0;
 if(demo){quickProgress(true);setTimeout(()=>quickProgress(false,'Ottimizzazione fatta: liberati 3,9 GB · DNS svuotata','ok'),5000);return;}
 optSeen.quick=true;quickProgress(true);post('/api/optimize/quick',{});
}
$('opt-quick').addEventListener('click',quickOptimize);
$('opt-run').addEventListener('click',async()=>{
 const keys=selectedKeys();if(!keys.length)return;
 const perm=keys.includes('recycle');
 if(!await ask('Pulire adesso?',`${$('opt-selected').textContent}.`+(perm?' Il cestino verrà svuotato: quei file non si potranno più recuperare.':' Sono solo file temporanei e cache.'),{danger:perm,ico:'clean',yes:'Pulisci'}))return;
 const items=(optData?.report?.items||[]).filter(i=>keys.includes(i.key));
 cleanSteps=items.map(i=>i.name).concat('Nuova analisi');cleanEst=items.reduce((a,i)=>a+i.bytes,0);
 if(demo){quickProgress(true);setTimeout(()=>quickProgress(false,'Pulizia: liberati '+bytes(cleanEst),'ok'),4000);return;}
 optSeen.quick=true;quickProgress(true);post('/api/optimize/clean',{keys});
});
$('opt-auto').addEventListener('click',()=>post('/api/optimize/auto',{enabled:$('opt-auto').getAttribute('aria-checked')!=='true'}).then(()=>loadOptimize(true)));
$('opt-large-scan').addEventListener('click',()=>post('/api/optimize/large/scan',{}));
$('opt-health-btn').addEventListener('click',()=>post('/api/optimize/health',{}));
$('opt-net-btn').addEventListener('click',netRun);
$('net-auto').addEventListener('click',()=>{const on=$('net-auto').getAttribute('aria-checked')!=='true';
 if(demo){DEMO_OPT.net_auto=on;renderNetHist(DEMO_OPT);return;}post('/api/optimize/net/auto',{enabled:on}).then(()=>loadOptimize(true));});
$('opt-dns').addEventListener('click',()=>post('/api/optimize/dns',{}));
$('opt-trim').addEventListener('click',()=>post('/api/optimize/trim',{}));
$('zc-opt-btn').addEventListener('click',e=>{e.stopPropagation();navigate('optimize');setTimeout(quickOptimize,350);});
$('zc-gaming-btn').addEventListener('click',e=>{e.stopPropagation();const gid=$('zc-gaming-btn').dataset.gid;const g=(gameData?.games||[]).find(x=>x.id===gid);if(g)launchGame(g);else navigate('gaming');});
document.querySelectorAll('.zone-card').forEach(c=>c.addEventListener('keydown',e=>{if(e.key==='Enter')navigate(c.dataset.view);}));
/* ---------- animazioni ---------- */
function inkTabs(box){
 if(!box||!box.offsetWidth)return;const sel=box.querySelector('button.selected');if(!sel)return;
 let ink=box.querySelector('.tab-ink');
 if(!ink){ink=el('span','tab-ink');box.prepend(ink);box.classList.add('has-ink');ink.style.transition='none';}
 ink.style.width=sel.offsetWidth+'px';ink.style.transform=`translateX(${sel.offsetLeft}px)`;
 if(ink.style.transition==='none'){void ink.offsetWidth;setTimeout(()=>ink.style.transition='',50);}
}
addEventListener('resize',()=>document.querySelectorAll('.page.active .tabs').forEach(inkTabs));
function syncTelegram(){
 // Tasto Indietro di Telegram fuori dalla Home e barra in alto nel colore della sezione.
 if(!tgApp)return;
 try{curView==='home'?tgApp.BackButton.hide():tgApp.BackButton.show();}catch(e){}
 try{tgApp.setHeaderColor({gaming:'#1a0d1c',optimize:'#0a1517'}[curView]||'#0b0e14');}catch(e){}
}
document.addEventListener('click',e=>{
 if(!tgApp)return;const b=e.target.closest?.('button,.zone-card,a');if(!b)return;
 try{tgApp.HapticFeedback.impactOccurred(b.classList.contains('primary')||b.classList.contains('mode-opt')?'medium':'light');}catch(e){}
},{passive:true});
// Barra laterale ridotta a sole icone (ricordata su questo dispositivo).
document.querySelectorAll('.rail-nav button').forEach(b=>{b.dataset.label=b.textContent.trim();b.setAttribute('aria-label',b.dataset.label);});
function setZone(){
 // Il colore di sfondo, titoli e menu segue la sezione (in Home segue la modalità).
 const z=curView==='gaming'||curView==='optimize'?curView:curView==='home'&&current?.mode&&current.mode!=='normal'?current.mode:'';
 if(document.body.dataset.zone!==z)document.body.dataset.zone=z;
}
function spark(valId,data,max,color){
 // Mini-grafico dal vivo sul fondo dei riquadri della Home.
 const tile=$(valId)?.closest('.tile');if(!tile)return;
 let svg=tile.querySelector('.spark');
 if(!svg){svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','spark');svg.setAttribute('viewBox','0 0 100 40');
  svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-hidden','true');tile.prepend(svg);}
 const pts=data.length>1?data:[0,0];const top=max||Math.max(1,...pts)*1.2;
 const line=pts.map((v,i)=>[i*100/(pts.length-1),38-Math.min(1,Math.max(0,v/top))*34]).map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
 const id='sg-'+valId;
 svg.innerHTML=`<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".3"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>`+
  `<path d="${line} L100,40 L0,40 Z" fill="url(#${id})"/><path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" stroke-opacity=".75" vector-effect="non-scaling-stroke"/>`;
}
// Luce che segue il mouse sulle carte (solo mouse, niente su telefono).
document.addEventListener('pointermove',e=>{
 if(e.pointerType!=='mouse')return;const c=e.target.closest?.('.card,.tile,.gstat,.ostat,.pwr');if(!c)return;
 const r=c.getBoundingClientRect();c.style.setProperty('--mx',(e.clientX-r.left)+'px');c.style.setProperty('--my',(e.clientY-r.top)+'px');
},{passive:true});

const calm=matchMedia('(prefers-reduced-motion: reduce)');
let lastMode=null,fxQuiet=0;
function countUp(node,value,fmt){
 // Il numero scorre dal valore precedente al nuovo (niente salti secchi ogni 4 secondi).
 if(typeof value!=='number'||!Number.isFinite(value)){node._v=undefined;node.textContent=fmt(value);return;}
 const from=typeof node._v==='number'?node._v:(calm.matches?value:0);node._v=value;
 cancelAnimationFrame(node._raf);
 if(calm.matches||Math.abs(from-value)<0.5){node.textContent=fmt(value);return;}
 const t0=performance.now(),dur=from===0?900:600;
 const step=t=>{const k=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-k,3);node.textContent=fmt(from+(value-from)*e);if(k<1)node._raf=requestAnimationFrame(step);};
 node._raf=requestAnimationFrame(step);
}
function swapIn(node,text){if(node.textContent===text)return;node.textContent=text;if(calm.matches)return;node.classList.remove('swap');void node.offsetWidth;node.classList.add('swap');}
function modeFx(mode){
 if(lastMode&&mode&&lastMode!==mode&&Date.now()>fxQuiet)
  modeSceneOpen(mode,null,{auto:true,sub:mode==='gaming'&&current?.boost?.running?.name?'Si gioca a '+current.boost.running.name:''});
 lastMode=mode;
}
function particles(){
 const box=$('game-particles');if(!box||box.childElementCount)return;
 const cols=['#ec4899','#a78bfa','#22d3ee','#f472b6'];
 for(let i=0;i<12;i++){const p=el('span');const s=2+Math.random()*3;
  p.style.cssText=`left:${Math.random()*100}%;--s:${s}px;--c:${cols[i%4]};--d:${6+Math.random()*8}s;--w:${-Math.random()*12}s;--dx:${(Math.random()-.5)*120}px`;box.append(p);}
}
function tilt(card){
 card.addEventListener('pointermove',e=>{
  if(e.pointerType!=='mouse'||calm.matches)return;
  const r=card.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
  card.classList.add('tilting');
  card.style.setProperty('--ry',((x-.5)*6).toFixed(2)+'deg');card.style.setProperty('--rx',((.5-y)*5).toFixed(2)+'deg');
  card.style.setProperty('--mx',(x*100).toFixed(1)+'%');card.style.setProperty('--my',(y*100).toFixed(1)+'%');
 });
 card.addEventListener('pointerleave',()=>{card.classList.remove('tilting');card.style.setProperty('--rx','0deg');card.style.setProperty('--ry','0deg');});
}
/* ---------- scene: Liquido o Discreto (scelta in Impostazioni → Animazioni) ---------- */
const MODE_FX={eco:{t:'AI ECO',s:'Turbo spento e tutto a risparmio: l’AI continua a lavorare',i:'leaf'},normal:{t:'Normale',s:'Piano energetico di Windows',i:'bolt'},gaming:{t:'Gaming',s:'Massime prestazioni',i:'game'}};
const NOTE_LABEL=[[/^energia/i,'Energia'],[/^luci gaming/i,'Luci'],[/^rgb/i,'Luci'],[/^ventole/i,'Ventole'],[/^gaming boost/i,'Gaming Boost'],[/^integrazione non applicata/i,'Errore']];
const LQ_COL={eco:['#047857','#34d399'],normal:['#1d4ed8','#60a5fa'],gaming:['#be185d','#a855f7'],clean:['#0e7490','#22d3ee']};
const EASE={spring:'cubic-bezier(.2,.9,.25,1.12)',out:'cubic-bezier(.16,1,.3,1)',io:'cubic-bezier(.65,0,.35,1)',drain:'cubic-bezier(.5,0,.75,0)'};
let modeScene=null;
function animStyle(){const s=current?.anim_style;return ['liquid','discreet','off'].includes(s)?s:'liquid';}
function sceneOrigin(src){const r=src?.getBoundingClientRect?.();return r&&r.width?[r.left+r.width/2,r.top+r.height/2]:[innerWidth/2,innerHeight/2];}
function noteLabels(message,ok){
 const seen=[];String(message||'').split(' · ').map(t=>t.trim()).filter(Boolean).forEach(t=>{
  const lab=(NOTE_LABEL.find(([re])=>re.test(t))||[0,''])[1];if(!lab||seen.some(x=>x.l===lab))return;
  seen.push({l:lab,t,bad:!ok||lab==='Errore'||/non applicat|non trovato|errore/i.test(t)});});
 return seen;
}
function parseBytes(t){const m=String(t).match(/liberati\s+([\d.,]+)\s*(B|KB|MB|GB|TB)/i);if(!m)return null;
 return parseFloat(m[1].replace(/\./g,'').replace(',','.'))*1024**['B','KB','MB','GB','TB'].indexOf(m[2].toUpperCase());}
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const WAVE=(c)=>`<svg class="lq-wave" viewBox="0 0 400 24" preserveAspectRatio="none"><path fill="${c}" d="M0 12 Q25 0 50 12 T100 12 T150 12 T200 12 T250 12 T300 12 T350 12 T400 12 V24 H0Z"/></svg>`;
function ensureGoo(){
 if(document.getElementById('nexar-goo'))return;
 const s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('width','0');s.setAttribute('height','0');s.style.position='absolute';
 s.innerHTML='<defs><filter id="nexar-goo"><feGaussianBlur in="SourceGraphic" stdDeviation="14" result="b"/><feColorMatrix in="b" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 24 -10"/></filter></defs>';
 document.body.append(s);
}

/* ===== Liquido: il colore si spande dal pulsante, riempie lo schermo e poi scola via ===== */
function liquidScene(kind,src,{title,sub,auto,img}){
 ensureGoo();
 const [c1,c2]=LQ_COL[kind]||LQ_COL.normal,[x,y]=sceneOrigin(src),W=innerWidth,H=innerHeight,R=Math.hypot(W,H);
 const box=el('div','lq');box.style.setProperty('--c1',c1);box.style.setProperty('--c2',c2);
 const goo=el('div','lq-goo');const fill=el('div','lq-fill');fill.innerHTML=WAVE(c2);
 if(img)fill.style.setProperty('--img',`url("${img}")`),fill.classList.add('img');
 const text=el('div','lq-text');const ttl=el('b','',title);const sb=el('small','',sub||'');const notes=el('div','lq-notes');text.append(ttl,sb,notes);
 box.append(goo,fill,text);document.body.append(box);
 for(let i=0;i<7;i++){const b=el('i');const s=70+Math.random()*40;
  b.style.cssText=`left:${x-s/2+(Math.random()-.5)*36}px;top:${y-s/2+(Math.random()-.5)*24}px;width:${s}px;height:${s}px`;goo.append(b);
  b.animate([{transform:'scale(0)'},{transform:`translate(${(Math.random()-.5)*W*.7}px,${(Math.random()-.5)*H*.7}px) scale(${R/s*(.6+Math.random()*.3)})`}],
   {duration:950+i*90,delay:i*55,easing:EASE.out,fill:'forwards'});}
 // quando il colore ha coperto tutto, al posto delle gocce (pesanti da disegnare) resta un fondo pieno
 fill.animate([{opacity:0},{opacity:1}],{duration:260,delay:620,fill:'forwards'}).finished.then(()=>goo.remove()).catch(()=>{});
 ttl.animate([{opacity:0,transform:'scale(.92) translateY(10px)'},{opacity:1,transform:'none'}],{duration:520,delay:600,easing:EASE.spring,fill:'forwards'});
 sb.animate([{opacity:0},{opacity:.88}],{duration:400,delay:720,fill:'forwards'});
 let closed=false;
 const close=async()=>{if(closed)return;closed=true;if(modeScene===h)modeScene=null;
  text.animate([{opacity:1},{opacity:0,transform:'translateY(-12px)'}],{duration:240,fill:'forwards'});
  await fill.animate([{transform:'translateY(0)'},{transform:`translateY(${H+40}px)`}],{duration:820,delay:120,easing:EASE.drain,fill:'forwards'}).finished.catch(()=>{});
  box.remove();};
 const h={box,close,
  notes(list){notes.replaceChildren();list.forEach((n,i)=>{const c=el('span',n.bad?'bad':'',n.l);c.title=n.t||'';notes.append(c);
   c.animate([{opacity:0,transform:'translateY(8px) scale(.9)'},{opacity:1,transform:'none'}],{duration:380,delay:i*110,easing:EASE.spring,fill:'forwards'});});},
  done(message,ok=true){const list=noteLabels(message,ok);if(!ok&&!list.length)list.push({l:String(message).slice(0,60),bad:true});this.notes(list);
   if(!ok)box.classList.add('fail');setTimeout(close,ok?1400+list.length*110:2800);}};
 box.addEventListener('click',close);
 if(auto){h.notes([{l:'Attivata automaticamente'}]);setTimeout(close,1900);}
 return h;
}
function liquidClean(steps,est){
 const box=el('div','lqc');const g=el('div','lqc-glass');const liq=el('div','lqc-liquid');liq.innerHTML=WAVE('#22d3ee');
 for(let i=0;i<7;i++){const b=el('i','lqc-bub');b.style.left=(8+i*13)+'%';b.style.animationDelay=(i*.27)+'s';liq.append(b);}
 const check=document.createElementNS('http://www.w3.org/2000/svg','svg');check.setAttribute('class','lqc-check');check.setAttribute('viewBox','0 0 24 24');
 check.innerHTML='<path d="m5 12.5 4.5 4.5L19 7.5" pathLength="1"/>';
 g.append(liq,check);
 const cnt=el('b','lqc-count','0 B');const lab=el('small','lqc-label','liberati');const step=el('span','lqc-step','');
 const btn=el('button','lqc-btn','Continua in background');btn.type='button';
 const wrap=el('div','lqc-wrap');wrap.append(g,cnt,lab,step,btn);box.append(el('div','lqc-dim'),wrap);document.body.append(box);
 g.animate([{opacity:0,transform:'translateY(30px) scale(.9)'},{opacity:1,transform:'none'}],{duration:560,easing:EASE.spring,fill:'forwards'});
 const t0=performance.now();let k=-1;const timers=[];
 timers.push(setInterval(()=>{const t=(performance.now()-t0)/1000,p=t/(t+5)*.92;liq.style.height=(86-p*86)+'%';cnt.textContent=est?bytes(est*p):Math.round(p*100)+'%';
  const n=Math.min(steps.length-1,Math.floor(t/.9));if(n!==k){k=n;step.textContent=steps[n];step.animate([{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'none'}],{duration:300,easing:EASE.out});}},60));
 let closed=false;
 const close=async()=>{if(closed)return;closed=true;timers.forEach(clearInterval);
  await wrap.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(20px) scale(.95)'}],{duration:380,easing:EASE.io,fill:'forwards'}).finished.catch(()=>{});box.remove();};
 btn.addEventListener('click',e=>{e.stopPropagation();close();});
 return {box,close,finish(message,ok=true){
  timers.forEach(clearInterval);
  liq.animate([{height:liq.style.height},{height:ok?'0%':liq.style.height}],{duration:700,easing:EASE.out,fill:'forwards'});
  box.classList.add(ok?'done':'fail');
  const freed=parseBytes(message);lab.textContent=ok?'liberati':'pulizia non riuscita';
  if(ok&&freed!=null){cnt._v=undefined;countUp(cnt,freed,v=>bytes(v));}else if(!ok)cnt.textContent='—';
  const note=String(message||'').replace(/^.*?liberati\s+[\d.,]+\s*\w+\s*/i,'').replace(/^[·.\s]+/,'');
  step.textContent=ok?(note?'Fatto · '+note:'Pulizia completata'):String(message).slice(0,120);
  g.animate([{boxShadow:'0 0 0 0 rgba(52,211,153,.7)'},{boxShadow:'0 0 0 28px rgba(52,211,153,0)'}],{duration:800,delay:500});
  btn.textContent='Fatto';box.addEventListener('click',close);setTimeout(close,5000);}};
}

/* ===== Discreto: un'isola nera in alto si allarga con lo stato, il pulsante si riempie di colore ===== */
function island(color,iconName){
 document.querySelectorAll('.isl').forEach(x=>x.remove());
 const is=el('div','isl');is.style.setProperty('--c',color);
 const ic=icon(iconName);const txt=el('div','isl-txt');const t1=el('b');const t2=el('small');txt.append(t1,t2);
 const spin=el('i','isl-spin');const ok=el('i','isl-ok');const bar=el('div','isl-bar');const bi=el('i');bar.append(bi);
 is.append(ic,txt,spin,ok,bar);document.body.append(is);
 is.animate([{opacity:0,transform:'translate(-50%,-14px) scale(.9)'},{opacity:1,transform:'translate(-50%,0)'}],{duration:320,easing:EASE.out,fill:'forwards'});
 const morph=(w,hh,d=520)=>{const r=is.getBoundingClientRect();return is.animate([{width:r.width+'px',height:r.height+'px'},{width:w+'px',height:hh+'px'}],{duration:d,easing:EASE.spring,fill:'forwards'}).finished.catch(()=>{});};
 let closed=false;
 const close=async()=>{if(closed)return;closed=true;txt.animate([{opacity:1},{opacity:0}],{duration:150,fill:'forwards'});bar.style.opacity=0;
  await morph(130,40,380);await is.animate([{opacity:1},{opacity:0,transform:'translate(-50%,-12px) scale(.9)'}],{duration:240,fill:'forwards'}).finished.catch(()=>{});is.remove();};
 const tick=()=>{spin.style.display='none';ok.style.display='grid';ok.animate([{transform:'scale(0)'},{transform:'scale(1)'}],{duration:380,easing:EASE.spring});};
 is.addEventListener('click',close);
 return {is,txt,t1,t2,bar,bi,spin,morph,close,tick};
}
const islandW=w=>Math.min(w,innerWidth-24);
function islandScene(kind,src,{title,sub,auto}){
 const M=MODE_FX[kind]||MODE_FX.normal,col=(LQ_COL[kind]||LQ_COL.normal)[1];const I=island(col,M.i);
 let fillEl=null;
 if(src?.appendChild&&!auto&&!src.closest?.('.mode-seg')){fillEl=el('span','fx-fill');fillEl.style.background=`color-mix(in srgb,${col} 26%,transparent)`;src.appendChild(fillEl);
  fillEl.animate([{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:800,easing:EASE.io,fill:'forwards'});}
 I.t1.textContent=title;I.t2.textContent=auto?'Attivata automaticamente':sub||'Applico energia, luci e ventole…';
 I.morph(islandW(340),56).then(()=>{I.txt.animate([{opacity:0},{opacity:1}],{duration:200,fill:'forwards'});if(!auto)I.spin.animate([{opacity:0},{opacity:1}],{duration:200,fill:'forwards'});});
 const end=ms=>setTimeout(()=>{I.close();fillEl?.animate([{opacity:1},{opacity:0}],{duration:400,fill:'forwards'}).finished.then(()=>fillEl.remove()).catch(()=>{});},ms);
 if(auto){I.tick();end(2200);}
 return {box:I.is,close:I.close,done(message,ok=true){
  const list=noteLabels(message,ok);I.tick();if(!ok){I.is.classList.add('fail');I.t2.textContent=String(message).slice(0,70);end(3000);return;}
  I.t1.textContent=title+' attiva';I.t2.textContent=list.map(n=>n.l).join(' · ')||sub||'';end(1700);}};
}
function islandClean(steps,est){
 // Isola della pulizia: anello che si riempie, polvere risucchiata, contatore, passi a segmenti; alla fine scintille e spunta.
 document.querySelectorAll('.isl').forEach(x=>x.remove());
 steps=steps?.length?steps:['Pulizia'];
 const is=el('div','isl cl');
 const ring=el('div','cl-ring');
 ring.innerHTML='<svg class="cl-arc" viewBox="0 0 56 56"><defs><linearGradient id="cl-grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#34d399"/></linearGradient></defs><circle class="tr" cx="28" cy="28" r="24" pathLength="100"/><circle class="ar" cx="28" cy="28" r="24" pathLength="100"/></svg><span class="cl-orb"></span><span class="cl-core"></span>';
 const brm=icon('clean');brm.classList.add('brm');const okI=icon('check');okI.classList.add('ok');ring.append(brm,okI);
 const arc=ring.querySelector('.ar');
 const mid=el('div','cl-mid');const top=el('div','cl-top');const cnt=el('b','cl-count',est?'0 B':'0%');const lbl=el('span','cl-lbl','in pulizia');top.append(cnt,lbl);
 const stepBox=el('div','cl-step');let stepEl=el('span','',steps[0]);stepBox.append(stepEl);
 const segs=el('div','cl-segs');const segEls=steps.map(()=>el('i'));segs.append(...segEls);
 mid.append(top,stepBox,segs);is.append(ring,mid);document.body.append(is);
 const W=islandW(430),H=94;
 is.animate([{opacity:0,transform:'translate(-50%,-14px) scale(.9)'},{opacity:1,transform:'translate(-50%,0)'}],{duration:320,easing:EASE.out,fill:'forwards'});
 is.animate([{width:'130px',height:'40px'},{width:'130px',height:'40px',offset:.25},{width:W+'px',height:H+'px'}],{duration:760,easing:EASE.spring,fill:'forwards'});
 ring.animate([{opacity:0,transform:'scale(.3) rotate(-90deg)'},{opacity:0,offset:.35},{opacity:1,transform:'none'}],{duration:760,easing:EASE.spring,fill:'forwards'});
 mid.animate([{opacity:0,transform:'translateX(-10px)'},{opacity:0,offset:.45},{opacity:1,transform:'none'}],{duration:760,easing:EASE.out,fill:'forwards'});
 segEls.forEach((s,i)=>s.animate([{transform:'scaleX(0)'},{transform:'scaleX(0)',offset:.5},{transform:'none'}],{duration:700+i*60,easing:EASE.out}));
 const slide=text=>{const old=stepEl;stepEl=el('span','',text);stepBox.append(stepEl);
  old.animate([{transform:'none',opacity:1},{transform:'translateY(-15px)',opacity:0}],{duration:300,easing:EASE.io,fill:'forwards'}).finished.then(()=>old.remove()).catch(()=>{});
  stepEl.animate([{transform:'translateY(15px)',opacity:0},{transform:'none',opacity:1}],{duration:420,easing:EASE.spring});};
 let k=0,p=0;segEls[0].classList.add('cur');
 const setStep=n=>{if(n===k)return;k=n;segEls.forEach((s,i)=>{s.classList.toggle('done',i<n);s.classList.toggle('cur',i===n);});slide(steps[n]||'');};
 const t0=performance.now(),timers=[];
 timers.push(setInterval(()=>{const t=(performance.now()-t0)/1000;p=t/(t+5)*.92;arc.style.strokeDasharray=`${(p*100).toFixed(1)} 100`;
  cnt.textContent=est?bytes(est*p):Math.round(p*100)+'%';setStep(Math.min(steps.length-1,Math.floor(t/.9)));},90));
 // "polvere" (frammenti di file) risucchiata nell'anello
 const DUST=['#22d3ee','#34d399','#a78bfa','#fbbf24','#60a5fa','#f472b6'];
 timers.push(setInterval(()=>{if(document.hidden||!is.isConnected)return;
  const d=el('i','cl-dust');d.style.background=DUST[Math.random()*DUST.length|0];const w=is.offsetWidth,x0=w-14-Math.random()*70,y0=10+Math.random()*(H-20);
  d.style.left=x0+'px';d.style.top=y0+'px';is.append(d);const cx=14+28-3,cy=H/2-3,sp=(Math.random()*2-1)*420;
  d.animate([{transform:'translate(0,0) rotate(0) scale(1)',opacity:0},{opacity:.85,offset:.12},{transform:`translate(${(cx-x0)*.55}px,${(cy-y0)*.2+(Math.random()-.5)*30}px) rotate(${sp/2}deg) scale(.8)`,offset:.6},
   {transform:`translate(${cx-x0}px,${cy-y0}px) rotate(${sp}deg) scale(.15)`,opacity:.1}],{duration:900+Math.random()*500,easing:'cubic-bezier(.45,0,.75,.35)'})
   .finished.then(()=>{d.remove();if(!is.classList.contains('done'))ring.querySelector('.cl-core').animate([{opacity:.0},{opacity:.55},{opacity:0}],{duration:260});}).catch(()=>d.remove());},150));
 let closed=false;
 const close=async()=>{if(closed)return;closed=true;timers.forEach(clearInterval);
  [ring,mid].forEach(x=>x.animate([{opacity:1},{opacity:0}],{duration:160,fill:'forwards'}));const r=is.getBoundingClientRect();
  await is.animate([{width:r.width+'px',height:r.height+'px'},{width:'130px',height:'40px'}],{duration:420,easing:EASE.spring,fill:'forwards'}).finished.catch(()=>{});
  await is.animate([{opacity:1},{opacity:0,transform:'translate(-50%,-12px) scale(.9)'}],{duration:240,fill:'forwards'}).finished.catch(()=>{});is.remove();};
 is.addEventListener('click',()=>{if(is.classList.contains('done')||is.classList.contains('fail'))close();});
 return {box:is,close,finish(message,ok=true){
  timers.forEach(clearInterval);is.querySelectorAll('.cl-dust').forEach(d=>d.remove());
  const freed=parseBytes(message);const note=String(message||'').replace(/^.*?liberati\s+[\d.,]+\s*\w+\s*/i,'').replace(/^[·.\s]+/,'');
  if(ok){
   segEls.forEach((s,i)=>setTimeout(()=>{s.classList.remove('cur');s.classList.add('done');},i*70));
   arc.style.strokeDasharray='100 100';is.classList.add('done');lbl.textContent='liberati';
   if(freed!=null){cnt._v=est?est*p:0;countUp(cnt,freed,v=>bytes(v));}else cnt.textContent='Fatto';
   slide(note?'Fatto · '+note:'Pulizia completata');
   ring.animate([{transform:'scale(1)'},{transform:'scale(1.16)'},{transform:'scale(1)'}],{duration:620,easing:EASE.spring});
   for(let i=0;i<14;i++){const sp=el('i','cl-spark');const a=i*360/14+(Math.random()*10-5);sp.style.background=i%2?'#6ee7b7':'#67e8f9';is.append(sp);
    sp.animate([{transform:`rotate(${a}deg) translateY(-24px) scaleY(.4)`,opacity:0},{transform:`rotate(${a}deg) translateY(-31px) scaleY(1)`,opacity:1,offset:.3},{transform:`rotate(${a}deg) translateY(-44px) scaleY(.2)`,opacity:0}],
     {duration:700,delay:120,easing:EASE.out}).finished.then(()=>sp.remove()).catch(()=>sp.remove());}
   is.animate([{boxShadow:'0 14px 40px -12px rgba(0,0,0,.9),0 0 0 1px rgba(52,211,153,.2),0 0 0 0 rgba(52,211,153,.55)'},{boxShadow:'0 14px 40px -12px rgba(0,0,0,.9),0 0 0 1px rgba(52,211,153,.35),0 0 0 18px rgba(52,211,153,0)'}],{duration:900,delay:150});
  }else{is.classList.add('fail');lbl.textContent='non riuscita';cnt.textContent='Pulizia';slide(String(message).slice(0,80));}
  setTimeout(close,ok?4200:5200);}};
}

/* ===== collegamenti con l'app ===== */
function modeSceneOpen(mode,src,{auto=false,sub=''}={}){
 const st=animStyle();if(calm.matches||document.hidden||st==='off')return null;
 modeScene?.close?.();
 const M=MODE_FX[mode];const o={title:M.t,sub:sub||M.s,auto};
 modeScene=st==='discreet'?islandScene(mode,src,o):liquidScene(mode,src,o);
 return modeScene;
}
function modeSceneDone(scene,message,ok=true){if(scene)scene.done(message,ok);else notify((ok?'✓ ':'⚠ ')+message,!ok);}
function fx(kind,title,sub,img){
 // Avvio di un gioco.
 const st=animStyle();if(calm.matches||document.hidden||st==='off')return;
 const s=st==='discreet'?islandScene('gaming',null,{title:'Avvio '+(sub||title),sub:'NEXAR prepara il PC',auto:true})
  :liquidScene('gaming',null,{title:sub||title,sub:'Avvio il gioco…',auto:true,img});
}
function markMode(mode){
 // Il selettore si sposta subito al clic, senza aspettare che il PC abbia applicato tutto.
 document.querySelectorAll('.mode-opt').forEach(b=>b.classList.toggle('selected',b.classList.contains(mode)));
 const h=$('hm-hero');if(h)h.dataset.mode=mode;lastMode=mode;
}
async function modeSwitch(mode,src){
 if(busy)return;
 const prev=current?.mode;markMode(mode);
 if(demo){statusDemo.mode=mode;const b=modeSceneOpen(mode,src);setTimeout(()=>modeSceneDone(b,'Energia: '+MODE_FX[mode].t+' · RGB: profilo applicato · Ventole: profilo '+(mode==='eco'?'silenzioso':'normale')+(mode==='gaming'?' · Gaming Boost attivo':'')),1100);return;}
 if(!key&&!tgInit){loginScreen(true);return;}
 fxQuiet=Date.now()+15000;busy=true;
 const scene=modeSceneOpen(mode,src);
 try{const r=await req('/api/mode','POST',{mode});modeSceneDone(scene,r.message);await refresh();}
 catch(ex){modeSceneDone(scene,ex.message,false);if(prev)markMode(prev);}
 finally{busy=false;}
}
const cfx={box:null,h:null};
function cleanStart(steps,est){
 const st=animStyle();if(cfx.h||calm.matches||st==='off')return;
 cfx.h=st==='discreet'?islandClean(steps,est||0):liquidClean(steps,est||0);cfx.box=cfx.h.box;
}
function cleanFinish(message,ok=true){
 const h=cfx.h;if(!h){if(message)notify((ok?'✓ ':'⚠ ')+message,!ok);return;}
 cfx.h=null;cfx.box=null;h.finish(message,ok);
}
function cleanClose(){const h=cfx.h;cfx.h=null;cfx.box=null;h?.close();}
function pageScan(){}
$('cfg-anim-try').addEventListener('click',e=>{
 // Anteprima dello stile scelto: nessuna modalità viene cambiata.
 if(current)current.anim_style=$('cfg-anim').value;const m=current?.mode||'normal';
 const s=modeSceneOpen(m,e.currentTarget);setTimeout(()=>modeSceneDone(s,'Energia: '+MODE_FX[m].t+' · RGB: profilo applicato · Ventole: profilo attuale'),1000);
});
/* ---------- impostazioni: sezioni, salvataggio automatico, AI ECO ---------- */
function flashSaved(panel){const s=panel?.querySelector('.saved');if(!s)return;s.textContent='✓ Salvato';s.classList.remove('show');void s.offsetWidth;s.classList.add('show');clearTimeout(s._t);s._t=setTimeout(()=>s.classList.remove('show'),1800);}
function openSettings(section){
 if(curView!=='settings')navigate('settings');
 const b=document.querySelector(`#set-nav [data-set="${section}"]`);if(b)b.click();
}
document.querySelectorAll('#set-nav [data-set]').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll('#set-nav [data-set]').forEach(x=>x.classList.toggle('selected',x===b));
 document.querySelectorAll('.set-panel').forEach(p=>p.hidden=p.dataset.set!==b.dataset.set);
 if(b.dataset.set==='eco')loadEco();if(b.dataset.set==='system')loadEvents();
 b.scrollIntoView({block:'nearest',inline:'center',behavior:'smooth'});
}));
async function saveSetting(patch,panel){
 if(demo){notify('Anteprima: nessuna impostazione modificata.');return;}
 try{await req('/api/settings','POST',patch);flashSaved(panel);refresh();}catch(ex){notify('⚠ '+ex.message,true);loadSettings();}
}
Object.entries(FIELDS).forEach(([id,f])=>$(id).addEventListener('change',()=>{
 const i=$(id),v=Number.parseInt(i.value,10);
 if(Number.isNaN(v)||v<+i.min||v>+i.max){notify(`⚠ Valore ammesso: da ${i.min} a ${i.max}`,true);loadSettings();return;}
 saveSetting({[f]:v},i.closest('.set-panel'));
}));
[['cfg-psu-class','psu_class'],['cfg-gaming-fans','gaming_fans'],['cfg-anim','anim_style']].forEach(([id,f])=>$(id).addEventListener('change',()=>{
 if(f==='anim_style'&&current)current.anim_style=$(id).value;saveSetting({[f]:$(id).value},$(id).closest('.set-panel'));}));
$('cfg-alerts').addEventListener('change',()=>saveSetting({alerts_enabled:$('cfg-alerts').checked},$('cfg-alerts').closest('.set-panel')));

let ecoData=null;
const DEMO_ECO={settings:{level:'balanced',turbo_off:true,cpu:90,park:25,disk_idle:10,pcie:true,usb:true,wifi:true,leds_off:true,fans_quiet:true,monitor:60,sleep_idle:0},avg_w:{eco:92,normal:131},price_eur_kwh:.3};
async function loadEco(){if(demo){renderEco(DEMO_ECO);return;}try{renderEco(await req('/api/eco'));}catch(ex){}}
function renderEco(d){
 ecoData=d;const e=d.settings;
 document.querySelectorAll('#eco-levels [data-level]').forEach(b=>b.classList.toggle('selected',b.dataset.level===e.level));
 $('eco-custom').hidden=e.level!=='custom';
 document.querySelectorAll('[data-eco]').forEach(t=>t.setAttribute('aria-checked',e[t.dataset.eco]?'true':'false'));
 document.querySelectorAll('[data-eco-range]').forEach(r=>{r.value=e[r.dataset.ecoRange];paintRange(r);});
 document.querySelectorAll('[data-eco-select]').forEach(s=>{const v=String(e[s.dataset.ecoSelect]);
  if(![...s.options].some(o=>o.value===v))s.append(new Option(v,v));s.value=v;});
 const a=d.avg_w||{},g=$('eco-gain');g.replaceChildren();
 if(a.eco&&a.normal&&a.normal>a.eco){
  const diff=a.normal-a.eco,month=diff/1000*24*30*(d.price_eur_kwh||.3);
  g.className='eco-gain ok';const big=el('b','',`−${diff} W`);
  const t=el('div');t.append(el('strong','','Risparmio misurato su questo PC'),el('span','',`In AI ECO ${a.eco} W in media, in Normale ${a.normal} W · circa ${eur(month)} al mese se resta acceso`));
  g.append(big,t);
 }else{g.className='eco-gain';const t=el('div');t.append(el('strong','','Il risparmio si misura da solo'),el('span','','Usa AI ECO e Normale per un po’: qui comparirà quanti watt risparmi davvero.'));g.append(icon('leaf'),t);}
}
function paintRange(r){
 const p=(r.value-r.min)/(r.max-r.min)*100;r.style.setProperty('--fill',p+'%');
 const o=r.closest('.rng')?.querySelector('output');if(o)o.textContent=r.value+'%';
}
async function saveEco(patch){
 if(demo){notify('Anteprima: comando non attivo.');return;}
 try{const r=await req('/api/eco','POST',patch);notify('✓ '+r.message);renderEco({...ecoData,settings:r.settings});flashSaved($('set-eco'));refresh();}
 catch(ex){notify('⚠ '+ex.message,true);loadEco();}
}
document.querySelectorAll('#eco-levels [data-level]').forEach(b=>b.addEventListener('click',()=>saveEco({level:b.dataset.level})));
document.querySelectorAll('[data-eco]').forEach(t=>t.addEventListener('click',()=>saveEco({[t.dataset.eco]:t.getAttribute('aria-checked')!=='true'})));
document.querySelectorAll('[data-eco-range]').forEach(r=>{r.addEventListener('input',()=>paintRange(r));r.addEventListener('change',()=>saveEco({[r.dataset.ecoRange]:+r.value}));});
document.querySelectorAll('[data-eco-select]').forEach(s=>s.addEventListener('change',()=>saveEco({[s.dataset.ecoSelect]:+s.value})));

/* ---------- ricerca rapida (Ctrl+K) e scorciatoie ---------- */
const PAGES=[['home','Panoramica','home'],['gaming','Gaming','game'],['optimize','Ottimizza','clean'],['energy','Consumi','plug'],['lights','Luci','bulb'],
 ['cooling','Ventole','fan'],['power','Accensione','power'],['links','Collegamenti','link'],['settings','Impostazioni','sliders']];
function paletteItems(){
 const it=PAGES.map(([v,t,ic],i)=>({t,s:`Pagina · ${i+1}`,ic,run:()=>navigate(v)}));
 it.push({t:'AI ECO',s:'Modalità',ic:'leaf',run:()=>action('eco')},{t:'Normale',s:'Modalità',ic:'bolt',run:()=>action('normal')},{t:'Gaming',s:'Modalità',ic:'game',run:()=>action('gaming')},
  {t:'Ottimizza ora',s:'Pulizia sicura e DNS',ic:'clean',run:()=>{navigate('optimize');setTimeout(quickOptimize,300);}},
  {t:'Spegni monitor',s:'Azione',ic:'monitor',run:()=>action('screen')},{t:'LED spenti',s:'Luci',ic:'bulb',run:()=>action('rgb-eco')},{t:'LED accesi',s:'Luci',ic:'palette',run:()=>action('rgb-normal')},
  {t:'Ventole silenziose',s:'Ventole',ic:'fan',run:()=>action('fans-eco')},{t:'Ventole normali',s:'Ventole',ic:'fan',run:()=>action('fans-normal')},
  {t:'Prova la rete',s:'Ottimizza',ic:'wave',run:()=>{navigate('optimize');optTabGo('net');netRun();}},
  {t:'Cerca file grandi',s:'Ottimizza',ic:'search',run:()=>{navigate('optimize');optTabGo('large');post('/api/optimize/large/scan',{});}},
  {t:'Programmi all’avvio',s:'Ottimizza',ic:'power',run:()=>{navigate('optimize');optTabGo('startup');}},
  {t:'Statistiche dei consumi',s:'Consumi',ic:'plug',run:()=>{navigate('energy');setTimeout(()=>document.querySelector('.stats-card')?.scrollIntoView({behavior:'smooth'}),200);}},
  {t:'Impostazioni AI ECO',s:'Impostazioni',ic:'leaf',run:()=>openSettings('eco')},{t:'Avvisi di temperatura',s:'Impostazioni',ic:'temp',run:()=>openSettings('alerts')},
  {t:'Prezzo dell’energia',s:'Impostazioni',ic:'plug',run:()=>openSettings('energy')},{t:'Animazioni',s:'Impostazioni',ic:'palette',run:()=>openSettings('look')},
  {t:'Telegram',s:'Impostazioni',ic:'send',run:()=>openSettings('telegram')},{t:'Aggiornamenti',s:'Impostazioni',ic:'refresh',run:()=>openSettings('updates')},
  {t:'Spegni il PC',s:'Accensione',ic:'power',run:()=>navigate('power')});
 (gameData?.games||[]).filter(g=>!g.hidden).slice(0,12).forEach(g=>it.push({t:'Gioca a '+g.name,s:g.store,ic:'play',run:()=>launchGame(g)}));
 return it;
}
let palSel=0,palList=[];
function paletteOpen(){
 const p=$('palette');if(!p.hidden)return;p.hidden=false;$('pal-q').value='';paletteRender();setTimeout(()=>$('pal-q').focus(),10);
}
function paletteClose(){$('palette').hidden=true;}
function norm2(t){return t.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');}
function paletteRender(){
 const q=norm2($('pal-q').value.trim());const all=paletteItems();
 palList=q?all.filter(x=>norm2(x.t+' '+x.s).includes(q)):all;palSel=0;
 const box=$('pal-list');box.replaceChildren();
 if(!palList.length){box.append(el('p','pal-empty','Nessun risultato'));return;}
 palList.slice(0,40).forEach((x,i)=>{const b=el('button','pal-item'+(i===0?' sel':''));b.type='button';const ic=el('span','pal-ico');ic.append(icon(x.ic));
  const t=el('div');t.append(el('b','',x.t),el('small','',x.s));b.append(ic,t);
  b.addEventListener('mousemove',()=>{if(palSel!==i){palSel=i;paletteMark();}});b.addEventListener('click',()=>paletteRun(i));box.append(b);});
}
function paletteMark(){[...$('pal-list').children].forEach((b,i)=>b.classList.toggle('sel',i===palSel));$('pal-list').children[palSel]?.scrollIntoView({block:'nearest'});}
function paletteRun(i){const x=palList[i];if(!x)return;paletteClose();x.run();}
$('pal-q').addEventListener('input',paletteRender);
$('pal-q').addEventListener('keydown',e=>{
 if(e.key==='ArrowDown'){e.preventDefault();palSel=Math.min(palList.length-1,palSel+1);paletteMark();}
 else if(e.key==='ArrowUp'){e.preventDefault();palSel=Math.max(0,palSel-1);paletteMark();}
 else if(e.key==='Enter'){e.preventDefault();paletteRun(palSel);}
 else if(e.key==='Escape'){paletteClose();}
});
$('palette').addEventListener('click',e=>{if(e.target===$('palette'))paletteClose();});
document.querySelectorAll('[data-palette]').forEach(b=>b.addEventListener('click',paletteOpen));
document.addEventListener('keydown',e=>{
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('palette').hidden?paletteOpen():paletteClose();return;}
 const typing=/^(input|textarea|select)$/i.test(document.activeElement?.tagName||'')||document.querySelector('dialog[open]')||!$('palette').hidden;
 if(typing||e.ctrlKey||e.metaKey||e.altKey)return;
 if(/^[1-9]$/.test(e.key)){const p=PAGES[+e.key-1];if(p)navigate(p[0]);}
});
let homeStatsAt=0;
function renderHomeHero(s){
 // Riga di stato della Home: dice subito se qualcosa richiede attenzione.
 const hero=$('hm-hero');if(!hero)return;hero.dataset.mode=s.mode||'normal';
 const up=s.pc?.uptime_s;const upTxt=typeof up==='number'&&up>0?`acceso da ${duration(up)}`:'';$('hm-pc').textContent=matchMedia('(max-width:760px)').matches?(upTxt?'PC '+upTxt:'Il tuo PC'):greeting()+(upTxt?' · '+upTxt:'');
 const hot=(s.cpu_temp>=85&&'Processore')||(s.gpu_temp>=83&&'Scheda video');
 const st=hot?[`${hot} molto caldo`,'warn']:s.update?.available?['Aggiornamento pronto','info']:s.ram>=90?['Memoria quasi piena','warn']
  :s.boost?.running?[`In gioco: ${s.boost.running.name||'partita'}`,'']:s.mode==='eco'?['Risparmio attivo','']:s.mode==='gaming'?['Pronto per giocare','']:['Tutto sotto controllo',''];
 const t=$('hm-status');if(t.textContent!==st[0])t.textContent=st[0];hero.dataset.state=st[1];
 if(Date.now()-homeStatsAt>300000){homeStatsAt=Date.now();loadStats();}
}
function renderHomeWeek(d){
 // Ultimi 7 giorni di consumo nella scheda Energia della Home.
 const box=$('hm-week');if(!box)return;box.replaceChildren();
 const today=new Date();const map=new Map((d.days||[]).map(x=>[x.day,x]));const days=[];
 for(let i=6;i>=0;i--){const dt=new Date(today-i*864e5);const k=`${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;days.push([dt,map.get(k)]);}
 const mx=Math.max(.01,...days.map(([,x])=>x?.kwh||0));
 days.forEach(([dt,x],i)=>{const c=el('div','wk'+(i===6?' today':''));const bar=el('div','wk-bar');const f=el('i');
  f.style.height=Math.max(4,(x?.kwh||0)/mx*100)+'%';f.style.setProperty('--i',i);bar.append(f);
  c.title=`${dt.toLocaleDateString('it-IT',{weekday:'long',day:'numeric'})}: ${x?nf(x.kwh,2)+' kWh · '+eur(x.cost):'nessun dato'}`;
  c.append(bar,el('small','',dt.toLocaleDateString('it-IT',{weekday:'narrow'})));box.append(c);});
}
function greeting(){
 const d=new Date(),h=d.getHours();
 const hi=h<5?'Buonanotte':h<13?'Buongiorno':h<18?'Buon pomeriggio':'Buonasera';
 return `${hi} · ${d.toLocaleDateString('it-IT',{weekday:'long',day:'numeric',month:'long'})}`;
}
/* ---------- statistiche (consumi da sempre) ---------- */
let statsData=null,statMetric='kwh',statSel=null;
const DEMO_STATS=(()=>{const days=[];const now=new Date();for(let i=29;i>=0;i--){const d=new Date(now-i*864e5);const h=6+Math.random()*9,k=h*(.11+Math.random()*.08);
 days.push({day:d.toISOString().slice(0,10),kwh:+k.toFixed(2),cost:+(k*.3).toFixed(2),hours:+h.toFixed(1),peak:250+Math.round(Math.random()*200),cpu_temp:60+Math.round(Math.random()*20),gpu_temp:55+Math.round(Math.random()*20),modes:{eco:+(h*.5).toFixed(1),normal:+(h*.3).toFixed(1),gaming:+(h*.2).toFixed(1)}});}
 return {since:days[0].day,price_eur_kwh:.3,total_kwh:48.6,total_cost:14.58,co2_kg:12.6,on_hours:312,avg_w:156,avg_day_kwh:1.62,avg_day_cost:.49,days_count:30,year_cost:177,
  modes:{eco:150,normal:98,gaming:64},gaming_hours:41.5,freed_total:1.24e10,records:{peak_w:{v:462,at:days[20].day},cpu_temp:{v:84,at:days[12].day},gpu_temp:{v:79,at:days[20].day},day_wh:{v:3120,at:days[20].day}},
  days,months:[{month:'2026-09',kwh:41.2,cost:12.36,hours:280},{month:'2026-10',kwh:52.8,cost:15.84,hours:338},{month:'2026-11',kwh:6.4,cost:1.92,hours:41}]};})();
const MONTHS_IT=['gen','feb','mar','apr','mag','giu','lug','ago','set','ott','nov','dic'];
const dayLabel=d=>new Date(d+'T12:00').toLocaleDateString('it-IT',{weekday:'short',day:'numeric',month:'short'});
async function loadStats(){
 if(demo){renderStats(DEMO_STATS);return;}
 try{renderStats(await req('/api/stats'));}catch(ex){}
}
function renderStats(d){
 statsData=d;renderHomeWeek(d);
 $('st-since').textContent=d.since?`Da quando usi NEXAR: dal ${new Date(d.since+'T12:00').toLocaleDateString('it-IT',{day:'numeric',month:'long',year:'numeric'})} · ${d.days_count} giorni`:'I dati si raccolgono mentre il PC è acceso';
 countUp($('st-kwh'),d.total_kwh,v=>nf(v,v<100?2:1)+' kWh');$('st-kwh-sub').textContent=d.avg_w?`in media ${d.avg_w} W alla presa`:'—';
 countUp($('st-cost'),d.total_cost,v=>eur(v));$('st-cost-sub').textContent=`a ${nf(d.price_eur_kwh*100,0)} c€ per kWh`;
 countUp($('st-hours'),d.on_hours,v=>nf(v,0)+' h');$('st-hours-sub').textContent=d.days_count?`${nf(d.on_hours/Math.max(1,d.days_count),1)} h al giorno`:'—';
 $('st-avgday').textContent=nf(d.avg_day_kwh,2)+' kWh';$('st-avgday-sub').textContent=eur(d.avg_day_cost)+' al giorno';
 $('st-year').textContent=d.year_cost!=null?eur(d.year_cost):'—';$('st-co2').textContent=nf(d.co2_kg,1)+' kg';
 renderDayBars();
 const mb=$('st-months');mb.replaceChildren();const mx=Math.max(.01,...d.months.map(m=>m.kwh));
 if(!d.months.length)mb.append(el('p','muted','Nessun mese ancora.'));
 d.months.slice().reverse().forEach(m=>{const [y,mo]=m.month.split('-');const r=el('div','mrow');
  const bar=el('div','bar');const f=el('span');f.style.width=(m.kwh/mx*100)+'%';bar.append(f);
  const t=el('div');t.append(el('b','',`${MONTHS_IT[+mo-1]} ${y}`),bar);r.append(t,el('strong','',nf(m.kwh,1)+' kWh'),el('small','',`${eur(m.cost)} · ${nf(m.hours,0)} h`));mb.append(r);});
 const R=d.records||{},rec=$('st-records');rec.replaceChildren();
 [['bolt','Picco di potenza',R.peak_w&&Math.round(R.peak_w.v)+' W',R.peak_w?.at],['cpu','Processore più caldo',R.cpu_temp&&Math.round(R.cpu_temp.v)+' °C',R.cpu_temp?.at],
  ['gpu','Scheda video più calda',R.gpu_temp&&Math.round(R.gpu_temp.v)+' °C',R.gpu_temp?.at],['plug','Giorno con più consumo',R.day_wh&&nf(R.day_wh.v/1000,2)+' kWh',R.day_wh?.at]]
  .filter(x=>x[2]).forEach(([ic,l,v,at])=>{const r=el('div','rec');const i=el('span','rec-ico');i.append(icon(ic));const t=el('div');t.append(el('small','',l),el('b','',v));r.append(i,t,el('em','',at?dayLabel(at):''));rec.append(r);});
 if(!rec.children.length)rec.append(el('p','muted','Ancora nessun record.'));
 const M=d.modes||{},tot=Object.values(M).reduce((a,b)=>a+b,0),bar=$('st-modes'),lg=$('st-modes-legend');bar.replaceChildren();lg.replaceChildren();
 [['eco','AI ECO','#34d399'],['normal','Normale','#60a5fa'],['gaming','Gaming','#ec4899']].forEach(([k,l,c])=>{const h=M[k]||0;if(tot){const s=el('i');s.style.cssText=`flex-grow:${h};background:${c}`;bar.append(s);}
  const it=el('span');const dot=el('i');dot.style.background=c;it.append(dot,document.createTextNode(`${l} ${nf(h,0)} h`+(tot?` · ${Math.round(h/tot*100)}%`:'')));lg.append(it);});
 const ex=$('st-extra');ex.replaceChildren();
 [['game','Ore di gioco',nf(d.gaming_hours,1)+' h'],['clean','Spazio liberato da NEXAR',bytes(d.freed_total)],['plug','Prezzo energia',`${nf(d.price_eur_kwh*100,0)} c€/kWh`]]
  .forEach(([ic,l,v])=>{const r=el('div');r.append(icon(ic),el('span','',l),el('b','',v));ex.append(r);});
}
function renderDayBars(){
 const d=statsData;if(!d)return;const box=$('st-days');box.replaceChildren();
 if(!d.days.length){box.append(el('p','muted','Raccolgo i dati: la prima barra compare oggi.'));return;}
 const val=x=>statMetric==='cost'?x.cost:statMetric==='hours'?x.hours:x.kwh;const mx=Math.max(.01,...d.days.map(val));
 const fmt=v=>statMetric==='cost'?eur(v):statMetric==='hours'?nf(v,1)+' h':nf(v,2)+' kWh';
 $('st-days-sub').textContent=`Media ${fmt(d.days.reduce((a,x)=>a+val(x),0)/d.days.length)} al giorno`;
 d.days.forEach((x,i)=>{const b=el('button','dbar'+(x.day===statSel?' sel':''));b.type='button';const f=el('i');f.style.height=Math.max(2,val(x)/mx*100)+'%';f.style.setProperty('--i',i);b.append(f);
  const dd=+x.day.slice(8);if(i===0||i===d.days.length-1||dd%5===0)b.append(el('small','',dd));
  b.title=dayLabel(x.day)+' · '+fmt(val(x));
  b.addEventListener('click',()=>{statSel=x.day;box.querySelectorAll('.dbar').forEach(z=>z.classList.toggle('sel',z===b));
   const md=Object.entries(x.modes||{}).map(([k,v])=>`${{eco:'ECO',normal:'Normale',gaming:'Gaming'}[k]} ${nf(v,1)} h`).join(' · ');
   $('st-tip').textContent=`${dayLabel(x.day)}: ${nf(x.kwh,2)} kWh · ${eur(x.cost)} · acceso ${nf(x.hours,1)} h · picco ${Math.round(x.peak||0)} W`+(x.cpu_temp?` · CPU max ${Math.round(x.cpu_temp)}°C`:'')+(x.gpu_temp?` · GPU max ${Math.round(x.gpu_temp)}°C`:'')+(md?` · ${md}`:'');});
  box.append(b);});
}
document.querySelectorAll('#st-metric button').forEach(b=>b.addEventListener('click',()=>{statMetric=b.dataset.m;document.querySelectorAll('#st-metric button').forEach(x=>x.classList.toggle('selected',x===b));renderDayBars();}));
setInterval(()=>{if(!document.hidden&&$('page-energy').classList.contains('active'))loadStats();},60000);
/* ---------- gaming ---------- */
let gameData=null,libStore='',showHidden=false,heroArt=null;const covers=new Map();
const STORE_COLORS={Steam:'#66c0f4',Epic:'#e5e7eb',Riot:'#ff6b75',GOG:'#c79cff'};
const FAN_NAMES={off:'Spente',off_pump:'Spente',eco:'Silenziose',normal:'Normali',max:'Massimo'};
const FAN_BAR={off:0,off_pump:8,eco:35,normal:60,max:100};
const DEMO_GAMING={boost:{active:true,game:'Hollow Knight',boosted:['hollow_knight.exe'],lowered:['discord.exe'],closed:['chrome.exe'],
  tweaks:['Modalità gioco di Windows','Registrazione Xbox in background spenta'],running:{id:'steam-367520',name:'Hollow Knight',store:'Steam'},
  session:{game:'Hollow Knight',gid:'steam-367520',start:Date.now()/1000-2580,elapsed:2580,cpu_temp_max:71,gpu_temp_max:66,cpu_temp_avg:63,gpu_temp_avg:60,cpu_avg:31,gpu_avg:74,kwh:.21,watts_avg:288},
  settings:{game_priority:true,game_mode:true,no_dvr:true,reopen:true,auto:true,mouse:false,apps:{'discord.exe':'lower','chrome.exe':'close'},eco_apps:{'chrome.exe':'lower'},stop_junk:true,eco_throttle:true,hidden:[]}},
 games:[{id:'steam-367520',name:'Hollow Knight',store:'Steam',size:5.2e9,last:Date.now()/1000-3000,playtime:9600,cover:false},
  {id:'steam-526870',name:'Satisfactory',store:'Steam',size:3e10,last:Date.now()/1000-90000,playtime:2400,cover:false},
  {id:'riot-valorant',name:'VALORANT',store:'Riot',size:0,last:Date.now()/1000-400000,playtime:3700,cover:false},
  {id:'steam-275850',name:'No Man’s Sky',store:'Steam',size:2.9e10,last:1763492602,playtime:0,cover:false},
  {id:'epic-Fortnite',name:'Fortnite',store:'Epic',size:1.1e11,last:0,playtime:0,cover:false},
  {id:'epic-Sugar',name:'Rocket League®',store:'Epic',size:2.4e10,last:0,playtime:0,cover:false},
  {id:'steam-2358720',name:'Black Myth: Wukong',store:'Steam',size:1.5e11,last:1764102958,playtime:0,cover:false},
  {id:'steam-739630',name:'Phasmophobia',store:'Steam',size:2e10,last:1778601360,playtime:0,cover:false}],
 history:[{game:'Hollow Knight',gid:'steam-367520',start:Date.now()/1000-90000,elapsed:4320,cpu_temp_max:74,gpu_temp_max:68,kwh:.34,cost:.1,watts_avg:283},
  {game:'VALORANT',gid:'riot-valorant',start:Date.now()/1000-400000,elapsed:3700,cpu_temp_max:79,gpu_temp_max:71,kwh:.31,cost:.09,watts_avg:301}],
 apps:[{name:'chrome.exe',bytes:1.2e9,count:12,game:false},{name:'discord.exe',bytes:4e8,count:5,game:false},{name:'overwolf.exe',bytes:3.1e8,count:6,game:false},
  {name:'spotify.exe',bytes:2.6e8,count:4,game:false},{name:'browser_assistant.exe',bytes:9e7,count:2,game:false},{name:'manycam.exe',bytes:1.4e8,count:1,game:false}],
 junk:{'overwolf.exe':'Overwolf','browser_assistant.exe':'assistente del browser Opera','manycam.exe':'webcam virtuale ManyCam'},
 stopper:{mode:'gaming',stopped:['overwolf.exe','browser_assistant.exe'],throttled:0},
 startup_junk:[{id:'x1',name:'Overwolf',why:'Overwolf'},{id:'x2',name:'Opera GX Browser Assistant',why:'assistente del browser Opera'}],
 fans:'normal',fans_enabled:true,rgb_color:'#ff3cc8',rgb_enabled:true,palette:statusDemo.rgb_palette};
function hue(t){let h=0;for(const c of String(t))h=(h*31+c.charCodeAt(0))%360;return h;}
function initials(n){return n.replace(/[^\p{L}\p{N} ]/gu,'').split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()||'?';}
function playtime(s){if(!s)return '';const m=Math.max(1,Math.round(s/60)),h=Math.floor(m/60);return h?`${h} h ${m%60?m%60+' min':''}`.trim():`${m} min`;}
function ago(ts){if(!ts)return '';const d=(Date.now()/1000-ts)/86400;
 return d<1?'oggi':d<2?'ieri':d<30?`${Math.floor(d)} giorni fa`:new Date(ts*1000).toLocaleDateString('it-IT',{day:'numeric',month:'short',year:'numeric'});}
function coverUrl(id,kind){
 // Le immagini arrivano dalla cache di Steam sul PC, con la stessa chiave della API.
 const k=id+'/'+kind;if(covers.has(k))return covers.get(k);
 const p=(async()=>{if(demo||(kind!=='icon'&&!id.startsWith('steam-')))return '';
  try{const r=await fetch(`/api/gaming/cover/${encodeURIComponent(id)}/${kind}`,{headers:tgInit?{'X-TG-Init-Data':tgInit}:{'X-PC-ECO-Key':key}});
   return r.ok?URL.createObjectURL(await r.blob()):'';}catch(e){return '';}})();
 covers.set(k,p);return p;
}
async function loadGaming(refresh=false,animate=false){
 if(demo){renderGaming(DEMO_GAMING,animate);return;}
 try{renderGaming(await req('/api/gaming'+(refresh?'?refresh=true':'')),animate);}catch(ex){notify('Gaming: '+ex.message,true);}
}
function renderGaming(d,animate=false){
 gameData=d;const s=d.boost?.settings||{};
 document.querySelectorAll('[data-boost]').forEach(t=>t.setAttribute('aria-checked',s[t.dataset.boost]?'true':'false'));
 document.querySelectorAll('#game-fans [data-fans]').forEach(b=>{b.classList.toggle('selected',b.dataset.fans===d.fans);b.disabled=!d.fans_enabled;});
 const sw=$('game-rgb');sw.replaceChildren();
 const none=el('button','swatch none'+(d.rgb_color?'':' selected'));none.type='button';none.title='Non cambiare le luci';none.append(icon('x'));
 none.addEventListener('click',()=>saveGaming({rgb_color:''}));sw.append(none);
 (d.palette||[]).forEach(c=>{const b=el('button','swatch'+(c===d.rgb_color?' selected':''));b.type='button';b.style.background=c;b.title=c.toUpperCase();
  b.addEventListener('click',()=>saveGaming({rgb_color:c}));sw.append(b);});
 sw.querySelectorAll('button').forEach(b=>b.disabled=!d.rgb_enabled);
 $('game-rgb-note').textContent=!d.rgb_enabled?'OpenRGB non collegato':d.rgb_color?'Uscendo torna il colore normale':'Le luci restano come sono';
 renderLibrary(animate);renderBoostApps(d);renderHistory(d.history||[]);
 renderGamingLive(current||statusDemo);
}
let libSort='recent';try{libSort=localStorage.getItem('nexar.libSort')||'recent';}catch(e){}
function libHero(g,running){
 // "Continua a giocare": l'ultimo gioco aperto, grande, con il tasto per ripartire subito.
 const h=$('lib-hero');if(!g){h.hidden=true;h.replaceChildren();h._id=null;return;}
 const playing=g.id===running,key=g.id+'|'+playing+'|'+g.last;if(h._id===key&&!h.hidden)return;h._id=key;h.hidden=false;
 h.style.setProperty('--h',hue(g.name));h.style.setProperty('--sc',STORE_COLORS[g.store]||'#94a3b8');h.className='lib-hero';
 const bg=el('div','lh-bg'),body=el('div','lh-body'),txt=el('div','lh-txt');
 txt.append(el('small','',playing?'In gioco ora':'Continua a giocare'),el('b','',g.name),
  el('span','',[g.store,'ultima volta '+ago(g.last),g.playtime?playtime(g.playtime)+' in tutto':''].filter(Boolean).join(' · ')));
 const go=el('button','btn primary lh-go');go.type='button';go.append(icon('play'),el('span','',playing?'In gioco':'Gioca'));go.disabled=playing;
 go.addEventListener('click',()=>launchGame(g));body.append(txt,go);
 const img=u=>{if(!u)return false;const im=el('img');im.alt='';im.onload=()=>h.classList.add('ready');im.src=u;bg.append(im);return true;};
 if(g.cover)coverUrl(g.id,'header').then(u=>img(u)||coverUrl(g.id,'capsule').then(img));
 else if(g.icon)coverUrl(g.id,'icon').then(u=>{if(img(u))h.classList.add('icon');});
 h.replaceChildren(bg,el('i','lh-scrim'),body);
}
function renderLibrary(animate=false){
 const d=gameData;if(!d)return;const games=d.games||[];const q=$('lib-search').value.trim().toLowerCase();
 const stores=[...new Set(games.filter(g=>!g.hidden).map(g=>g.store))];if(libStore&&!stores.includes(libStore))libStore='';
 const seg=$('lib-stores');seg.hidden=stores.length<2;
 seg.replaceChildren(...['',...stores].map(st=>{const b=el('button',st===libStore?'selected':'',st||'Tutti');b.type='button';
  b.addEventListener('click',()=>{libStore=st;renderLibrary(true);});return b;}));
 const hiddenN=games.filter(g=>g.hidden).length;
 const list=games.filter(g=>(showHidden||!g.hidden)&&(!libStore||g.store===libStore)&&(!q||g.name.toLowerCase().includes(q)));
 const byName=(a,b)=>a.name.localeCompare(b.name,'it',{sensitivity:'base'});
 list.sort(libSort==='az'?byName:libSort==='time'?(a,b)=>(b.playtime||0)-(a.playtime||0)||byName(a,b):(a,b)=>(b.last||0)-(a.last||0)||byName(a,b));
 document.querySelectorAll('#lib-sort button').forEach(b=>b.classList.toggle('selected',b.dataset.sort===libSort));
 libHero(!q&&!libStore?games.filter(g=>!g.hidden&&g.last).sort((a,b)=>b.last-a.last)[0]:null,(current?.boost||d.boost)?.running?.id);
 const running=(current?.boost||d.boost)?.running?.id;
 $('lib-sub').textContent=games.length?`${games.length-hiddenN} giochi · ${stores.join(', ')}`:'Nessun gioco trovato';
 const lh=$('lib-hidden');lh.hidden=!hiddenN;lh.textContent=showHidden?'Nascondi i programmi esclusi':`Mostra ${hiddenN} ${hiddenN>1?'esclusi':'escluso'}`;
 const grid=$('game-grid');grid.replaceChildren();
 if(!list.length){grid.append(el('p','muted',games.length?'Nessun gioco corrisponde alla ricerca.':'Non ho trovato giochi di Steam, Epic, Riot o GOG su questo PC.'));return;}
 list.forEach((g,i)=>{
  // Locandina 2:3 come nei launcher. Steam: copertina dalla sua cache; Epic/Riot/GOG: icona grande del gioco
  // su uno sfondo fatto con i suoi colori; altrimenti una locandina disegnata col nome.
  const playing=g.id===running;
  const card=el('article','gcard'+(g.hidden?' is-hidden':'')+(playing?' playing':'')+(animate?' enter':''));
  card.style.setProperty('--i',Math.min(i,18));card.style.setProperty('--h',hue(g.name));card.style.setProperty('--sc',STORE_COLORS[g.store]||'#94a3b8');
  const art=el('div','gc-art');
  const gen=el('div','gc-gen'),gt=el('b','',g.name);gt.style.setProperty('--n',Math.max(8,...String(g.name).split(/\s+/).map(w=>w.length)));gen.append(gt,el('small','',g.store));art.append(gen);
  const cover=u=>{if(!u)return false;const im=el('img','cov');im.alt='';im.onload=()=>art.classList.add('ready');im.src=u;art.prepend(im);return true;};
  const iconArt=u=>{if(!u)return;const bg=el('img','ia-bg'),fg=el('img','ia-fg');bg.alt=fg.alt='';bg.src=fg.src=u;
   fg.onload=()=>{art.classList.add('icon','ready');};art.append(bg,fg,el('span','ia-name',g.name));};
  if(g.cover)coverUrl(g.id,'capsule').then(u=>cover(u)||coverUrl(g.id,'header').then(h=>{if(cover(h))art.classList.add('wide');}));
  else if(g.icon)coverUrl(g.id,'icon').then(iconArt);
  art.append(el('i','scrim'));
  const play=el('button','gc-play');play.type='button';play.append(icon('play'));play.setAttribute('aria-label',(playing?'In gioco: ':'Gioca a ')+g.name);
  play.disabled=playing||g.hidden;play.addEventListener('click',e=>{e.stopPropagation();launchGame(g);});
  const hide=el('button','gc-hide');hide.type='button';hide.title=g.hidden?'Rimetti tra i giochi':'Non è un gioco: escludi';hide.setAttribute('aria-label',hide.title);
  hide.append(icon(g.hidden?'eye':'eye-off'));
  hide.addEventListener('click',e=>{e.stopPropagation();const h=new Set(d.boost?.settings?.hidden||[]);g.hidden?h.delete(g.id):h.add(g.id);saveGaming({hidden:[...h]});});
  art.append(play,hide);if(playing)art.append(el('span','gc-now','IN GIOCO'));
  const cap=el('div','gc-cap');const meta=el('div','gc-meta');meta.append(el('i'),el('span','',[g.store,g.playtime?playtime(g.playtime):'',g.last?ago(g.last):'mai giocato'].filter(Boolean).join(' · ')));
  cap.append(el('b','',g.name),meta);
  card.append(art,cap);tilt(art);
  if(g.size)card.title=`${g.name} · ${bytes(g.size)}`;
  grid.append(card);
 });
}
let stopMode='gaming';
function renderBoostApps(d){
 // Una scelta per app e per modalità. I programmi noti come inutili partono già su "Chiudi" (Lascia = "keep").
 const s=d.boost?.settings||{},key=stopMode==='eco'?'eco_apps':'apps',chosen=s[key]||{},junk=d.junk||{},junkOn=s.stop_junk!==false;
 document.querySelectorAll('#stop-mode button').forEach(b=>b.classList.toggle('selected',b.dataset.sm===stopMode));
 $('stop-eco-row').hidden=stopMode!=='eco';
 const st=d.stopper||{},live=st.mode===stopMode&&(st.stopped||[]).length;
 $('stop-sub').textContent=live?`Adesso: fermati ${st.stopped.map(n=>n.replace(/\.exe$/i,'')).join(', ')}`+(st.throttled?` · ${st.throttled} in risparmio`:'')
  :stopMode==='eco'?'Cosa fare di ogni app quando sei in AI ECO':'Cosa fare di ogni app mentre giochi';
 const sj=d.startup_junk||[];$('stop-startup').hidden=!sj.length;
 if(sj.length){$('stop-startup-title').textContent=`${sj.length} ${sj.length>1?'programmi inutili partono':'programma inutile parte'} con Windows`;
  $('stop-startup-sub').textContent=sj.map(j=>j.name).join(', ')+' · si riattivano quando vuoi da Ottimizza → Avvio';}
 const box=$('boost-apps');box.replaceChildren();
 const apps=(d.apps||[]).filter(a=>!a.game);
 Object.keys(chosen).forEach(n=>{if(!apps.some(a=>a.name===n))apps.push({name:n,bytes:0,count:0,closed:true});});
 apps.sort((a,b)=>(!!junk[b.name]-!!junk[a.name])||(b.bytes-a.bytes));
 if(!apps.length){box.append(el('p','muted','Nessuna app in background da gestire.'));return;}
 apps.forEach(a=>{
  const isJunk=!!junk[a.name],cur=chosen[a.name]==='keep'?'':chosen[a.name]||(isJunk&&junkOn?'close':'');
  const row=el('div','boost-app'+(isJunk?' junk':''));const t=el('div');
  const label=isJunk?junk[a.name].charAt(0).toUpperCase()+junk[a.name].slice(1):a.name.replace(/\.exe$/i,'');
  const nm=el('b','',label);if(isJunk)nm.append(el('em','pill warn','inutile'));
  t.append(nm,el('small','',(isJunk?a.name.replace(/\.exe$/i,'')+' · ':'')+(a.closed?'non aperta ora':`${bytes(a.bytes)} di RAM`+(a.count>1?` · ${a.count} processi`:''))));
  const seg=el('div','seg3');
  [['','Lascia'],['lower','Rallenta'],['close','Chiudi']].forEach(([v,l])=>{const b=el('button',v,l);b.type='button';b.classList.toggle('selected',cur===v);
   b.addEventListener('click',()=>{const next=Object.fromEntries(Object.entries(chosen).filter(([k])=>k!==a.name));
    if(v)next[a.name]=v;else if(isJunk&&junkOn)next[a.name]='keep';saveGaming({[key]:next});});seg.append(b);});
  row.append(t,seg);box.append(row);
 });
}
document.querySelectorAll('#stop-mode button').forEach(b=>b.addEventListener('click',()=>{stopMode=b.dataset.sm;if(gameData)renderBoostApps(gameData);}));
$('stop-startup-btn').addEventListener('click',async()=>{if(demo){notify('Anteprima: comando non attivo.');return;}
 try{const r=await req('/api/gaming/startup-junk','POST',{});notify('✓ '+r.message);await loadGaming();}catch(ex){notify('⚠ '+ex.message,true);}});

/* ---------- app sul PC da aprire a distanza ---------- */
let rapps=null;const appIcons=new Map();
function appIconUrl(k){if(appIcons.has(k))return appIcons.get(k);
 const p=(async()=>{if(demo)return '';try{const r=await fetch(`/api/apps/icon/${k}`,{headers:tgInit?{'X-TG-Init-Data':tgInit}:{'X-PC-ECO-Key':key}});
  return r.ok?URL.createObjectURL(await r.blob()):'';}catch(e){return '';}})();appIcons.set(k,p);return p;}
function appIco(a,cls){const ic=el('span',cls,initials(a.name));ic.style.setProperty('--h',hue(a.name));
 appIconUrl(a.key).then(u=>{if(!u)return;const im=el('img');im.alt='';im.onload=()=>{ic.textContent='';ic.append(im);ic.classList.add('img');};im.src=u;});return ic;}
const DEMO_APPS={pinned:[{id:'Claude_x!Claude',name:'Claude',key:'a1',running:true,closable:false},{id:'OpenAI.Codex_x!App',name:'Codex',key:'a2',running:false,closable:false},
 {id:'steam',name:'Steam',key:'a3',running:false,closable:true},{id:'spotify',name:'Spotify',key:'a4',running:true,closable:false}],
 available:['Claude','Codex','Steam','Spotify','Discord','Google Chrome','Visual Studio Code','Terminale','OBS Studio','Blocco note'].map((n,i)=>({id:'d'+i,name:n,key:'b'+i,pinned:i<4}))};
async function loadApps(all=false){
 if(demo){rapps=DEMO_APPS;renderApps();return rapps;}
 try{rapps=await req('/api/apps'+(all?'?all=true':''));renderApps();return rapps;}catch(ex){$('rapps').replaceChildren(el('p','muted','App non disponibili: '+ex.message));}
}
function renderApps(){
 const box=$('rapps'),list=rapps?.pinned||[];box.replaceChildren();
 $('rapps-sub').textContent=list.length?`${list.filter(a=>a.running).length} aperte su ${list.length} · tocca per aprire, anche da Telegram`:'Aggiungi le app che vuoi aprire da qui';
 list.forEach((a,i)=>{
  const t=el('div','rapp'+(a.running?' on':'')+(a.missing?' missing':''));t.style.setProperty('--i',i);
  const open=el('button','rapp-open');open.type='button';open.setAttribute('aria-label',(a.running?'Porta avanti ':'Apri ')+a.name);
  open.append(appIco(a,'rapp-ico'),el('b','',a.name),el('small','',a.missing?'non più installata':a.running?'aperta':'chiusa'));
  open.disabled=!!a.missing;open.addEventListener('click',()=>appOpen(a,t));t.append(open);
  if(a.running&&a.closable){const x=el('button','rapp-x');x.type='button';x.title='Chiudi '+a.name;x.setAttribute('aria-label',x.title);x.append(icon('x'));
   x.addEventListener('click',e=>{e.stopPropagation();appClose(a);});t.append(x);}
  box.append(t);});
 const add=el('button','rapp rapp-add');add.type='button';add.append(el('span','rapp-ico plus','+'),el('b','','Aggiungi'),el('small','','dal menu Start'));
 add.addEventListener('click',openAppSheet);box.append(add);
}
async function appOpen(a,tile){
 tile?.classList.add('launch');setTimeout(()=>tile?.classList.remove('launch'),1400);
 if(demo){notify('✓ Apro '+a.name);return;}
 try{const r=await req('/api/apps/open','POST',{id:a.id});notify('🚀 '+r.message);setTimeout(()=>loadApps(),2500);}catch(ex){notify('⚠ '+ex.message,true);}
}
async function appClose(a){
 if(demo){notify('✓ Chiudo '+a.name);return;}
 try{const r=await req('/api/apps/close','POST',{id:a.id});notify('✓ '+r.message);setTimeout(()=>loadApps(),2000);}catch(ex){notify('⚠ '+ex.message,true);}
}
async function openAppSheet(){
 const d=$('app-sheet');$('as-search').value='';$('as-list').replaceChildren(el('p','muted','Cerco le app del PC…'));if(!d.open)d.showModal();
 await loadApps(true);renderAppSheet();
}
function renderAppSheet(){
 const q=$('as-search').value.trim().toLowerCase(),box=$('as-list'),all=(rapps?.available||[]).filter(a=>!q||a.name.toLowerCase().includes(q));
 box.replaceChildren();if(!all.length){box.append(el('p','muted',q?'Nessuna app con questo nome.':'Nessuna app trovata nel menu Start.'));return;}
 [...all.filter(a=>a.pinned),...all.filter(a=>!a.pinned)].slice(0,120).forEach(a=>{
  const row=el('button','as-row'+(a.pinned?' on':''));row.type='button';row.setAttribute('aria-pressed',a.pinned?'true':'false');
  const chk=el('span','as-chk');if(a.pinned)chk.append(icon('check'));else chk.textContent='+';row.append(appIco(a,'as-ico'),el('b','',a.name),chk);
  row.addEventListener('click',async()=>{
   if(demo){a.pinned=!a.pinned;DEMO_APPS.pinned=a.pinned?[...DEMO_APPS.pinned,{...a,running:false}]:DEMO_APPS.pinned.filter(p=>p.name!==a.name);renderAppSheet();renderApps();return;}
   try{await req('/api/apps/pin','POST',{id:a.id,pinned:!a.pinned});await loadApps(true);renderAppSheet();}catch(ex){notify('⚠ '+ex.message,true);}});
  box.append(row);});
}
$('rapps-add').addEventListener('click',openAppSheet);
$('as-search').addEventListener('input',renderAppSheet);
$('as-close').addEventListener('click',()=>$('app-sheet').close());
$('app-sheet').addEventListener('click',e=>{if(e.target===e.currentTarget)$('app-sheet').close();});

/* ---------- schermo del PC ---------- */
var scrInfo=null,scrUrl='',scrBusy=false,scrLiveOn=false;   // var: navigate() li legge anche prima di questa riga
const DEMO_SCREEN={settings:{view:true,ai_alert:true},ai_busy:['codex.exe'],windows:[
 {id:1,title:'Codex',exe:'Codex.exe',hung:false},{id:2,title:'NEXAR — app.js — Visual Studio Code',exe:'Code.exe',hung:false},
 {id:3,title:'Claude',exe:'claude.exe',hung:false},{id:4,title:'Spotify Premium',exe:'Spotify.exe',hung:true,min:true}]};
function demoShot(){
 const c=document.createElement('canvas');c.width=1600;c.height=900;const g=c.getContext('2d');
 const bg=g.createLinearGradient(0,0,1600,900);bg.addColorStop(0,'#0f2a4a');bg.addColorStop(1,'#3b1d52');g.fillStyle=bg;g.fillRect(0,0,1600,900);
 [[80,70,820,560,'#1e1e1e','Codex'],[700,180,820,600,'#f7f7f5','Claude']].forEach(([x,y,w,h,col,t])=>{g.fillStyle='rgba(0,0,0,.35)';g.fillRect(x+8,y+12,w,h);
  g.fillStyle=col;g.fillRect(x,y,w,h);g.fillStyle=col==='#1e1e1e'?'#2d2d2d':'#e8e6e1';g.fillRect(x,y,w,40);g.fillStyle=col==='#1e1e1e'?'#ddd':'#333';g.font='600 18px Segoe UI';g.fillText(t,x+16,y+26);
  for(let i=0;i<12;i++){g.fillStyle=col==='#1e1e1e'?`hsl(${190+i*9} 60% ${55+i%3*8}%)`:'#b9b5ab';g.fillRect(x+24,y+70+i*36,180+((i*97)%420),12);}});
 g.fillStyle='rgba(20,22,28,.92)';g.fillRect(0,852,1600,48);
 return c.toDataURL('image/jpeg',.8);
}
async function loadScreen(take=true){
 if(demo)scrInfo=DEMO_SCREEN;
 else{try{scrInfo=await req('/api/screen');}catch(ex){$('scr-wins').replaceChildren(el('p','muted','Non disponibile: '+ex.message));return;}}
 renderScreen();if(take&&scrInfo.settings.view)shot();
}
function renderScreen(){
 const s=scrInfo?.settings||{},wins=scrInfo?.windows||[];
 $('scr-ai').setAttribute('aria-checked',s.ai_alert?'true':'false');$('scr-allow').setAttribute('aria-checked',s.view?'true':'false');
 $('scr-card').classList.toggle('off',!s.view);
 if(!s.view){$('scr-view').classList.remove('has');$('scr-empty').querySelector('b').textContent='Vista da remoto disattivata';}
 const busy=(scrInfo?.ai_busy||[]).map(n=>{n=n.replace(/\.exe$/i,'');return n.charAt(0).toUpperCase()+n.slice(1);});
 $('scr-sub').textContent=busy.length?`${busy.join(' e ')} sta lavorando${s.ai_alert?' · ti avviso quando finisce':''}`:'Guarda cosa succede sul PC, anche da Telegram';
 $('scr-wcount').textContent=wins.length?`${wins.length}`:'';
 const box=$('scr-wins');box.replaceChildren();
 if(!wins.length){box.append(el('p','muted','Nessuna finestra aperta.'));return;}
 wins.forEach(w=>{
  const row=el('div','scr-win'+(w.hung?' hung':''));const name=(w.exe||w.title).replace(/\.exe$/i,'');
  const ic=el('span','as-ico',initials(name));ic.style.setProperty('--h',hue(name));
  const t=el('div');t.append(el('b','',w.title));const sm=el('small','',name+(w.min?' · ridotta a icona':''));
  if(w.hung){sm.append(document.createTextNode(' · '));sm.append(el('em','','non risponde'));}t.append(sm);
  const b=el('button','btn'+(w.hung?' danger':''),w.hung?'Chiudi programma':'Chiudi');b.type='button';b.addEventListener('click',()=>scrCloseWin(w));
  row.append(ic,t,b);box.append(row);});
}
async function shot(){
 if(scrBusy)return;scrBusy=true;const v=$('scr-view');v.classList.add('loading');
 try{
  let u;
  if(demo){await new Promise(r=>setTimeout(r,500));u=demoShot();}
  else{const r=await fetch('/api/screen/shot',{headers:tgInit?{'X-TG-Init-Data':tgInit}:{'X-PC-ECO-Key':key},cache:'no-store'});
   if(!r.ok){const o=await r.json().catch(()=>({}));throw new Error(o.detail||'Schermo non disponibile');}
   u=URL.createObjectURL(await r.blob());}
  await new Promise(res=>{const im=$('scr-img');im.onload=im.onerror=res;im.src=u;});
  if(scrUrl.startsWith('blob:'))URL.revokeObjectURL(scrUrl);scrUrl=u;$('scr-full-img').src=u;
  v.classList.add('has');$('scr-time').textContent=new Date().toLocaleTimeString('it-IT');
 }catch(ex){v.classList.remove('has');$('scr-empty').querySelector('b').textContent=ex.message;$('scr-time').textContent='';scrLive(false);}
 finally{scrBusy=false;v.classList.remove('loading');}
}
async function scrLive(on){
 scrLiveOn=on;$('scr-live').setAttribute('aria-checked',on?'true':'false');
 while(scrLiveOn){
  if(curView!=='screen'||document.hidden){scrLive(false);break;}
  await shot();await new Promise(r=>setTimeout(r,2500));
 }
}
async function scrAction(action,extra={}){
 if(demo){notify('Anteprima: comando non attivo.');return;}
 try{const r=await req('/api/screen/action','POST',{action,...extra});notify('✓ '+r.message);
  setTimeout(()=>{loadScreen(false);if(action!=='monitor_off'&&action!=='lock')shot();},action==='close'?1500:400);}
 catch(ex){notify('⚠ '+ex.message,true);}
}
async function scrCloseWin(w){
 if(w.hung){if(!await ask('Chiudere '+(w.exe||w.title).replace(/\.exe$/i,'')+'?','Non risponde: chiudo tutto il programma. Il lavoro non salvato si perde.',{ico:'x',yes:'Chiudi programma'}))return;
  return scrAction('close',{id:w.id,force:true});}
 scrAction('close',{id:w.id});
}
async function scrSetting(k){
 const on=$(k==='view'?'scr-allow':'scr-ai').getAttribute('aria-checked')!=='true';
 if(demo){DEMO_SCREEN.settings[k==='view'?'view':'ai_alert']=on;renderScreen();return;}
 try{const r=await req('/api/screen/settings','POST',{[k==='view'?'view':'ai_alert']:on});scrInfo.settings=r.settings;renderScreen();if(k==='view'&&on)shot();}
 catch(ex){notify('⚠ '+ex.message,true);}
}
$('scr-refresh').addEventListener('click',()=>{shot();loadScreen(false);});
$('scr-view').addEventListener('click',()=>{if(!$('scr-view').classList.contains('has')){shot();return;}$('scr-full').showModal();});
$('scr-live').addEventListener('click',()=>scrLive(!scrLiveOn));
document.querySelectorAll('[data-scr]').forEach(b=>b.addEventListener('click',async()=>{
 if(b.dataset.scr==='lock'&&!await ask('Bloccare il PC?','Va alla schermata di accesso: per sbloccarlo serve il PIN sul PC.',{danger:false,ico:'lock',yes:'Blocca'}))return;
 scrAction(b.dataset.scr);}));
$('scr-ai').addEventListener('click',e=>{e.preventDefault();scrSetting('ai_alert');});
$('scr-allow').addEventListener('click',e=>{e.preventDefault();scrSetting('view');});
$('scr-full-x').addEventListener('click',()=>$('scr-full').close());
$('scr-full-r').addEventListener('click',shot);
$('scr-full').addEventListener('click',e=>{if(e.target===e.currentTarget||e.target.tagName==='IMG')$('scr-full').close();});

/* ---------- controllo remoto: mouse e tastiera ---------- */
var rcInfo=null;
const RC={token:'',on:false,v:0,seq:0,w:16,h:9,mons:[],mode:'touch',q:[],sending:false,url:'',cur:null,
 z:{s:1,x:0,y:0},pts:new Map(),g:null,latch:new Set(),kbPrev:' ',frames:[],bytes:[],idle:10,lastIn:0,idleT:null};
const DEMO_RC={enabled:true,pin_set:true,idle_minutes:10,active:false,locked_for:0,local:true};
function rcHead(){const h=tgInit?{'X-TG-Init-Data':tgInit}:{'X-PC-ECO-Key':key};if(RC.token)h['X-Remote-Session']=RC.token;return h;}
async function rcPost(path,body){
 const r=await fetch(path,{method:'POST',headers:{...rcHead(),'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
 const o=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(o.detail||'Errore di comunicazione');e.status=r.status;throw e;}return o;
}
async function loadRemote(){
 if(demo)rcInfo={...DEMO_RC,active:RC.on};else{try{rcInfo=await req('/api/remote');}catch(ex){return;}}
 renderRemote();
}
function renderRemote(){
 const i=rcInfo||{};const local=!!i.local;
 $('rc-enabled').setAttribute('aria-checked',i.enabled?'true':'false');
 $('rc-note').textContent=i.locked_for?`Bloccato per troppi PIN sbagliati: ancora ${Math.ceil(i.locked_for/60)} min`
  :i.enabled?`Acceso · ogni sessione chiede il PIN · si chiude dopo ${i.idle_minutes} min senza comandi`
  :local?(i.pin_set?'Spento: accendilo per usarlo da lontano':'Scegli un PIN, poi accendilo'):'Spento: si accende dal PC, per sicurezza';
 $('rc-setup').hidden=!local;$('rc-pin-set').querySelector('span').textContent=i.pin_set?'Cambia il PIN':'Scegli il PIN';
 $('rc-idle').value=String(i.idle_minutes||10);
 $('rc-live').hidden=!i.active;
 if(i.active&&i.session)$('rc-live-sub').textContent=`Da ${i.session.who} · da ${Math.max(1,Math.round(i.session.since_s/60))} min`;
 $('rc-take').classList.toggle('off',!i.enabled);
}
async function rcSetup(body){
 if(demo){Object.assign(DEMO_RC,body.enabled!==undefined?{enabled:body.enabled}:{},body.pin?{pin_set:true}:{},body.idle_minutes?{idle_minutes:body.idle_minutes}:{});rcInfo={...DEMO_RC};renderRemote();return true;}
 try{const r=await rcPost('/api/remote/setup',body);rcInfo={...r.info,local:true};renderRemote();notify('✓ '+r.message);return true;}catch(ex){notify('⚠ '+ex.message,true);return false;}
}
function pinSheet(mode){
 // mode: 'enter' = entra con il PIN, 'set' = scegli un PIN nuovo (solo dal PC)
 const d=$('rc-pin'),a=$('rc-pin-in'),b=$('rc-pin-in2');a.value='';b.value='';$('rc-pin-err').textContent='';
 b.hidden=mode!=='set';$('rc-pin-title').textContent=mode==='set'?'Scegli il PIN':'PIN del controllo remoto';
 $('rc-pin-text').textContent=mode==='set'?'6 cifre, non tutte uguali. Servirà ogni volta che controlli il PC da lontano: non usare quello di Windows.':'Inserisci il PIN di 6 cifre scelto sul PC.';
 $('rc-pin-ok').textContent=mode==='set'?'Salva':'Entra';d.dataset.mode=mode;d.showModal();setTimeout(()=>a.focus(),60);
}
async function pinSubmit(){
 const d=$('rc-pin'),pin=$('rc-pin-in').value.trim(),err=$('rc-pin-err');
 if(!/^\d{6}$/.test(pin)){err.textContent='Servono 6 cifre';return;}
 if(d.dataset.mode==='set'){
  if(pin!==$('rc-pin-in2').value.trim()){err.textContent='I due PIN non sono uguali';return;}
  if(await rcSetup({pin,enabled:true}))d.close();return;
 }
 $('rc-pin-ok').disabled=true;
 try{
  const s=demo?{token:'demo',monitors:[{id:0,name:'Schermo 1 (principale) · 2560×1440'},{id:1,name:'Schermo 2 · 1920×1080'}],idle_minutes:10}:await rcPost('/api/remote/start',{pin});
  d.close();rcOpen(s);
 }catch(ex){err.textContent=ex.message;$('rc-pin-in').select();}
 finally{$('rc-pin-ok').disabled=false;}
}
$('rc-pin-ok').addEventListener('click',pinSubmit);
$('rc-pin-cancel').addEventListener('click',()=>$('rc-pin').close());
['rc-pin-in','rc-pin-in2'].forEach(id=>$(id).addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();pinSubmit();}}));
$('rc-take').addEventListener('click',()=>{
 const i=rcInfo||{};
 if(!i.enabled){if(i.local){i.pin_set?rcSetup({enabled:true}).then(ok=>ok&&pinSheet('enter')):pinSheet('set');}
  else notify('Il controllo remoto è spento: si accende dal PC, in Schermo → Controllo e privacy.',true);return;}
 pinSheet('enter');
});
$('rc-enabled').addEventListener('click',e=>{e.preventDefault();const on=$('rc-enabled').getAttribute('aria-checked')!=='true';
 if(!rcInfo?.local){if(on){notify('Per sicurezza il controllo remoto si accende solo dal PC.',true);return;}
  (demo?Promise.resolve({info:{...DEMO_RC,enabled:false}}):rcPost('/api/remote/off',{})).then(r=>{rcInfo={...r.info,local:false};renderRemote();notify('✓ Controllo remoto spento');}).catch(ex=>notify('⚠ '+ex.message,true));return;}
 if(on&&!rcInfo.pin_set){pinSheet('set');return;}rcSetup({enabled:on});});
$('rc-pin-set').addEventListener('click',()=>pinSheet('set'));
$('rc-idle').addEventListener('change',()=>rcSetup({idle_minutes:+$('rc-idle').value}));
$('rc-live-end').addEventListener('click',async()=>{if(RC.on){rcClose();return;}
 try{const r=demo?{message:'Controllo terminato'}:await rcPost('/api/remote/end',{});notify('✓ '+r.message);loadRemote();}catch(ex){notify('⚠ '+ex.message,true);}});

function rcOpen(s){
 Object.assign(RC,{token:s.token,on:true,v:0,seq:0,mons:s.monitors||[],q:[],sending:false,cur:null,z:{s:1,x:0,y:0},idle:s.idle_minutes||10,lastIn:Date.now(),frames:[],bytes:[]});
 RC.pts.clear();RC.g=null;RC.latch.clear();
 const sel=$('rc-mon');sel.replaceChildren(...RC.mons.map(m=>{const o=el('option','',m.name);o.value=m.id;return o;}));
 if(RC.mons.length>1){const o=el('option','','Tutti gli schermi');o.value='all';sel.append(o);}sel.hidden=RC.mons.length<2;
 $('rc-q').value='balanced';$('rc-fps').value='10';let saved='';try{saved=localStorage.getItem('nexar.rcMode')||'';}catch(e){}rcMode(saved==='pad'?'pad':'touch');
 $('rc-keys').hidden=true;$('rc-kb').hidden=true;$('rc').classList.remove('bar-off');$('rc-show').hidden=true;
 rcMsg('');$('rc').showModal();rcLayout();rcLoop();rcIdleWatch();
 const coarse=matchMedia('(pointer:coarse)').matches,portrait=innerHeight>innerWidth;
 rcHint(!coarse?'Il mouse e la tastiera ora comandano il PC':portrait?'Gira il telefono per vederlo più grande · due dita = zoom':'Tocca = clic · tieni premuto = tasto destro · due dita = scorri o zoom');
 // In Telegram: niente chiusura col gesto verso il basso mentre trascini, e schermo intero dove si può
 if(tgApp){try{tgApp.disableVerticalSwipes?.();}catch(e){}try{tgApp.requestFullscreen?.();}catch(e){}}
 if(scrLiveOn)scrLive(false);if(rcInfo){rcInfo.active=true;renderRemote();}
}
async function rcClose(reason){
 if(!RC.on)return;RC.on=false;clearTimeout(RC.idleT);
 const tok=RC.token;RC.token='';
 if(tok&&!demo){try{await fetch('/api/remote/end',{method:'POST',headers:{...(tgInit?{'X-TG-Init-Data':tgInit}:{'X-PC-ECO-Key':key}),'Content-Type':'application/json'},body:'{}'});}catch(e){}}
 if($('rc').open)$('rc').close();
 if(RC.url.startsWith('blob:'))URL.revokeObjectURL(RC.url);RC.url='';$('rc-img').removeAttribute('src');
 if(tgApp){try{tgApp.enableVerticalSwipes?.();}catch(e){}try{if(tgApp.isFullscreen)tgApp.exitFullscreen?.();}catch(e){}}
 if(reason)notify(reason,true);loadRemote();
}
$('rc').addEventListener('cancel',e=>{e.preventDefault();});   // Esc va al PC, non chiude
$('rc').addEventListener('close',()=>{if(RC.on)rcClose();});
$('rc-end').addEventListener('click',()=>rcClose());
function rcMsg(html,btn){const m=$('rc-msg');if(!html){m.hidden=true;return;}m.innerHTML=html;m.hidden=false;
 if(btn){const b=el('button','btn primary',btn.label);b.type='button';b.addEventListener('click',btn.run);m.append(b);}}
let rcHintT=null;
function rcHint(t){const h=$('rc-hint');h.textContent=t;h.classList.add('show');clearTimeout(rcHintT);rcHintT=setTimeout(()=>h.classList.remove('show'),3800);}

// dimensioni: immagine "contenuta" nello spazio disponibile, poi zoom/spostamento con transform
function rcLayout(){
 const st=$('rc-stage').getBoundingClientRect(),z=$('rc-zoom');
 const k=Math.min(st.width/RC.w,st.height/RC.h);const w=RC.w*k,h=RC.h*k;
 RC.base={w,h,x:(st.width-w)/2,y:(st.height-h)/2};z.style.width=w+'px';z.style.height=h+'px';rcApplyZoom();
}
function rcApplyZoom(){
 const b=RC.base;if(!b)return;const st=$('rc-stage').getBoundingClientRect(),z=RC.z;
 if(z.s<=1.001){z.s=1;z.x=0;z.y=0;}
 else{const W=b.w*z.s,H=b.h*z.s;   // niente bordi vuoti quando ingrandito
  z.x=W<=st.width?(st.width-W)/2-b.x:Math.min(-b.x,Math.max(st.width-W-b.x,z.x));
  z.y=H<=st.height?(st.height-H)/2-b.y:Math.min(-b.y,Math.max(st.height-H-b.y,z.y));}
 $('rc-zoom').style.transform=`translate(${b.x+z.x}px,${b.y+z.y}px) scale(${z.s})`;rcDrawCursor();
}
addEventListener('resize',()=>{if(RC.on)rcLayout();});
function rcNorm(cx,cy){const r=$('rc-img').getBoundingClientRect();return{x:Math.min(1,Math.max(0,(cx-r.left)/r.width)),y:Math.min(1,Math.max(0,(cy-r.top)/r.height))};}
function rcDrawCursor(){
 const c=$('rc-cur');if(!RC.cur){c.hidden=true;return;}c.hidden=false;
 c.style.transform=`translate(${RC.cur.x*RC.base.w}px,${RC.cur.y*RC.base.h}px) scale(${1/RC.z.s})`;c.style.transformOrigin='2px 2px';
}

// fotogrammi: il PC risponde appena lo schermo cambia
async function rcLoop(){
 let fails=0;
 while(RC.on){
  if(demo){await new Promise(r=>setTimeout(r,800));if(!RC.on)break;if(!RC.seq){const u=demoShot();RC.w=1600;RC.h=900;RC.seq=1;$('rc-img').src=u;rcLayout();RC.cur=RC.cur||{x:.42,y:.4};rcDrawCursor();$('rc-stat').textContent='Anteprima';}continue;}
  try{
   const t0=performance.now();
   const r=await fetch(`/api/remote/frame?v=${RC.v}&seq=${RC.seq}`,{headers:rcHead(),cache:'no-store'});
   if(r.status===403||r.status===401){const o=await r.json().catch(()=>({}));rcClose(o.detail||'Sessione terminata');return;}
   if(!r.ok)throw new Error('HTTP '+r.status);
   let meta;
   if((r.headers.get('content-type')||'').startsWith('image/')){
    meta=JSON.parse(r.headers.get('x-remote-meta')||'{}');const blob=await r.blob();
    const u=URL.createObjectURL(blob);const im=$('rc-img');
    await new Promise(res=>{im.onload=im.onerror=res;im.src=u;});
    if(RC.url.startsWith('blob:'))URL.revokeObjectURL(RC.url);RC.url=u;RC.seq=meta.seq;
    if(meta.w!==RC.w||meta.h!==RC.h){RC.w=meta.w;RC.h=meta.h;rcLayout();}
    const now=performance.now();RC.frames.push(now);RC.bytes.push([now,blob.size]);
   }else meta=await r.json();
   RC.v=meta.v;fails=0;
   if(meta.cursor&&RC.mode==='touch'||meta.cursor&&!RC.cur){RC.cur={x:meta.cursor[0],y:meta.cursor[1]};rcDrawCursor();}
   if(meta.state==='locked')rcMsg('<b>Il PC è bloccato</b>Da qui non si può sbloccare: serve il PIN di Windows sul PC. Lo schermo torna appena viene sbloccato.');
   else if(!$('rc-msg').dataset.keep)rcMsg('');
   rcStats();
  }catch(ex){
   fails++;$('rc-stat').textContent='Connessione persa, riprovo…';
   await new Promise(r=>setTimeout(r,Math.min(4000,400*fails)));
  }
 }
}
function rcStats(){
 const now=performance.now();RC.frames=RC.frames.filter(t=>now-t<3000);RC.bytes=RC.bytes.filter(b=>now-b[0]<3000);
 const fps=RC.frames.length/3,kbs=RC.bytes.reduce((a,b)=>a+b[1],0)/3/1024;
 $('rc-stat').textContent=`${fps.toFixed(fps<10?1:0)} fps · ${kbs<1000?Math.round(kbs)+' KB/s':(kbs/1024).toFixed(1)+' MB/s'}`;
}
// comandi: in fila, uno alla volta (i movimenti si accorpano)
function rcSend(ev){
 if(!RC.on)return;RC.lastIn=Date.now();
 const last=RC.q[RC.q.length-1];if(ev.t==='move'&&last&&last.t==='move')RC.q[RC.q.length-1]=ev;else RC.q.push(ev);
 rcFlush();
}
async function rcFlush(){
 if(RC.sending||!RC.q.length||!RC.on)return;RC.sending=true;
 const batch=RC.q.splice(0,RC.q.length);
 try{if(!demo)await rcPost('/api/remote/input',{events:batch});}
 catch(ex){if(ex.status===403){rcClose(ex.message);return;}notify('⚠ '+ex.message,true);}
 finally{RC.sending=false;}
 if(RC.q.length)rcFlush();
}
function rcIdleWatch(){
 clearTimeout(RC.idleT);if(!RC.on)return;
 const left=RC.idle*60000-(Date.now()-RC.lastIn);
 if(left<65000){rcMsg('<b>Ancora lì?</b>Senza comandi la sessione si chiude fra un minuto.',{label:'Continua',run:()=>{rcSend({t:'alive'});delete $('rc-msg').dataset.keep;rcMsg('');}});$('rc-msg').dataset.keep='1';}
 RC.idleT=setTimeout(rcIdleWatch,Math.max(5000,Math.min(left-60000,30000)));
}
// impostazioni della sessione
async function rcConfig(body){
 if(demo){rcHint('Anteprima: impostazione non inviata');return;}
 try{await rcPost('/api/remote/config',body);RC.seq=0;}catch(ex){notify('⚠ '+ex.message,true);}
}
$('rc-mon').addEventListener('change',()=>{const v=$('rc-mon').value;rcConfig({mon:v==='all'?'all':+v});RC.z={s:1,x:0,y:0};});
$('rc-q').addEventListener('change',()=>rcConfig({quality:$('rc-q').value}));
$('rc-fps').addEventListener('change',()=>rcConfig({fps:+$('rc-fps').value}));
function rcMode(m){RC.mode=m;$('rc').classList.toggle('pad',m==='pad');document.querySelectorAll('#rc-mode button').forEach(b=>b.classList.toggle('on',b.dataset.mode===m));
 try{localStorage.setItem('nexar.rcMode',m);}catch(e){}}
document.querySelectorAll('#rc-mode button').forEach(b=>b.addEventListener('click',()=>{rcMode(b.dataset.mode);
 rcHint(b.dataset.mode==='pad'?'Muovi il dito per spostare il puntatore · tocca = clic · tieni premuto e muovi = trascina':'Tocca dove vuoi cliccare · tieni premuto = tasto destro');}));
$('rc-hide').addEventListener('click',()=>{$('rc').classList.add('bar-off');$('rc-show').hidden=false;setTimeout(rcLayout,30);});
$('rc-show').addEventListener('click',()=>{$('rc').classList.remove('bar-off');$('rc-show').hidden=true;setTimeout(rcLayout,30);});
$('rc-keys-btn').addEventListener('click',()=>{$('rc-keys').hidden=!$('rc-keys').hidden;$('rc-keys-btn').classList.toggle('on',!$('rc-keys').hidden);setTimeout(rcLayout,30);});
$('rc-kb-btn').addEventListener('click',()=>{const kb=$('rc-kb');kb.hidden=!kb.hidden;$('rc-kb-btn').classList.toggle('on',!kb.hidden);
 if(!kb.hidden){const t=$('rc-text');t.value=' ';RC.kbPrev=' ';t.focus();}setTimeout(rcLayout,300);});
// tasti speciali e "blocca" di Ctrl/Alt/Maiusc/Win per il tasto dopo
function rcMods(extra){const m=[...RC.latch,...(extra?[extra]:[])];RC.latch.clear();document.querySelectorAll('[data-latch]').forEach(b=>b.classList.remove('on'));return m;}
document.querySelectorAll('#rc [data-k]').forEach(b=>b.addEventListener('click',()=>{rcSend({t:'key',k:b.dataset.k,mods:rcMods(b.dataset.m)});if(navigator.vibrate)navigator.vibrate(8);}));
document.querySelectorAll('[data-latch]').forEach(b=>b.addEventListener('click',()=>{const m=b.dataset.latch;RC.latch.has(m)?RC.latch.delete(m):RC.latch.add(m);b.classList.toggle('on',RC.latch.has(m));}));
// scrittura dal telefono: si manda solo la differenza (funziona anche con correttore e dettatura)
function rcTextOut(s){
 if(!s)return;
 if(RC.latch.size&&s.length===1&&/[a-z0-9]/i.test(s)){rcSend({t:'key',k:s.toLowerCase(),mods:rcMods()});return;}
 rcSend({t:'text',s});
}
$('rc-text').addEventListener('input',()=>{
 const t=$('rc-text'),cur=t.value,prev=RC.kbPrev;let p=0;while(p<cur.length&&p<prev.length&&cur[p]===prev[p])p++;
 for(let i=0;i<prev.length-p;i++)rcSend({t:'key',k:'backspace',mods:[]});
 rcTextOut(cur.slice(p));
 if(!cur.length||cur.length>80){t.value=' ';}RC.kbPrev=t.value;
});
$('rc-text').addEventListener('keydown',e=>{
 if(e.key==='Enter'){e.preventDefault();rcSend({t:'key',k:'enter',mods:rcMods()});$('rc-text').value=' ';RC.kbPrev=' ';}
 else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Tab','Escape'].includes(e.key)){e.preventDefault();rcSend({t:'key',k:{ArrowLeft:'left',ArrowRight:'right',ArrowUp:'up',ArrowDown:'down',Tab:'tab',Escape:'esc'}[e.key],mods:rcMods()});}
});
// tastiera vera (dal computer): tutto al PC, anche Esc
const RC_KEYMAP={Enter:'enter',Escape:'esc',Tab:'tab',Backspace:'backspace',Delete:'delete',ArrowLeft:'left',ArrowRight:'right',ArrowUp:'up',ArrowDown:'down',
 Home:'home',End:'end',PageUp:'pageup',PageDown:'pagedown',Insert:'insert',ContextMenu:'menu',' ':'space'};
document.addEventListener('keydown',e=>{
 if(!RC.on||!$('rc').open||e.target.closest?.('#rc-kb,select,#rc-pin'))return;
 if(['Control','Alt','Shift','Meta','AltGraph','CapsLock'].includes(e.key))return;
 const altgr=e.getModifierState&&e.getModifierState('AltGraph');
 const mods=altgr?[]:[e.ctrlKey&&'ctrl',e.altKey&&'alt',e.shiftKey&&'shift',e.metaKey&&'win'].filter(Boolean);
 let k=RC_KEYMAP[e.key]||(/^F\d{1,2}$/.test(e.key)?e.key.toLowerCase():'');
 if(!k&&e.key.length===1){
  if(!mods.some(m=>m!=='shift')){e.preventDefault();rcSend({t:'text',s:e.key});return;}
  k=/^[a-z0-9]$/i.test(e.key)?e.key.toLowerCase():(e.code.startsWith('Key')?e.code.slice(3).toLowerCase():e.code.startsWith('Digit')?e.code.slice(5):'');
 }
 if(!k)return;e.preventDefault();rcSend({t:'key',k,mods});
},true);
// mouse, tocco e touchpad
const stage=$('rc-stage');
stage.addEventListener('contextmenu',e=>e.preventDefault());
stage.addEventListener('wheel',e=>{if(!RC.on)return;e.preventDefault();
 if(e.ctrlKey){rcZoomAt(e.clientX,e.clientY,RC.z.s*(e.deltaY<0?1.15:1/1.15));return;}
 const n=rcNorm(e.clientX,e.clientY),f=e.deltaMode===1?40:1;rcSend({t:'wheel',x:n.x,y:n.y,dy:Math.round(-e.deltaY*f*1.2),dx:Math.round(e.deltaX*f*1.2)});},{passive:false});
function rcZoomAt(cx,cy,s){
 const st=$('rc-stage').getBoundingClientRect(),b=RC.base,z=RC.z;s=Math.min(5,Math.max(1,s));
 const px=(cx-st.left-b.x-z.x)/z.s,py=(cy-st.top-b.y-z.y)/z.s;   // punto sotto le dita
 z.x=cx-st.left-b.x-px*s;z.y=cy-st.top-b.y-py*s;z.s=s;rcApplyZoom();
}
function rcPadMove(dx,dy){
 const r=$('rc-img').getBoundingClientRect(),sp=Math.hypot(dx,dy),acc=1.1+Math.min(2.4,sp/14);   // più veloce = va più lontano
 const c=RC.cur||{x:.5,y:.5};RC.cur={x:Math.min(1,Math.max(0,c.x+dx*acc/r.width)),y:Math.min(1,Math.max(0,c.y+dy*acc/r.height))};
 rcDrawCursor();rcSend({t:'move',x:RC.cur.x,y:RC.cur.y});
 if(RC.z.s>1){const cr=$('rc-cur').getBoundingClientRect(),st=$('rc-stage').getBoundingClientRect(),m=40;   // lo zoom segue il puntatore
  if(cr.left<st.left+m)RC.z.x+=st.left+m-cr.left;else if(cr.right>st.right-m)RC.z.x-=cr.right-st.right+m;
  if(cr.top<st.top+m)RC.z.y+=st.top+m-cr.top;else if(cr.bottom>st.bottom-m)RC.z.y-=cr.bottom-st.bottom+m;rcApplyZoom();}
}
const BTN=['left','middle','right'];
stage.addEventListener('pointerdown',e=>{
 if(!RC.on||e.target.closest('.rc-msg'))return;stage.setPointerCapture(e.pointerId);
 if(e.pointerType==='mouse'){const n=rcNorm(e.clientX,e.clientY);RC.cur=n;rcDrawCursor();rcSend({t:'down',b:BTN[e.button]||'left',x:n.x,y:n.y});return;}
 RC.pts.set(e.pointerId,{x:e.clientX,y:e.clientY,x0:e.clientX,y0:e.clientY});
 if(RC.pts.size===1){
  const g=RC.g={kind:'one',t0:performance.now(),x0:e.clientX,y0:e.clientY,moved:false,drag:false,held:false};
  g.timer=setTimeout(()=>{if(RC.g!==g||g.moved)return;g.held=true;if(navigator.vibrate)navigator.vibrate(18);
   if(RC.mode==='touch'){const n=rcNorm(g.x0,g.y0);rcSend({t:'click',b:'right',x:n.x,y:n.y});rcHint('Tasto destro');}
   else{g.drag=true;rcSend({t:'down',b:'left',x:RC.cur?.x??.5,y:RC.cur?.y??.5});rcHint('Trascina');}},520);
 }else if(RC.pts.size===2){
  const g=RC.g;if(g){clearTimeout(g.timer);if(g.drag)rcSend({t:'up',b:'left'});}
  const [a,b]=[...RC.pts.values()];RC.g={kind:'two',d0:Math.hypot(a.x-b.x,a.y-b.y),s0:RC.z.s,mx:(a.x+b.x)/2,my:(a.y+b.y)/2,mode:'',t0:performance.now(),acc:0};
 }
});
stage.addEventListener('pointermove',e=>{
 if(!RC.on)return;
 if(e.pointerType==='mouse'){const n=rcNorm(e.clientX,e.clientY);RC.cur=n;rcDrawCursor();rcSend({t:'move',x:n.x,y:n.y});return;}
 const p=RC.pts.get(e.pointerId);if(!p)return;const dx=e.clientX-p.x,dy=e.clientY-p.y;p.x=e.clientX;p.y=e.clientY;const g=RC.g;if(!g)return;
 if(g.kind==='one'){
  if(!g.moved&&Math.hypot(e.clientX-g.x0,e.clientY-g.y0)>9){g.moved=true;clearTimeout(g.timer);
   if(RC.mode==='touch'&&!g.held){const n=rcNorm(g.x0,g.y0);g.drag=true;rcSend({t:'down',b:'left',x:n.x,y:n.y});}}
  if(!g.moved)return;
  if(RC.mode==='touch'){if(g.drag){const n=rcNorm(e.clientX,e.clientY);RC.cur=n;rcDrawCursor();rcSend({t:'move',x:n.x,y:n.y});}}
  else rcPadMove(dx,dy);
 }else if(g.kind==='two'&&RC.pts.size===2){
  const [a,b]=[...RC.pts.values()];const d=Math.hypot(a.x-b.x,a.y-b.y),mx=(a.x+b.x)/2,my=(a.y+b.y)/2;
  if(!g.mode){if(Math.abs(d-g.d0)>28)g.mode='zoom';else if(Math.hypot(mx-g.mx,my-g.my)>10)g.mode=RC.z.s>1?'pan':'scroll';}
  if(g.mode==='zoom'){rcZoomAt(mx,my,g.s0*d/g.d0);RC.z.x+=mx-g.mx;RC.z.y+=my-g.my;rcApplyZoom();}
  else if(g.mode==='pan'){RC.z.x+=mx-g.mx;RC.z.y+=my-g.my;rcApplyZoom();}
  else if(g.mode==='scroll'){g.acc+=my-g.my;const step=Math.trunc(g.acc/6);if(step){g.acc-=step*6;const n=RC.cur||rcNorm(mx,my);rcSend({t:'wheel',x:n.x,y:n.y,dy:step*40});}}
  g.mx=mx;g.my=my;
 }
});
function rcPointerEnd(e){
 if(!RC.on)return;
 if(e.pointerType==='mouse'){const n=rcNorm(e.clientX,e.clientY);rcSend({t:'up',b:BTN[e.button]||'left',x:n.x,y:n.y});return;}
 if(!RC.pts.has(e.pointerId))return;RC.pts.delete(e.pointerId);const g=RC.g;if(!g)return;
 if(g.kind==='one'){
  clearTimeout(g.timer);
  if(e.type==='pointercancel'){if(g.drag)rcSend({t:'up',b:'left'});RC.g=null;return;}
  if(g.drag){const n=RC.mode==='touch'?rcNorm(e.clientX,e.clientY):RC.cur;rcSend({t:'up',b:'left',x:n.x,y:n.y});}
  else if(!g.moved&&!g.held){
   if(RC.mode==='touch'){const n=rcNorm(e.clientX,e.clientY);RC.cur=n;rcDrawCursor();rcSend({t:'click',b:'left',x:n.x,y:n.y});}
   else rcSend({t:'click',b:'left',x:RC.cur?.x??.5,y:RC.cur?.y??.5});
  }
  RC.g=null;
 }else if(g.kind==='two'){
  if(!g.mode&&performance.now()-g.t0<300&&RC.mode==='pad'){rcSend({t:'click',b:'right',x:RC.cur?.x??.5,y:RC.cur?.y??.5});rcHint('Tasto destro');}
  if(RC.pts.size===0)RC.g=null;else RC.g={kind:'rest'};   // un dito rimasto: non diventa un clic
 }else if(RC.pts.size===0)RC.g=null;
}
stage.addEventListener('pointerup',rcPointerEnd);stage.addEventListener('pointercancel',rcPointerEnd);
function renderHistory(list){
 const box=$('game-history');box.replaceChildren();
 if(!list.length){$('hist-sub').textContent='Durata, temperature massime e consumo di ogni sessione';box.append(el('p','muted','Ancora nessuna partita: la prima comparirà qui.'));return;}
 $('hist-sub').textContent=`${list.length} ${list.length>1?'sessioni':'sessione'} · ${playtime(list.reduce((a,h)=>a+h.elapsed,0))} in tutto`;
 list.forEach(h=>{
  const row=el('div','hist-row');const name=h.game||'Gaming';
  const ico=el('span','hist-ico',initials(name));ico.style.setProperty('--h',hue(name));
  if(h.gid?.startsWith('steam-'))coverUrl(h.gid,'header').then(u=>{if(u){ico.style.backgroundImage=`url("${u}")`;ico.textContent='';}});
  const t=el('div');t.append(el('b','',h.game||'Gaming senza gioco riconosciuto'),
   el('small','',new Date(h.start*1000).toLocaleString('it-IT',{weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})));
  const chips=el('div','hist-chips');
  [[playtime(h.elapsed),'clock'],h.cpu_temp_max!=null&&[`CPU ${Math.round(h.cpu_temp_max)}°`,'cpu'],h.gpu_temp_max!=null&&[`GPU ${Math.round(h.gpu_temp_max)}°`,'gpu'],
   h.kwh&&[`${nf(h.kwh,2)} kWh · ${eur(h.cost)}`,'plug']].filter(Boolean)
   .forEach(([txt,ic])=>{const c=el('span');c.append(icon(ic),document.createTextNode(txt));chips.append(c);});
  row.append(ico,t,chips);box.append(row);
 });
}
function setHeroArt(gid){
 if(heroArt===(gid||''))return;heroArt=gid||'';
 const art=$('game-hero-art'),logo=$('game-logo'),hero=$('game-hero');
 art.style.backgroundImage='';art.classList.remove('img');logo.hidden=true;hero.classList.remove('with-logo');
 art.style.setProperty('--h',hue(gid||'nexar'));
 if(!gid?.startsWith('steam-'))return;
 coverUrl(gid,'hero').then(u=>{if(u&&heroArt===gid){art.style.backgroundImage=`url("${u}")`;art.classList.add('img');}});
 coverUrl(gid,'logo').then(u=>{if(u&&heroArt===gid){logo.onload=()=>{logo.hidden=false;hero.classList.add('with-logo');logo.classList.remove('swap');void logo.offsetWidth;logo.classList.add('swap');};logo.src=u;}});
}
function setHeroBtn(id,spec){
 const b=$(id);b.hidden=!spec;if(!spec)return;const [label,ic,act]=spec;
 b.dataset.act=act;b.querySelector('use').setAttribute('href','#i-'+ic);b.querySelector('span').textContent=label;b.classList.toggle('exit',act==='exit');
}
function renderGamingLive(s){
 const b=s.boost||(demo?DEMO_GAMING.boost:null);if(!b)return;
 const on=!!b.active,ses=b.session,run=b.running;
 $('boost-state').textContent=on?'ATTIVE':'SPENTE';$('boost-state').classList.toggle('on',on);
 const live=[on&&b.game&&'⚡ '+b.game+' a priorità alta',...(b.closed||[]).map(n=>'⛔ '+n.replace('.exe','')+' chiusa'),...(b.lowered||[]).map(n=>'🐢 '+n.replace('.exe','')+' rallentata'),...(b.tweaks||[]).map(t=>'✓ '+t)].filter(Boolean);
 $('boost-live').replaceChildren(...(on?live.map(t=>el('span','',t)):[]));
 const last=(gameData?.games||[]).find(g=>!g.hidden&&g.last);
 let state,title,sub,main,second=null,gid='';
 if(on&&(ses?.game||run)){state='IN GIOCO';title=ses?.game||run.name;gid=ses?.gid||run?.id;sub='Gaming attivo: il gioco ha la precedenza su tutto il resto.';main=['Esci da Gaming','x','exit'];}
 else if(on){state='GAMING ATTIVO';title='Aspetto il gioco';sub='Apri un gioco: gli do la priorità appena parte.';main=['Esci da Gaming','x','exit'];}
 else if(run){state='GIOCO APERTO';title=run.name;gid=run.id;sub='Gaming è spento: attivalo per dare la precedenza al gioco.';main=['Attiva Gaming','game','on'];}
 else if(last){state='PRONTO';title=last.name;gid=last.id;
  sub=`Ultima partita ${ago(last.last)}`+(last.playtime?` · ${playtime(last.playtime)} con NEXAR`:'')+'. Premi Gioca: NEXAR prepara il PC e apre il gioco.';
  main=['Gioca','play','launch:'+last.id];second=['Solo Gaming','game','on'];}
 else{state='PRONTO';title='Pronto a giocare';sub='Apri un gioco: NEXAR attiva Gaming da sola e rimette tutto com’era quando lo chiudi.';main=['Attiva Gaming','game','on'];}
 $('game-hero').classList.toggle('live',on);
 particles();
 $('game-state').lastElementChild.textContent=state;swapIn($('game-title'),title);swapIn($('game-sub'),sub);
 $('game-timer').textContent=on&&ses?'⏱ '+duration(ses.elapsed):'';
 setHeroBtn('game-main',main);setHeroBtn('game-second',second);setHeroArt(gid);
 // statistiche dal vivo (con i massimi della partita in corso)
 const mx=(v,k)=>on&&ses&&ses[k]!=null?` · max ${Math.round(ses[k])}°`:'';
 countUp($('gs-cpu'),s.cpu_temp,deg);$('gs-cpu').closest('.gstat').classList.toggle('hot',(s.cpu_temp||0)>=85);$('gs-cpu-sub').textContent=`${pct(s.cpu)} di carico`+mx(s.cpu_temp,'cpu_temp_max');setBar('gs-cpu-bar',s.cpu_temp);
 countUp($('gs-gpu'),s.gpu_temp,deg);$('gs-gpu').closest('.gstat').classList.toggle('hot',(s.gpu_temp||0)>=83);$('gs-gpu-sub').textContent=`${pct(s.gpu)} di carico`+mx(s.gpu_temp,'gpu_temp_max');setBar('gs-gpu-bar',s.gpu_temp);
 const pw=s.power||{};countUp($('gs-power'),pw.total,v=>typeof v==='number'?Math.round(v)+' W':'—');
 $('gs-power-sub').textContent=on&&ses?`${nf(ses.kwh,2)} kWh in questa partita`:typeof pw.amps==='number'?`${nf(pw.amps,2)} A alla presa`:'—';
 setBar('gs-power-bar',pw.total,pw.psu_watts||750);
 const lvl=s.fans_level||'normal',fans=(s.fans||[]).filter(f=>f.rpm>0);
 $('gs-fan').textContent=FAN_NAMES[lvl]||'—';$('gs-fan-sub').textContent=fans.length?`${Math.round(fans.reduce((a,f)=>a+f.rpm,0)/fans.length)} giri/min medi`:'—';
 setBar('gs-fan-bar',FAN_BAR[lvl]??50);
 if(gameData&&(gameData.boost?.running?.id||'')!==(run?.id||'')){gameData.boost={...gameData.boost,running:run};renderLibrary();}
}
async function launchGame(g){
 fxQuiet=Date.now()+15000;
 fx('launch','AVVIO',g.name,g.cover?await coverUrl(g.id,'hero'):'');
 if(demo){notify('Anteprima: comando non attivo.');return;}
 try{const r=await req('/api/gaming/launch','POST',{id:g.id});notify('🎮 '+r.message);await refresh();}catch(ex){notify('⚠ '+ex.message,true);}
}
async function saveGaming(change){
 if(demo){notify('Anteprima: comando non attivo.');return;}
 try{const r=await req('/api/gaming/settings','POST',change);notify('✓ '+r.message);await loadGaming();}catch(ex){notify('⚠ '+ex.message,true);}
}
async function heroAction(act,src){
 if(!act)return;
 if(act==='exit')return action('normal',src);
 if(act==='on')return action('gaming',src);
 if(act.startsWith('launch:')){const g=(gameData?.games||[]).find(x=>x.id===act.slice(7));if(g)launchGame(g);}
}
$('game-hero').addEventListener('pointermove',e=>{if(e.pointerType!=='mouse'||calm.matches)return;const r=e.currentTarget.getBoundingClientRect();
 e.currentTarget.style.setProperty('--px',((e.clientX-r.left)/r.width-.5).toFixed(3));e.currentTarget.style.setProperty('--py',((e.clientY-r.top)/r.height-.5).toFixed(3));},{passive:true});
$('game-hero').addEventListener('pointerleave',e=>{e.currentTarget.style.setProperty('--px',0);e.currentTarget.style.setProperty('--py',0);});
document.querySelectorAll('[data-boost]').forEach(t=>t.addEventListener('click',e=>{e.preventDefault();saveGaming({[t.dataset.boost]:t.getAttribute('aria-checked')!=='true'});}));
document.querySelectorAll('#game-fans [data-fans]').forEach(b=>b.addEventListener('click',()=>saveGaming({fans:b.dataset.fans})));
$('game-main').addEventListener('click',()=>heroAction($('game-main').dataset.act,$('game-main')));
$('game-second').addEventListener('click',()=>heroAction($('game-second').dataset.act,$('game-second')));
$('lib-search').addEventListener('input',()=>renderLibrary());
document.querySelectorAll('#lib-sort button').forEach(b=>b.addEventListener('click',()=>{libSort=b.dataset.sort;try{localStorage.setItem('nexar.libSort',libSort);}catch(e){}renderLibrary(true);}));
$('lib-reload').addEventListener('click',()=>loadGaming(true,true));
$('lib-hidden').addEventListener('click',()=>{showHidden=!showHidden;renderLibrary();});
$('boost-reload').addEventListener('click',()=>loadGaming());
$('upd-check').addEventListener('click',()=>{updLater='';try{sessionStorage.removeItem('nexar_upd_later');}catch(e){}post('/api/update/check',{});});
$('upd-install').addEventListener('click',()=>startUpdate());
$('links-refresh').addEventListener('click',()=>post('/api/discover',{}));
$('fans-upgrade-btn').addEventListener('click',()=>post('/api/fans/setup',{}));
$('logout').addEventListener('click',()=>{sessionStorage.removeItem('pc_eco_key');key='';loginScreen(true);});
$('auto-toggle').addEventListener('click',toggleAuto);
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>action(b.dataset.action,b)));

if(demo){$('demo-strip').hidden=false;loginScreen(false);[7,9,8,12,11,17,14,13,15,12,18,15,12,10,9,11,13].forEach((v,i)=>{hist.cpu.push(v);hist.gpu.push(4+i%5);hist.power.push(98+v*1.4);});render(statusDemo);}
else if(key||tgInit){loginScreen(false);refresh();}else loginScreen(true);
navigate('home');
setInterval(()=>{if(!document.hidden)refresh();},4000);
/* ---------- barra della finestra (solo nell'app per Windows) ---------- */
// La barra grigia di Windows non c'è più: qui ci sono trascinamento, Snap, doppio clic per
// ingrandire e ridimensionamento dal bordo alto.
function setupWinbar(){
 const api=window.pywebview?.api;if(!api?.win_drag||$('winbar'))return;
 const root=document.documentElement;root.classList.add('in-desktop');
 const bar=document.createElement('div');bar.id='winbar';bar.className='winbar';
 bar.innerHTML=`<div class="wb-btns">
  <button type="button" class="wb-btn" data-wb="min" title="Riduci a icona" aria-label="Riduci a icona"><svg viewBox="0 0 12 12"><path d="M2 6h8"/></svg></button>
  <button type="button" class="wb-btn" data-wb="max" title="Ingrandisci" aria-label="Ingrandisci"><svg viewBox="0 0 12 12"><rect class="wb-max-in" x="1.75" y="1.75" width="8.5" height="8.5" rx="2"/><path class="wb-max-out" d="M3.75 3.25V2.9c0-.6.5-1.15 1.15-1.15h4.2c.6 0 1.15.5 1.15 1.15v4.2c0 .6-.5 1.15-1.15 1.15h-.35"/><rect class="wb-max-out" x="1.75" y="3.75" width="6.5" height="6.5" rx="1.6"/></svg></button>
  <button type="button" class="wb-btn close" data-wb="close" title="Chiudi: NEXAR resta attivo vicino all'orologio" aria-label="Chiudi"><svg viewBox="0 0 12 12"><path d="M2.5 2.5l7 7M9.5 2.5l-7 7"/></svg></button></div>`;
 const edges=document.createElement('div');edges.className='wb-edges';edges.setAttribute('aria-hidden','true');
 edges.innerHTML='<i data-edge="top"></i><i data-edge="topleft"></i><i data-edge="topright"></i>';
 document.body.append(bar,edges);
 const sync=()=>api.win_state().then(s=>{root.classList.toggle('win-max',!!s.max);
  const m=bar.querySelector('[data-wb=max]');m.title=s.max?'Ripristina':'Ingrandisci';m.setAttribute('aria-label',m.title);}).catch(()=>{});
 let last=0;
 const drag=e=>{
  if(e.button!==0||e.target.closest('button,a,input'))return;e.preventDefault();
  const now=performance.now();if(now-last<400){last=0;api.win_toggle_max().then(()=>setTimeout(sync,250));return;}
  last=now;api.win_drag();
 };
 bar.addEventListener('mousedown',drag);
 // si trascina anche dal logo e dalla zona del titolo della pagina
 document.querySelectorAll('.rail .brand,.main>.top').forEach(n=>n.addEventListener('mousedown',drag));
 edges.addEventListener('mousedown',e=>{const k=e.target.dataset.edge;if(k&&e.button===0){e.preventDefault();api.win_resize(k);}});
 bar.addEventListener('click',e=>{const b=e.target.closest('[data-wb]');if(!b)return;const k=b.dataset.wb;
  ({min:()=>api.win_min(),max:()=>api.win_toggle_max(),close:()=>api.win_close()})[k]?.().then?.(()=>setTimeout(sync,250));});
 addEventListener('resize',()=>{clearTimeout(sync.t);sync.t=setTimeout(sync,60);});
 addEventListener('scroll',()=>bar.classList.toggle('scrolled',scrollY>6),{passive:true});
 sync();
}
addEventListener('pywebviewready',setupWinbar);
if(window.pywebview?.api)setupWinbar();
})();
