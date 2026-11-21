'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const key = 'futubiz_backend_ready_v1';
  const money = n => (n < 0 ? '−' : '') + '$' + Math.abs(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
  const round = n => Math.round((n + Number.EPSILON) * 100) / 100;
  let state = {balance:10000, name:'Futubiz Trader', payout:90, history:[], digits:[], totalTrades:0, totalPnl:0};
  let storageOK = false;
  try {
    const old = JSON.parse(localStorage.getItem(key) || 'null');
    if (old && Number.isFinite(old.balance) && old.balance >= 0 && old.balance <= 100000000 && Array.isArray(old.history)) {
      state = {...state, ...old, history:old.history.filter(t => t && typeof t.kind === 'string' && Number.isFinite(t.net) && Number.isFinite(t.stake) && Number.isInteger(t.digit) && t.digit >= 0 && t.digit <= 9).slice(0,50), digits:Array.isArray(old.digits) ? old.digits.filter(n=>Number.isInteger(n) && n>=0 && n<=9).slice(-30) : []};
      state.totalTrades = Number.isSafeInteger(old.totalTrades) && old.totalTrades >= 0 ? old.totalTrades : 0;
      state.totalPnl = Number.isFinite(old.totalPnl) ? old.totalPnl : 0;
    }
    localStorage.setItem(key, JSON.stringify(state)); storageOK = true;
  } catch (_) {}
  function save() { try { localStorage.setItem(key, JSON.stringify(state)); storageOK=true; } catch (_) {storageOK=false;} }
  const categories = {
    rise:{title:'Rise / Fall', explanation:'Rise wins on digits 5–9; Fall wins on 0–4. Not price movement.', names:['Rise ↗','Fall ↘'], kinds:['rise','fall']},
    matches:{title:'Matches / Differs', explanation:'Matches wins when the random digit equals your chosen digit. Differs wins when it does not.', names:['Matches =','Differs ≠'], kinds:['matches','differs']},
    even:{title:'Even / Odd', explanation:'Even wins on 0, 2, 4, 6 or 8. Odd wins on 1, 3, 5, 7 or 9.', names:['Even','Odd'], kinds:['even','odd']},
    over:{title:'Over / Under', explanation:'Over wins above your selected digit. Under wins below it; equality loses.', names:['Over ↑','Under ↓'], kinds:['over','under']}
  };
  let category='rise';
  const counts = (kind,b) => kind==='over'?9-b:kind==='under'?b:kind==='matches'?1:kind==='differs'?9:5;
  const isWin = (kind,d,b) => kind==='over'?d>b:kind==='under'?d<b:kind==='matches'?d===b:kind==='differs'?d!==b:kind==='even'?d%2===0:kind==='odd'?d%2===1:kind==='rise'?d>=5:d<5;
  function validAmount(raw) {const n=Number(raw); return raw.trim()!=='' && Number.isFinite(n) && n>=0.01 && n<=1000000 && Math.abs(n*100-Math.round(n*100))<0.00001;}
  function updateOptions() {
    const c=categories[category], barrier=Number($('barrier').value), raw=$('stake').value, stake=Number(raw);
    $('categoryTitle').textContent=c.title; $('explanation').textContent=c.explanation;
    $('barrierRow').hidden=category!=='matches' && category!=='over';
    [ $('optionA'), $('optionB') ].forEach((button,i)=>{
      const wins=counts(c.kinds[i],barrier);
      button.querySelector('.option-name').textContent=c.names[i];
      button.querySelector('.option-chance').textContent='Win chance: '+wins*10+'%';
      button.querySelector('.option-return').textContent=wins===0?'Cannot win':validAmount(raw)?'Win return: '+money(round(stake*.9/(wins/10))):'Win return: —';
      button.disabled=wins===0;
      button.setAttribute('aria-label',c.names[i]+', '+wins*10+' percent win chance. '+button.querySelector('.option-return').textContent+'. Place one simulated trade.');
    });
    document.querySelectorAll('[data-amount]').forEach(b=>b.classList.toggle('selected',validAmount(raw)&&Number(b.dataset.amount)===stake));
  }
  function randomDigit() {
    if (window.crypto && window.crypto.getRandomValues) {let a=new Uint8Array(1); do {window.crypto.getRandomValues(a);} while(a[0]>=250); return a[0]%10;}
    return Math.floor(Math.random()*10);
  }
  function trade(index) {
    const raw=$('stake').value, stake=Number(raw), barrier=Number($('barrier').value), kind=categories[category].kinds[index], wins=counts(kind,barrier);
    if (!validAmount(raw)) {$('tradeResult').textContent='Enter a valid amount from $0.01 to $1,000,000 with at most two decimals.';return;}
    if (stake>state.balance) {$('tradeResult').textContent='Not enough virtual funds. Add demo funds or choose a smaller amount.';return;}
    if (!wins) {$('tradeResult').textContent='This option cannot win with the chosen digit.';return;}
    const digit=randomDigit(), win=isWin(kind,digit,barrier), payout=round(stake*.9/(wins/10)), net=win?round(payout-stake):-stake;
    if (state.balance+net>100000000) {$('tradeResult').textContent='Virtual balance limit reached. No trade recorded.';return;}
    state.balance=round(state.balance+net); state.totalTrades++; state.totalPnl=round(state.totalPnl+net);
    state.history.unshift({kind,barrier,digit,stake,net,win,time:new Date().toISOString(),returnAmount:win?payout:0}); state.history=state.history.slice(0,50);
    state.digits.push(digit);state.digits=state.digits.slice(-30);save();render();
    $('tradeResult').textContent=(win?'Practice win':'Practice loss')+' · random digit '+digit+' · '+(net>=0?'+':'')+money(net)+' virtual';
  }
  function renderHistory(target,items) {
    target.replaceChildren();
    if (!items.length) {const p=document.createElement('p');p.className='fine';p.textContent='No practice trades yet.';target.append(p);return;}
    items.forEach(t=>{
      const row=document.createElement('div'), left=document.createElement('div'), title=document.createElement('strong'), detail=document.createElement('span'), amount=document.createElement('strong');
      row.className='history-item'; title.textContent=t.kind.charAt(0).toUpperCase()+t.kind.slice(1)+' · '+(t.win?'WIN':'LOSS');
      const usesBarrier=['over','under','matches','differs'].includes(t.kind) && Number.isInteger(t.barrier);
      detail.textContent='Digit '+t.digit+(usesBarrier?' · chosen '+t.barrier:'')+' · '+money(t.stake)+' stake'+(t.time && Number.isFinite(Date.parse(t.time))?' · '+new Date(t.time).toLocaleString():'');
      detail.style.display='block'; amount.className=t.net>=0?'profit':'loss';amount.textContent=(t.net>=0?'+':'')+money(t.net);
      left.append(title,detail);row.append(left,amount);target.append(row);
    });
  }
  function render() {
    $('balance').textContent=money(state.balance);document.querySelectorAll('.balance-copy').forEach(e=>e.textContent=money(state.balance));
    renderHistory($('recentHistory'),state.history.slice(0,3));renderHistory($('history'),state.history);
    $('storageStatus').textContent=storageOK?'Your demo balance and history are saved in this browser only, with no online sync. Multiple tabs can overwrite one another.':'Browser storage is unavailable; changes last only while this page remains open.';
    updateOptions();
  }
  function go(page) {
    document.querySelectorAll('.page').forEach(e=>e.classList.toggle('active',e.id==='page-'+page));
    document.querySelectorAll('.bottom-nav [data-page]').forEach(b=>{const on=b.dataset.page===page;b.classList.toggle('active',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    window.scrollTo(0,0);if(page==='trade')requestAnimationFrame(draw);
  }
  document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>go(b.dataset.page)));
  document.querySelectorAll('[data-category]').forEach(b=>b.addEventListener('click',()=>{category=b.dataset.category;document.querySelectorAll('[data-category]').forEach(t=>{const on=t===b;t.classList.toggle('active',on);t.setAttribute('aria-pressed',String(on));});$('tradeResult').textContent='Choose an option to place one virtual trade.';updateOptions();}));
  $('barrier').addEventListener('change',updateOptions);$('stake').addEventListener('input',updateOptions);
  document.querySelectorAll('[data-amount]').forEach(b=>b.addEventListener('click',()=>{$('stake').value=Number(b.dataset.amount).toFixed(2);updateOptions();}));
  function adjust(by) {let value=validAmount($('stake').value)?Number($('stake').value):1; $('stake').value=Math.min(1000000,Math.max(.01,round(value+by))).toFixed(2);updateOptions();}
  $('increase').addEventListener('click',()=>adjust(1));$('decrease').addEventListener('click',()=>adjust(-1));$('optionA').addEventListener('click',()=>trade(0));$('optionB').addEventListener('click',()=>trade(1));
  $('topup').addEventListener('click',()=>{if(state.balance+10000>100000000){$('fundsResult').textContent='Virtual balance limit reached.';return;}state.balance=round(state.balance+10000);save();render();$('fundsResult').textContent='Added $10,000 in virtual funds.';});
  $('clearHistory').addEventListener('click',()=>{if(!window.confirm('Clear practice history? Your virtual balance stays the same.'))return;state.history=[];state.digits=[];save();render();});
  let price=1000;const points=[];for(let i=0;i<70;i++){price=Math.max(1,price+(Math.random()-.5)*5);points.push(price);}
  function draw() {
    const canvas=$('chart'),r=canvas.getBoundingClientRect();if(!r.width||!r.height)return;
    const ratio=window.devicePixelRatio||1;canvas.width=Math.round(r.width*ratio);canvas.height=Math.round(r.height*ratio);
    const c=canvas.getContext('2d');if(!c)return;c.setTransform(ratio,0,0,ratio,0,0);const w=r.width,h=r.height;
    c.strokeStyle='#303649';c.lineWidth=1;for(let i=1;i<5;i++){c.beginPath();c.moveTo(0,h*i/5);c.lineTo(w,h*i/5);c.stroke();}for(let i=1;i<5;i++){c.beginPath();c.moveTo(w*i/5,0);c.lineTo(w*i/5,h);c.stroke();}
    const lo=Math.min(...points),hi=Math.max(...points),x=i=>i*(w-16)/(points.length-1)+8,y=v=>20+(hi-v)/(hi-lo||1)*(h-40);
    c.beginPath();points.forEach((v,i)=>i?c.lineTo(x(i),y(v)):c.moveTo(x(i),y(v)));c.lineTo(x(points.length-1),h);c.lineTo(x(0),h);c.closePath();const gradient=c.createLinearGradient(0,0,0,h);gradient.addColorStop(0,'rgba(153,135,255,.30)');gradient.addColorStop(1,'rgba(153,135,255,0)');c.fillStyle=gradient;c.fill();
    c.beginPath();points.forEach((v,i)=>i?c.lineTo(x(i),y(v)):c.moveTo(x(i),y(v)));c.strokeStyle='#ad9cff';c.lineWidth=2;c.stroke();c.beginPath();c.arc(x(points.length-1),y(points[points.length-1]),4,0,Math.PI*2);c.fillStyle='#d2c8ff';c.fill();$('price').textContent=price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  }
  setInterval(()=>{price=Math.max(1,price+(Math.random()-.5)*5);points.push(price);points.shift();if($('page-trade').classList.contains('active'))draw();},2500);
  window.addEventListener('resize',draw);$('market').addEventListener('change',draw);render();requestAnimationFrame(draw);
})();
