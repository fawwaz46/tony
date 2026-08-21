"use strict";(()=>{var T={breaks:"Breaks","behavior-change":"Behaves differently",compatible:"Compatible"},S={breaks:0,"behavior-change":1,compatible:2},M={new:"new",changed:"changed",removed:"no longer happens",same:""},r=s=>String(s??"").replace(/[&<>"']/g,n=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[n]),g=(s,n=0)=>{let i=typeof s=="number"?s:Number(s);return Number.isFinite(i)?Math.trunc(i):n},w=s=>String(s??"").replace(/[^a-zA-Z0-9_-]/g,""),k=s=>s.replace(/[^A-Za-z0-9]/g,"_"),v=s=>String(s).padStart(2,"0");function L(s){if(!s)return"";let n=g(s[0]),i=g(s[1]);return`<span class="ln">${n===i?`line ${n}`:`lines ${n}\u2013${i}`}</span>`}var R=[["prev","Prev"],["now","New"],["impact","Changes"]],B=0;function C(s,n,i,a){if(n==="risk")return`<div class="ann risk"><p class="t">Potential risk${L(i)}</p><p class="n">${r(s.text)}</p></div>`;let h=r(s.title||"Note"),l=R.filter(([e])=>s[e]).map(([e,m])=>({key:e,label:m,text:s[e]}));if(l.length<=1){let e=l[0]?.text??s.note??"";return`<div class="ann"><p class="t">${h}${L(i)}</p><p class="n">${r(e)}</p></div>`}let p=++B,t=l.map((e,m)=>`<button class="pt" data-g="${p}" data-p="${e.key}" aria-selected="${m===0}">${e.label}</button>`).join(""),o=l.map((e,m)=>`<p class="n pane" data-g="${p}" data-p="${e.key}"${m===0?"":" hidden"}>${r(e.text)}</p>`).join("");return`<div class="ann"><p class="t">${h}<span class="k">${r(a.toUpperCase())}</span>${L(i)}</p><div class="tabs">${t}</div>${o}</div>`}function W(s,n,i){return s.map((a,h)=>{let l=h+1,p=a.blocks??[],t=p.filter(u=>u.k!=="row").length,o=(u,c)=>c[u]??{},e;a.binary?e='<p class="bin">Binary \u2014 not shown.</p>':p.length===0?e='<p class="bin">No textual changes.</p>':e=`<div class="hunk">${p.map(c=>c.k==="row"?`<div class="l ${w(c.cls)}"><span class="g">${c.g==null?"":g(c.g)}</span>${r(c.text)||"&nbsp;"}</div>`:C(o(g(c.n),c.k==="risk"?i:n),c.k==="risk"?"risk":"note",c.span,String(c.tag??""))).join("")}</div>`;let m=!a.binary&&t>0?" open":"",$=a.oldPath?`<span class="from">from ${r(a.oldPath)}</span>`:"",d=t>0?`<span class="nb">${t}</span>`:"";return`
<details class="file" id="file-${k(a.path)}"${m}>
  <summary>
    <span class="ix">[${v(l)}]</span>
    <span class="st ${r(a.status)}">${r(String(a.status).slice(0,3))}</span>
    <span class="fp">${r(a.path)}</span>${$}
    ${d}
    <span class="cnt"><b class="${g(a.additions)?"pos":"z"}">+${g(a.additions)}</b> <b class="${g(a.deletions)?"neg":"z"}">&minus;${g(a.deletions)}</b></span>
  </summary>
  ${e}
</details>`}).join("")}function D(s){let n=s.kind??"behavior-change",i="";return s.symbol&&(i=`<span class="via">via <code>${r(s.symbol)}</code>${s.fromPath?` in ${r(s.fromPath)}`:""}</span>`),`<div class="ann imp ${r(n)}"><p class="t">${r(T[n]??n)}${i}</p><p class="n">${r(s.why)}</p></div>`}function O(s,n){let i=new Map;for(let l of s)l.path&&(i.has(l.path)||i.set(l.path,[]),i.get(l.path).push(l));let a=l=>Math.min(...l.map(p=>S[p.kind]??1));return[...i.entries()].sort((l,p)=>a(l[1])-a(p[1])).map(([l,p],t)=>{let o=t+1,e=Object.keys(S).find(c=>S[c]===a(p)),m=n[l]??null,$=new Map;for(let c of p){let b=g(c.line,1);$.has(b)||$.set(b,[]),$.get(b).push(c)}let d=p.slice().sort((c,b)=>(c.line??1)-(b.line??1)).map(c=>`<a class="jump ${w(c.kind)}" href="#imp-${k(l)}-${g(c.line,1)}">line ${g(c.line,1)}</a>`).join(" "),u;if(!m)u='<p class="bin">Source not available for this file.</p>';else{let c=g(m.start,1),b=Math.max(0,c-1),q=c+m.lines.length-1,E=Math.max(0,g(m.total)-q),f=[];b>0&&f.push(`<div class="l c elide"><span class="g"></span>\u2026 ${b} earlier line${b===1?"":"s"}</div>`),m.lines.forEach((A,j)=>{let y=c+j;for(let I of $.get(y)??[])f.push(D(I));let P=$.has(y)?" hit":"";f.push(`<div class="l c${P}" id="imp-${k(l)}-${y}"><span class="g">${y}</span>${r(A)||"&nbsp;"}</div>`)}),E>0&&f.push(`<div class="l c elide"><span class="g"></span>\u2026 ${E} later line${E===1?"":"s"}</div>`),u=f.join("")}return`
<details class="file impacted ${e}" id="impact-${k(l)}"${o===1?" open":""}>
  <summary>
    <span class="ix">[${v(o)}]</span>
    <span class="st ${e}">${r(T[e]??e)}</span>
    <span class="fp">${r(l)}</span>
    <span class="nb">${p.length}</span>
    <span class="cnt">not edited</span>
  </summary>
  <div class="jumps">${p.length} impact site${p.length===1?"":"s"}: ${d}</div>
  <div class="hunk full">${u}</div>
</details>`}).join("")}function z(s){let n=s.window??null;if(!n)return'<div class="cw none">happens outside the codebase</div>';let i=g(n.hot?.[0],0),a=g(n.hot?.[1],-1),h=n.lines.map((l,p)=>{let t=g(n.start,1)+p;return`<div class="l c${t>=i&&t<=a?" hot":""}"><span class="g">${t}</span>${r(l)||"&nbsp;"}</div>`}).join("");return`<div class="cw"><div class="cwh">${r(s.path)}</div><div class="hunk">${h}</div></div>`}function _(s){let n=Object.entries(s??{}).slice(0,3);return n.length===0?"":`<div class="state"><p class="cap">[ state ]</p>${n.map(([a,h])=>{let l=String(h);if(l.includes("->")){let[p,,t]=(()=>{let o=l.indexOf("->");return[l.slice(0,o),"->",l.slice(o+2)]})();return`<div class="sv"><span class="sk">${r(a)}</span><span class="was">${r(p.trim())}</span><span class="to">\u2192</span><span class="now">${r(t.trim())}</span></div>`}return`<div class="sv"><span class="sk">${r(a)}</span><span class="now">${r(l)}</span></div>`}).join("")}</div>`}function F(s){return s.length===0?"":'<div class="wintro"><p><b>These are traces, not diagrams.</b> Each one follows a single real scenario from the moment it starts, one step at a time. The code shown is read straight from your files.</p><p>Use <b>next</b> to advance. Before you press it, say what you think happens next \u2014 that guess is what makes the step stick.</p></div>'+s.map((i,a)=>{let h=i.steps??[];if(h.length===0)return"";let l=[];for(let d of h)d.path&&!l.includes(d.path)&&l.push(d.path);let p=h.filter(d=>(d.phase||"same")!=="same").length,t=s.length>1?` / ${v(s.length)}`:"",o=l.map(d=>`<span class="chip">${r(d.split("/").pop())}</span>`).join("")+(p>0?`<span class="chip hot">${p} of ${h.length} steps are new</span>`:""),e=i.whatChanged?`<p class="wchg"><span class="tl">What changed</span> ${r(i.whatChanged)}</p>`:"",m=h.map((d,u)=>{let c=d.phase||"same";return`<button class="dot ${w(c)}" data-w="${a}" data-s="${u}" aria-label="Step ${u+1}"${u===0?' aria-current="true"':""}>${v(u+1)}</button>`}).join(""),$=h.map((d,u)=>{let c=d.phase||"same",b=M[c]?`<span class="ph ${w(c)}">${M[c]}</span>`:"";return`<div class="stepPanel${u===0?" on":""}" data-w="${a}" data-s="${u}"><p class="say">${r(d.say)}${b}</p><div class="split">${z(d)}${_(d.state)}</div></div>`}).join("");return`
<section class="wt" data-w="${a}" data-n="${h.length}">
  <header class="wth">
    <p class="cap">[ walkthrough ${v(a+1)}${t} ]</p>
    <h3>${r(i.title||"Walkthrough")}</h3>
    <p class="trig"><span class="tl">Starts when</span> ${r(i.trigger)}</p>
    ${e}
    <div class="covers">${o}</div>
  </header>
  <div class="dots">${m}</div>
  <div class="panels">${$}</div>
  <div class="wtnav">
    <button class="wprev" data-w="${a}" disabled>&#8249; back</button>
    <span class="wpos" data-w="${a}">step 1 of ${h.length}</span>
    <button class="wnext" data-w="${a}">next &#8250;</button>
  </div>
</section>`}).join("")}function x(s,n){let i=n.files??[],a=n.annotations??[],h=n.risks??[],l=(n.impacts??[]).filter(u=>u.path),p=n.walkthroughs??[],t=n.impactWindows??{},o=new Set(l.map(u=>u.path)).size,e=i.reduce((u,c)=>u+g(c.additions),0),m=i.reduce((u,c)=>u+g(c.deletions),0),$=h.filter(u=>!u.path),d=$.length?`<section class="loose"><h2>Risks outside the diff</h2><ul>${$.map(u=>`<li>${r(u.text)}</li>`).join("")}</ul></section>`:"";s.innerHTML=`
<div class="wrap">
<header>
  <div class="mh">
    <span class="brand">tony</span>
    <span class="rng">${r(n.range)}</span>
    <span class="repo">${r(n.repo)}</span>
  </div>
  <h1>${r(n.intent||"No summary produced.")}</h1>
  <div class="meta">
    <span>${i.length} files</span>
    <span><b class="pos">+${e}</b> <b class="neg">&minus;${m}</b></span>
    <span>${a.length} annotations</span>
    <label class="toggle"><input type="checkbox" id="riskToggle"> potential risks (${h.length})</label>
  </div>
</header>
${d}
<nav class="tabs-main">
  <button class="mt" data-t="files" aria-selected="true">File changes <span class="c">${i.length}</span></button>
  <button class="mt" data-t="blast" aria-selected="false"${o?"":" disabled"}>Blast radius <span class="c">${o}</span></button>
  <button class="mt" data-t="walk" aria-selected="false"${p.length?"":" disabled"}>How it works <span class="c">${p.length}</span></button>
</nav>
<div id="pane-files">${W(i,a,h)}</div>
<div id="pane-blast" hidden>
  <div class="stepper" id="stepper">
    <button id="prevImp" aria-label="Previous impact">&#8249;</button>
    <span id="impPos">impact 1 of ${l.length}</span>
    <button id="nextImp" aria-label="Next impact">&#8250;</button>
    <span class="sh" id="impWhere"></span>
  </div>
  ${O(l,t)}
</div>
<div id="pane-walk" hidden>${F(p)}</div>
</div>`,K(s)}function K(s){let n=t=>s.querySelector(`#${t}`);s.querySelectorAll(".mt").forEach(t=>t.addEventListener("click",()=>{let o=t.dataset.t;s.querySelectorAll(".mt").forEach(e=>e.setAttribute("aria-selected",String(e.dataset.t===o))),n("pane-files").hidden=o!=="files",n("pane-blast").hidden=o!=="blast",n("pane-walk").hidden=o!=="walk"})),s.querySelectorAll(".wt").forEach(t=>{let o=Number(t.dataset.n),e=0,m=()=>{t.querySelectorAll(".stepPanel").forEach(d=>d.classList.toggle("on",Number(d.dataset.s)===e)),t.querySelectorAll(".dot").forEach(d=>d.toggleAttribute("aria-current",Number(d.dataset.s)===e)),t.querySelector(".wpos").textContent=`step ${e+1} of ${o}`,t.querySelector(".wprev").disabled=e===0,t.querySelector(".wnext").disabled=e===o-1},$=d=>{e=Math.max(0,Math.min(o-1,d)),m()};t.querySelector(".wprev").onclick=()=>$(e-1),t.querySelector(".wnext").onclick=()=>$(e+1),t.querySelectorAll(".dot").forEach(d=>{d.onclick=()=>$(Number(d.dataset.s))}),m()});function i(t){let o=t.querySelector(".hunk.full"),e=t.querySelector(".l.hit");o&&e&&(o.scrollTop=Math.max(0,e.offsetTop-o.clientHeight/3))}s.querySelectorAll("#pane-blast details.impacted").forEach(t=>{t.open&&i(t),t.addEventListener("toggle",()=>{t.open&&i(t)})});let a=[...s.querySelectorAll("#pane-blast .l.hit")],h=-1;function l(t){if(!a.length)return;h=(t+a.length)%a.length;let o=a[h];o.closest("details").open=!0,a.forEach(m=>m.classList.remove("focus")),o.classList.add("focus"),o.scrollIntoView({behavior:"smooth",block:"center"}),n("impPos").textContent=`impact ${h+1} of ${a.length}`;let e=o.closest("details").querySelector(".fp");n("impWhere").textContent=e?e.textContent:""}n("prevImp")?.addEventListener("click",()=>l(h-1)),n("nextImp")?.addEventListener("click",()=>l(h+1)),document.addEventListener("keydown",t=>{n("pane-blast").hidden||(t.key==="]"&&l(h+1),t.key==="["&&l(h-1))}),s.addEventListener("click",t=>{let o=t.target.closest(".pt");if(!o)return;let e=o.dataset.g,m=o.dataset.p;s.querySelectorAll(`.pt[data-g="${e}"]`).forEach($=>$.setAttribute("aria-selected",String($.dataset.p===m))),s.querySelectorAll(`.pane[data-g="${e}"]`).forEach($=>{$.hidden=$.dataset.p!==m})});let p=n("riskToggle");document.body.classList.add("risks-off"),p.addEventListener("change",()=>document.body.classList.toggle("risks-off",!p.checked))}var H=document.getElementById("tony-root"),N=document.getElementById("tony-payload");H&&N&&x(H,JSON.parse(N.textContent||"{}"));})();
