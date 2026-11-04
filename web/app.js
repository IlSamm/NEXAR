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
 optimize:['Ottimizza','Pulizia, programmi all’avvio, dischi e memoria.'],
 links:['Collegamenti','Programmi trovati e collegati da soli.'],
 settings:['Impostazioni','AI ECO, energia, Telegram e registro.'],
 more:['Altro','Accensione, collegamenti e impostazioni.'],
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
const hist={cpu:[],gpu:[],power:[]};
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
 const tab=['power','links','settings','optimize'].includes(view)?'more':view;
 document.querySelectorAll('.rail-nav [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
 document.querySelectorAll('.tabbar [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===tab));
 document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+view));
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
 $('cpu-val').textContent=pct(s.cpu);$('gpu-val').textContent=pct(s.gpu);$('ram-val').textContent=pct(s.ram);
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
 $('fan-val').textContent=avg?avg+' RPM':'—';setBar('fan-bar',avg,1800);
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
 push(hist.cpu,s.cpu);push(hist.gpu,s.gpu);push(hist.power,s.power?.total);
 chart('chart-load',[{data:hist.cpu,color:COMP.cpu},{data:hist.gpu,color:COMP.gpu}],100,'%');
 chart('chart-power',[{data:hist.power,color:'#34d399'}],0,' W');
 renderLinks(s.integrations||[],s.jobs||{});
 renderUpdate(s.version,s.update||{},s.jobs?.update);
 watchOptimizeJobs(s.jobs||{});
 renderGamingLive(s);
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
async function action(name){
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
let optData=null,boostData=null;const optSeen={};
function watchOptimizeJobs(jobs){
 // A fine analisi o pulizia ricarica la pagina, se è aperta.
 ['optimize-scan','optimize-clean','trim'].forEach(n=>{const j=jobs[n];if(!j)return;
  const busy=j.state==='running';
  if(n!=='trim'){$('opt-scan').disabled=busy;$('opt-quick').disabled=busy;$('opt-quick-label').textContent=busy?'Ottimizzo…':'Ottimizza ora';$('opt-run').disabled=busy||!selectedKeys().length;}
  if(!busy&&optSeen[n]!==undefined&&optSeen[n]!==j.at&&$('page-optimize').classList.contains('active'))loadOptimize();optSeen[n]=j.at;});
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
  {key:'recycle',name:'Cestino',desc:'Svuota il cestino',bytes:2.4e9,files:42,admin:false,permanent:true,note:''}]},
 disks:[{drive:'C:',total:5e11,used:4.7e11,free:3e10,percent:94},{drive:'D:',total:1e12,used:3e11,free:7e11,percent:30}],
 memory:{percent:51,used:1.6e10,total:3.2e10,top:[{name:'chatgpt.exe',bytes:2.6e9},{name:'claude.exe',bytes:2.4e9}]},
 startup:[{id:'a',name:'Discord',scope:'utente',enabled:true,admin:false},{id:'b',name:'Steam',scope:'utente',enabled:false,admin:false}]};
