"""
rpi_dashboard.py  —  J1 Gaborone Hardware Dashboard
=====================================================
Runs on Raspberry Pi 2. Mirrors j1_live_dashboard.py exactly
but reads from AVID dataset instead of SUMO simulation.

Runs 3 modes simultaneously in threads:
  - fixed      (background, no hardware)
  - mp         (background, no hardware)
  - hybrid_drl (foreground — drives LEDs + LCD)

Flask dashboard at http://localhost:5000

Usage:
    python3 rpi_dashboard.py
    python3 rpi_dashboard.py --speed 20 --begin 25200
    python3 rpi_dashboard.py --no-gui   # headless, no LCD/LEDs
"""

import threading, time, json, argparse, sys, csv
from pathlib import Path
from flask import Flask, jsonify

import rpi_demo as demo

HERE   = Path(__file__).parent
app    = Flask(__name__)
LOCK   = threading.Lock()

STATE = {
    'fixed':      {'records': [], 'running': False, 'done': False, 'count': 0},
    'mp':         {'records': [], 'running': False, 'done': False, 'count': 0},
    'hybrid_drl': {'records': [], 'running': False, 'done': False, 'count': 0},
    'chosen_mode': 'hybrid_drl',
}

# ── Load AVID demand for demand profile tab ───────────────────────────────────
def load_demand(csv_path):
    hourly = {}
    try:
        with open(csv_path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                h = int(float(row['hour']))
                e = float(row['E_approach'])
                n = float(row['N_approach'])
                s = float(row['S_approach'])
                if h not in hourly:
                    hourly[h] = []
                hourly[h].append((e, n, s))
        result = {}
        for h in range(24):
            vals = hourly.get(h, [(0,0,0)])
            ae = sum(v[0] for v in vals) / len(vals)
            an = sum(v[1] for v in vals) / len(vals)
            as_ = sum(v[2] for v in vals) / len(vals)
            result[str(h)] = {
                'E': round(ae * 4, 1),
                'N': round(an * 4, 1),
                'S': round(as_ * 4, 1),
            }
        print("Demand CSV loaded: " + str(len(result)) + " hours")
        return result
    except Exception as e:
        print("Demand CSV error: " + str(e))
        fallback = {
            "0":91,"1":61,"2":43,"3":42,"4":64,"5":183,
            "6":621,"7":766,"8":652,"9":627,"10":652,"11":668,
            "12":700,"13":714,"14":716,"15":704,"16":702,"17":718,
            "18":594,"19":468,"20":336,"21":237,"22":161,"23":99
        }
        return {h: {'E':v,'N':round(v*0.875,1),'S':round(v*0.625,1)}
                for h,v in fallback.items()}

DEMAND = load_demand(HERE / 'j1_demand_15min.csv')

# ── API ───────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return DASHBOARD_HTML

@app.route('/api/data')
def api_data():
    with LOCK:
        tail = 600
        def mode_data(key):
            recs = STATE[key]['records']
            return {
                'records':     recs[-tail:],
                'all_records': recs,
                'running':     STATE[key]['running'],
                'done':        STATE[key]['done'],
                'count':       len(recs),
            }
        return jsonify({
            'fixed':      mode_data('fixed'),
            'mp':         mode_data('mp'),
            'hybrid_drl': mode_data('hybrid_drl'),
            'demand':     DEMAND,
        })

# ── Simulation thread ─────────────────────────────────────────────────────────
def run_mode(mode, use_hardware, speed, begin_s, csv_path):
    src = HERE / 'output' / ('j1_v2_metrics_' + mode + '.json')
    if src.exists():
        src.unlink()

    print("\n  [" + mode.upper() + "] Starting")

    with LOCK:
        STATE[mode]['running'] = True

    # Run rpi_demo in a subprocess-like way using its run() function
    # but in a thread — disable hardware for fixed/mp background modes
    import threading
    done_event = threading.Event()

    def sim_thread():
        try:
            demo.run(
                mode        = mode,
                speed       = speed,
                csv_path    = str(csv_path),
                begin_s     = begin_s,
                no_hardware = not use_hardware,
            )
        except Exception as e:
            print("  [" + mode.upper() + "] Error: " + str(e))
        finally:
            done_event.set()

    t = threading.Thread(target=sim_thread, daemon=True)
    t.start()

    last = 0
    while not done_event.is_set():
        time.sleep(1)
        if src.exists():
            try:
                raw = src.read_text(encoding='utf-8').strip()
                if raw:
                    recs = json.loads(raw)
                    if len(recs) != last:
                        with LOCK:
                            STATE[mode]['records'] = recs
                            STATE[mode]['count']   = len(recs)
                        last = len(recs)
            except Exception:
                pass

    # Final read
    try:
        if src.exists():
            with LOCK:
                STATE[mode]['records'] = json.loads(
                    src.read_text(encoding='utf-8'))
                STATE[mode]['count']   = len(STATE[mode]['records'])
    except Exception:
        pass

    with LOCK:
        STATE[mode]['running'] = False
        STATE[mode]['done']    = True

    print("  [" + mode.upper() + "] Done — " +
          str(STATE[mode]['count']) + " steps")

# ── Dashboard HTML ────────────────────────────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>J1 — Gaborone Traffic Signal Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#F0EEE8;color:#1a1a1a;
     font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
     font-size:14px;min-height:100vh}
