param([string]$ListFile, [string]$OutDir)
# Baixa cada URL e gera folha de contato: 1 linha por video, 6 frames espalhados, rotulo com indice/@/duracao
New-Item -ItemType Directory -Force $OutDir | Out-Null
$fix = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
$rows = @(); $i = 0
foreach ($url in Get-Content $ListFile) {
    if (-not $url.Trim()) { continue }
    $i++
    $id = ($url -split '/video/')[1]
    $user = ($url -split '/@')[1].Split('/')[0]
    $mp4 = Join-Path $OutDir "$id.mp4"
    if (-not (Test-Path $mp4)) { yt-dlp -q -S "res:720" -o $mp4 $url 2>$null }
    if (-not (Test-Path $mp4)) { "[$i] FALHOU @$user"; continue }
    $dur = [double](ffprobe -v error -show_entries format=duration -of csv=p=0 $mp4)
    $tiles = @()
    foreach ($p in 0.05, 0.22, 0.4, 0.58, 0.76, 0.93) {
        $t = [math]::Round($dur * $p, 1)
        $f = Join-Path $OutDir "$id-$p.jpg"
        ffmpeg -v error -y -ss $t -i $mp4 -frames:v 1 -vf "$fix,scale=-2:260,pad=148:260:(ow-iw)/2:0,drawtext=text='$t':fontcolor=yellow:fontsize=14:x=3:y=244:fontfile='C\:/Windows/Fonts/arial.ttf'" $f 2>$null
        if (Test-Path $f) { $tiles += $f }
    }
    if ($tiles.Count -eq 0) { continue }
    $row = Join-Path $OutDir "row-$i.jpg"
    $in = $tiles | ForEach-Object { '-i'; $_ }
    ffmpeg -v error -y @in -filter_complex "hstack=inputs=$($tiles.Count),pad=iw:ih+26:0:26:black,drawtext=text='$i  @$user  $([math]::Round($dur))s':fontcolor=yellow:fontsize=19:x=6:y=3:fontfile='C\:/Windows/Fonts/arial.ttf'" $row 2>$null
    if (Test-Path $row) { $rows += $row }
    "[$i] @$user $id $([math]::Round($dur))s"
}
$in = $rows | ForEach-Object { '-i'; $_ }
$out = Join-Path $OutDir "folha.jpg"
if ($rows.Count -gt 1) { ffmpeg -v error -y @in -filter_complex "vstack=inputs=$($rows.Count)" $out 2>$null } elseif ($rows.Count -eq 1) { Copy-Item $rows[0] $out }
