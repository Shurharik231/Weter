/* Runtime bridge: keeps heavy trajectory/favorable calculations in the browser. */
(()=>{
'use strict';
function rtStatus(s,e=false){if(typeof window.status==='function')window.status(s,e);}
function rtProgress(v,show=true){if(typeof window.progress==='function')window.progress(v,show);}
function rtClear(){if(typeof window.clearLines==='function')window.clearLines();}
window.weterBrowserRuntime={
 async direct(){rtClear();rtStatus('Расчёт в браузере…');rtProgress(3);if(typeof window.runTrajectoryExact==='function')return window.runTrajectoryExact();if(typeof window.trajectoryExact==='function')return window.trajectoryExact();throw Error('Вычислительное ядро прямой траектории не загружено');},
 async back(){rtClear();rtStatus('Расчёт ансамбля в браузере…');rtProgress(3);if(typeof window.runBackExact==='function')return window.runBackExact();if(typeof window.backTrajectoryExact==='function')return window.backTrajectoryExact();throw Error('Вычислительное ядро обратной траектории не загружено');},
 async favorable(){rtClear();rtStatus('Расчёт окна запуска в браузере…');rtProgress(3);if(typeof window.favorableExact==='function')return window.favorableExact();throw Error('Вычислительное ядро планировщика не загружено');}
};
})();
