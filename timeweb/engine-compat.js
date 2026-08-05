/* Weter browser compatibility layer.
 * This file intentionally lives in timeweb only. It adds diagnostics and
 * advanced input fields without changing the Python project.
 */
(() => {
'use strict';
function addField(sectionId,id,label,value,placeholder){
  if(document.getElementById(id)) return;
  const sec=document.getElementById(sectionId); if(!sec) return;
  const wrap=document.createElement('label'); wrap.dataset.advanced='1';
  wrap.textContent=label;
  const ta=document.createElement('textarea'); ta.id=id; ta.rows=3; ta.placeholder=placeholder||''; ta.value=value||'';
  ta.style.cssText='width:100%;padding:8px;border:1px solid #ccd3d9;border-radius:7px;margin-top:4px;font:12px monospace;resize:vertical';
  wrap.appendChild(ta); sec.appendChild(wrap);
}
function addNumber(sectionId,id,label,value,min,max,step){
  if(document.getElementById(id)) return;
  const sec=document.getElementById(sectionId); if(!sec) return;
  const wrap=document.createElement('label'); wrap.dataset.advanced='1'; wrap.textContent=label;
  const inp=document.createElement('input'); inp.id=id; inp.type='number'; inp.value=value; inp.min=min; inp.max=max; inp.step=step;
  wrap.appendChild(inp); sec.appendChild(wrap);
}
function install(){
  addNumber('back','bstep','Шаг обратного расчёта, мин',1,0.1,60,0.1);
  addField('fav','fpolygon','Целевая зона polygon (JSON)','', '[{"lat":44.70,"lon":34.50},{"lat":44.72,"lon":34.52},{"lat":44.71,"lon":34.55}]');
  addField('fav','frestricted','Запрещённые зоны (JSON)','', '[[{"lat":44.70,"lon":34.50},{"lat":44.71,"lon":34.51},{"lat":44.70,"lon":34.52}]]');
  addField('fav','fhazards','Опасные зоны (JSON)','', '[[{"lat":44.70,"lon":34.50},{"lat":44.71,"lon":34.51},{"lat":44.70,"lon":34.52}]]');
  const note=document.createElement('div'); note.className='note'; note.textContent='Расширенные зоны передаются вычислительному ядру. Оставьте поля пустыми для режима одиночной цели.';
  const fav=document.getElementById('fav'); if(fav&&!fav.querySelector('[data-advanced-note]')){note.dataset.advancedNote='1';fav.appendChild(note);}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();
