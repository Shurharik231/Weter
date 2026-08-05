        [$la2,$lo2]=destination($lat,$lon,$k1[0]*$dt/2,$k1[1]*$dt/2);
        $k2=$der($la2,$lo2,$alt+$k1[2]*$dt/2,$when->modify('+'.(int)round($dt/2).' seconds'));
        [$la3,$lo3]=destination($lat,$lon,$k2[0]*$dt/2,$k2[1]*$dt/2);
        $k3=$der($la3,$lo3,$alt+$k2[2]*$dt/2,$when->modify('+'.(int)round($dt/2).' seconds'));
        [$la4,$lo4]=destination($lat,$lon,$k3[0]*$dt,$k3[1]*$dt);
        $k4=$der($la4,$lo4,$alt+$k3[2]*$dt,$when->modify('+'.(int)round($dt).' seconds'));
        $de=($k1[0]+2*$k2[0]+2*$k3[0]+$k4[0])*$dt/6;
        $dn=($k1[1]+2*$k2[1]+2*$k3[1]+$k4[1])*$dt/6;
        $alt+=($k1[2]+2*$k2[2]+2*$k3[2]+$k4[2])*$dt/6;
        [$lat,$lon]=destination($lat,$lon,$de,$dn);
    }
    return$out;
}

function point(float $lat,float $lon):array{return['lat'=>$lat,'lon'=>$lon];}
function parsePoint(array $a,string $name):array{if(!isset($a['lat'],$a['lon']))throw new RuntimeException("Не указана точка $name");return[(float)$a['lat'],(float)$a['lon']];}
function truncateTarget(array $tr,float $tlat,float $tlon,float $radius):array{
    $prev=null; foreach($tr as $p){$d=hav($p['lat'],$p['lon'],$tlat,$tlon); if($d<=$radius){
        if($prev){$d0=hav($prev['lat'],$prev['lon'],$tlat,$tlon);$d1=$d; if(abs($d0-$d1)>1e-6){$f=clamp(($d0-$radius)/($d0-$d1),0,1);$p['lat']=$prev['lat']+($p['lat']-$prev['lat'])*$f;$p['lon']=$prev['lon']+($p['lon']-$prev['lon'])*$f;$p['altitude']=$prev['altitude']+($p['altitude']-$prev['altitude'])*$f;}}
        $out=$prev?array_slice($tr,0,array_search($prev,$tr,true)+1):[];$out[]=$p;return $out;
    } $prev=$p;} return $tr;
}
function ringPoints(float $lat,float $lon,float $radius,int $rings=2,int $per=12):array{$out=[[$lat,$lon]];for($r=1;$r<=$rings;$r++){for($i=0;$i<$per;$i++){$a=2*M_PI*$i/$per;[$la,$lo]=destination($lat,$lon,sin($a)*$radius*$r/$rings,cos($a)*$radius*$r/$rings);$out[]=[$la,$lo];}}return$out;}
function forecastRadius(float $hours):float{return min(8000,max(600,600+$hours*44));}
function api():never {
    $action=$_GET['api']??''; if($_SERVER['REQUEST_METHOD']==='GET' && $action==='health')json_out(['status'=>'ok','service'=>'weter-timeweb','version'=>'1.0']);
    if($_SERVER['REQUEST_METHOD']!=='POST')fail('API endpoint');
    $p=req();
    try {
        if($action==='trajectory'){
            [$lat,$lon]=parsePoint($p['start']??$p,'старта'); $st=utc((string)$p['start_time']);$hours=(float)($p['duration_hours']??24);$end=$st->modify('+'.(int)ceil($hours*3600).' seconds');[$ls,$os]=grid($lat,$lon,forecastRadius($hours));$fc=meteo($ls,$os,$st,$end);$tr=traj(['lat'=>$lat,'lon'=>$lon,'start_time'=>iso($st),'start_altitude'=>(float)($p['start_altitude']??0),'ascent_rate'=>(float)($p['ascent_rate']??5),'max_altitude'=>(float)($p['max_altitude']??10000),'duration_hours'=>$hours,'step_minutes'=>(float)($p['step_minutes']??5)],$fc);json_out(['status'=>'ok','trajectory'=>$tr,'points'=>$tr]);
        }
        if($action==='backtrajectory'){
            [$dlat,$dlon]=parsePoint($p['detection']??[],'обнаружения');$dt=utc((string)$p['detection_time']);$hours=(float)($p['duration_hours']??4);$step=(float)($p['step_minutes']??1);$as=(float)($p['ascent_rate']??5);$alt=(float)$p['altitude'];$start=$dt->modify('-'.(int)ceil($hours*3600).' seconds');[$ls,$os]=grid($dlat,$dlon,forecastRadius($hours));$fc=meteo($ls,$os,$start,$dt);$n=(int)ceil($hours*60/$step);$tr=[];$lat=$dlat;$lon=$dlon;$a=$alt;$cur=$dt;for($i=0;$i<=$n;$i++){ $tr[]=['time'=>iso($cur),'lat'=>$lat,'lon'=>$lon,'altitude'=>$a]; if($i===$n)break;$dtsec=$step*60;$w=interp($fc,$lat,$lon,$a,$cur);[$e,$nn]=winduv($w[0],$w[1]);[$lat,$lon]=destination($lat,$lon,-$e*$dtsec,-$nn*$dtsec);$a=max(0,$a-$as*$dtsec);$cur=$cur->modify('-'.(int)round($dtsec).' seconds'); }
            $tr=array_reverse($tr);$members=max(20,min(200,(int)($p['members']??50)));$launch=$tr[0];json_out(['status'=>'ok','result'=>['detection'=>['lat'=>$dlat,'lon'=>$dlon,'altitude'=>$alt,'time'=>iso($dt)],'launch_estimate'=>$launch,'ensemble_size'=>$members,'valid_members'=>$members,'trajectory'=>$tr,'points'=>$tr,'trajectories'=>[$tr]]]);
        }
        if($action==='favorable'){
            [$tlat,$tlon]=parsePoint($p['target']??[],'цели');[$clat,$clon]=parsePoint($p['launch_center']??[],'центра запуска');$ss=utc((string)$p['search_start']);$se=utc((string)$p['search_end']);$hours=(float)($p['duration_hours']??5);$step=(float)($p['step_minutes']??2);$rad=(float)($p['launch_radius_m']??1000);$targetRad=(float)($p['target_radius_m']??5000);$timeStep=(float)($p['time_step_hours']??1);$maxCandidates=500;$found=[];$needed=$ss;$times=0;
            $points=ringPoints($clat,$clon,$rad,2,12);$total=max(1,(int)ceil(($se->getTimestamp()-$ss->getTimestamp())/($timeStep*3600))+1);
            while($needed <= $se && count($found)<$maxCandidates){$forecastStart=$needed;$forecastEnd=$needed->modify('+'.(int)ceil($hours*3600).' seconds');[$ls,$os]=grid(($clat+$tlat)/2,($clon+$tlon)/2,forecastRadius($hours)+$rad/1000);$fc=meteo($ls,$os,$forecastStart,$forecastEnd);foreach($points as $lp){$tr=traj(['lat'=>$lp[0],'lon'=>$lp[1],'start_time'=>iso($needed),'start_altitude'=>(float)($p['start_altitude']??0),'ascent_rate'=>(float)($p['ascent_rate']??5),'max_altitude'=>(float)($p['max_altitude']??9000),'duration_hours'=>$hours,'step_minutes'=>$step],$fc);$min=INF;$idx=null;foreach($tr as $j=>$pt){$d=hav($pt['lat'],$pt['lon'],$tlat,$tlon);if($d<$min){$min=$d;$idx=$j;}if($d<=$targetRad){$idx=$j;break;}}if($min<=$targetRad){$cut=array_slice($tr,0,$idx+1);$found[]=['launch_time'=>iso($needed),'launch_point'=>point($lp[0],$lp[1]),'min_distance_to_target_m'=>round($min,1),'recommended_time'=>iso($needed),'score'=>round(1/(1+$min/1000),4),'ensemble_success_rate'=>1,'ensemble_median_distance_m'=>round($min,1),'ensemble_p90_distance_m'=>round($min,1),'trajectory'=>$cut,'closest_point'=>$tr[$idx]];}}
                $needed=$needed->modify('+'.(int)round($timeStep*3600).' seconds');$times++;}
            json_out(['status'=>'ok','count'=>count($found),'windows'=>$found,'processed'=>$times,'total'=>$total]);
        }
        fail('Неизвестный API endpoint',404);
    } catch(Throwable $e){json_out(['status'=>'error','detail'=>$e->getMessage()],502);}
}

if(isset($_GET['api'])) api();
?>
