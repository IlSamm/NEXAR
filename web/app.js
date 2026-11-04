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
 gaming:['Gaming','I tuoi giochi, il PC pronto a giocare e le statistiche di ogni partita.'],
 optimize:['Ottimizza','Pulizia, programmi pesanti, file grandi, dischi e rete.'],
 links:['Collegamenti','Programmi trovati e collegati da soli.'],
 settings:['Impostazioni','AI ECO, energia, Telegram e registro.'],
 more:['Altro','Consumi, accensione, collegamenti e impostazioni.'],
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
 sc.onload=()=>{const w=window.Telegram?.WebApp;if(!w)return;w.ready();w.expand();try{w.setHeaderColor('#090b0f');w.setBackgroundColor('#090b0f');}catch(e){}};
 document.head.append(sc);
}
let current=null,busy=false,rgbTouched=false,schedKind='shutdown';
const hist={cpu:[],gpu:[],power:[],ram:[],fan:[]};let curView='home';
const COMP={cpu:'#38bdf8',gpu:'#a78bfa',board:'#94a3b8',ram:'#2dd4bf',disks:'#fbbf24',cooling:'#34d399',rgb:'#f472b6',usb:'#fb923c',monitor:'#e2e8f0'};
const statusDemo={connected:true,version:'1.0.0',update:{supported:true,auto:true,available:false,checked_at:'2026-11-03T21:10:00'},mode:'gaming',fans_level:'max',fans_levels_ready:true,cpu:12,cpu_temp:46,gpu:6,gpu_temp:38,gpu_watts:24,ram:34,ram_used:10.9,ram_total:31.1,eco_cpu_max_percent:90,
 fans:[{name:'CPU Fan',rpm:930},{name:'System Fan #1',rpm:0},{name:'System Fan #2',rpm:740},{name:'System Fan #3',rpm:750},{name:'Pump Fan',rpm:2400}],
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
function notify(txt,error=false){const e=$('toast');e.textContent=txt;e.classList.toggle('error',error);e.classList.add('show');clearTimeout(notify.timer);notify.timer=setTimeout(()=>e.classList.remove('show'),4800);}
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
 if(view==='settings'&&!demo){loadSettings();loadEvents();}
 if(view==='lights')loadRgbDevices();
 if(view==='optimize')loadOptimize();
 if(view==='gaming')loadGaming(false,true);
 const tab=['power','links','settings','energy','lights'].includes(view)&&!document.querySelector(`.tabbar [data-view="${view}"]`)?'more':view;
 document.querySelectorAll('.rail-nav [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
 document.querySelectorAll('.tabbar [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===tab));
 document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+view));
 curView=view;setZone();
 document.querySelectorAll('.page.active .tabs').forEach(inkTabs);
 $('page-title').textContent=titles[view][0];$('page-desc').textContent=titles[view][1];
 window.scrollTo({top:0});
}
function setBar(id,v,max=100){$(id).style.width=(typeof v==='number'?Math.max(0,Math.min(100,v/max*100)):0)+'%';}
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
function push(arr,v){if(typeof v==='number'){arr.push(v);if(arr.length>60)arr.shift();}}

