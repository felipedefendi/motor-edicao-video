"""Monta VSL longa em segmentos H.264 sem perdas e copia o audio original uma vez.
Cada intervalo usa limites inteiros [inicio,fim). Cache por receita permite retomar.
Uso: py -3.12 motor/montar_longo.py jobs/<job> [--saida VSL_cognihoney.mp4]
"""
from pathlib import Path
import concurrent.futures,hashlib,json,subprocess,sys,os

def probe(p):
 return json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate,nb_frames,start_time','-of','json',str(p)]))['streams'][0]

def main():
 job=Path(sys.argv[1]).resolve();name=sys.argv[sys.argv.index('--saida')+1] if '--saida' in sys.argv else 'VSL_cognihoney.mp4';src=job/'entrada/original.mp4';v=probe(src)
 assert v['r_frame_rate']=='30/1' and (v['width'],v['height'])==(1080,1920),'Este motor exige o contrato 1080x1920/30fps'
 total=int(v['nb_frames']);fps=30;wins=json.loads((job/'docs/janelas.json').read_text(encoding='utf-8-sig'));wins.sort(key=lambda x:x.get('inicio_quadro',round(x['inicio']*fps)))
 segs=[];cursor=0
 for w in wins:
  a=w.get('inicio_quadro',round(w['inicio']*fps));b=w.get('fim_quadro_exclusivo',round(w['fim']*fps))
  assert cursor<=a<b<=total, f'Janela invalida/sobreposta: {w}'
  assert w.get('clipe'),f'Janela sem clipe: {w}'
  if cursor<a:segs.append({'tipo':'original','inicio':cursor,'n':a-cursor,'fonte':str(src),'offset':cursor})
  clip=(job/w['clipe']).resolve();cv=probe(clip);off=round(w.get('inicio_clipe',0)*fps)
  assert cv['r_frame_rate']=='30/1' and (cv['width'],cv['height'])==(1080,1920),f'Contrato do clipe: {clip}'
  assert int(cv['nb_frames'])>=off+b-a,f'Clipe curto: {clip}'
  segs.append({'tipo':'troca','janela':w['trecho'],'inicio':a,'n':b-a,'fonte':str(clip),'offset':off});cursor=b
 if cursor<total:segs.append({'tipo':'original','inicio':cursor,'n':total-cursor,'fonte':str(src),'offset':cursor})
 assert sum(s['n'] for s in segs)==total
 work=job/'work/segmentos_sem_perdas';work.mkdir(parents=True,exist_ok=True);ent=job/'entrega';ent.mkdir(exist_ok=True);hist=ent/'_historico';hist.mkdir(exist_ok=True)
 for i,s in enumerate(segs):s['id']=i;s['arquivo']=str(work/f's{i:04d}.mp4')
 (job/'docs/segmentos_montagem.json').write_text(json.dumps(segs,indent=2),encoding='utf-8')
 def encode(s):
  inp=Path(s['fonte']);dst=Path(s['arquivo']);meta=dst.with_suffix('.json');stat=inp.stat();recipe={**s,'size_fonte':stat.st_size,'mtime_fonte':stat.st_mtime_ns,'codec':'x264_qp0_fast_bf0_v1'}
  key=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
  if dst.exists() and meta.exists():
   old=json.loads(meta.read_text())
   if old.get('receita_sha256')==key and int(probe(dst).get('nb_frames',-1))==s['n']:return f"cache {s['id']:04d}: {s['n']} quadros"
  seek=s['offset']//fps;rem=s['offset']%fps;tmp=dst.with_suffix('.partial.mp4');vf=f'trim=start_frame={rem}:end_frame={rem+s["n"]},setpts=PTS-STARTPTS,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709,format=yuv420p'
  args=['ffmpeg','-v','error','-y','-threads','2','-ss',str(seek),'-i',str(inp),'-vf',vf,'-frames:v',str(s['n']),'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','0','-bf','0','-r','30','-video_track_timescale','15360',str(tmp)]
  r=subprocess.run(args,capture_output=True,text=True)
  if r.returncode:raise RuntimeError(f"Segmento {s['id']}: {r.stderr[-3000:]}")
  assert int(probe(tmp)['nb_frames'])==s['n'],f"Contagem do segmento {s['id']}"
  tmp.replace(dst);meta.write_text(json.dumps({'receita_sha256':key,'receita':recipe},indent=2));return f"pronto {s['id']:04d}: {s['tipo']} {s['n']} quadros"
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
  for r in ex.map(encode,segs):print(r,flush=True)
 lista=work/'concat.txt';lista.write_text(''.join("file '"+Path(s['arquivo']).name+"'\n" for s in segs),encoding='utf-8')
 dst=ent/name
 if dst.exists():
  i=1
  while (hist/f'{i:02d}_{name}').exists():i+=1
  dst.replace(hist/f'{i:02d}_{name}')
 tmp=ent/(dst.stem+'.partial.mp4')
 subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(lista),'-i',str(src),'-map','0:v:0','-map','1:a:0','-c','copy','-map_metadata','1','-movflags','+faststart',str(tmp)],check=True)
 assert int(probe(tmp)['nb_frames'])==total,'Contagem final divergente'
 tmp.replace(dst);print(f'MASTER CONCLUIDO: {dst}; {total} quadros. Executar auditoria estrita e visual.',flush=True)

if __name__=='__main__':main()
