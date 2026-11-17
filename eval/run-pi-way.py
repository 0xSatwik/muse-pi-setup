import json,subprocess,time
from pathlib import Path
R=Path(__file__).parent; ROOT=R.parent
import sys
models=[sys.argv[1]]
prompts=[json.loads(x) for x in open(R/'promptfoo-prompts.jsonl')]
arc=[json.loads(x) for x in open(R/'arc-questions.jsonl')]
base=['pi','--no-session','--no-tools','--no-mcp','--no-extensions','--no-skills','--no-prompt-templates','--no-context-files','--mode','text']
def call(model,ident,prompt):
 raw=R/'raw-newkey'/model.replace('/','__');raw.mkdir(parents=True,exist_ok=True)
 out=raw/(ident+'.txt'); meta=raw/(ident+'.meta.json')
 if out.exists() and meta.exists():
  saved=json.loads(meta.read_text())
  return {'id':ident,'answer':out.read_text(),'exit_code':saved['exit_code'],'duration_s':saved['duration_s']}
 started=time.time()
 try:
  p=subprocess.run(base+['--model',model,'-p','--',prompt],cwd='/root/work',capture_output=True,text=True,timeout=150)
  answer=p.stdout.strip(); err=p.stderr.strip(); rc=p.returncode
 except subprocess.TimeoutExpired as e:
  answer=(e.stdout or b'').decode(errors='replace') if isinstance(e.stdout,bytes) else (e.stdout or '')
  err='timeout';rc=124
 out.write_text(answer)
 meta.write_text(json.dumps({'model':model,'id':ident,'exit_code':rc,'duration_s':round(time.time()-started,2),'stderr':err[:3000]},indent=2))
 return {'id':ident,'answer':answer,'exit_code':rc,'duration_s':round(time.time()-started,2)}
summary={}
for model in models:
 print('starting',model,flush=True); entries=[]
 for i,x in enumerate(prompts):
  entries.append(call(model,f'promptfoo-{i:02d}',x['prompt']))
  print(model,'promptfoo',i+1,'/',len(prompts),'rc',entries[-1]['exit_code'],flush=True)
 for x in arc:
  p="Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: [LETTER]' (without quotes) where [LETTER] is one of A,B,C,D.\n\n"+x['question']
  entries.append(call(model,f"arc-{x['index']:02d}",p))
  if (int(x['index'])+1)%5==0:print(model,'ARC',int(x['index'])+1,'/',len(arc),'rc',entries[-1]['exit_code'],flush=True)
 summary[model]=entries
 (R/(model.replace('/','__')+'-raw-newkey.json')).write_text(json.dumps(entries,indent=2))
print('all calls complete',flush=True)
