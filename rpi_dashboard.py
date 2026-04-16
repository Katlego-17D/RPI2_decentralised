#!/usr/bin/env python3
"""
rpi_dashboard.py — Live 5-tab dashboard for RPi traffic signal demo
3 modes in parallel · Real AVID demand · Equity forcing
Dashboard: http://<pi-ip>:5000
"""
import threading,time,math,argparse,json
from pathlib import Path
import numpy as np
from rpi_demo import (AVID_HOURLY,get_demand,PHASE_GREEN,PHASE_LABEL,PHASE_DRAIN,
    PHASE_UPSTREAM,GREEN_S,YELLOW_S,SERVICE_RATE,QUEUE_DECAY,EQUITY_MAX,
    SIM_BEGIN,SIM_END,SIM_SECONDS,
    QueueSim,DQNInference,HardwareIO,pick_fixed,pick_mp,pick_drl)
HERE=Path(__file__).parent
from flask import Flask,jsonify
app=Flask(__name__)

LOCK=threading.Lock()
STATE={m:{'records':[],'running':False,'done':False} for m in ['fixed','mp','hybrid_drl']}

def run_mode(mode,speed,hw=None):
    sim=QueueSim(); dqn=None
    if mode=='hybrid_drl':
        wp=HERE/'j1_dqn_weights.npz'
        if wp.exists():
            try: dqn=DQNInference(str(wp))
            except: pass
    with LOCK: STATE[mode]['running']=True; STATE[mode]['records']=[]
    sim_t=SIM_BEGIN;ci=0;pi=0;sw_n=0
    while sim_t<SIM_END:
        if mode=='fixed': ph=pick_fixed(ci)
        elif mode=='mp': ph=pick_mp(sim)
        else: ph=pick_drl(sim,dqn,pi,sim_t)
        ni=PHASE_GREEN.index(ph)
        if ni!=pi:
            sw_n+=1
            if hw and mode=='hybrid_drl':
                hw.apply_phase(PHASE_GREEN[pi]+1);time.sleep(YELLOW_S/speed)
                hw.all_red();time.sleep(1.0/speed)
        pi=ni
        if hw and mode=='hybrid_drl': hw.apply_phase(ph)
        q=sim.total_queue(); reward=-q/100.0
        h=sim_t//3600;m=(sim_t%3600)//60
        rec={'step':ci,'sim_t':sim_t,'hhmm':f'{h:02d}:{m:02d}','phase':ph,
             'q_A':round(sim.queues['A'],2),'q_B':round(sim.queues['B'],2),
             'q_C':round(sim.queues['C'],2),'q_D':round(sim.queues['D'],2),
             'reward':round(reward,4),'sw':1 if ni!=pi or ci==0 else 0}
        with LOCK: STATE[mode]['records'].append(rec)
        sim.step(ph,sim_t)
        time.sleep(GREEN_S/speed);sim_t+=GREEN_S;ci+=1
    with LOCK: STATE[mode]['running']=False;STATE[mode]['done']=True
    print(f"[{mode}] Done — {ci} steps")

@app.route('/')
def index(): return HTML
@app.route('/api/data')
def api_data():
    with LOCK:
        demand={str(h):{'E':round(e,1),'N':round(n,1),'S':round(s,1)}
                for h,(e,n,s) in AVID_HOURLY.items()}
        return jsonify({m:{'records':STATE[m]['records'][-3000:],
            'running':STATE[m]['running'],'done':STATE[m]['done']}
            for m in ['fixed','mp','hybrid_drl']}|{'demand':demand})

