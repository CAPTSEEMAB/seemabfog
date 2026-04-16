import React, { useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import './AlertsPage.css';

const SEV = {
  CRITICAL: { color:'#dc2626', bg:'rgba(220,38,38,0.1)' },
  HIGH:     { color:'#38bdf8', bg:'rgba(56,189,248,0.1)' },
  MEDIUM:   { color:'#06b6d4', bg:'rgba(6,182,212,0.1)' },
  LOW:      { color:'#22c55e', bg:'rgba(34,197,94,0.1)' },
};

const AlertsPage = ({ notifications, autoRefresh, setAutoRefresh, refresh }) => {
  const [filter, setFilter] = useState('ALL');

  const sorted = useMemo(() =>
    [...notifications].sort((a,b) => new Date(b.timestamp)-new Date(a.timestamp)),
    [notifications]
  );

  const filtered = filter === 'ALL' ? sorted : sorted.filter(a => a.severity === filter);

  const counts = useMemo(() => {
    const c = { CRITICAL:0, HIGH:0, MEDIUM:0, LOW:0 };
    notifications.forEach(n => { if(c[n.severity]!==undefined) c[n.severity]++; });
    return c;
  }, [notifications]);

  // Histogram: alerts per minute (last 10 minutes)
  const histogram = useMemo(() => {
    const now = Date.now();
    const bins = Array.from({length:10}, (_,i) => ({ min: i, count:0 }));
    notifications.forEach(n => {
      const ago = Math.floor((now - new Date(n.timestamp).getTime()) / 60000);
      if(ago >= 0 && ago < 10) bins[ago].count++;
    });
    return bins.reverse().map(b => ({ label:`-${b.min}m`, count: b.count }));
  }, [notifications]);

  return (
    <div className="ap">
      <header className="ap-top">
        <h1 className="ap-h1">Alert Stream</h1>
        <div className="ap-actions">
          <label className="dp-toggle">
            <input type="checkbox" checked={autoRefresh} onChange={()=>setAutoRefresh(!autoRefresh)} />
            Live
          </label>
          <button className="dp-refresh" onClick={refresh}>↻</button>
        </div>
      </header>

      <div className="ap-body">
        {/* Left: Stats panel */}
        <div className="ap-stats">
          {/* Severity counters */}
          <div className="ap-counters">
            {['ALL','CRITICAL','HIGH','MEDIUM','LOW'].map(k => (
              <button key={k} className={`ap-counter ${filter===k?'ap-active':''}`}
                style={k!=='ALL' ? { '--ac': SEV[k].color } : { '--ac': '#0ea5e9' }}
                onClick={() => setFilter(k)}>
                <span className="ac-num">{k==='ALL' ? notifications.length : counts[k]}</span>
                <span className="ac-label">{k}</span>
              </button>
            ))}
          </div>

          {/* Alert frequency histogram */}
          <div className="ap-histo">
            <h3 className="ap-sec-title">Alert Frequency (10 min)</h3>
            <ResponsiveContainer width="100%" height={120}>
              <BarChart data={histogram} barCategoryGap="15%">
                <XAxis dataKey="label" tick={{fill:'#555',fontSize:9}} axisLine={false} tickLine={false}/>
                <YAxis hide/>
                <Tooltip contentStyle={{background:'#142338',border:'1px solid #1a3350',borderRadius:8,color:'#ccc',fontSize:11}} />
                <Bar dataKey="count" radius={[3,3,0,0]}>
                  {histogram.map((d,i) => (
                    <Cell key={i} fill={d.count > 5 ? '#dc2626' : d.count > 2 ? '#0ea5e9' : '#1a3350'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Type breakdown */}
          <div className="ap-types">
            <h3 className="ap-sec-title">By Type</h3>
            {['HIGH_WATER','FLOOD_WARNING','FLASH_FLOOD'].map(t => {
              const c = notifications.filter(n=>n.type===t).length;
              return (
                <div className="type-row" key={t}>
                  <span className="type-name">{t.replace(/_/g,' ')}</span>
                  <div className="type-bar-track">
                    <div className="type-bar-fill" style={{width:`${Math.min(100,(c/Math.max(1,notifications.length))*100)}%`}}/>
                  </div>
                  <span className="type-count">{c}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Timeline */}
        <div className="ap-timeline">
          <div className="tl-line"/>
          {filtered.length === 0 ? (
            <div className="tl-empty">No alerts match this filter</div>
          ) : filtered.map((a,i) => {
            const s = SEV[a.severity] || SEV.LOW;
            return (
              <div className="tl-item" key={a.alert_id||i}>
                <div className="tl-dot" style={{background:s.color}}/>
                <div className="tl-card" style={{borderColor:s.color}}>
                  <div className="tl-head">
                    <span className="tl-type">{(a.type||'').replace(/_/g,' ')}</span>
                    <span className="tl-sev" style={{background:s.bg,color:s.color}}>{a.severity}</span>
                    <span className="tl-ago">{relTime(a.timestamp)}</span>
                  </div>
                  <p className="tl-msg">{a.message}</p>
                  <div className="tl-meta">
                    <span>📍 {a.station || '—'}</span>
                    {a.value !== undefined && <span>📊 {typeof a.value==='number'?a.value.toFixed(2):a.value}</span>}
                    {a.threshold !== undefined && <span>⚠️ threshold: {typeof a.threshold==='number'?a.threshold.toFixed(1):a.threshold}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

function relTime(ts) {
  if(!ts) return '';
  const d = Math.floor((Date.now()-new Date(ts).getTime())/1000);
  if(d<60) return `${d}s ago`;
  if(d<3600) return `${Math.floor(d/60)}m ago`;
  return `${Math.floor(d/3600)}h ago`;
}

export default AlertsPage;
