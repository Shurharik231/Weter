<?php
// Weter — standalone PHP 8.2 web version for ordinary Timeweb hosting.
// No Composer, Python or server daemon required.
declare(strict_types=1);

const EARTH = 6371000.0;
const OPEN_METEO = 'https://api.open-meteo.com/v1/forecast';
const LEVELS = [1000,975,950,925,900,850,800,700,600,550,500,450,400,350,300];

function json_out($data, int $status=200): never {
    http_response_code($status); header('Content-Type: application/json; charset=utf-8'); echo json_encode($data, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES); exit;
}
function fail(string $msg, int $status=422): never { json_out(['status'=>'error','detail'=>$msg], $status); }
function req(): array { $raw=file_get_contents('php://input'); $d=json_decode($raw ?: '[]', true); return is_array($d)?$d:[]; }
function utc(string $s): DateTimeImmutable { try { $d=new DateTimeImmutable($s); } catch(Throwable $e) { throw new RuntimeException('Некорректная дата: '.$s); } return $d->setTimezone(new DateTimeZone('UTC')); }
function iso(DateTimeImmutable $d): string { return $d->format('Y-m-d\TH:i:s\Z'); }
function clamp(float $v,float $a,float $b):float{return max($a,min($b,$v));}
function hav(float $lat1,float $lon1,float $lat2,float $lon2):float { $p1=deg2rad($lat1);$p2=deg2rad($lat2);$dp=deg2rad($lat2-$lat1);$dl=deg2rad($lon2-$lon1);$a=sin($dp/2)**2+cos($p1)*cos($p2)*sin($dl/2)**2;return 2*EARTH*asin(sqrt(clamp($a,0,1))); }