HTML=r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>J1 RPi Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#F0EEE8;color:#1a1a1a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,sans-serif;font-size:14px}
.pg{max-width:1100px;margin:0 auto;padding:28px 24px 60px}
.hdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:5px}
h1{font-size:20px;font-weight:600;letter-spacing:-.3px}
.badge{font-size:11px;background:#6B9E7A;color:#fff;padding:3px 10px;border-radius:12px}
.sub{font-size:13px;color:#888;margin-bottom:22px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px}
.card{background:#E8E5DE;border-radius:10px;padding:16px 18px}
.card-lbl{font-size:11px;color:#777;margin-bottom:8px;text-transform:uppercase;letter-spacing:.04em}
.card-val{font-size:30px;font-weight:700;letter-spacing:-.5px;line-height:1}
.card-val sub{font-size:15px;font-weight:400}
.card-sub{font-size:11px;color:#999;margin-top:6px}
.tabs{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:22px}
.tab{padding:7px 16px;border:1.5px solid #C8C5BC;border-radius:20px;background:transparent;font-size:12px;font-weight:500;color:#555;cursor:pointer;transition:all .12s;font-family:inherit}
.tab:hover{border-color:#888;color:#1a1a1a}
.tab.active{background:#E2DDD6;border-color:#AEA9A0;color:#1a1a1a;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.panel{background:#fff;border-radius:12px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.panel-hidden{display:none!important}
.cleg{display:flex;align-items:center;gap:18px;margin-bottom:16px;flex-wrap:wrap}
.cl{display:flex;align-items:center;gap:6px;font-size:12px;color:#444}
.sq{width:12px;height:12px;border-radius:3px;flex-shrink:0}
.clr{margin-left:auto;font-size:11px;color:#aaa;display:flex;align-items:center;gap:6px}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#6B9E7A;animation:blink 1.2s ease-in-out infinite}
.dot-w{background:#C8C5BC!important;animation:none!important}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.1}}
.fn{margin-top:12px;font-size:11px;color:#999}
.ptable{width:100%;border-collapse:collapse;font-size:12px;margin-top:18px}
.ptable th{text-align:left;padding:8px 12px;font-size:10px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.05em;border-bottom:1.5px solid #F0EEE8}
.ptable td{padding:9px 12px;border-bottom:1px solid #F5F3EE;color:#333}
.ptable td:first-child{font-weight:500}.cr{color:#B85A4A}.cb{color:#5A8AB0}.cg{color:#4D8A5E}
.topo-wrap{display:flex;flex-direction:column;align-items:center;gap:22px}
.topo-svg{width:100%;max-width:480px}
.topo-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;width:100%}
.ibox{background:#F8F6F0;border-radius:8px;padding:14px 16px}
.ibox h3{font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.ibox code{font-family:"SF Mono",Menlo,monospace;font-size:11px;color:#666;display:block;line-height:1.7}
.dbox{background:#F8F6F0;border-radius:8px;padding:14px 16px}
.dbox h3{font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.dbox p{font-size:12px;color:#444;line-height:1.8}
.demand-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}
@media(max-width:700px){.cards,.topo-grid,.demand-grid{grid-template-columns:1fr}}
</style></head><body>
<div class="pg">
<div class="hdr"><h1>J1 A1 Western Bypass / Airport Road, Gaborone</h1><span class="badge">RPi Live</span></div>
<div class="sub">Raspberry Pi 2 · AM Peak 06:00–09:00 · Max Pressure + DQN · AVID Oct 2025 · N=17,856 records</div>
<div class="cards">
<div class="card"><div class="card-lbl">Max Pressure avg queue</div><div class="card-val" id="k1">– <sub>veh</sub></div><div class="card-sub" id="k1s">waiting...</div></div>
<div class="card"><div class="card-lbl">MP + DRL avg queue</div><div class="card-val" id="k2">– <sub>veh</sub></div><div class="card-sub" id="k2s">waiting...</div></div>
<div class="card"><div class="card-lbl">Simulation steps</div><div class="card-val" id="k3">–</div><div class="card-sub" id="k3s">waiting...</div></div>
</div>
<div class="tabs">
<button class="tab active" onclick="showTab('queue',this)">Queue comparison</button>
<button class="tab" onclick="showTab('perf',this)">Controller performance</button>
<button class="tab" onclick="showTab('training',this)">Training curve</button>
<button class="tab" onclick="showTab('topo',this)">Junction topology</button>
<button class="tab" onclick="showTab('demand',this)">Demand profile</button>
</div>
<div class="panel" id="tab-queue">
<div class="cleg">
<div class="cl"><div class="sq" style="background:#C1695A"></div>Fixed timing</div>
<div class="cl"><div class="sq" style="background:#7BA7CC"></div>Max Pressure</div>
<div class="cl"><div class="sq" style="background:#6B9E7A"></div>MP + DRL</div>
<div class="clr"><div class="dot dot-w" id="ldot"></div><span id="ltxt">Waiting...</span></div>
</div>
<canvas id="cQ" style="max-height:300px"></canvas>
<div class="fn" id="qfn">AM peak 06:00–09:00 · 30s steps · total vehicles queued at J1</div>
</div>
<div class="panel panel-hidden" id="tab-perf">
<canvas id="cP" style="max-height:200px"></canvas>
<table class="ptable"><thead><tr><th>Controller</th><th>Mean queue</th><th>Std dev</th><th>Max queue</th><th>Switches/hr</th></tr></thead><tbody id="ptb"></tbody></table>
<div class="fn">Live evaluation · AM peak 06:00–09:00 · equity forcing (max wait 90s) · service rate 2200 veh/hr</div>
</div>
<div class="panel panel-hidden" id="tab-training">
<div class="cleg">
<div class="cl"><div class="sq" style="background:#3D7A52"></div>Reward signal</div>
<div class="cl"><div class="sq" style="background:#A8D4B8"></div>Rolling average</div>
</div>
<canvas id="cT" style="max-height:280px"></canvas>
<div class="fn">DQN inference reward (-queue/100) · higher = better · rolling window = 20</div>
</div>
<div class="panel panel-hidden" id="tab-topo">
<div class="topo-wrap">
<svg class="topo-svg" viewBox="0 0 500 460" style="font-family:inherit">
<rect x="220" y="16" width="60" height="168" rx="6" fill="#DDDAD2"/>
<line x1="238" y1="16" x2="238" y2="184" stroke="#C8C5BC"/><line x1="262" y1="16" x2="262" y2="184" stroke="#C8C5BC"/>
<rect x="220" y="264" width="60" height="168" rx="6" fill="#DDDAD2"/>
<line x1="238" y1="264" x2="238" y2="432" stroke="#C8C5BC"/><line x1="262" y1="264" x2="262" y2="432" stroke="#C8C5BC"/>
<rect x="280" y="184" width="200" height="60" rx="6" fill="#DDDAD2"/>
<line x1="280" y1="202" x2="480" y2="202" stroke="#C8C5BC"/><line x1="280" y1="226" x2="480" y2="226" stroke="#C8C5BC"/>
<rect x="20" y="184" width="200" height="60" rx="6" fill="#DDDAD2"/>
<line x1="20" y1="202" x2="220" y2="202" stroke="#C8C5BC"/><line x1="20" y1="226" x2="220" y2="226" stroke="#C8C5BC"/>
<rect x="210" y="176" width="80" height="80" rx="7" fill="#fff" stroke="#C8C5BC" stroke-width="1.5"/>
<text x="250" y="220" text-anchor="middle" font-size="11" font-weight="600" fill="#555">J1</text>
<text x="250" y="44" text-anchor="middle" font-size="14" font-weight="700" fill="#5A8AB0">D (AVID N)</text>
<text x="250" y="410" text-anchor="middle" font-size="14" font-weight="700" fill="#6B9E7A">C (AVID S)</text>
<text x="90" y="214" text-anchor="middle" font-size="14" font-weight="700" fill="#C1695A">A (est.)</text>
<text x="410" y="214" text-anchor="middle" font-size="14" font-weight="700" fill="#8B7EC8">B (AVID E)</text>
<text x="250" y="68" text-anchor="middle" font-size="10" fill="#888">Airport Rd North</text>
<text x="250" y="390" text-anchor="middle" font-size="10" fill="#888">Airport Rd South</text>
<text x="90" y="236" text-anchor="middle" font-size="10" fill="#888">A1 Bypass West</text>
<text x="410" y="236" text-anchor="middle" font-size="10" fill="#888">A1 Bypass East</text>
</svg>
<div class="topo-grid">
<div class="ibox"><h3>Camera → Arm mapping</h3><code>AVID E → Arm B (East approach)<br>AVID N → Arm D (North approach)<br>AVID S → Arm C (South approach)<br>Arm A = estimated (0.7 × AVID E)</code></div>
<div class="ibox"><h3>TLS phases (equity forced)</h3><code>Ph0: D green (links 3,4)<br>Ph2: A+B green (links 1,2,7,8)<br>Ph4: B+C green (links 0,11)<br>Ph6: C+D green (links 5,6,9,10)<br>Max wait before force: 90s</code></div>
</div></div></div>
<div class="panel panel-hidden" id="tab-demand">
<div class="cleg">
<div class="cl"><div class="sq" style="background:#C1695A"></div>East (AVID E)</div>
<div class="cl"><div class="sq" style="background:#7BA7CC"></div>North (AVID N)</div>
<div class="cl"><div class="sq" style="background:#6B9E7A"></div>South (AVID S)</div>
</div>
<canvas id="cD" style="max-height:280px"></canvas>
<div class="fn">Mean vehicles per hour · AVID camera data Oct 2025 (31 days) · Node 1 = A1/Airport Road · N=17,856 records</div>
<div class="demand-grid">
<div class="dbox"><h3>Oct 2025 totals</h3><p>East (AVID E): 534,176 vehicles<br>North (AVID N): 601,904 vehicles<br>South (AVID S): 509,685 vehicles<br>Total: 1,645,765 vehicles</p></div>
<div class="dbox"><h3>Vehicle classes detected</h3><p>Class 1: motorcycles / light<br>Class 2: passenger cars<br>Class 3: light trucks<br>Class 4: heavy vehicles<br>Class 5: buses / articulated</p></div>
</div></div>
</div>
<script>
const G='#EEEAE2',T='#aaa';
function mkS(){return{responsive:true,animation:{duration:300},interaction:{mode:'index',intersect:false},
plugins:{legend:{display:false},tooltip:{backgroundColor:'#fff',titleColor:'#1a1a1a',bodyColor:'#666',borderColor:'#E0DDD6',borderWidth:1,padding:8}},
scales:{x:{ticks:{color:T,font:{size:10},maxTicksLimit:12,maxRotation:0},grid:{color:G},border:{color:'#DDD'}},
y:{ticks:{color:T,font:{size:10}},grid:{color:G},border:{color:'#DDD'},beginAtZero:true}}}}

const cQ=new Chart(document.getElementById('cQ'),{type:'line',data:{labels:[],datasets:[
{label:'Fixed',data:[],borderColor:'#C1695A',backgroundColor:'rgba(193,105,90,.08)',borderWidth:2,pointRadius:0,tension:.4,fill:true},
{label:'MP',data:[],borderColor:'#7BA7CC',backgroundColor:'rgba(123,167,204,.08)',borderWidth:2,pointRadius:0,tension:.4,fill:true},
{label:'DRL',data:[],borderColor:'#6B9E7A',backgroundColor:'rgba(107,158,122,.08)',borderWidth:2,pointRadius:0,tension:.4,fill:true}
]},options:mkS()});

const cP=new Chart(document.getElementById('cP'),{type:'bar',data:{labels:['Fixed','Max Pressure','MP + DRL'],
datasets:[{data:[0,0,0],backgroundColor:['rgba(193,105,90,.75)','rgba(123,167,204,.75)','rgba(107,158,122,.75)'],borderRadius:6,barThickness:48}]},
options:{...mkS(),indexAxis:'y',plugins:{...mkS().plugins,legend:{display:false}}}});

const cT=new Chart(document.getElementById('cT'),{type:'line',data:{labels:[],datasets:[
{label:'Reward',data:[],borderColor:'#3D7A52',borderWidth:1.5,pointRadius:0,tension:.3},
{label:'Rolling',data:[],borderColor:'#A8D4B8',borderWidth:2.5,pointRadius:0,tension:.4}
]},options:mkS()});

const cD=new Chart(document.getElementById('cD'),{type:'line',data:{labels:[],datasets:[
{label:'East',data:[],borderColor:'#C1695A',backgroundColor:'rgba(193,105,90,.10)',borderWidth:2,pointRadius:4,pointBackgroundColor:'#C1695A',tension:.4,fill:true},
{label:'North',data:[],borderColor:'#7BA7CC',backgroundColor:'rgba(123,167,204,.10)',borderWidth:2,pointRadius:4,pointBackgroundColor:'#7BA7CC',tension:.4,fill:true},
{label:'South',data:[],borderColor:'#6B9E7A',backgroundColor:'rgba(107,158,122,.10)',borderWidth:2,pointRadius:4,pointBackgroundColor:'#6B9E7A',tension:.4,fill:true}
]},options:{...mkS(),scales:{...mkS().scales,y:{...mkS().scales.y,title:{display:true,text:'Mean vehicles/hr',color:T,font:{size:10}}}}}});

const TABS=['queue','perf','training','topo','demand'];
function showTab(n,b){TABS.forEach(t=>document.getElementById('tab-'+t).classList.toggle('panel-hidden',t!==n));
document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));if(b)b.classList.add('active');
[cQ,cP,cT,cD].forEach(c=>{try{c.update('none')}catch(e){}});}

function roll(a,w){return a.map((_,i)=>{const s=a.slice(Math.max(0,i-w+1),i+1);return s.reduce((x,y)=>x+y,0)/s.length;});}
function mn(a){return a.length?a.reduce((x,y)=>x+y,0)/a.length:0;}
function sd(a){const m=mn(a);return Math.sqrt(a.reduce((s,v)=>s+(v-m)**2,0)/Math.max(a.length,1));}
function getQ(r){return(r.q_A||0)+(r.q_B||0)+(r.q_C||0)+(r.q_D||0);}
let demLoaded=false;

async function poll(){
try{
const r=await fetch('/api/data').then(x=>x.json());
const FR=r.fixed?.records||[],MR=r.mp?.records||[],DR=r.hybrid_drl?.records||[];
const running=r.fixed?.running||r.mp?.running||r.hybrid_drl?.running;
const total=Math.max(FR.length,MR.length,DR.length);
const dot=document.getElementById('ldot'),txt=document.getElementById('ltxt');
if(total>0){dot.classList.remove('dot-w');txt.textContent=`Live · ${total} steps`;}
else{dot.classList.add('dot-w');txt.textContent=running?'Starting...':'Waiting...';}
if(total===0){setTimeout(poll,1500);return;}

const rawF=FR.map(getQ),rawM=MR.map(getQ),rawD=DR.map(getQ);
const longest=[FR,MR,DR].reduce((a,b)=>a.length>=b.length?a:b);
cQ.data.labels=longest.map(x=>x.hhmm||'');
cQ.data.datasets[0].data=roll(rawF,10);cQ.data.datasets[1].data=roll(rawM,10);cQ.data.datasets[2].data=roll(rawD,10);
cQ.update();

const aF=mn(rawF),aM=mn(rawM),aD=mn(rawD);
const pM=aF?((aF-aM)/aF*100):0,pD=aF?((aF-aD)/aF*100):0;
document.getElementById('k1').innerHTML=`${aM.toFixed(1)} <sub>veh</sub>`;
document.getElementById('k1s').textContent=`${pM.toFixed(1)}% reduction vs fixed`;
document.getElementById('k2').innerHTML=`${aD.toFixed(1)} <sub>veh</sub>`;
document.getElementById('k2s').textContent=`${pD.toFixed(1)}% reduction vs fixed`;
document.getElementById('k3').textContent=total.toLocaleString();
document.getElementById('k3s').textContent=running?'Running — 3 modes':'All modes complete';

cP.data.datasets[0].data=[aF,aM,aD];cP.update('none');
const swF=FR.reduce((a,r)=>a+(r.sw||0),0),swM=MR.reduce((a,r)=>a+(r.sw||0),0),swD=DR.reduce((a,r)=>a+(r.sw||0),0);
const hrs=Math.max(longest.length*30,1)/3600;
document.getElementById('ptb').innerHTML=[
{n:'Fixed timing',v:aF,s:sd(rawF),mx:rawF.length?Math.max(...rawF):0,sw:swF,c:'cr'},
{n:'Max Pressure',v:aM,s:sd(rawM),mx:rawM.length?Math.max(...rawM):0,sw:swM,c:'cb'},
{n:'MP + DRL',v:aD,s:sd(rawD),mx:rawD.length?Math.max(...rawD):0,sw:swD,c:'cg'}
].map(o=>`<tr><td>${o.n}</td><td class="${o.c}">${o.v.toFixed(1)}</td><td>±${o.s.toFixed(1)}</td><td>${o.mx.toFixed(0)}</td><td>${Math.round(o.sw/hrs)}/hr</td></tr>`).join('');

if(DR.length>5){
const rews=DR.map(x=>x.reward||0);
cT.data.labels=DR.map(x=>x.hhmm||'');
cT.data.datasets[0].data=rews;cT.data.datasets[1].data=roll(rews,20);cT.update('none');}

if(!demLoaded&&r.demand){
const d=r.demand;const hs=Object.keys(d).map(Number).sort((a,b)=>a-b);
cD.data.labels=hs.map(h=>`${h}:00`);
cD.data.datasets[0].data=hs.map(h=>d[String(h)]?.E||0);
cD.data.datasets[1].data=hs.map(h=>d[String(h)]?.N||0);
cD.data.datasets[2].data=hs.map(h=>d[String(h)]?.S||0);
cD.update('none');demLoaded=true;}
}catch(e){console.warn('poll:',e);}
setTimeout(poll,1500);}
poll();
</script></body></html>'''

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--speed',type=float,default=10)
    p.add_argument('--no-hardware',action='store_true')
    a=p.parse_args()
    hw=None
    if not a.no_hardware:
        hw=HardwareIO();hw.blink_boot()
    print(f"\n{'='*55}\n  J1 RPi Dashboard — 3 modes parallel\n  Speed: {a.speed}x | HW: {'YES' if hw else 'NO'}\n  http://0.0.0.0:5000\n{'='*55}\n")
    for mode in ['fixed','mp','hybrid_drl']:
        h=hw if mode=='hybrid_drl' else None
        threading.Thread(target=run_mode,args=(mode,a.speed,h),daemon=True).start()
        print(f"  [{mode}] started");time.sleep(0.5)
    try: app.run(host='0.0.0.0',port=5000,debug=False,use_reloader=False)
    except KeyboardInterrupt: print("\nStopped.")
    finally:
        if hw: hw.cleanup()

if __name__=='__main__': main()