async function loadOptimize(){
 if(demo){renderOptimize(DEMO_OPT);return;}
 try{renderOptimize(await req('/api/optimize'));}catch(ex){notify('Ottimizza: '+ex.message,true);}
}
function healthScore(d){
 // Punteggio semplice e spiegabile: ogni problema toglie punti e diventa un consiglio.
 let score=100;const tips=[];const rep=d.report;const c=(d.disks||[]).find(x=>/^C/i.test(x.drive))||(d.disks||[])[0];
 if(rep){const gb=rep.total/2**30;if(gb>=0.5){score-=Math.min(25,Math.round(gb*4));tips.push(`${bytes(rep.total)} di file inutili da pulire`);}}
 else tips.push('Premi Analizza per misurare i file inutili');
 if(c){const free=c.free/c.total;if(free<0.1){score-=30;tips.push(`Disco ${c.drive} quasi pieno: ${bytes(c.free)} liberi`);}else if(free<0.2){score-=15;tips.push(`Disco ${c.drive} con poco spazio (${bytes(c.free)} liberi)`);}}
 const on=(d.startup||[]).filter(i=>i.enabled).length;if(on>8){score-=Math.min(20,(on-8)*2);tips.push(`${on} programmi partono con Windows: spegni quelli che non usi`);}
 const ram=d.memory?.percent||0;if(ram>80){score-=15;tips.push(`RAM al ${Math.round(ram)}%: chiudi qualcosa o usa Gaming Boost`);}else if(ram>65)score-=6;
 return {score:Math.max(0,Math.min(100,score)),tips:tips.slice(0,3),c,on,ram};
}
function renderOptimize(d){
 optData=d;
 const h=healthScore(d);
 countUp($('opt-score'),h.score,v=>Math.round(v));$('opt-score-ring').style.strokeDasharray=`${h.score} 100`;
 $('opt-score-label').textContent=h.score>=85?'Ottimo':h.score>=65?'Buono':'Da migliorare';
 $('opt-score-ring').closest('.health').className='health'+(h.score<65?' low':h.score<85?' mid':'');
 $('opt-st-junk').textContent=d.report?bytes(d.report.total):'—';$('opt-st-disk').textContent=h.c?bytes(h.c.free):'—';
 $('opt-st-startup').textContent=(d.startup||[]).length?`${h.on} attive`:'—';$('opt-st-ram').textContent=d.memory?Math.round(h.ram)+'%':'—';
 $('opt-tips').replaceChildren(...(h.tips.length?h.tips.map(t=>el('li','',t)):[el('li','ok','Tutto in ordine')]));
 const dk=$('opt-disks');dk.replaceChildren();
 (d.disks||[]).forEach(x=>{const c=el('div','disk'+(x.free<0.1*x.total?' low':''));const top=el('div','disk-top');top.append(el('b','',x.drive),el('small','',`${bytes(x.free)} liberi su ${bytes(x.total)}`));
  const bar=el('div','bar');const f=el('span');f.style.width=x.percent+'%';bar.append(f);c.append(top,bar);dk.append(c);});
 const box=$('opt-clean');const rep=d.report;
 if(rep){
  box.replaceChildren();
  $('opt-clean-sub').textContent=`${bytes(rep.total)} recuperabili · analisi delle ${rep.at.slice(11,16)}`;
  rep.items.forEach(i=>{
   const row=el('label','clean-row'+(i.bytes?'':' empty'));const cb=el('input');cb.type='checkbox';cb.value=i.key;
   const blocked=(i.admin&&current?.remote)||i.note.startsWith('chiudi');
   cb.checked=i.bytes>0&&!i.permanent&&!i.admin&&!blocked;cb.disabled=!i.bytes||blocked;cb.addEventListener('change',updateSelected);
   const t=el('div');const name=el('b','',i.name);
   if(i.permanent)name.append(el('em','pill warn','definitivo'));if(i.admin)name.append(el('em','pill admin','🛡 admin'));
   t.append(name,el('small','',i.note||i.desc));row.append(cb,t,el('strong','',i.bytes?bytes(i.bytes):'pulito'));box.append(row);
  });
  updateSelected();
 }
 const st=$('opt-startup');st.replaceChildren();const items=d.startup||[];
 $('opt-startup-sub').textContent=`${items.filter(i=>i.enabled).length} attivi su ${items.length}: meno programmi = Windows parte prima`;
 items.forEach(i=>{
  const row=el('div','startup-row');const t=el('div');t.append(el('b','',i.name),el('small','',i.scope+(i.admin?' · serve admin':'')));
  const tg=el('button','toggle');tg.type='button';tg.setAttribute('role','switch');tg.setAttribute('aria-checked',i.enabled?'true':'false');tg.setAttribute('aria-label','Avvio di '+i.name);tg.append(el('span'));
  tg.disabled=i.admin&&!!current?.remote;
  tg.addEventListener('click',async()=>{if(demo){notify('Anteprima: comando non attivo.');return;}
   try{const r=await req('/api/optimize/startup','POST',{id:i.id,enabled:!i.enabled});notify('✓ '+r.message);loadOptimize();}catch(ex){notify('⚠ '+ex.message,true);}});
  row.append(t,tg);st.append(row);
 });
 const m=d.memory||{};$('opt-mem-sub').textContent=m.total?`${bytes(m.used)} usati su ${bytes(m.total)} (${Math.round(m.percent)}%)`:'—';
 const mm=$('opt-mem');mm.replaceChildren();const max=Math.max(1,...(m.top||[]).map(x=>x.bytes));
 (m.top||[]).forEach(x=>{const r=el('div','mem-row');const bar=el('div','bar');const f=el('span');f.style.width=(x.bytes/max*100)+'%';bar.append(f);
  r.append(el('span','',x.name.replace(/\.exe$/i,'')),el('b','',bytes(x.bytes)),bar);mm.append(r);});
}
document.querySelectorAll('#opt-tabs button').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll('#opt-tabs button').forEach(x=>x.classList.toggle('selected',x===b));
 document.querySelectorAll('.opt-panel').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.panel);
}));
$('opt-scan').addEventListener('click',()=>post('/api/optimize/scan',{}));
$('opt-quick').addEventListener('click',async()=>{
 const est=optData?.report?.items?.filter(i=>['temp','shader','thumbs','crash','browser'].includes(i.key)).reduce((a,i)=>a+i.bytes,0);
 if(!await ask('Ottimizzare adesso?',`Pulisco file temporanei, cache dei giochi, anteprime, rapporti di errore e cache dei browser chiusi${est?' (circa '+bytes(est)+')':''}, poi svuoto la cache DNS. Cestino e documenti non vengono toccati.`,{danger:false,ico:'clean',yes:'Ottimizza'}))return;
 post('/api/optimize/quick',{});
});
$('opt-run').addEventListener('click',async()=>{
 const keys=selectedKeys();if(!keys.length)return;
 const perm=keys.includes('recycle');
 if(!await ask('Pulire adesso?',`${$('opt-selected').textContent}.`+(perm?' Il cestino verrà svuotato: quei file non si potranno più recuperare.':' Sono solo file temporanei e cache.'),{danger:perm,ico:'clean',yes:'Pulisci'}))return;
 post('/api/optimize/clean',{keys});
});
$('opt-dns').addEventListener('click',()=>post('/api/optimize/dns',{}));
$('opt-trim').addEventListener('click',()=>post('/api/optimize/trim',{}));
/* ---------- animazioni ---------- */
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
function fx(kind,title,sub,img){
 // Effetto a schermo intero di 2 secondi: non blocca i clic.
 if(calm.matches||document.hidden)return;
 document.querySelectorAll('.gfx').forEach(x=>x.remove());
 const box=el('div','gfx '+kind+(img?' img':''));if(img)box.style.setProperty('--img',`url("${img}")`);
 const rings=el('div','gfx-rings');rings.append(el('i'),el('i'),el('i'));
 const core=el('div','gfx-core');core.append(icon(kind==='off'?'check':kind==='launch'?'play':'game'));
 box.append(el('div','gfx-bg'),rings,core,el('b','',title));if(sub)box.append(el('small','',sub));
 document.body.append(box);setTimeout(()=>box.remove(),2000);
}
function modeFx(mode){
 if(lastMode&&mode&&lastMode!==mode&&Date.now()>fxQuiet){
  if(mode==='gaming')fx('on','GAMING ON',current?.boost?.running?.name?'Si gioca a '+current.boost.running.name:'Massime prestazioni');
  else if(lastMode==='gaming')fx('off','GAMING OFF','Tutto come prima');
 }
 lastMode=mode;
}
function particles(){
 const box=$('game-particles');if(!box||box.childElementCount)return;
 const cols=['#ec4899','#a78bfa','#22d3ee','#f472b6'];
 for(let i=0;i<22;i++){const p=el('span');const s=2+Math.random()*3;
  p.style.cssText=`left:${Math.random()*100}%;--s:${s}px;--c:${cols[i%4]};--d:${6+Math.random()*8}s;--w:${-Math.random()*12}s;--dx:${(Math.random()-.5)*120}px`;box.append(p);}
}
function tilt(card){
 card.addEventListener('pointermove',e=>{
  if(e.pointerType!=='mouse'||calm.matches)return;
  const r=card.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
  card.classList.add('tilting');
  card.style.setProperty('--ry',((x-.5)*10).toFixed(2)+'deg');card.style.setProperty('--rx',((.5-y)*8).toFixed(2)+'deg');
  card.style.setProperty('--mx',(x*100).toFixed(1)+'%');card.style.setProperty('--my',(y*100).toFixed(1)+'%');
 });
 card.addEventListener('pointerleave',()=>{card.classList.remove('tilting');card.style.setProperty('--rx','0deg');card.style.setProperty('--ry','0deg');});
}
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
async function heroAction(act){
 if(!act)return;
 if(act==='exit')return action('normal');
 if(act==='on')return action('gaming');
 if(act.startsWith('launch:')){const g=(gameData?.games||[]).find(x=>x.id===act.slice(7));if(g)launchGame(g);}
}
document.querySelectorAll('[data-boost]').forEach(t=>t.addEventListener('click',e=>{e.preventDefault();saveGaming({[t.dataset.boost]:t.getAttribute('aria-checked')!=='true'});}));
document.querySelectorAll('#game-fans [data-fans]').forEach(b=>b.addEventListener('click',()=>saveGaming({fans:b.dataset.fans})));
$('game-main').addEventListener('click',()=>heroAction($('game-main').dataset.act));
$('game-second').addEventListener('click',()=>heroAction($('game-second').dataset.act));
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
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>action(b.dataset.action)));

if(demo){$('demo-strip').hidden=false;loginScreen(false);[7,9,8,12,11,17,14,13,15,12,18,15,12,10,9,11,13].forEach((v,i)=>{hist.cpu.push(v);hist.gpu.push(4+i%5);hist.power.push(98+v*1.4);});render(statusDemo);}
else if(key||tgInit){loginScreen(false);refresh();}else loginScreen(true);
navigate('home');
setInterval(()=>{if(!document.hidden)refresh();},4000);
})();
