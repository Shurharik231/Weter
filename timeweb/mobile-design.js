/* UI-only mobile interactions. Does not touch calculation/map state. */
(()=>{
  const init=()=>{
    const side=document.querySelector('.side');
    if(!side)return;
    const toggle=document.createElement('button');
    toggle.className='ui-menu-toggle';
    toggle.type='button';
    toggle.setAttribute('aria-label','Открыть меню');
    toggle.setAttribute('aria-expanded','true');
    toggle.textContent='☰';
    document.body.appendChild(toggle);
    const setOpen=open=>{side.classList.toggle('ui-collapsed',!open);toggle.textContent=open?'×':'☰';toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',open?'Скрыть меню':'Открыть меню')};
    toggle.addEventListener('click',()=>setOpen(side.classList.contains('ui-collapsed')));
    document.querySelectorAll('.tab').forEach(tab=>tab.addEventListener('click',()=>{if(innerWidth<=850)setOpen(false)}));
    window.addEventListener('resize',()=>{if(innerWidth>850)setOpen(true)});
    const help=document.createElement('button');help.className='ui-help';help.type='button';help.textContent='?';help.setAttribute('aria-label','Подсказка');
    const card=document.createElement('div');card.className='ui-help-card';card.innerHTML='<strong>Как пользоваться</strong><span>Выберите вкладку, задайте параметры и укажите точку на карте. На мобильном меню можно открыть кнопкой ☰.</span>';
    document.body.append(help,card);help.addEventListener('click',()=>card.classList.toggle('open'));
    document.addEventListener('click',e=>{if(card.classList.contains('open')&&!card.contains(e.target)&&e.target!==help)card.classList.remove('open')});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
