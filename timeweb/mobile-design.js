/* UI-only mobile interactions. Does not alter calculation/map state. */
(()=>{
  const init=()=>{
    const side=document.querySelector('.side');
    if(!side)return;
    const backdrop=document.createElement('div');
    backdrop.className='ui-menu-backdrop ui-hidden';
    backdrop.setAttribute('aria-hidden','true');
    document.body.appendChild(backdrop);

    const toggle=document.createElement('button');
    toggle.className='ui-menu-toggle';
    toggle.type='button';
    toggle.setAttribute('aria-label','Открыть меню');
    toggle.setAttribute('aria-expanded','false');
    toggle.textContent='☰';
    document.body.appendChild(toggle);

    const dock=document.createElement('div');
    dock.className='ui-action-dock';
    dock.innerHTML='<div class="ui-action-state"><strong>Точка выбрана</strong><span>Можно сразу запускать расчёт</span></div><button type="button">Рассчитать</button>';
    document.body.appendChild(dock);
    const dockButton=dock.querySelector('button');

    let selecting=false;
    let lastSelectedMode=null;
    const actionMap={direct:'direct',back:'back',fav:'fav'};
    const actionLabels={direct:'Рассчитать траекторию',back:'Найти возможный запуск',fav:'Найти окна запуска'};

    const setOpen=open=>{
      side.classList.toggle('ui-collapsed',!open);
      backdrop.classList.toggle('ui-hidden',!open);
      toggle.textContent=open?'×':'☰';
      toggle.setAttribute('aria-expanded',String(open));
      toggle.setAttribute('aria-label',open?'Скрыть меню':'Открыть меню');
    };
    const activeMode=()=>document.querySelector('.tab.active')?.dataset.panel||'direct';
    const showDock=(mode=activeMode())=>{
      lastSelectedMode=mode;
      dockButton.textContent=actionLabels[mode]||'Рассчитать';
      dock.classList.add('open');
    };
    const hideDock=()=>dock.classList.remove('open');

    setOpen(true);
    toggle.addEventListener('click',()=>setOpen(side.classList.contains('ui-collapsed')));
    backdrop.addEventListener('click',()=>setOpen(false));

    document.querySelectorAll('.secondary').forEach(btn=>btn.addEventListener('click',()=>{
      selecting=true;
      lastSelectedMode=activeMode();
      hideDock();
      setOpen(false);
    }));

    const attachMapSelectionUi=()=>{
      try{
        if(typeof map==='undefined'||!map||typeof map.on!=='function')return false;
        map.on('click',()=>{
          if(!selecting)return;
          selecting=false;
          showDock(lastSelectedMode||activeMode());
        });
        return true;
      }catch(e){return false}
    };
    if(!attachMapSelectionUi()){
      let tries=0;const timer=setInterval(()=>{if(attachMapSelectionUi()||++tries>30)clearInterval(timer)},100);
    }

    dockButton.addEventListener('click',()=>{
      const mode=lastSelectedMode||activeMode();
      const fn=actionMap[mode];
      hideDock();
      if(typeof window[fn]==='function'){
        window[fn]();
      }
    });

    window.addEventListener('resize',()=>{
      if(innerWidth>850){setOpen(true);hideDock();selecting=false;}
    });

    const help=document.createElement('button');
    help.className='ui-help';help.type='button';help.textContent='?';help.setAttribute('aria-label','Подсказка');
    const card=document.createElement('div');
    card.className='ui-help-card';
    card.innerHTML='<strong>Как пользоваться</strong><span>Выберите вкладку → нажмите «Выбрать на карте» → коснитесь нужной точки. После выбора внизу появится кнопка расчёта — меню открывать заново не нужно.</span>';
    document.body.append(help,card);
    help.addEventListener('click',()=>card.classList.toggle('open'));
    document.addEventListener('click',e=>{if(card.classList.contains('open')&&!card.contains(e.target)&&e.target!==help)card.classList.remove('open')});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
