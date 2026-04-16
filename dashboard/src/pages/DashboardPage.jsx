import React, { useMemo } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell, RadialBarChart, RadialBar,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from 'recharts';
import './DashboardPage.css';

const C = { primary:'#0ea5e9', sky:'#38bdf8', cyan:'#06b6d4', light:'#7dd3fc',
  deep:'#0c4a6e', red:'#ef4444', green:'#22c55e', purple:'#a855f7', rose:'#f43f5e' };

const DashboardPage = ({ cloudSummaryA, cloudSummaryB, fogStatusA, fogStatusB, notifications, metricsHistory, lastUpdated, autoRefresh, setAutoRefresh, refresh }) => {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const agg = useMemo(() => cloudSummaryA?.aggregates || [], [cloudSummaryA]);
  const kpis = cloudSummaryA?.kpis || {};
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const last = useMemo(() => agg[agg.length - 1] || {}, [agg]);

  const riskIdx = last.flood_risk_index || 0;
  const riskLevel = riskIdx > 3 ? 'CRITICAL' : riskIdx > 2 ? 'HIGH' : riskIdx > 1 ? 'ELEVATED' : 'NORMAL';
  const riskColor = riskIdx > 3 ? C.red : riskIdx > 2 ? C.primary : riskIdx > 1 ? C.sky : C.green;

  const bandwidthSaved = fogStatusA?.rates_10s?.reduction_pct || 0;
  const totalEvents = kpis.total_events_1h || 0;
  const highWaterEvents = kpis.high_water_events_1h || 0;
  const floodWarnings = kpis.flood_warning_events_1h || 0;
  const flashFloods = kpis.flash_flood_events_1h || 0;

  const sparkData = useMemo(() => agg.slice(-30).map(a => ({
    t: a.SK ? new Date(a.SK).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}) : '',
    wl: a.max_water_level || 0,
    fr: a.avg_flow_rate || 0,
  })), [agg]);

  const barData = useMemo(() => agg.slice(-12).map(a => ({
    t: a.SK ? new Date(a.SK).toLocaleTimeString([],{minute:'2-digit',second:'2-digit'}) : '',
    flow: a.avg_flow_rate || 0,
    risk: a.flood_risk_index || 0,
  })), [agg]);

  const alertCounts = useMemo(() => {
    const c = { CRITICAL:0, HIGH:0, MEDIUM:0, LOW:0 };
    notifications.forEach(n => { if(c[n.severity]!==undefined) c[n.severity]++; });
    return c;
  }, [notifications]);

  // Radar chart: normalized sensor readings (0-100 scale)
  const radarData = useMemo(() => {
    const wl = last.max_water_level || 0;
    const fr = last.avg_flow_rate || 0;
    const sm = last.avg_soil_moisture || 0;
    const tb = last.avg_turbidity || 0;
    const ri = last.flood_risk_index || 0;
    return [
      { sensor: 'Water Level', value: Math.min(100, (wl / 15) * 100), raw: `${wl.toFixed(1)}m` },
      { sensor: 'Flow Rate', value: Math.min(100, (fr / 500) * 100), raw: `${fr.toFixed(0)} m³/s` },
      { sensor: 'Soil Moisture', value: Math.min(100, sm), raw: `${sm.toFixed(0)}%` },
      { sensor: 'Turbidity', value: Math.min(100, (tb / 100) * 100), raw: `${tb.toFixed(1)} NTU` },
      { sensor: 'Flood Risk', value: Math.min(100, (ri / 15) * 100), raw: ri.toFixed(1) },
    ];
  }, [last]);

  const resilience = kpis.flood_resilience_score ?? 0;
  const gaugeData = [{ value: Math.max(resilience, 1), fill: resilience >= 60 ? C.green : resilience >= 30 ? C.sky : C.red }];

  const recentAlerts = notifications.slice(0, 5);

  return (
    <div className="dp">
      {/* ── Top Bar ── */}
      <header className="dp-top">
        <div className="dp-title-group">
          <h1 className="dp-h1">Flood Operations Center</h1>
          <span className="dp-time">{lastUpdated ? `${lastUpdated.toLocaleTimeString()}` : '—'}</span>
        </div>
        <div className="dp-actions">
          <label className="dp-toggle">
            <input type="checkbox" checked={autoRefresh} onChange={()=>setAutoRefresh(!autoRefresh)} />
            Live
          </label>
          <button className="dp-refresh" onClick={refresh}>↻</button>
        </div>
      </header>

      {/* ── Risk Banner ── */}
      <div className="risk-banner" style={{ borderColor: riskColor }}>
        <div className="risk-left">
          <span className="risk-label">THREAT LEVEL</span>
          <span className="risk-level" style={{ color: riskColor }}>{riskLevel}</span>
        </div>
        <div className="risk-center">
          <div className="risk-bar-track">
            <div className="risk-bar-fill" style={{ width:`${Math.min(100, riskIdx*25)}%`, background: riskColor }}/>
          </div>
          <span className="risk-index">Index: {riskIdx.toFixed(2)}</span>
        </div>
        <div className="risk-right">
          <span className="risk-stat">{notifications.length}<small> alerts</small></span>
          <span className="risk-stat">2<small> stations</small></span>
        </div>
      </div>

      {/* ── Metric Strip ── */}
      <div className="metric-strip">
        {[
          { label:'Water Level', val:`${(last.max_water_level||0).toFixed(1)}m`, icon:'💧' },
          { label:'Flow Rate', val:`${(last.avg_flow_rate||0).toFixed(1)} m³/s`, icon:'🌊' },
          { label:'Soil Moisture', val:`${(last.avg_soil_moisture||0).toFixed(0)}%`, icon:'🌱' },
          { label:'Turbidity', val:`${(last.avg_turbidity||0).toFixed(1)} NTU`, icon:'🔬' },
          { label:'Events (1h)', val: totalEvents.toLocaleString(), icon:'📊' },
          { label:'Bandwidth Saved', val:`${bandwidthSaved.toFixed(0)}%`, icon:'📡' },
        ].map((m,i) => (
          <div className="ms-item" key={i}>
            <span className="ms-icon">{m.icon}</span>
            <div className="ms-text">
              <span className="ms-val">{m.val}</span>
              <span className="ms-lbl">{m.label}</span>
            </div>
          </div>
        ))}
      </div>

      {/* ── Full-width Sparkline ── */}
      <div className="spark-section">
        <ResponsiveContainer width="100%" height={160}>
          <AreaChart data={sparkData} margin={{top:10,right:16,left:16,bottom:0}}>
            <defs>
              <linearGradient id="spk" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={C.primary} stopOpacity={0.4}/>
                <stop offset="100%" stopColor={C.primary} stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="spk-danger" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={C.red} stopOpacity={0.15}/>
                <stop offset="100%" stopColor={C.red} stopOpacity={0}/>
              </linearGradient>
            </defs>
            <XAxis dataKey="t" tick={{fill:'#5a7a9b',fontSize:10}} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
            <YAxis hide domain={[0, 'auto']}/>
            <Tooltip
              contentStyle={{background:'#142338',border:'1px solid #1a3350',borderRadius:8,color:'#e0f2fe',fontSize:12,padding:'8px 12px'}}
              labelStyle={{color:'#7dd3fc',fontWeight:600,marginBottom:4}}
              formatter={(value, name) => [`${Number(value).toFixed(2)}m`, 'Water Level']}
              labelFormatter={(label) => `Time: ${label}`}
              cursor={{stroke:'#38bdf8',strokeWidth:1,strokeDasharray:'4 3'}}
            />
            {/* Fixed threshold lines */}
            <ReferenceLine y={1.8} stroke="#22c55e" strokeDasharray="6 4" strokeOpacity={0.5} label={{value:'LOW 1.8m',position:'right',fill:'#22c55e',fontSize:9}}/>
            <ReferenceLine y={2.5} stroke="#06b6d4" strokeDasharray="6 4" strokeOpacity={0.6} label={{value:'MED 2.5m',position:'right',fill:'#06b6d4',fontSize:9}}/>
            <ReferenceLine y={3.2} stroke="#f59e0b" strokeDasharray="6 4" strokeOpacity={0.7} label={{value:'HIGH 3.2m',position:'right',fill:'#f59e0b',fontSize:9}}/>
            <ReferenceLine y={5.25} stroke="#ef4444" strokeDasharray="6 4" strokeOpacity={0.8} label={{value:'CRIT 5.25m',position:'right',fill:'#ef4444',fontSize:9}}/>
            <Area type="monotone" dataKey="wl" stroke={C.primary} strokeWidth={2} fill="url(#spk)" dot={false} name="wl" activeDot={{r:5,fill:C.primary,stroke:'#0a1628',strokeWidth:2}}/>
          </AreaChart>
        </ResponsiveContainer>
        <div className="spark-legend">
          <span className="spark-legend-item"><span className="spark-line-solid"/> Water Level (m)</span>
          <span className="spark-legend-item"><span className="spark-ref-line" style={{borderColor:'#22c55e'}}/> LOW</span>
          <span className="spark-legend-item"><span className="spark-ref-line" style={{borderColor:'#06b6d4'}}/> MEDIUM</span>
          <span className="spark-legend-item"><span className="spark-ref-line" style={{borderColor:'#f59e0b'}}/> HIGH</span>
          <span className="spark-legend-item"><span className="spark-ref-line" style={{borderColor:'#ef4444'}}/> CRITICAL</span>
        </div>
      </div>

      {/* ── Bento Grid ── */}
      <div className="bento">
        {/* Cell 1: Vertical bar chart */}
        <div className="bento-cell bc-bars">
          <h3 className="bc-title">Flow Pulses</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={barData} barCategoryGap="20%">
              <XAxis dataKey="t" tick={{fill:'#5a7a9b',fontSize:10}} axisLine={false} tickLine={false}/>
              <YAxis hide/>
              <Tooltip contentStyle={{background:'#142338',border:'1px solid #1a3350',borderRadius:8,color:'#ccc',fontSize:12}} />
              <Bar dataKey="flow" radius={[4,4,0,0]}>
                {barData.map((d,i) => (
                  <Cell key={i} fill={d.risk > 2 ? C.red : d.risk > 1 ? C.primary : C.green} fillOpacity={0.75}/>
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Cell 2: Radar chart — sensor readings */}
        <div className="bento-cell bc-tree">
          <h3 className="bc-title">Sensor Readings</h3>
          <ResponsiveContainer width="100%" height={180}>
            <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
              <PolarGrid stroke="#1a3350" />
              <PolarAngleAxis dataKey="sensor" tick={{fill:'#5a7a9b',fontSize:10}} />
              <PolarRadiusAxis tick={false} axisLine={false} domain={[0,100]} />
              <Radar name="Reading" dataKey="value" stroke={C.primary} fill={C.primary} fillOpacity={0.25} strokeWidth={2} />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        {/* Cell 3: Radial gauge */}
        <div className="bento-cell bc-gauge">
          <h3 className="bc-title">Resilience Score</h3>
          <div className="gauge-wrap">
            <ResponsiveContainer width={160} height={100}>
              <RadialBarChart cx="50%" cy="100%" innerRadius="70%" outerRadius="100%" barSize={12} data={gaugeData} startAngle={180} endAngle={0}>
                <RadialBar background={{fill:'#1a3350'}} dataKey="value" cornerRadius={8}/>
              </RadialBarChart>
            </ResponsiveContainer>
            <div className="gauge-num" style={{color:gaugeData[0].fill}}>{resilience}</div>
          </div>
          <div className="gauge-sub">
            <span>⚡ {highWaterEvents} high water</span>
            <span>🌊 {floodWarnings} warnings</span>
            <span>🔴 {flashFloods} flash floods</span>
          </div>
        </div>

        {/* Cell 4: Alert severity breakdown */}
        <div className="bento-cell bc-sev">
          <h3 className="bc-title">Severity Breakdown</h3>
          <div className="sev-bars">
            {[
              {k:'CRITICAL', c:'#dc2626', v:alertCounts.CRITICAL},
              {k:'HIGH', c:'#38bdf8', v:alertCounts.HIGH},
              {k:'MEDIUM', c:'#06b6d4', v:alertCounts.MEDIUM},
              {k:'LOW', c:'#22c55e', v:alertCounts.LOW},
            ].map(s => (
              <div className="sev-row" key={s.k}>
                <span className="sev-dot" style={{background:s.c}}/>
                <span className="sev-k">{s.k}</span>
                <div className="sev-track">
                  <div className="sev-fill" style={{width:`${Math.min(100,(s.v/Math.max(1,notifications.length))*100)}%`,background:s.c}}/>
                </div>
                <span className="sev-v">{s.v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Cell 5: Live alert feed */}
        <div className="bento-cell bc-feed">
          <div className="feed-head">
            <h3 className="bc-title">Live Feed</h3>
            <a href="#/alerts" className="feed-link">All →</a>
          </div>
          <div className="feed-list">
            {recentAlerts.length === 0 ? <p className="feed-empty">No alerts yet</p> :
              recentAlerts.map((a,i) => (
                <div className="feed-item" key={a.alert_id||i}>
                  <span className="feed-sev" style={{background:
                    a.severity==='CRITICAL'?'#dc2626':a.severity==='HIGH'?'#38bdf8':a.severity==='MEDIUM'?'#06b6d4':'#22c55e'
                  }}/>
                  <div className="feed-body">
                    <span className="feed-type">{(a.type||'').replace(/_/g,' ')}</span>
                    <span className="feed-msg">{a.message?.substring(0,60)}</span>
                  </div>
                  <span className="feed-ago">{relTime(a.timestamp)}</span>
                </div>
              ))
            }
          </div>
        </div>
      </div>
    </div>
  );
};

function relTime(ts) {
  if(!ts) return '';
  const d = Math.floor((Date.now()-new Date(ts).getTime())/1000);
  if(d<60) return `${d}s`;
  if(d<3600) return `${Math.floor(d/60)}m`;
  return `${Math.floor(d/3600)}h`;
}

export default DashboardPage;
