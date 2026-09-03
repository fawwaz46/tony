"use strict";(()=>{var M={breaks:"Breaks","behavior-change":"Behaves differently",compatible:"Compatible"},T={breaks:0,"behavior-change":1,compatible:2},x={new:"new",changed:"changed",removed:"no longer happens",same:""},h=e=>String(e??"").replace(/[&<>"']/g,t=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[t]),g=(e,t=0)=>{let s=typeof e=="number"?e:Number(e);return Number.isFinite(s)?Math.trunc(s):t},S=e=>String(e??"").replace(/[^a-zA-Z0-9_-]/g,""),k=e=>e.replace(/[^A-Za-z0-9]/g,"_"),E=e=>String(e).padStart(2,"0");function w(e){if(!e)return"";let t=g(e[0]),s=g(e[1]);return`<span class="ln">${t===s?`line ${t}`:`lines ${t}\u2013${s}`}</span>`}var R=[["prev","Prev"],["now","New"],["impact","Changes"]],B=0;function W(e){return`<div class="gap"><span class="gl">${w(e)}</span><span class="gt">not explained</span></div>`}function F(e,t){return`<div class="ann skip"><p class="t">Not explained${w(t)}</p><p class="n">${h(e.why||"")}</p></div>`}function z(e,t,s,m){if(t==="risk")return`<div class="ann risk"><p class="t">Potential risk${w(s)}</p><p class="n">${h(e.text)}</p></div>`;let n=h(e.title||"Note"),a=R.filter(([l])=>e[l]).map(([l,o])=>({key:l,label:o,text:e[l]}));if(a.length<=1){let l=a[0]?.text??e.note??"";return`<div class="ann"><p class="t">${n}${w(s)}</p><p class="n">${h(l)}</p></div>`}let p=++B,f=a.map((l,o)=>`<button class="pt" data-g="${p}" data-p="${l.key}" aria-selected="${o===0}">${l.label}</button>`).join(""),i=a.map((l,o)=>`<p class="n pane" data-g="${p}" data-p="${l.key}"${o===0?"":" hidden"}>${h(l.text)}</p>`).join("");return`<div class="ann"><p class="t">${n}<span class="k">${h(m.toUpperCase())}</span>${w(s)}</p><div class="tabs">${f}</div>${i}</div>`}function D(e,t,s,m){return e.map((n,a)=>{let p=a+1,f=n.blocks??[],i=f.filter(d=>d.k==="note"||d.k==="risk").length,l=f.filter(d=>d.k==="gap").length,o=(d,r)=>r[d]??{},$;n.binary?$='<p class="bin">Binary \u2014 not shown.</p>':f.length===0?$='<p class="bin">No textual changes.</p>':$=`<div class="hunk">${f.map(r=>r.k==="row"?`<div class="l ${S(r.cls)}"><span class="g">${r.g==null?"":g(r.g)}</span>${h(r.text)||"&nbsp;"}</div>`:r.k==="gap"?W(r.span):r.k==="skip"?F(o(g(r.n),m),r.span):z(o(g(r.n),r.k==="risk"?s:t),r.k==="risk"?"risk":"note",r.span,String(r.tag??""))).join("")}</div>`;let b=n.oldPath?`<span class="from">from ${h(n.oldPath)}</span>`:"",u=i>0?`<span class="nb">${i}</span>`:"",c=g(n.unexplainedLines)>0?`<span class="gb">${g(n.unexplainedLines)} lines unexplained</span>`:"";return`
<section class="file" id="file-${k(n.path)}"${a===0?"":" hidden"}>
  <div class="fhead">
    <span class="ix">[${E(p)}]</span>
    <span class="st ${h(n.status)}">${h(String(n.status).slice(0,3))}</span>
    <span class="fp">${h(n.path)}</span>${b}
    ${u}${c}
    <span class="cnt"><b class="${g(n.additions)?"pos":"z"}">+${g(n.additions)}</b> <b class="${g(n.deletions)?"neg":"z"}">&minus;${g(n.deletions)}</b></span>
  </div>
  ${$}
</section>`}).join("")}var O={added:"+",deleted:"\u2212",renamed:"\u2192"};function _(e){let t={name:"",dir:!0,children:[]};e.forEach((n,a)=>{let p=String(n?.path??"").split("/").filter(Boolean);if(p.length===0)return;let f=t;p.slice(0,-1).forEach(i=>{let l=f.children.find(o=>o.dir&&o.name===i);l||(l={name:i,dir:!0,children:[]},f.children.push(l)),f=l}),f.children.push({name:p[p.length-1],dir:!1,children:[],file:n,index:a+1})});let s=n=>{for(n.children=n.children.map(s);n.dir&&n.children.length===1&&n.children[0].dir;){let a=n.children[0];n.name=`${n.name}/${a.name}`,n.children=a.children}return n},m=n=>(n.forEach(a=>m(a.children)),n.sort((a,p)=>a.dir===p.dir?a.name.localeCompare(p.name):a.dir?-1:1),n);return m(t.children.map(s))}function H(e){return e.map(t=>{if(t.dir)return`
<li class="td">
  <button class="tdh" type="button" aria-expanded="true">
    <span class="tw" aria-hidden="true"></span><span class="tnm">${h(t.name)}</span>
  </button>
  <ul class="tsub">${H(t.children)}</ul>
</li>`;let s=t.file??{},m=String(s.status??""),n=O[m]??"\xB1";return`
<li class="tfl" data-search="${h(String(s.path??"").toLowerCase())}">
  <button class="tfb" type="button" data-target="file-${k(String(s.path??""))}"${t.index===1?" aria-current":""}>
    <span class="ti ${S(m)}" aria-hidden="true">${n}</span>
    <span class="tnm">${h(t.name)}</span>
    ${g(s.unexplainedLines)?`<span class="tg" title="${g(s.unexplainedLines)} lines unexplained">\u25CF</span>`:""}
    <span class="tct"><b class="${g(s.additions)?"pos":"z"}">+${g(s.additions)}</b> <b class="${g(s.deletions)?"neg":"z"}">&minus;${g(s.deletions)}</b></span>
  </button>
</li>`}).join("")}function U(e){let t=_(e);return t.length===0?"":`
<aside class="tree" aria-label="Changed files">
  <div class="tfil">
    <input type="search" id="treeFilter" placeholder="Filter files\u2026" aria-label="Filter files" autocomplete="off">
  </div>
  <ul class="tn">${H(t)}</ul>
  <p class="tnone" hidden>No files match.</p>
</aside>`}function G(e){let t=e.kind??"behavior-change",s="";return e.symbol&&(s=`<span class="via">via <code>${h(e.symbol)}</code>${e.fromPath?` in ${h(e.fromPath)}`:""}</span>`),`<div class="ann imp ${h(t)}"><p class="t">${h(M[t]??t)}${s}</p><p class="n">${h(e.why)}</p></div>`}function K(e,t){let s=new Map;for(let a of e)a.path&&(s.has(a.path)||s.set(a.path,[]),s.get(a.path).push(a));let m=a=>Math.min(...a.map(p=>T[p.kind]??1));return[...s.entries()].sort((a,p)=>m(a[1])-m(p[1])).map(([a,p],f)=>{let i=f+1,l=Object.keys(T).find(c=>T[c]===m(p)),o=t[a]??null,$=new Map;for(let c of p){let d=g(c.line,1);$.has(d)||$.set(d,[]),$.get(d).push(c)}let b=p.slice().sort((c,d)=>(c.line??1)-(d.line??1)).map(c=>`<a class="jump ${S(c.kind)}" href="#imp-${k(a)}-${g(c.line,1)}">line ${g(c.line,1)}</a>`).join(" "),u;if(!o)u='<p class="bin">Source not available for this file.</p>';else{let c=g(o.start,1),d=Math.max(0,c-1),r=c+o.lines.length-1,y=Math.max(0,g(o.total)-r),v=[];d>0&&v.push(`<div class="l c elide"><span class="g"></span>\u2026 ${d} earlier line${d===1?"":"s"}</div>`),o.lines.forEach((I,j)=>{let L=c+j;for(let C of $.get(L)??[])v.push(G(C));let P=$.has(L)?" hit":"";v.push(`<div class="l c${P}" id="imp-${k(a)}-${L}"><span class="g">${L}</span>${h(I)||"&nbsp;"}</div>`)}),y>0&&v.push(`<div class="l c elide"><span class="g"></span>\u2026 ${y} later line${y===1?"":"s"}</div>`),u=v.join("")}return`
<details class="file impacted ${l}" id="impact-${k(a)}"${i===1?" open":""}>
  <summary>
    <span class="ix">[${E(i)}]</span>
    <span class="st ${l}">${h(M[l]??l)}</span>
    <span class="fp">${h(a)}</span>
    <span class="nb">${p.length}</span>
    <span class="cnt">not edited</span>
  </summary>
  <div class="jumps">${p.length} impact site${p.length===1?"":"s"}: ${b}</div>
  <div class="hunk full">${u}</div>
</details>`}).join("")}function V(e){let t=e.window??null;if(!t)return'<div class="cw none">happens outside the codebase</div>';let s=g(t.hot?.[0],0),m=g(t.hot?.[1],-1),n=t.lines.map((a,p)=>{let f=g(t.start,1)+p;return`<div class="l c${f>=s&&f<=m?" hot":""}"><span class="g">${f}</span>${h(a)||"&nbsp;"}</div>`}).join("");return`<div class="cw"><div class="cwh">${h(e.path)}</div><div class="hunk">${n}</div></div>`}function Z(e){let t=Object.entries(e??{}).slice(0,3);return t.length===0?"":`<div class="state"><p class="cap">[ state ]</p>${t.map(([m,n])=>{let a=String(n);if(a.includes("->")){let[p,,f]=(()=>{let i=a.indexOf("->");return[a.slice(0,i),"->",a.slice(i+2)]})();return`<div class="sv"><span class="sk">${h(m)}</span><span class="was">${h(p.trim())}</span><span class="to">\u2192</span><span class="now">${h(f.trim())}</span></div>`}return`<div class="sv"><span class="sk">${h(m)}</span><span class="now">${h(a)}</span></div>`}).join("")}</div>`}function J(e){return e.length===0?"":'<div class="wintro"><p><b>These are traces, not diagrams.</b> Each one follows a single real scenario from the moment it starts, one step at a time. The code shown is read straight from your files.</p><p>Use <b>next</b> to advance. Before you press it, say what you think happens next \u2014 that guess is what makes the step stick.</p></div>'+e.map((s,m)=>{let n=s.steps??[];if(n.length===0)return"";let a=[];for(let u of n)u.path&&!a.includes(u.path)&&a.push(u.path);let p=n.filter(u=>(u.phase||"same")!=="same").length,f=e.length>1?` / ${E(e.length)}`:"",i=a.map(u=>`<span class="chip">${h(u.split("/").pop())}</span>`).join("")+(p>0?`<span class="chip hot">${p} of ${n.length} steps are new</span>`:""),l=s.whatChanged?`<p class="wchg"><span class="tl">What changed</span> ${h(s.whatChanged)}</p>`:"",o=s.reach==="downstream"?'<span class="rch">not changed by this diff \u2014 reached by it</span>':"",$=n.map((u,c)=>{let d=u.phase||"same";return`<button class="dot ${S(d)}" data-w="${m}" data-s="${c}" aria-label="Step ${c+1}"${c===0?' aria-current="true"':""}>${E(c+1)}</button>`}).join(""),b=n.map((u,c)=>{let d=u.phase||"same",r=x[d]?`<span class="ph ${S(d)}">${x[d]}</span>`:"";return`<div class="stepPanel${c===0?" on":""}" data-w="${m}" data-s="${c}"><p class="say">${h(u.say)}${r}</p><div class="split">${V(u)}${Z(u.state)}</div></div>`}).join("");return`
<section class="wt" data-w="${m}" data-n="${n.length}">
  <header class="wth">
    <p class="cap">[ walkthrough ${E(m+1)}${f} ]${o}</p>
    <h3>${h(s.title||"Walkthrough")}</h3>
    <p class="trig"><span class="tl">Starts when</span> ${h(s.trigger)}</p>
    ${l}
    <div class="covers">${i}</div>
  </header>
  <div class="dots">${$}</div>
  <div class="panels">${b}</div>
  <div class="wtnav">
    <button class="wprev" data-w="${m}" disabled>&#8249; back</button>
    <span class="wpos" data-w="${m}">step 1 of ${n.length}</span>
    <button class="wnext" data-w="${m}">next &#8250;</button>
  </div>
</section>`}).join("")}function N(e,t){let s=t.files??[],m=t.annotations??[],n=t.risks??[],a=t.skips??[],p=(t.impacts??[]).filter(r=>r.path),f=t.walkthroughs??[],i=t.impactWindows??{},l=new Set(p.map(r=>r.path)).size,o=s.reduce((r,y)=>r+g(y.additions),0),$=s.reduce((r,y)=>r+g(y.deletions),0),b=n.filter(r=>!r.path),u=g(t.coverage?.unexplainedLines),c=Math.round(100*u/Math.max(g(t.coverage?.changedLines),1)),d=b.length?`<section class="loose"><h2>Risks outside the diff</h2><ul>${b.map(r=>`<li>${h(r.text)}</li>`).join("")}</ul></section>`:"";e.innerHTML=`
<div class="wrap">
<header>
  <div class="mh">
    <span class="brand">tony</span>
    <span class="rng">${h(t.range)}</span>
    <span class="repo">${h(t.repo)}</span>
  </div>
  <h1>${h(t.intent||"No summary produced.")}</h1>
  <div class="meta">
    <span>${s.length} files</span>
    <span><b class="pos">+${o}</b> <b class="neg">&minus;${$}</b></span>
    <span>${m.length} annotations</span>
    <label class="toggle"><input type="checkbox" id="riskToggle"> potential risks (${n.length})</label>
    ${u>0?`<span class="gsum">${u} of ${g(t.coverage?.changedLines)} changed lines unexplained (${c}%)</span>`:""}
  </div>
</header>
${d}
<nav class="tabs-main">
  <button class="mt" data-t="files" aria-selected="true">File changes <span class="c">${s.length}</span></button>
  <button class="mt" data-t="blast" aria-selected="false"${l?"":" disabled"}>Blast radius <span class="c">${l}</span></button>
  <button class="mt" data-t="walk" aria-selected="false"${f.length?"":" disabled"}>How it works <span class="c">${f.length}</span></button>
</nav>
<div id="pane-files">
  <div class="flayout">
    ${U(s)}
    <div class="fmain">${D(s,m,n,a)}</div>
  </div>
</div>
<div id="pane-blast" hidden>
  <div class="stepper" id="stepper">
    <button id="prevImp" aria-label="Previous impact">&#8249;</button>
    <span id="impPos">impact 1 of ${p.length}</span>
    <button id="nextImp" aria-label="Next impact">&#8250;</button>
    <span class="sh" id="impWhere"></span>
  </div>
  ${K(p,i)}
</div>
<div id="pane-walk" hidden>${J(f)}</div>
</div>`,Q(e)}function Q(e){let t=i=>e.querySelector(`#${i}`);e.querySelectorAll(".mt").forEach(i=>i.addEventListener("click",()=>{let l=i.dataset.t;e.querySelectorAll(".mt").forEach(o=>o.setAttribute("aria-selected",String(o.dataset.t===l))),t("pane-files").hidden=l!=="files",t("pane-blast").hidden=l!=="blast",t("pane-walk").hidden=l!=="walk"}));let s=e.querySelector(".tree");if(s){let i=Array.from(s.querySelectorAll(".tfb")),l=Array.from(e.querySelectorAll("#pane-files .file")),o=Math.max(0,i.findIndex(c=>c.hasAttribute("aria-current"))),$=c=>{let d=i[c];if(!d)return;let r=d.dataset.target;l.forEach(y=>{y.hidden=y.id!==r}),i.forEach((y,v)=>y.toggleAttribute("aria-current",v===c)),o=c,e.querySelector("#pane-files")?.scrollIntoView?.({block:"start"})};i.forEach((c,d)=>{c.addEventListener("click",()=>$(d))}),document.addEventListener("keydown",c=>{if(t("pane-files").hidden)return;let d=c.target;d&&d.tagName==="INPUT"||(c.key==="]"&&$(Math.min(i.length-1,o+1)),c.key==="["&&$(Math.max(0,o-1)))}),s.querySelectorAll(".tdh").forEach(c=>{c.addEventListener("click",()=>{let d=c.getAttribute("aria-expanded")==="true";c.setAttribute("aria-expanded",String(!d));let r=c.nextElementSibling;r&&(r.hidden=d)})});let b=s.querySelector("#treeFilter"),u=s.querySelector(".tnone");b?.addEventListener("input",()=>{let c=b.value.trim().toLowerCase(),d=0;if(s.querySelectorAll(".tfl").forEach(r=>{let y=!c||(r.dataset.search??"").includes(c);r.hidden=!y,y&&d++}),s.querySelectorAll(".td").forEach(r=>{let y=r.querySelector(".tfl:not([hidden])")!==null;if(r.hidden=!y,c&&y){r.querySelector(".tdh")?.setAttribute("aria-expanded","true");let v=r.querySelector(".tsub");v&&(v.hidden=!1)}}),u&&(u.hidden=d>0),d>0&&i[o]?.parentElement?.hidden){let r=i.findIndex(y=>!y.parentElement?.hidden);r>=0&&$(r)}})}e.querySelectorAll(".wt").forEach(i=>{let l=Number(i.dataset.n),o=0,$=()=>{i.querySelectorAll(".stepPanel").forEach(u=>u.classList.toggle("on",Number(u.dataset.s)===o)),i.querySelectorAll(".dot").forEach(u=>u.toggleAttribute("aria-current",Number(u.dataset.s)===o)),i.querySelector(".wpos").textContent=`step ${o+1} of ${l}`,i.querySelector(".wprev").disabled=o===0,i.querySelector(".wnext").disabled=o===l-1},b=u=>{o=Math.max(0,Math.min(l-1,u)),$()};i.querySelector(".wprev").onclick=()=>b(o-1),i.querySelector(".wnext").onclick=()=>b(o+1),i.querySelectorAll(".dot").forEach(u=>{u.onclick=()=>b(Number(u.dataset.s))}),$()});function m(i){let l=i.querySelector(".hunk.full"),o=i.querySelector(".l.hit");l&&o&&(l.scrollTop=Math.max(0,o.offsetTop-l.clientHeight/3))}e.querySelectorAll("#pane-blast details.impacted").forEach(i=>{i.open&&m(i),i.addEventListener("toggle",()=>{i.open&&m(i)})});let n=[...e.querySelectorAll("#pane-blast .l.hit")],a=-1;function p(i){if(!n.length)return;a=(i+n.length)%n.length;let l=n[a];l.closest("details").open=!0,n.forEach($=>$.classList.remove("focus")),l.classList.add("focus"),l.scrollIntoView({behavior:"smooth",block:"center"}),t("impPos").textContent=`impact ${a+1} of ${n.length}`;let o=l.closest("details").querySelector(".fp");t("impWhere").textContent=o?o.textContent:""}t("prevImp")?.addEventListener("click",()=>p(a-1)),t("nextImp")?.addEventListener("click",()=>p(a+1)),document.addEventListener("keydown",i=>{t("pane-blast").hidden||(i.key==="]"&&p(a+1),i.key==="["&&p(a-1))}),e.addEventListener("click",i=>{let l=i.target.closest(".pt");if(!l)return;let o=l.dataset.g,$=l.dataset.p;e.querySelectorAll(`.pt[data-g="${o}"]`).forEach(b=>b.setAttribute("aria-selected",String(b.dataset.p===$))),e.querySelectorAll(`.pane[data-g="${o}"]`).forEach(b=>{b.hidden=b.dataset.p!==$})});let f=t("riskToggle");document.body.classList.add("risks-off"),f.addEventListener("change",()=>document.body.classList.toggle("risks-off",!f.checked))}var q=document.getElementById("tony-root"),A=document.getElementById("tony-payload");q&&A&&N(q,JSON.parse(A.textContent||"{}"));})();
