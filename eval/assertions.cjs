module.exports = (output, context) => {
 const s=output.trim(), t=context.vars.task, exp=JSON.parse(context.vars.expected), low=s.toLowerCase();
 let pass=false;
 if(t==='json'){try{const x=JSON.parse(s);pass=x.name==='maple'&&x.count===3&&Object.keys(x).length===2}catch{}}
 else if(t==='word-count') pass=s.split(/\s+/).length===6&&!/\b(wet|water)\b/i.test(s);
 else if(t==='algebra') pass=Number(s)===0.5;
 else if(t==='sql-left-join') pass=exp.every(e=>low.includes(e.toLowerCase()))&&/count\s*\(\s*(?:\w+\.)?(?:id|user_id)\s*\)/i.test(s);
 else if(t==='incident'||t==='decision'||t==='uncertainty') {const max={incident:35,decision:30,uncertainty:25}[t];pass=s.split(/\s+/).length<=max&&exp.every(e=>low.includes(e.toLowerCase()));}
 else if(t==='python-dedupe') pass=exp.every(e=>s.includes(e))&&(/set\(/.test(s)||/dict\.fromkeys/.test(s)||/not in/.test(s));
 else pass=exp.some(e=>s.toLowerCase()===e.toLowerCase());
 return {pass,score:pass?1:0,reason:pass?'Meets deterministic task checks':'Fails one or more content/format checks'};
};