/* ---------- rendering ---------- */
function render(s){
 current=s;
 modeFx(s.mode);
 const eco=s.mode==='eco';
 document.querySelectorAll('.mode-opt').forEach(b=>b.classList.toggle('selected',b.classList.contains(s.mode)));
 $('mode-desc').textContent=eco?`CPU al ${s.eco_cpu_max_percent??'—'}%, monitor spento dopo ${Math.round((s.monitor_timeout_seconds||60)/60)} min`
  :s.mode==='gaming'?'CPU sempre al massimo, monitor mai spento, LED accesi':'Piano energetico originale di Windows';
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
 $('hw-cpu').textContent=deg(s.cpu_temp);$('hw-gpu').textContent=deg(s.gpu_temp);setBar('hw-cpu-bar',s.cpu_temp,95);setBar('hw-gpu-bar',s.gpu_temp,90);
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
 $('upd-auto').setAttribute('aria-checked',u.auto===false?'false':'true');
 const running=job?.state==='running'||['downloading','installing'].includes(u.status);
 $('upd-install').hidden=!u.available;$('upd-install').disabled=running;
 $('upd-install').textContent=running?(u.message||'Installazione…'):`Installa ${u.latest||''}`;
 $('upd-text').textContent=!u.supported?'Disponibili solo nell\'app installata':u.status==='error'?u.message
  :u.available?`Nuova versione ${u.latest} pronta`:u.checked_at?`Aggiornato · controllato ${u.checked_at.slice(11,16)}`:'Controllo al primo avvio';
}
let splashGone=false;
function hideSplash(){
 if(splashGone)return;splashGone=true;
 setTimeout(()=>{$('splash').classList.add('gone');setTimeout(()=>$('splash').remove(),600);},Math.max(0,1100-performance.now()));
}
function renderFans(fans){
 const box=$('fan-list');box.replaceChildren();
 if(!fans.length){box.append(el('p','muted','Nessun RPM disponibile: collega i sensori in Collegamenti.'));return;}
 const spinning=fans.filter(f=>f.rpm>0),empty=fans.length-spinning.length;
 spinning.forEach(f=>{
  const c=el('div','fan');const top=el('div','fan-top');top.append(el('span','',f.name.replace('CPU Fan','Radiatore (CPU Fan)').replace('Pump Fan','Pompa')),el('b','',`${f.rpm} RPM`));
  const bar=el('div','bar');const fill=el('span');fill.style.width=Math.min(100,f.rpm/(/pump/i.test(f.name)?3000:1800)*100)+'%';bar.append(fill);c.append(top,bar);box.append(c);
 });
 if(empty){const c=el('div','fan idle');const top=el('div','fan-top');top.append(el('span','','Connettori liberi'),el('b','',`${empty}`));c.append(top);box.append(c);}
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
  const items=[...(p.items||[])].sort((a,b)=>b.watts-a.watts);
  const stack=$('e-stack'),list=$('e-list');stack.replaceChildren();list.replaceChildren();
  items.concat([{key:'loss',name:'Perdite alimentatore',watts:p.loss,source:'calcolato',detail:`calore dell'alimentatore`}]).forEach(i=>{
   const seg=el('span',i.key==='loss'?'loss':'');seg.style.setProperty('--c',COMP[i.key]||'#64748b');seg.style.flexGrow=i.watts;seg.title=`${i.name}: ${nf(i.watts)} W`;stack.append(seg);
   const row=el('div','brk');const sw=el('i',i.key==='loss'?'loss':'');sw.style.setProperty('--c',COMP[i.key]||'#64748b');
   const txt=el('div');const name=el('b','',i.name);name.append(el('em',i.source==='misurato'?'m':'',i.source));txt.append(name,el('small','',i.detail||''));
   row.append(sw,txt,el('strong','',(i.source==='misurato'?'':'~')+nf(i.watts,i.watts<10?1:0)+' W'));list.append(row);
  });
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
 const box=$('links-list');box.replaceChildren();
 items.forEach(r=>{
  const row=el('div','link-row');const txt=el('div','link-text');txt.append(el('strong','',r.name),el('small','',r.detail));
  const [word,cls]=LEVELS[r.level]||LEVELS.missing;const ico=el('div','link-ico');ico.append(icon(LINK_ICONS[r.key]||'link'));
  row.append(ico,txt,el('b','state '+cls,word));
  const a=current?.remote?null:linkAction(r,jobs);
  if(a){const b=el('button','btn small '+(a.primary?'primary':''),a.running?'In corso…':a.label);b.type='button';b.disabled=!!a.running;b.addEventListener('click',a.run);row.append(b);}
  box.append(row);
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
  data.devices.forEach(d=>{
   const row=el('div','rgb-dev');const c=el('input');c.type='color';c.value=d.color||$('rgb-color').value;c.setAttribute('aria-label','Colore '+d.name);
   const b=el('button','btn small','Applica');b.type='button';b.addEventListener('click',()=>applyColor(c.value,d.key));
   const t=el('div');t.append(el('b','',d.name),el('small','',d.leds?`circa ${d.leds} LED`:'periferica'));row.append(t,c,b);box.append(row);
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
const FIELDS={'cfg-cpu':'eco_cpu_max_percent','cfg-monitor':'monitor_timeout_seconds','cfg-delay':'restore_delay_seconds','cfg-cpu-alert':'cpu_temp_alert','cfg-gpu-alert':'gpu_temp_alert',
 'cfg-price':'energy_price_cents','cfg-psu':'psu_watts','cfg-monitor-w':'monitor_watts','cfg-extra':'extra_watts'};
async function loadSettings(){
 if((!key&&!tgInit)||demo)return;
 try{
  const s=await req('/api/settings');
  Object.entries(FIELDS).forEach(([id,f])=>$(id).value=s[f]);$('cfg-psu-class').value=s.psu_class;$('cfg-gaming-fans').value=s.gaming_fans;$('cfg-alerts').checked=s.alerts_enabled;
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
$('settings-form').addEventListener('submit',async ev=>{
 ev.preventDefault();if(demo){notify('Anteprima: nessuna impostazione modificata.');return;}if(!key&&!tgInit)return;
 const fields={alerts_enabled:$('cfg-alerts').checked,psu_class:$('cfg-psu-class').value,gaming_fans:$('cfg-gaming-fans').value};
 Object.entries(FIELDS).forEach(([id,f])=>fields[f]=Number.parseInt($(id).value,10));
 try{await req('/api/settings','POST',fields);notify('✓ Impostazioni salvate.');await loadEvents();await refresh();}catch(ex){notify('⚠ '+ex.message,true);}
});
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
 net:{at:Date.now()/1000,router:{host:'192.168.0.1',ms:1,loss:0},internet:{host:'1.1.1.1',ms:21,loss:0},google:{host:'8.8.8.8',ms:22,loss:0},dns_ms:35,quality:'ottima'}};
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
 $('opt-score-label').textContent=h.score>=85?'Ottimo':h.score>=65?'Buono':'Da migliorare';
 $('opt-health').className='health'+(h.score<65?' low':h.score<85?' mid':'')+($('opt-health').classList.contains('scanning')?' scanning':'');
 swapIn($('opt-title'),!d.report?'Controllo il PC…':h.score>=85?'Il PC è in ottima forma':h.score>=65?'Va bene, ma si può fare meglio':'Il PC ha bisogno di una pulita');
 $('opt-tips').replaceChildren(...(h.tips.length?h.tips.map(([ic,t,go])=>{const li=el('li');li.append(icon(ic),document.createTextNode(t));
  if(go){li.classList.add('link');li.addEventListener('click',()=>optTabGo(go));}return li;}):[(()=>{const li=el('li','ok');li.append(icon('check'),document.createTextNode('Tutto in ordine'));return li;})()]));
 countUp($('opt-freed'),d.freed_total||0,v=>bytes(v));
 const last=(d.history||[])[0];$('opt-freed-sub').textContent=last?`ultima pulizia ${ago(last.at)}`+(d.auto&&d.auto_next?` · prossima automatica ${ago2(d.auto_next)}`:''):d.auto?'pulizia automatica attiva':'nessuna pulizia ancora';
 // statistiche
 $('opt-st-junk').textContent=d.report?bytes(d.report.total):'—';$('opt-st-junk-sub').textContent=d.report?`analisi delle ${d.report.at.slice(11,16)}`:'analisi in corso';
 $('opt-st-disk').textContent=h.c?bytes(h.c.free):'—';$('opt-st-disk-sub').textContent=h.c?`su ${bytes(h.c.total)} (${Math.round(100-h.c.percent)}% libero)`:'—';
 $('opt-st-startup').textContent=(d.startup||[]).length?`${h.on} attive`:'—';
 $('opt-st-ram').textContent=d.memory?Math.round(h.ram)+'%':'—';$('opt-st-ram-sub').textContent=d.memory?.total?`${bytes(d.memory.used)} di ${bytes(d.memory.total)}`:'—';
 $('tb-clean').textContent=d.report?bytes(d.report.total):'';$('tb-startup').textContent=h.on||'';$('tb-large').textContent=d.large?.count||'';
 renderClean(d);renderStartup(d.startup||[]);renderDisks(d);renderLarge(d.large);renderNet(d.net);renderOptHistory(d);
 renderZones();
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
 const st=$('opt-startup');st.replaceChildren();
 $('opt-startup-sub').textContent=`${items.filter(i=>i.enabled).length} attivi su ${items.length}: meno programmi = Windows parte prima`;
 items.forEach(i=>{
  const row=el('div','startup-row');const ic=el('span','app-ico',initials(i.name));ic.style.setProperty('--h',hue(i.name));
  const t=el('div');t.append(el('b','',i.name),el('small','',i.scope+(i.admin?' · serve admin':'')));
  const tg=el('button','toggle');tg.type='button';tg.setAttribute('role','switch');tg.setAttribute('aria-checked',i.enabled?'true':'false');tg.setAttribute('aria-label','Avvio di '+i.name);tg.append(el('span'));
  tg.disabled=i.admin&&!!current?.remote;
  tg.addEventListener('click',async()=>{if(demo){notify('Anteprima: comando non attivo.');return;}
   try{const r=await req('/api/optimize/startup','POST',{id:i.id,enabled:!i.enabled});notify('✓ '+r.message);loadOptimize();}catch(ex){notify('⚠ '+ex.message,true);}});
  row.append(ic,t,tg);st.append(row);
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
function renderNet(n){
 const box=$('opt-net');if(!n)return;box.replaceChildren();
 const Q={ottima:['Ottima','ok'],buona:['Buona','mid'],lenta:['Lenta','low'],offline:['Non connesso','low']}[n.quality]||['—',''];
 $('opt-net-sub').textContent=`Prova ${ago(n.at)} alle ${new Date(n.at*1000).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})}`;
 const big=el('div','net-big '+Q[1]);big.append(el('small','','Connessione'),el('b','',Q[0]),el('span','',n.internet?.ms!=null?`${n.internet.ms} ms verso internet`:'internet non raggiungibile'));box.append(big);
 [['Router di casa',n.router,10],['Internet (Cloudflare)',n.internet,60],['Google',n.google,60]].forEach(([label,x,good])=>{if(!x)return;
  const c=el('div','net-m');const ms=x.ms;c.append(el('small','',label),el('b','',ms!=null?ms+' ms':'—'),el('span','',x.loss?`${x.loss}% pacchetti persi`:x.host));
  const bar=el('div','bar');const f=el('span');f.style.width=(ms==null?100:Math.min(100,ms/(good*2)*100))+'%';f.className=ms==null||ms>good*1.5?'bad':ms>good*.6?'mid':'';bar.append(f);c.append(bar);box.append(c);});
 const dn=el('div','net-m');dn.append(el('small','','DNS'),el('b','',n.dns_ms!=null?n.dns_ms+' ms':'—'),el('span','','tempo per trovare un sito'));box.append(dn);
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
$('opt-net-btn').addEventListener('click',()=>post('/api/optimize/net',{}));
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
/* ---------- scene: cambio modalità, avvio gioco e pulizia (stile pulito, tipografico) ---------- */
const MODE_FX={eco:{t:'AI ECO',s:'Consuma meno, l’AI continua a lavorare'},normal:{t:'Normale',s:'Il piano energetico di Windows'},gaming:{t:'Gaming',s:'Massime prestazioni'}};
const NOTE_LABEL=[[/^energia/i,'Energia'],[/^luci gaming/i,'Luci'],[/^rgb/i,'Luci'],[/^ventole/i,'Ventole'],[/^gaming boost/i,'Boost'],[/^integrazione non applicata/i,'Errore']];
let modeScene=null;
function sceneBuild(kind,{kicker,title,sub,img}){
 // Velo sfocato sull'app, luce del colore della modalità, nome grande che si rivela, linea di avanzamento.
 modeScene?.remove();
 const box=el('div','scene s-'+kind+(img?' with-img':''));
 if(img)box.style.setProperty('--img',`url("${img}")`);
 const center=el('div','sc-center');
 const name=el('div','sc-name');name.append(el('span','',title));
 center.append(el('small','sc-kicker',kicker),name,el('div','sc-line'),el('p','sc-sub',sub||''),el('div','sc-tags'));
 box.append(el('div','sc-veil'),el('div','sc-glow'),center);
 document.body.append(box);modeScene=box;
 box.addEventListener('click',()=>sceneClose(box));
 return box;
}
function modeSceneOpen(mode,src,{auto=false,sub=''}={}){
 if(calm.matches||document.hidden)return null;
 const M=MODE_FX[mode];
 const box=sceneBuild(mode,{kicker:auto?'Attivata automaticamente':'Modalità',title:M.t,sub:sub||M.s});
 box.classList.add('busy');
 if(auto){box.classList.remove('busy');box.classList.add('ok');setTimeout(()=>sceneClose(box),1700);}
 return box;
}
function modeSceneDone(box,message,ok=true){
 if(!box||!box.isConnected)return;
 box.classList.remove('busy');box.classList.add(ok?'ok':'fail');
 const tags=box.querySelector('.sc-tags');const seen=new Set();
 String(message||'').split(' · ').map(t=>t.trim()).filter(Boolean).forEach(t=>{
  const lab=(NOTE_LABEL.find(([re])=>re.test(t))||[0,''])[1];if(!lab||seen.has(lab))return;seen.add(lab);
  const bad=!ok||lab==='Errore'||/non applicat|non trovato|errore/i.test(t);
  const tag=el('span',bad?'bad':'',lab);tag.title=t;tag.style.setProperty('--i',seen.size-1);tags.append(tag);});
 if(!ok)box.querySelector('.sc-sub').textContent=String(message).slice(0,140);
 setTimeout(()=>sceneClose(box),ok?1500:2800);
}
function sceneClose(box){if(!box||box.classList.contains('out'))return;box.classList.add('out');setTimeout(()=>box.remove(),600);if(modeScene===box)modeScene=null;}
function fx(kind,title,sub,img){
 // Avvio di un gioco: stessa scena, con la copertina sfocata dietro.
 if(calm.matches||document.hidden)return;
 const box=sceneBuild('gaming',{kicker:'Avvio',title:sub||title,sub:'NEXAR prepara il PC',img});
 box.classList.add('ok');setTimeout(()=>sceneClose(box),1900);
}
async function modeSwitch(mode,src){
 if(busy)return;
 if(demo){const b=modeSceneOpen(mode,src);setTimeout(()=>modeSceneDone(b,'Energia: '+MODE_FX[mode].t+' · RGB: profilo applicato · Ventole: profilo '+(mode==='eco'?'silenzioso':'normale')+(mode==='gaming'?' · Gaming Boost attivo':'')),900);return;}
 if(!key&&!tgInit){loginScreen(true);return;}
 fxQuiet=Date.now()+15000;busy=true;
 const scene=modeSceneOpen(mode,src);
 try{const r=await req('/api/mode','POST',{mode});if(scene)modeSceneDone(scene,r.message);else notify('✓ '+r.message);await refresh();}
 catch(ex){if(scene)modeSceneDone(scene,ex.message,false);else notify('⚠ '+ex.message,true);}
 finally{busy=false;}
}

/* pulizia: un anello sottile che si riempie, numero grande, un passo alla volta */
const cfx={box:null,timers:[],t0:0,est:0,steps:[],k:-1};
function parseBytes(t){const m=String(t).match(/liberati\s+([\d.,]+)\s*(B|KB|MB|GB|TB)/i);if(!m)return null;
 return parseFloat(m[1].replace(/\./g,'').replace(',','.'))*1024**['B','KB','MB','GB','TB'].indexOf(m[2].toUpperCase());}
function svgEl(tag,attrs){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));return e;}
function cleanStart(steps,est){
 if(cfx.box||calm.matches)return;
 cfx.t0=performance.now();cfx.est=est||0;cfx.steps=steps;cfx.k=-1;
 const box=el('div','cscene');const wrap=el('div','cs-wrap');
 const ring=el('div','cs-ring');
 const svg=svgEl('svg',{viewBox:'0 0 200 200'});
 const defs=svgEl('defs',{});const g=svgEl('linearGradient',{id:'cs-grad',x1:'0',y1:'0',x2:'1',y2:'1'});
 g.append(svgEl('stop',{offset:'0','stop-color':'#67e8f9'}),svgEl('stop',{offset:'1','stop-color':'#34d399'}));defs.append(g);
 svg.append(defs,svgEl('circle',{class:'cs-track',cx:100,cy:100,r:88,pathLength:100}),svgEl('circle',{class:'cs-prog',cx:100,cy:100,r:88,pathLength:100}));
 const head=el('i','cs-head');
 const inner=el('div','cs-inner');
 const check=svgEl('svg',{class:'cs-check',viewBox:'0 0 52 52'});check.append(svgEl('path',{d:'M15 27.5l7.5 7.5L37.5 19'}));
 inner.append(check,el('b','cs-amount','0 B'),el('small','cs-unit','pulito'));
 ring.append(svg,head,inner);
 const step=el('div','cs-step');step.append(el('span','cs-step-t','Preparo la pulizia'),el('small','cs-step-n',''));
 const btn=el('button','cs-close','Continua in background');btn.type='button';btn.addEventListener('click',e=>{e.stopPropagation();cleanClose();});
 wrap.append(el('small','sc-kicker','Ottimizza'),ring,step,btn);
 box.append(el('div','sc-veil'),el('div','sc-glow'),wrap);document.body.append(box);cfx.box=box;
 const setP=p=>{box.style.setProperty('--p',(p*100).toFixed(2));};
 setP(0);
 cfx.timers.push(setInterval(()=>{
  const t=(performance.now()-cfx.t0)/1000,p=t/(t+5)*.92;setP(p);
  box.querySelector('.cs-amount').textContent=cfx.est?bytes(cfx.est*p):Math.round(p*100)+'%';
  const k=Math.min(steps.length-1,Math.floor(t/.9));
  if(k!==cfx.k){cfx.k=k;const st=box.querySelector('.cs-step-t');st.classList.remove('in');void st.offsetWidth;st.textContent=steps[k];st.classList.add('in');
   box.querySelector('.cs-step-n').textContent=`${k+1} di ${steps.length}`;}
 },60));
}
function cleanFinish(message,ok=true){
 const box=cfx.box;if(!box){if(message)notify((ok?'✓ ':'⚠ ')+message,!ok);return;}
 cfx.timers.forEach(clearInterval);cfx.timers=[];
 box.style.setProperty('--p',ok?100:Math.max(5,parseFloat(box.style.getPropertyValue('--p'))||5));
 box.classList.add(ok?'done':'fail');
 const amount=box.querySelector('.cs-amount'),freed=parseBytes(message);
 box.querySelector('.cs-unit').textContent=ok?'liberati':'non riuscita';
 if(ok&&freed!=null){amount._v=cfx.est?cfx.est*.5:0;countUp(amount,freed,v=>bytes(v));}else if(!ok)amount.textContent='—';
 const note=String(message||'').replace(/^.*?liberati\s+[\d.,]+\s*\w+\s*/i,'').replace(/^[·.\s]+/,'');
 const st=box.querySelector('.cs-step-t');st.classList.remove('in');void st.offsetWidth;
 st.textContent=ok?(note?'Fatto · '+note:'Pulizia completata'):String(message).slice(0,140);st.classList.add('in');
 box.querySelector('.cs-step-n').textContent=ok?`${cfx.steps.length} di ${cfx.steps.length}`:'';
 box.querySelector('.cs-close').textContent='Fatto';
 box.addEventListener('click',()=>cleanClose());
 setTimeout(cleanClose,5000);
}
function cleanClose(){const box=cfx.box;if(!box)return;cfx.timers.forEach(clearInterval);cfx.timers=[];cfx.box=null;box.classList.add('out');setTimeout(()=>box.remove(),600);}
/* ---------- gaming ---------- */
let gameData=null,libStore='',showHidden=false,heroArt=null;const covers=new Map();
const STORE_COLORS={Steam:'#66c0f4',Epic:'#e5e7eb',Riot:'#ff6b75',GOG:'#c79cff'};
const FAN_NAMES={off:'Spente',off_pump:'Spente',eco:'Silenziose',normal:'Normali',max:'Massimo'};
const FAN_BAR={off:0,off_pump:8,eco:35,normal:60,max:100};
const DEMO_GAMING={boost:{active:true,game:'Hollow Knight',boosted:['hollow_knight.exe'],lowered:['discord.exe'],closed:['chrome.exe'],
  tweaks:['Modalità gioco di Windows','Registrazione Xbox in background spenta'],running:{id:'steam-367520',name:'Hollow Knight',store:'Steam'},
  session:{game:'Hollow Knight',gid:'steam-367520',start:Date.now()/1000-2580,elapsed:2580,cpu_temp_max:71,gpu_temp_max:66,cpu_temp_avg:63,gpu_temp_avg:60,cpu_avg:31,gpu_avg:74,kwh:.21,watts_avg:288},
  settings:{game_priority:true,game_mode:true,no_dvr:true,reopen:true,auto:true,mouse:false,apps:{'discord.exe':'lower','chrome.exe':'close'},hidden:[]}},
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
 apps:[{name:'chrome.exe',bytes:1.2e9,count:12,game:false},{name:'discord.exe',bytes:4e8,count:5,game:false},{name:'spotify.exe',bytes:2.6e8,count:4,game:false}],
 fans:'normal',fans_enabled:true,rgb_color:'#ff3cc8',rgb_enabled:true,palette:statusDemo.rgb_palette};
function hue(t){let h=0;for(const c of String(t))h=(h*31+c.charCodeAt(0))%360;return h;}
function initials(n){return n.replace(/[^\p{L}\p{N} ]/gu,'').split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()||'?';}
function playtime(s){if(!s)return '';const m=Math.max(1,Math.round(s/60)),h=Math.floor(m/60);return h?`${h} h ${m%60?m%60+' min':''}`.trim():`${m} min`;}
function ago(ts){if(!ts)return '';const d=(Date.now()/1000-ts)/86400;
 return d<1?'oggi':d<2?'ieri':d<30?`${Math.floor(d)} giorni fa`:new Date(ts*1000).toLocaleDateString('it-IT',{day:'numeric',month:'short',year:'numeric'});}
function coverUrl(id,kind){
 // Le immagini arrivano dalla cache di Steam sul PC, con la stessa chiave della API.
 const k=id+'/'+kind;if(covers.has(k))return covers.get(k);
 const p=(async()=>{if(demo||!id.startsWith('steam-'))return '';
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
function renderLibrary(animate=false){
 const d=gameData;if(!d)return;const games=d.games||[];const q=$('lib-search').value.trim().toLowerCase();
 const stores=[...new Set(games.filter(g=>!g.hidden).map(g=>g.store))];if(libStore&&!stores.includes(libStore))libStore='';
 const seg=$('lib-stores');seg.hidden=stores.length<2;
 seg.replaceChildren(...['',...stores].map(st=>{const b=el('button',st===libStore?'selected':'',st||'Tutti');b.type='button';
  b.addEventListener('click',()=>{libStore=st;renderLibrary(true);});return b;}));
 const hiddenN=games.filter(g=>g.hidden).length;
 const list=games.filter(g=>(showHidden||!g.hidden)&&(!libStore||g.store===libStore)&&(!q||g.name.toLowerCase().includes(q)));
 const running=(current?.boost||d.boost)?.running?.id;
 $('lib-sub').textContent=games.length?`${games.length-hiddenN} giochi · ${stores.join(', ')}`:'Nessun gioco trovato';
 const lh=$('lib-hidden');lh.hidden=!hiddenN;lh.textContent=showHidden?'Nascondi i programmi esclusi':`Mostra ${hiddenN} ${hiddenN>1?'esclusi':'escluso'}`;
 const grid=$('game-grid');grid.replaceChildren();
 if(!list.length){grid.append(el('p','muted',games.length?'Nessun gioco corrisponde alla ricerca.':'Non ho trovato giochi di Steam, Epic, Riot o GOG su questo PC.'));return;}
 list.forEach((g,i)=>{
  const playing=g.id===running;
  const card=el('article','game-card'+(g.hidden?' is-hidden':'')+(playing?' playing':'')+(animate?' enter':''));
  card.style.setProperty('--i',Math.min(i,16));tilt(card);
  const cov=el('div','game-cover');cov.style.setProperty('--h',hue(g.name));cov.append(el('span','initials',initials(g.name)));
  const badge=el('span','store-badge',g.store);badge.style.setProperty('--sc',STORE_COLORS[g.store]||'#94a3b8');cov.append(badge);
  if(playing)cov.append(el('span','now-badge','IN GIOCO'));
  if(g.cover)coverUrl(g.id,'header').then(u=>{if(!u)return;const im=el('img');im.alt='';im.onload=()=>cov.classList.add('has-img');im.src=u;cov.prepend(im);});
  const meta=el('div','game-meta');meta.append(el('b','',g.name));
  meta.append(el('small','',[g.playtime?playtime(g.playtime)+' con NEXAR':'',g.last?ago(g.last):'mai giocato',g.size?bytes(g.size):''].filter(Boolean).join(' · ')));
  const acts=el('div','game-actions');
  const play=el('button','btn primary small');play.type='button';play.append(icon('play'),document.createTextNode(playing?'In gioco':'Gioca'));play.disabled=playing||g.hidden;
  play.addEventListener('click',()=>launchGame(g));
  const hide=el('button','icon-btn small');hide.type='button';hide.title=g.hidden?'Rimetti tra i giochi':'Non è un gioco: escludi';hide.setAttribute('aria-label',hide.title);
  hide.append(icon(g.hidden?'eye':'eye-off'));
  hide.addEventListener('click',()=>{const h=new Set(d.boost?.settings?.hidden||[]);g.hidden?h.delete(g.id):h.add(g.id);saveGaming({hidden:[...h]});});
  acts.append(play,hide);card.append(cov,meta,acts);grid.append(card);
 });
}
function renderBoostApps(d){
 const box=$('boost-apps');box.replaceChildren();const chosen=d.boost?.settings?.apps||{};
 const apps=(d.apps||[]).filter(a=>!a.game);
 Object.keys(chosen).forEach(n=>{if(!apps.some(a=>a.name===n))apps.push({name:n,bytes:0,count:0,closed:true});});
 if(!apps.length){box.append(el('p','muted','Nessuna app in background da gestire.'));return;}
 apps.forEach(a=>{
  const row=el('div','boost-app');const t=el('div');
  t.append(el('b','',a.name.replace(/\.exe$/i,'')),el('small','',a.closed?'non aperta ora':`${bytes(a.bytes)} di RAM`+(a.count>1?` · ${a.count} processi`:'')));
  const seg=el('div','seg3');
  [['','Lascia'],['lower','Rallenta'],['close','Chiudi']].forEach(([v,l])=>{const b=el('button',v,l);b.type='button';b.classList.toggle('selected',(chosen[a.name]||'')===v);
   b.addEventListener('click',()=>{const next=Object.fromEntries(Object.entries(chosen).filter(([k])=>k!==a.name));if(v)next[a.name]=v;saveGaming({apps:next});});seg.append(b);});
  row.append(t,seg);box.append(row);
 });
}
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
document.querySelectorAll('[data-boost]').forEach(t=>t.addEventListener('click',e=>{e.preventDefault();saveGaming({[t.dataset.boost]:t.getAttribute('aria-checked')!=='true'});}));
document.querySelectorAll('#game-fans [data-fans]').forEach(b=>b.addEventListener('click',()=>saveGaming({fans:b.dataset.fans})));
$('game-main').addEventListener('click',()=>heroAction($('game-main').dataset.act,$('game-main')));
$('game-second').addEventListener('click',()=>heroAction($('game-second').dataset.act,$('game-second')));
$('lib-search').addEventListener('input',renderLibrary);
$('lib-reload').addEventListener('click',()=>loadGaming(true,true));
$('lib-hidden').addEventListener('click',()=>{showHidden=!showHidden;renderLibrary();});
$('boost-reload').addEventListener('click',()=>loadGaming());
$('upd-check').addEventListener('click',()=>post('/api/update/check',{}));
$('upd-install').addEventListener('click',async()=>{
 if(await ask('Installare l\'aggiornamento?','NEXAR si chiude per qualche secondo e riparte da solo con la nuova versione.',{danger:false,ico:'refresh',yes:'Installa'}))post('/api/update/install',{});
});
$('upd-auto').addEventListener('click',()=>post('/api/update/auto',{enabled:$('upd-auto').getAttribute('aria-checked')!=='true'}));
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
})();
