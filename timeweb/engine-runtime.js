/* Runtime bridge: browser-first execution for all heavy modes. */
(()=>{
'use strict';
function rtStatus(s,e=false){if(typeof window.status==='function')window.status(s,e);}
function rtProgress(v,show=true){if(typeof window.progress==='function')window.progress(v,show);}
function rtClear(){if(typeof window.clearLines==='function')window.clearLines();}
const runtime={
 async direct(){rtClear();rtStatus('Прямая траектория: расчёт в браузере…');rtProgress(3);if(typeof window.runTrajectoryExact==='function')return window.runTrajectoryExact();if(typeof window.trajectoryExact==='function')return window.trajectoryExact();throw Error('Вычислительное ядро прямой траектории не загружено');},
 async back(){rtClear();rtStatus('Обратная траектория: расчёт ансамбля в браузере…');rtProgress(3);if(typeof window.runBackExact==='function')return window.runBackExact();if(typeof window.backTrajectoryExact==='function')return window.backTrajectoryExact();throw Error('Вычислительное ядро обратной траектории не загружено');},
 async favorable(){rtClear();rtStatus('Окно запуска: расчёт в браузере…');rtProgress(3);if(typeof window.favorableExact==='function')return window.favorableExact();throw Error('Вычислительное ядро планировщика не загружено');}
};
window.weterBrowserRuntime=runtime;
/* Loaded by core1 shutdown after the page inline script, so replace its handlers. */
window.direct=()=>runtime.direct();
window.back=()=>runtime.back();
window.fav=()=>runtime.favorable();
})();