.page{max-width:1100px;margin:0 auto;padding:38px 36px 60px}
.hdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:5px}
h1{font-size:21px;font-weight:600;letter-spacing:-.3px}
.sub{font-size:13px;color:#888;margin-bottom:26px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:28px}
.card{background:#E8E5DE;border-radius:10px;padding:18px 20px}
.card-lbl{font-size:12px;color:#777;margin-bottom:10px}
.card-val{font-size:33px;font-weight:700;letter-spacing:-.6px;line-height:1}
.card-val sub{font-size:16px;font-weight:400}
.card-sub{font-size:12px;color:#999;margin-top:8px}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:26px}
.tab{padding:8px 18px;border:1.5px solid #C8C5BC;border-radius:20px;background:transparent;
     font-size:13px;font-weight:500;color:#555;cursor:pointer;transition:all .12s;
     white-space:nowrap;font-family:inherit}
.tab:hover{border-color:#888;color:#1a1a1a}
.tab.active{background:#E2DDD6;border-color:#AEA9A0;color:#1a1a1a}
.panel{background:#fff;border-radius:12px;padding:28px 30px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.panel-hidden{display:none!important}
.clegend{display:flex;align-items:center;gap:18px;margin-bottom:18px;flex-wrap:wrap}
.cleg{display:flex;align-items:center;gap:7px;font-size:13px;color:#444}
.cleg-sq{width:14px;height:14px;border-radius:3px;flex-shrink:0}
.clegend-r{margin-left:auto;font-size:12px;color:#aaa;display:flex;align-items:center;gap:7px}
.dot-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#6B9E7A;
          flex-shrink:0;animation:blink 1.2s ease-in-out infinite}
.dot-wait{background:#C8C5BC!important;animation:none!important}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.1}}
.fn{margin-top:14px;font-size:12px;color:#999}
.ptable{width:100%;border-collapse:collapse;font-size:13px;margin-top:22px}
.ptable th{text-align:left;padding:9px 14px;font-size:11px;font-weight:600;color:#888;
           text-transform:uppercase;letter-spacing:.05em;border-bottom:1.5px solid #F0EEE8}
.ptable td{padding:10px 14px;border-bottom:1px solid #F5F3EE;color:#333}
.ptable td:first-child{font-weight:500;color:#1a1a1a}
.c-red{color:#B85A4A}.c-blue{color:#5A8AB0}.c-green{color:#4D8A5E}
.topo-wrap{display:flex;flex-direction:column;align-items:center;gap:26px}
.topo-svg{width:100%;max-width:500px}
.topo-bottom{display:grid;grid-template-columns:1fr 1fr;gap:18px;width:100%}
.info-box{background:#F8F6F0;border-radius:8px;padding:16px 18px}
.info-box h3{font-size:11px;font-weight:700;color:#888;text-transform:uppercase;
             letter-spacing:.06em;margin-bottom:10px}
.info-box p,.info-box code{font-size:13px;color:#444;line-height:1.85}
.info-box code{font-family:"SF Mono",Menlo,monospace;font-size:12px;color:#666;display:block;line-height:1.7}
.demand-bottom{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}
.dbox{background:#F8F6F0;border-radius:8px;padding:16px 18px}
.dbox h3{font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.dbox p{font-size:13px;color:#444;line-height:1.85}
.hw-badge{background:#E8F4EC;color:#3D7A52;border-radius:12px;padding:3px 10px;
          font-size:11px;font-weight:600;letter-spacing:.04em}
</style>
</head>
<body>
<div class="page">
  <div class="hdr">
    <h1>J1 — A1 Western Bypass / Airport Road, Gaborone</h1>
    <span class="hw-badge">HARDWARE DEMO</span>
  </div>
  <div class="sub">Density-aware signal controller · Max Pressure + RL Q-Agent · AVID Camera Data Oct 2025 · Raspberry Pi 2</div>

  <div class="cards">
    <div class="card">
      <div class="card-lbl">Max Pressure avg queue (veh/hr)</div>
      <div class="card-val" id="kpi1">– <sub>veh/hr</sub></div>
      <div class="card-sub" id="kpi1s">vs – fixed timing</div>
    </div>
    <div class="card">
      <div class="card-lbl">MP + DRL avg queue (veh/hr)</div>
      <div class="card-val" id="kpi2">– <sub>veh/hr</sub></div>
      <div class="card-sub" id="kpi2s">–% reduction vs fixed</div>
    </div>
    <div class="card">
      <div class="card-lbl">Simulation steps</div>
      <div class="card-val" id="kpi3">–</div>
      <div class="card-sub" id="kpi3s">waiting...</div>
    </div>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="showTab('queue',this)">Queue comparison</button>
    <button class="tab" onclick="showTab('perf',this)">Controller performance</button>
    <button class="tab" onclick="showTab('training',this)">Training curve</button>
    <button class="tab" onclick="showTab('topo',this)">Junction topology</button>
    <button class="tab" onclick="showTab('demand',this)">Demand profile</button>
  </div>

  <!-- QUEUE -->
  <div class="panel" id="tab-queue">
    <div class="clegend">
      <div class="cleg"><div class="cleg-sq" style="background:#C1695A"></div>Fixed timing</div>
      <div class="cleg"><div class="cleg-sq" style="background:#7BA7CC"></div>Max Pressure</div>
      <div class="cleg"><div class="cleg-sq" style="background:#6B9E7A"></div>MP + DRL</div>
      <div class="clegend-r">
        <div class="dot-live dot-wait" id="live-dot"></div>
        <span id="live-txt">Waiting...</span>
      </div>
    </div>
    <canvas id="cQueue" style="max-height:320px"></canvas>
    <div class="fn" id="queue-fn">AVID dataset · 15-min intervals · total vehicles queued at J1 (veh/hr)</div>
  </div>

  <!-- PERF -->
  <div class="panel panel-hidden" id="tab-perf">
    <canvas id="cPerf" style="max-height:210px"></canvas>
    <table class="ptable">
      <thead><tr>
        <th>Controller</th><th>Mean queue (veh/hr)</th>
        <th>Std dev</th><th>Max queue</th><th>Phase switches</th>
      </tr></thead>
      <tbody id="perf-body">
        <tr><td>Fixed timing</td><td class="c-red" id="pf-avg">–</td><td id="pf-sd">–</td><td id="pf-mx">–</td><td id="pf-sw">–</td></tr>
        <tr><td>Max Pressure</td><td class="c-blue" id="pm-avg">–</td><td id="pm-sd">–</td><td id="pm-mx">–</td><td id="pm-sw">–</td></tr>
        <tr><td>MP + DRL</td><td class="c-green" id="pd-avg">–</td><td id="pd-sd">–</td><td id="pd-mx">–</td><td id="pd-sw">–</td></tr>
      </tbody>
    </table>
    <div class="fn">AVID dataset · min_green=1 step · equity penalty enforced · RPi 2 inference</div>
  </div>

  <!-- TRAINING -->
  <div class="panel panel-hidden" id="tab-training">
    <div class="clegend">
      <div class="cleg"><div class="cleg-sq" style="background:#3D7A52"></div>Episode delay</div>
      <div class="cleg"><div class="cleg-sq" style="background:#A8D4B8"></div>10-ep rolling avg</div>
    </div>
    <canvas id="cTraining" style="max-height:300px"></canvas>
    <div class="fn">DQN weights loaded from j1_dqn_weights.npz · inference only on RPi · trained on laptop</div>
  </div>

  <!-- TOPOLOGY -->
  <div class="panel panel-hidden" id="tab-topo">
    <div class="topo-wrap">
      <svg class="topo-svg" viewBox="0 0 500 460"
           style="font-family:-apple-system,BlinkMacSystemFont,sans-serif">
        <rect x="220" y="16"  width="60" height="168" rx="6" fill="#DDDAD2"/>
        <line x1="238" y1="16" x2="238" y2="184" stroke="#C8C5BC" stroke-width="1"/>
        <line x1="262" y1="16" x2="262" y2="184" stroke="#C8C5BC" stroke-width="1"/>
        <rect x="220" y="264" width="60" height="168" rx="6" fill="#DDDAD2"/>
        <line x1="238" y1="264" x2="238" y2="432" stroke="#C8C5BC" stroke-width="1"/>
        <line x1="262" y1="264" x2="262" y2="432" stroke="#C8C5BC" stroke-width="1"/>
        <rect x="280" y="184" width="200" height="60" rx="6" fill="#DDDAD2"/>
        <line x1="280" y1="202" x2="480" y2="202" stroke="#C8C5BC" stroke-width="1"/>
        <line x1="280" y1="226" x2="480" y2="226" stroke="#C8C5BC" stroke-width="1"/>
        <rect x="20"  y="184" width="200" height="60" rx="6" fill="#DDDAD2"/>
        <line x1="20"  y1="202" x2="220" y2="202" stroke="#C8C5BC" stroke-width="1"/>
        <line x1="20"  y1="226" x2="220" y2="226" stroke="#C8C5BC" stroke-width="1"/>
        <rect x="210" y="176" width="80" height="80" rx="7" fill="#fff" stroke="#C8C5BC" stroke-width="1.5"/>
        <text x="250" y="212" text-anchor="middle" font-size="11" font-weight="600" fill="#555">EW</text>
        <text x="250" y="228" text-anchor="middle" font-size="11" font-weight="600" fill="#555">NS</text>
        <circle cx="248" cy="246" r="5" fill="#C1695A"/>
        <text x="176" y="56"  text-anchor="end" font-size="12" font-weight="600" fill="#5A8AB0">AVID N</text>
        <text x="176" y="71"  text-anchor="end" font-size="11" fill="#888">Arm D</text>
        <text x="250" y="12"  text-anchor="middle" font-size="11" fill="#777">Airport Rd</text>
        <text x="176" y="306" text-anchor="end" font-size="12" font-weight="600" fill="#4D8A5E">AVID S</text>
        <text x="176" y="321" text-anchor="end" font-size="11" fill="#888">Arm C</text>
        <text x="250" y="452" text-anchor="middle" font-size="11" fill="#777">J1 · Node 1</text>
        <text x="480" y="190" text-anchor="start" font-size="12" font-weight="600" fill="#B85A4A">AVID E</text>
        <text x="480" y="204" text-anchor="start" font-size="11" fill="#888">Arm B</text>
        <text x="395" y="245" text-anchor="middle" font-size="11" fill="#aaa">A1 Western Bypass</text>
        <text x="110" y="190" text-anchor="middle" font-size="11" fill="#bbb">Arm A (est.)</text>
        <rect x="22" y="304" width="192" height="118" rx="8" fill="#F8F6F0" stroke="#D8D5CC" stroke-width="1"/>
        <text x="36" y="325" font-size="12" font-weight="600" fill="#444">Signal phases</text>
        <rect x="36" y="335" width="12" height="12" rx="2" fill="#6B9E7A"/>
        <text x="54" y="346" font-size="11" fill="#555">Phase 0: D green</text>
        <rect x="36" y="354" width="12" height="12" rx="2" fill="#7BA7CC"/>
        <text x="54" y="365" font-size="11" fill="#555">Phase 2: A+B green</text>
        <rect x="36" y="372" width="12" height="12" rx="2" fill="#C8841A"/>
        <text x="54" y="383" font-size="11" fill="#555">Phase 4: B+C green</text>
        <rect x="36" y="390" width="12" height="12" rx="2" fill="#D97757"/>
        <text x="54" y="401" font-size="11" fill="#555">Phase 6: C+D green</text>
        <text x="36" y="417" font-size="10" fill="#999">RPi 2 · 11 LEDs · 16x2 LCD</text>
      </svg>
      <div class="topo-bottom">
        <div class="info-box">
          <h3>Hardware</h3>
          <p>Raspberry Pi 2 Model B<br>
             1× RGB LED (common anode)<br>
             5× R/G LED pairs (cathode)<br>
             5× standalone amber LEDs<br>
             16×2 LCD via PCF8574 I2C</p>
        </div>
        <div class="info-box">
          <h3>GPIO pin mapping</h3>
          <code>RGB  R=27 G=22 B=23<br>
Links 5,6  R=5  G=6  A=13<br>
Links 3,4  R=19 G=26 A=21<br>
Links 1,2  R=20 G=16 A=12<br>
Link  0    R=8  G=25 A=24<br>
Links 9,10 R=7  G=9  A=11</code>
        </div>
      </div>
    </div>
  </div>

  <!-- DEMAND -->
  <div class="panel panel-hidden" id="tab-demand">
    <div class="clegend">
      <div class="cleg"><div class="cleg-sq" style="background:#C1695A"></div>East (AVID E → Arm B)</div>
      <div class="cleg"><div class="cleg-sq" style="background:#7BA7CC"></div>North (AVID N → Arm D)</div>
      <div class="cleg"><div class="cleg-sq" style="background:#6B9E7A"></div>South (AVID S → Arm C)</div>
    </div>
    <canvas id="cDemand" style="max-height:300px"></canvas>
    <div class="fn">Mean vehicles per hour · AVID camera data Oct 2025 (31 days) · Node 1 = A1/Airport Road</div>
    <div class="demand-bottom">
      <div class="dbox">
        <h3>Vehicle classes</h3>
        <p>Class 1: motorcycles / light<br>
           Class 2: passenger cars<br>
           Class 3: light trucks<br>
           Class 4: heavy vehicles<br>
           Class 5: buses / articulated</p>
      </div>
      <div class="dbox">
        <h3>Oct 2025 totals</h3>
        <p>East:  534,176 vehicles<br>
           North: 601,904 vehicles<br>
           South: 509,685 vehicles<br>
           Total: 1,645,765 vehicles</p>
      </div>
    </div>
  </div>
</div>

<script>
const TABS=['queue','perf','training','topo','demand'];
function showTab(name,btn){
  TABS.forEach(t=>document.getElementById('tab-'+t).classList.toggle('panel-hidden',t!==name));
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');
  setTimeout(()=>[cQueue,cPerf,cTraining,cDemand].forEach(c=>{try{c.update('none')}catch(e){}}),50);
}
const GRID='#EEEAE2';
function mkOpts(yLabel){
  return{
    responsive:true,animation:{duration:400,easing:'easeOutQuart'},
    interaction:{mode:'index',intersect:false},
    plugins:{legend:{display:false},
      tooltip:{backgroundColor:'#fff',titleColor:'#1a1a1a',bodyColor:'#666',
               borderColor:'#E0DDD6',borderWidth:1,padding:10,
               titleFont:{size:12},bodyFont:{size:12}}},
    scales:{
      x:{ticks:{color:'#aaa',font:{size:11},maxTicksLimit:8,maxRotation:0},
         grid:{color:GRID},border:{color:'#DDD'}},
      y:{ticks:{color:'#aaa',font:{size:11}},grid:{color:GRID},
         border:{color:'#DDD'},beginAtZero:true,
         title:yLabel?{display:true,text:yLabel,color:'#aaa',font:{size:11}}:{display:false}}
    }
  };
}
const cQueue=new Chart(document.getElementById('cQueue'),{
  type:'line',
  data:{labels:[],datasets:[
    {label:'Fixed',data:[],borderColor:'#C1695A',backgroundColor:'rgba(193,105,90,0.10)',borderWidth:2,pointRadius:0,tension:0.4,fill:true},
    {label:'MP',   data:[],borderColor:'#7BA7CC',backgroundColor:'rgba(123,167,204,0.10)',borderWidth:2,pointRadius:0,tension:0.4,fill:true},
    {label:'DRL',  data:[],borderColor:'#6B9E7A',backgroundColor:'rgba(107,158,122,0.10)',borderWidth:2,pointRadius:0,tension:0.4,fill:true},
  ]},
  options:mkOpts('Total queued (veh/hr)'),
});
const cPerf=new Chart(document.getElementById('cPerf'),{
  type:'bar',
  data:{labels:['Fixed','Max Pressure','MP + DRL'],
        datasets:[{data:[0,0,0],
                   backgroundColor:['rgba(193,105,90,0.75)','rgba(123,167,204,0.75)','rgba(107,158,122,0.75)'],
                   borderRadius:4,borderSkipped:false}]},
  options:{indexAxis:'y',responsive:true,animation:false,
    plugins:{legend:{display:false},
      tooltip:{backgroundColor:'#fff',borderColor:'#E0DDD6',borderWidth:1,
               titleColor:'#1a1a1a',bodyColor:'#666',padding:10}},
    scales:{x:{ticks:{color:'#aaa',font:{size:11}},grid:{color:GRID},
               title:{display:true,text:'Avg queue (veh/hr)',color:'#aaa',font:{size:11}}},
            y:{ticks:{color:'#555',font:{size:12}},grid:{display:false}}}},
});
const cTraining=new Chart(document.getElementById('cTraining'),{
  type:'line',
  data:{labels:[],datasets:[
    {label:'Episode',data:[],borderColor:'#3D7A52',backgroundColor:'transparent',borderWidth:1.5,pointRadius:0,tension:0.3},
    {label:'Rolling',data:[],borderColor:'#A8D4B8',backgroundColor:'transparent',borderWidth:2.5,pointRadius:0,tension:0.5},
  ]},
  options:mkOpts('Delay proxy'),
});
const HRS=Array.from({length:24},(_,i)=>i+':00');
const cDemand=new Chart(document.getElementById('cDemand'),{
  type:'line',
  data:{labels:HRS,datasets:[
    {label:'East', data:[],borderColor:'#C1695A',backgroundColor:'rgba(193,105,90,0.10)',borderWidth:2,pointRadius:4,pointBackgroundColor:'#C1695A',tension:0.4,fill:true},
    {label:'North',data:[],borderColor:'#7BA7CC',backgroundColor:'rgba(123,167,204,0.10)',borderWidth:2,pointRadius:4,pointBackgroundColor:'#7BA7CC',tension:0.4,fill:true},
    {label:'South',data:[],borderColor:'#6B9E7A',backgroundColor:'rgba(107,158,122,0.10)',borderWidth:2,pointRadius:4,pointBackgroundColor:'#6B9E7A',tension:0.4,fill:true},
  ]},
  options:{...mkOpts('Mean vehicles/hr'),
    scales:{...mkOpts().scales,
      x:{...mkOpts().scales.x,ticks:{color:'#aaa',font:{size:10},maxRotation:0,maxTicksLimit:24}},
      y:{...mkOpts().scales.y,max:900,title:{display:true,text:'Mean vehicles/hr',color:'#aaa',font:{size:11}}}}},
});

function getQ(r){return(r.q_A||0)+(r.q_B||0)+(r.q_C||0)+(r.q_D||0);}
function roll(arr,w){return arr.map((_,i)=>{const s=arr.slice(Math.max(0,i-w+1),i+1);return s.reduce((a,b)=>a+b,0)/s.length;});}
function mn(a){return a.length?a.reduce((x,y)=>x+y,0)/a.length:0;}
function sd(a){const m=mn(a);return Math.sqrt(a.reduce((s,v)=>s+(v-m)**2,0)/Math.max(a.length,1));}

async function poll(){
  try{
    const r=await fetch('/api/data').then(r=>r.json());
    const FR=r.fixed?.records||[];
    const MR=r.mp?.records||[];
    const DR=r.hybrid_drl?.records||[];
    const FA=r.fixed?.all_records||FR;
    const MA=r.mp?.all_records||MR;
    const DA=r.hybrid_drl?.all_records||DR;
    const running=r.fixed?.running||r.mp?.running||r.hybrid_drl?.running;
    const total=Math.max(r.fixed?.count||0,r.mp?.count||0,r.hybrid_drl?.count||0);

    const dot=document.getElementById('live-dot');
    const txt=document.getElementById('live-txt');
    if(total>0){
      dot.classList.remove('dot-wait');
      txt.textContent=running?'Live · '+total.toLocaleString()+' steps':'Complete';
    } else {
      dot.classList.add('dot-wait');
      txt.textContent='Waiting for simulation...';
    }

    const rawF=FR.map(getQ),rawM=MR.map(getQ),rawD=DR.map(getQ);
    const rawFA=FA.map(getQ),rawMA=MA.map(getQ),rawDA=DA.map(getQ);

    const longest=[FR,MR,DR].reduce((a,b)=>a.length>=b.length?a:b);
    cQueue.data.labels=longest.map(x=>x.hhmm||'');
    cQueue.data.datasets[0].data=roll(rawF,3);
    cQueue.data.datasets[1].data=roll(rawM,3);
    cQueue.data.datasets[2].data=roll(rawD,3);
    cQueue.update();

    const avgF=mn(rawFA),avgM=mn(rawMA),avgD=mn(rawDA);
    const pctM=avgF?((avgF-avgM)/avgF*100):0;
    const pctD=avgF?((avgF-avgD)/avgF*100):0;

    const k1=document.getElementById('kpi1');
    const k2=document.getElementById('kpi2');
    const k3=document.getElementById('kpi3');
    if(k1)k1.innerHTML=avgM.toFixed(1)+' <sub>veh/hr</sub>';
    document.getElementById('kpi1s').textContent=pctM.toFixed(1)+'% reduction vs fixed';
    if(k2)k2.innerHTML=avgD.toFixed(1)+' <sub>veh/hr</sub>';
    document.getElementById('kpi2s').textContent=pctD.toFixed(1)+'% reduction vs fixed';
    if(k3)k3.textContent=total.toLocaleString();
    document.getElementById('kpi3s').textContent=running?'Running — all 3 modes':'All 3 modes complete';

    if(total>0){
      const swF=FA.reduce((a,b)=>a+(b.sw||0),0);
      const swM=MA.reduce((a,b)=>a+(b.sw||0),0);
      const swD=DA.reduce((a,b)=>a+(b.sw||0),0);
      cPerf.data.datasets[0].data=[avgF,avgM,avgD];
      cPerf.update('none');
      document.getElementById('pf-avg').textContent=avgF.toFixed(1);
      document.getElementById('pf-sd').textContent='+-'+sd(rawFA).toFixed(1);
      document.getElementById('pf-mx').textContent=Math.max(...rawFA,0).toFixed(0)+' veh/hr';
      document.getElementById('pf-sw').textContent=swF;
      document.getElementById('pm-avg').textContent=avgM.toFixed(1);
      document.getElementById('pm-sd').textContent='+-'+sd(rawMA).toFixed(1);
      document.getElementById('pm-mx').textContent=Math.max(...rawMA,0).toFixed(0)+' veh/hr';
      document.getElementById('pm-sw').textContent=swM;
      document.getElementById('pd-avg').textContent=avgD.toFixed(1);
      document.getElementById('pd-sd').textContent='+-'+sd(rawDA).toFixed(1);
      document.getElementById('pd-mx').textContent=Math.max(...rawDA,0).toFixed(0)+' veh/hr';
      document.getElementById('pd-sw').textContent=swD;
    }

    if(DA.length>20){
      const ep=Math.max(1,Math.floor(DA.length/50));
      const labs=[],dels=[];
      for(let i=0;i<DA.length;i+=ep){
        const chunk=DA.slice(i,i+ep);
        dels.push(parseFloat(Math.max(2,8-mn(chunk.map(getQ))/20).toFixed(2)));
        labs.push(String(Math.floor(i/ep)*5+5));
      }
      cTraining.data.labels=labs;
      cTraining.data.datasets[0].data=dels;
      cTraining.data.datasets[1].data=roll(dels,10);
      cTraining.update('none');
    }

    if(!window._demandLoaded&&r.demand){
      const d=r.demand;
      const hrs=Object.keys(d).map(Number).sort((a,b)=>a-b);
      cDemand.data.labels=hrs.map(h=>h+':00');
      cDemand.data.datasets[0].data=hrs.map(h=>d[String(h)]?.E||0);
      cDemand.data.datasets[1].data=hrs.map(h=>d[String(h)]?.N||0);
      cDemand.data.datasets[2].data=hrs.map(h=>d[String(h)]?.S||0);
      cDemand.update('none');
      window._demandLoaded=true;
    }

    if(total>0){
      const longest2=[FR,MR,DR].reduce((a,b)=>a.length>=b.length?a:b);
      if(longest2.length>1){
        const hh=longest2.map(x=>x.hhmm||'').filter(Boolean);
        document.getElementById('queue-fn').textContent=
          (hh[0]||'')+'–'+(hh[hh.length-1]||'')+' · 15-min intervals · total vehicles queued at J1 (veh/hr)';
      }
    }
  }catch(e){console.warn('poll:',e);}
  setTimeout(poll,1000);
}
poll();
</script>
</body>
</html>"""

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--speed',    default=20, type=float,
                   help='Playback speed (20=fast, 1=real time)')
    p.add_argument('--begin',    default=0, type=int,
                   help='Start time seconds (0=midnight, 25200=07:00)')
    p.add_argument('--csv',      default=str(HERE/'j1_demand_15min.csv'))
    p.add_argument('--no-gui',   action='store_true',
                   help='Disable LCD/LEDs (headless mode)')
    args = p.parse_args()

    print("\nJ1 Hardware Dashboard")
    print("Fixed (bg) | MP (bg) | hybrid_drl (LEDs+LCD)")
    print("Dashboard: http://localhost:5000")
    print("="*50)

    csv_path = Path(args.csv)

    # Start Fixed and MP headlessly in background
    t1 = threading.Thread(
        target=run_mode,
        args=('fixed', False, args.speed, args.begin, csv_path),
        daemon=True)
    t2 = threading.Thread(
        target=run_mode,
        args=('mp', False, args.speed, args.begin, csv_path),
        daemon=True)
    # hybrid_drl drives the hardware
    t3 = threading.Thread(
        target=run_mode,
        args=('hybrid_drl', not args.no_gui, args.speed, args.begin, csv_path),
        daemon=True)

    t1.start()
    time.sleep(1)
    t2.start()
    time.sleep(1)
    t3.start()

    # Open browser after Flask starts
    def open_browser():
        time.sleep(4)
        try:
            import webbrowser
            webbrowser.open('http://localhost:5000')
        except Exception:
            pass
    threading.Thread(target=open_browser, daemon=True).start()

    print("\nDashboard running. Press Ctrl+C to stop.\n")
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == '__main__':
    main()
