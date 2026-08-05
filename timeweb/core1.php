<?php
declare(strict_types=1);
const EARTH = 6371000.0;
const OPEN_METEO = 'https://api.open-meteo.com/v1/forecast';
const LEVELS = [1000,975,950,925,900,850,800,700,600,550,500,450,400,350,300];
function json_out(mixed $data,int $status=200):never{http_response_code($status);header('Content-Type: application/json; charset=utf-8');echo json_encode($data,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);exit;}
function fail(string $msg,int $status=422):never{json_out(['status'=>'error','detail'=>$msg],$status);}
function req():array{$raw=file_get_contents('php://input');$d=json_decode($raw?:'[]',true);return is_array($d)?$d:[];}
function utc(string $s):DateTimeImmutable{try{$d=new DateTimeImmutable($s);}catch(Throwable){throw new RuntimeException('Некорректная дата: '.$s);}return $d->setTimezone(new DateTimeZone('UTC'));}
function iso(DateTimeImmutable $d):string{return $d->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\\TH:i:s\\Z');}
function clamp(float $v,float $a,float $b):float{return max($a,min($b,$v));}
function hav(float $lat1,float $lon1,float $lat2,float $lon2):float{$p1=deg2rad($lat1);$p2=deg2rad($lat2);$dp=deg2rad($lat2-$lat1);$dl=deg2rad($lon2-$lon1);$a=sin($dp/2)**2+cos($p1)*cos($p2)*sin($dl/2)**2;return 2*EARTH*asin(sqrt(clamp($a,0,1)));}
function point(float $lat,float $lon):array{return ['lat'=>$lat,'lon'=>$lon];}
function destination(float $lat,float $lon,float $east,float $north):array{$d=hypot($east,$north);if($d<1e-9)return[$lat,$lon];$br=atan2($east,$north);$ad=$d/EARTH;$p=deg2rad($lat);$l=deg2rad($lon);$p2=asin(sin($p)*cos($ad)+cos($p)*sin($ad)*cos($br));$l2=$l+atan2(sin($br)*sin($ad)*cos($p),cos($ad)-sin($p)*sin($p2));return[rad2deg($p2),fmod(rad2deg($l2)+540,360)-180];}
function winduv(float $speed,float $from):array{$a=deg2rad(fmod($from+180,360));return[sin($a)*$speed,cos($a)*$speed];}
function uvwind(float $e,float $n):array{$s=hypot($e,$n);if($s<1e-9)return[0.0,0.0];$tow=fmod(rad2deg(atan2($e,$n))+360,360);return[$s,fmod($tow+180,360)];}
function forecastRadius(float $hours):float{return min(8000.0,max(600.0,600.0+$hours*44.0));}
function grid(float $lat,float $lon,float $radiusKm):array{$ld=$radiusKm/111.0;$od=$radiusKm/max(20.0,111*cos(deg2rad($lat)));$ls=[];$os=[];foreach([-1,-.5,0,.5,1] as $x){$ls[]=$lat+$ld*$x;$os[]=$lon+$od*$x;}return[$ls,$os];}
function parsePoint(array $a,string $name):array{if(!isset($a['lat'],$a['lon']))throw new RuntimeException("Не указана точка $name");$lat=(float)$a['lat'];$lon=(float)$a['lon'];if($lat<-90||$lat>90||$lon<-180||$lon>180)throw new RuntimeException("Некорректные координаты: $name");return[$lat,$lon];}
function gaussian():float{$u=max(1e-12,mt_rand()/mt_getrandmax());$v=max(1e-12,mt_rand()/mt_getrandmax());return sqrt(-2*log($u))*cos(2*M_PI*$v);}
if(!isset($_GET['api']))register_shutdown_function(static function():void{
  echo '<script src="engine.js?v=20260805"></script><script src="engine-compat.js?v=20260805"></script><script src="engine-zones.js?v=20260805"></script>';
});
