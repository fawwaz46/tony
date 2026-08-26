"use strict";(()=>{var M={breaks:"Breaks","behavior-change":"Behaves differently",compatible:"Compatible"},T={breaks:0,"behavior-change":1,compatible:2},x={new:"new",changed:"changed",removed:"no longer happens",same:""},u=e=>String(e??"").replace(/[&<>"']/g,t=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[t]),g=(e,t=0)=>{let s=typeof e=="number"?e:Number(e);return Number.isFinite(s)?Math.trunc(s):t},w=e=>String(e??"").replace(/[^a-zA-Z0-9_-]/g,""),k=e=>e.replace(/[^A-Za-z0-9]/g,"_"),E=e=>String(e).padStart(2,"0");function S(e){if(!e)return"";let t=g(e[0]),s=g(e[1]);return`<span class="ln">${t===s?`line ${t}`:`lines ${t}\u2013${s}`}</span>`}var R=[["prev","Prev"],["now","New"],["impact","Changes"]],B=0;function W(e){return`<div class="gap"><span class="gl">${S(e)}</span><span class="gt">not explained</span></div>`}function F(e,t,s,d){if(t==="risk")return`<div class="ann risk"><p class="t">Potential risk${S(s)}</p><p class="n">${u(e.text)}</p></div>`;let o=u(e.title||"Note"),n=R.filter(([l])=>e[l]).map(([l,c])=>({key:l,label:c,text:e[l]}));if(n.length<=1){let l=n[0]?.text??e.note??"";return`<div class="ann"><p class="t">${o}${S(s)}</p><p class="n">${u(l)}</p></div>`}let p=++B,$=n.map((l,c)=>`<button class="pt" data-g="${p}" data-p="${l.key}" aria-selected="${c===0}">${l.label}</button>`).join(""),a=n.map((l,c)=>`<p class="n pane" data-g="${p}" data-p="${l.key}"${c===0?"":" hidden"}>${u(l.text)}</p>`).join("");return`<div class="ann"><p class="t">${o}<span class="k">${u(d.toUpperCase())}</span>${S(s)}</p><div class="tabs">${$}</div>${a}</div>`}function z(e,t,s){return e.map((d,o)=>{let n=o+1,p=d.blocks??[],$=p.filter(r=>r.k==="note"||r.k==="risk").length,a=p.filter(r=>r.k==="gap").length,l=(r,i)=>i[r]??{},c;d.binary?c='<p class="bin">Binary \u2014 not shown.</p>':p.length===0?c='<p class="bin">No textual changes.</p>':c=`<div class="hunk">${p.map(i=>i.k==="row"?`<div class="l ${w(i.cls)}"><span class="g">${i.g==null?"":g(i.g)}</span>${u(i.text)||"&nbsp;"}</div>`:i.k==="gap"?W(i.span):F(l(g(i.n),i.k==="risk"?s:t),i.k==="risk"?"risk":"note",i.span,String(i.tag??""))).join("")}</div>`;let f=d.oldPath?`<span class="from">from ${u(d.oldPath)}</span>`:"",h=$>0?`<span class="nb">${$}</span>`:"",m=g(d.unexplainedLines)>0?`<span class="gb">${g(d.unexplainedLines)} lines unexplained</span>`:"";return`
<section class="file" id="file-${k(d.path)}"${o===0?"":" hidden"}>
  <div class="fhead">
    <span class="ix">[${E(n)}]</span>
    <span class="st ${u(d.status)}">${u(String(d.status).slice(0,3))}</span>
    <span class="fp">${u(d.path)}</span>${f}
    ${h}${m}
    <span class="cnt"><b class="${g(d.additions)?"pos":"z"}">+${g(d.additions)}</b> <b class="${g(d.deletions)?"neg":"z"}">&minus;${g(d.deletions)}</b></span>
  </div>
  ${c}
</section>`}).join("")}var D={added:"+",deleted:"\u2212",renamed:"\u2192"};function O(e){let t={name:"",dir:!0,children:[]};e.forEach((o,n)=>{let p=String(o?.path??"").split("/").filter(Boolean);if(p.length===0)return;let $=t;p.slice(0,-1).forEach(a=>{let l=$.children.find(c=>c.dir&&c.name===a);l||(l={name:a,dir:!0,children:[]},$.children.push(l)),$=l}),$.children.push({name:p[p.length-1],dir:!1,children:[],file:o,index:n+1})});let s=o=>{for(o.children=o.children.map(s);o.dir&&o.children.length===1&&o.children[0].dir;){let n=o.children[0];o.name=`${o.name}/${n.name}`,o.children=n.children}return o},d=o=>(o.forEach(n=>d(n.children)),o.sort((n,p)=>n.dir===p.dir?n.name.localeCompare(p.name):n.dir?-1:1),o);return d(t.children.map(s))}function H(e){return e.map(t=>{if(t.dir)return`
<li class="td">
  <button class="tdh" type="button" aria-expanded="true">
    <span class="tw" aria-hidden="true"></span><span class="tnm">${u(t.name)}</span>
  </button>
  <ul class="tsub">${H(t.children)}</ul>
</li>`;let s=t.file??{},d=String(s.status??""),o=D[d]??"\xB1";return`
<li class="tfl" data-search="${u(String(s.path??"").toLowerCase())}">
  <button class="tfb" type="button" data-target="file-${k(String(s.path??""))}"${t.index===1?" aria-current":""}>
    <span class="ti ${w(d)}" aria-hidden="true">${o}</span>
    <span class="tnm">${u(t.name)}</span>
    ${g(s.unexplainedLines)?`<span class="tg" title="${g(s.unexplainedLines)} lines unexplained">\u25CF</span>`:""}
    <span class="tct"><b class="${g(s.additions)?"pos":"z"}">+${g(s.additions)}</b> <b class="${g(s.deletions)?"neg":"z"}">&minus;${g(s.deletions)}</b></span>
  </button>
</li>`}).join("")}function _(e){let t=O(e);return t.length===0?"":`
<aside class="tree" aria-label="Changed files">
  <div class="tfil">
    <input type="search" id="treeFilter" placeholder="Filter files\u2026" aria-label="Filter files" autocomplete="off">
  </div>
  <ul class="tn">${H(t)}</ul>
  <p class="tnone" hidden>No files match.</p>
</aside>`}function U(e){let t=e.kind??"behavior-change",s="";return e.symbol&&(s=`<span class="via">via <code>${u(e.symbol)}</code>${e.fromPath?` in ${u(e.fromPath)}`:""}</span>`),`<div class="ann imp ${u(t)}"><p class="t">${u(M[t]??t)}${s}</p><p class="n">${u(e.why)}</p></div>`}function G(e,t){let s=new Map;for(let n of e)n.path&&(s.has(n.path)||s.set(n.path,[]),s.get(n.path).push(n));let d=n=>Math.min(...n.map(p=>T[p.kind]??1));return[...s.entries()].sort((n,p)=>d(n[1])-d(p[1])).map(([n,p],$)=>{let a=$+1,l=Object.keys(T).find(r=>T[r]===d(p)),c=t[n]??null,f=new Map;for(let r of p){let i=g(r.line,1);f.has(i)||f.set(i,[]),f.get(i).push(r)}let h=p.slice().sort((r,i)=>(r.line??1)-(i.line??1)).map(r=>`<a class="jump ${w(r.kind)}" href="#imp-${k(n)}-${g(r.line,1)}">line ${g(r.line,1)}</a>`).join(" "),m;if(!c)m='<p class="bin">Source not available for this file.</p>';else{let r=g(c.start,1),i=Math.max(0,r-1),b=r+c.lines.length-1,v=Math.max(0,g(c.total)-b),y=[];i>0&&y.push(`<div class="l c elide"><span class="g"></span>\u2026 ${i} earlier line${i===1?"":"s"}</div>`),c.lines.forEach((I,j)=>{let L=r+j;for(let C of f.get(L)??[])y.push(U(C));let P=f.has(L)?" hit":"";y.push(`<div class="l c${P}" id="imp-${k(n)}-${L}"><span class="g">${L}</span>${u(I)||"&nbsp;"}</div>`)}),v>0&&y.push(`<div class="l c elide"><span class="g"></span>\u2026 ${v} later line${v===1?"":"s"}</div>`),m=y.join("")}return`
<details class="file impacted ${l}" id="impact-${k(n)}"${a===1?" open":""}>
  <summary>
    <span class="ix">[${E(a)}]</span>
    <span class="st ${l}">${u(M[l]??l)}</span>
    <span class="fp">${u(n)}</span>
    <span class="nb">${p.length}</span>
    <span class="cnt">not edited</span>
  </summary>
  <div class="jumps">${p.length} impact site${p.length===1?"":"s"}: ${h}</div>
  <div class="hunk full">${m}</div>
</details>`}).join("")}function K(e){let t=e.window??null;if(!t)return'<div class="cw none">happens outside the codebase</div>';let s=g(t.hot?.[0],0),d=g(t.hot?.[1],-1),o=t.lines.map((n,p)=>{let $=g(t.start,1)+p;return`<div class="l c${$>=s&&$<=d?" hot":""}"><span class="g">${$}</span>${u(n)||"&nbsp;"}</div>`}).join("");return`<div class="cw"><div class="cwh">${u(e.path)}</div><div class="hunk">${o}</div></div>`}function V(e){let t=Object.entries(e??{}).slice(0,3);return t.length===0?"":`<div class="state"><p class="cap">[ state ]</p>${t.map(([d,o])=>{let n=String(o);if(n.includes("->")){let[p,,$]=(()=>{let a=n.indexOf("->");return[n.slice(0,a),"->",n.slice(a+2)]})();return`<div class="sv"><span class="sk">${u(d)}</span><span class="was">${u(p.trim())}</span><span class="to">\u2192</span><span class="now">${u($.trim())}</span></div>`}return`<div class="sv"><span class="sk">${u(d)}</span><span class="now">${u(n)}</span></div>`}).join("")}</div>`}function Z(e){return e.length===0?"":'<div class="wintro"><p><b>These are traces, not diagrams.</b> Each one follows a single real scenario from the moment it starts, one step at a time. The code shown is read straight from your files.</p><p>Use <b>next</b> to advance. Before you press it, say what you think happens next \u2014 that guess is what makes the step stick.</p></div>'+e.map((s,d)=>{let o=s.steps??[];if(o.length===0)return"";let n=[];for(let h of o)h.path&&!n.includes(h.path)&&n.push(h.path);let p=o.filter(h=>(h.phase||"same")!=="same").length,$=e.length>1?` / ${E(e.length)}`:"",a=n.map(h=>`<span class="chip">${u(h.split("/").pop())}</span>`).join("")+(p>0?`<span class="chip hot">${p} of ${o.length} steps are new</span>`:""),l=s.whatChanged?`<p class="wchg"><span class="tl">What changed</span> ${u(s.whatChanged)}</p>`:"",c=o.map((h,m)=>{let r=h.phase||"same";return`<button class="dot ${w(r)}" data-w="${d}" data-s="${m}" aria-label="Step ${m+1}"${m===0?' aria-current="true"':""}>${E(m+1)}</button>`}).join(""),f=o.map((h,m)=>{let r=h.phase||"same",i=x[r]?`<span class="ph ${w(r)}">${x[r]}</span>`:"";return`<div class="stepPanel${m===0?" on":""}" data-w="${d}" data-s="${m}"><p class="say">${u(h.say)}${i}</p><div class="split">${K(h)}${V(h.state)}</div></div>`}).join("");return`
<section class="wt" data-w="${d}" data-n="${o.length}">
  <header class="wth">
    <p class="cap">[ walkthrough ${E(d+1)}${$} ]</p>
    <h3>${u(s.title||"Walkthrough")}</h3>
    <p class="trig"><span class="tl">Starts when</span> ${u(s.trigger)}</p>
    ${l}
    <div class="covers">${a}</div>
  </header>
  <div class="dots">${c}</div>
  <div class="panels">${f}</div>
  <div class="wtnav">
    <button class="wprev" data-w="${d}" disabled>&#8249; back</button>
    <span class="wpos" data-w="${d}">step 1 of ${o.length}</span>
    <button class="wnext" data-w="${d}">next &#8250;</button>
  </div>
</section>`}).join("")}function N(e,t){let s=t.files??[],d=t.annotations??[],o=t.risks??[],n=(t.impacts??[]).filter(i=>i.path),p=t.walkthroughs??[],$=t.impactWindows??{},a=new Set(n.map(i=>i.path)).size,l=s.reduce((i,b)=>i+g(b.additions),0),c=s.reduce((i,b)=>i+g(b.deletions),0),f=o.filter(i=>!i.path),h=g(t.coverage?.unexplainedLines),m=Math.round(100*h/Math.max(g(t.coverage?.changedLines),1)),r=f.length?`<section class="loose"><h2>Risks outside the diff</h2><ul>${f.map(i=>`<li>${u(i.text)}</li>`).join("")}</ul></section>`:"";e.innerHTML=`
<div class="wrap">
<header>
  <div class="mh">
    <span class="brand">tony</span>
    <span class="rng">${u(t.range)}</span>
    <span class="repo">${u(t.repo)}</span>
  </div>
  <h1>${u(t.intent||"No summary produced.")}</h1>
  <div class="meta">
    <span>${s.length} files</span>
    <span><b class="pos">+${l}</b> <b class="neg">&minus;${c}</b></span>
    <span>${d.length} annotations</span>
    <label class="toggle"><input type="checkbox" id="riskToggle"> potential risks (${o.length})</label>
    ${h>0?`<span class="gsum">${h} of ${g(t.coverage?.changedLines)} changed lines unexplained (${m}%)</span>`:""}
  </div>
</header>
${r}
<nav class="tabs-main">
  <button class="mt" data-t="files" aria-selected="true">File changes <span class="c">${s.length}</span></button>
  <button class="mt" data-t="blast" aria-selected="false"${a?"":" disabled"}>Blast radius <span class="c">${a}</span></button>
  <button class="mt" data-t="walk" aria-selected="false"${p.length?"":" disabled"}>How it works <span class="c">${p.length}</span></button>
</nav>
<div id="pane-files">
  <div class="flayout">
    ${_(s)}
    <div class="fmain">${z(s,d,o)}</div>
  </div>
</div>
<div id="pane-blast" hidden>
  <div class="stepper" id="stepper">
    <button id="prevImp" aria-label="Previous impact">&#8249;</button>
    <span id="impPos">impact 1 of ${n.length}</span>
    <button id="nextImp" aria-label="Next impact">&#8250;</button>
    <span class="sh" id="impWhere"></span>
  </div>
  ${G(n,$)}
</div>
<div id="pane-walk" hidden>${Z(p)}</div>
</div>`,J(e)}function J(e){let t=a=>e.querySelector(`#${a}`);e.querySelectorAll(".mt").forEach(a=>a.addEventListener("click",()=>{let l=a.dataset.t;e.querySelectorAll(".mt").forEach(c=>c.setAttribute("aria-selected",String(c.dataset.t===l))),t("pane-files").hidden=l!=="files",t("pane-blast").hidden=l!=="blast",t("pane-walk").hidden=l!=="walk"}));let s=e.querySelector(".tree");if(s){let a=Array.from(s.querySelectorAll(".tfb")),l=Array.from(e.querySelectorAll("#pane-files .file")),c=Math.max(0,a.findIndex(r=>r.hasAttribute("aria-current"))),f=r=>{let i=a[r];if(!i)return;let b=i.dataset.target;l.forEach(v=>{v.hidden=v.id!==b}),a.forEach((v,y)=>v.toggleAttribute("aria-current",y===r)),c=r,e.querySelector("#pane-files")?.scrollIntoView?.({block:"start"})};a.forEach((r,i)=>{r.addEventListener("click",()=>f(i))}),document.addEventListener("keydown",r=>{if(t("pane-files").hidden)return;let i=r.target;i&&i.tagName==="INPUT"||(r.key==="]"&&f(Math.min(a.length-1,c+1)),r.key==="["&&f(Math.max(0,c-1)))}),s.querySelectorAll(".tdh").forEach(r=>{r.addEventListener("click",()=>{let i=r.getAttribute("aria-expanded")==="true";r.setAttribute("aria-expanded",String(!i));let b=r.nextElementSibling;b&&(b.hidden=i)})});let h=s.querySelector("#treeFilter"),m=s.querySelector(".tnone");h?.addEventListener("input",()=>{let r=h.value.trim().toLowerCase(),i=0;if(s.querySelectorAll(".tfl").forEach(b=>{let v=!r||(b.dataset.search??"").includes(r);b.hidden=!v,v&&i++}),s.querySelectorAll(".td").forEach(b=>{let v=b.querySelector(".tfl:not([hidden])")!==null;if(b.hidden=!v,r&&v){b.querySelector(".tdh")?.setAttribute("aria-expanded","true");let y=b.querySelector(".tsub");y&&(y.hidden=!1)}}),m&&(m.hidden=i>0),i>0&&a[c]?.parentElement?.hidden){let b=a.findIndex(v=>!v.parentElement?.hidden);b>=0&&f(b)}})}e.querySelectorAll(".wt").forEach(a=>{let l=Number(a.dataset.n),c=0,f=()=>{a.querySelectorAll(".stepPanel").forEach(m=>m.classList.toggle("on",Number(m.dataset.s)===c)),a.querySelectorAll(".dot").forEach(m=>m.toggleAttribute("aria-current",Number(m.dataset.s)===c)),a.querySelector(".wpos").textContent=`step ${c+1} of ${l}`,a.querySelector(".wprev").disabled=c===0,a.querySelector(".wnext").disabled=c===l-1},h=m=>{c=Math.max(0,Math.min(l-1,m)),f()};a.querySelector(".wprev").onclick=()=>h(c-1),a.querySelector(".wnext").onclick=()=>h(c+1),a.querySelectorAll(".dot").forEach(m=>{m.onclick=()=>h(Number(m.dataset.s))}),f()});function d(a){let l=a.querySelector(".hunk.full"),c=a.querySelector(".l.hit");l&&c&&(l.scrollTop=Math.max(0,c.offsetTop-l.clientHeight/3))}e.querySelectorAll("#pane-blast details.impacted").forEach(a=>{a.open&&d(a),a.addEventListener("toggle",()=>{a.open&&d(a)})});let o=[...e.querySelectorAll("#pane-blast .l.hit")],n=-1;function p(a){if(!o.length)return;n=(a+o.length)%o.length;let l=o[n];l.closest("details").open=!0,o.forEach(f=>f.classList.remove("focus")),l.classList.add("focus"),l.scrollIntoView({behavior:"smooth",block:"center"}),t("impPos").textContent=`impact ${n+1} of ${o.length}`;let c=l.closest("details").querySelector(".fp");t("impWhere").textContent=c?c.textContent:""}t("prevImp")?.addEventListener("click",()=>p(n-1)),t("nextImp")?.addEventListener("click",()=>p(n+1)),document.addEventListener("keydown",a=>{t("pane-blast").hidden||(a.key==="]"&&p(n+1),a.key==="["&&p(n-1))}),e.addEventListener("click",a=>{let l=a.target.closest(".pt");if(!l)return;let c=l.dataset.g,f=l.dataset.p;e.querySelectorAll(`.pt[data-g="${c}"]`).forEach(h=>h.setAttribute("aria-selected",String(h.dataset.p===f))),e.querySelectorAll(`.pane[data-g="${c}"]`).forEach(h=>{h.hidden=h.dataset.p!==f})});let $=t("riskToggle");document.body.classList.add("risks-off"),$.addEventListener("change",()=>document.body.classList.toggle("risks-off",!$.checked))}var q=document.getElementById("tony-root"),A=document.getElementById("tony-payload");q&&A&&N(q,JSON.parse(A.textContent||"{}"));})();
