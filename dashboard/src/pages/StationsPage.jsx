import React from 'react';
import {
  AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip, Legend,
} from 'recharts';
import './StationsPage.css';

const META = {
  A: { name:'River Station Alpha', river:'Indus North Branch', loc:'Upstream Valley',
       coords:'33.6844°N, 73.0479°E', elev:'520m', risk:'High', riskClr:'#ef4444',
       catchment:'2,450 km²', rainfall:'1,200 mm', bankCap:'5.2 m' },
  B: { name:'River Station Beta', river:'Indus South Fork', loc:'Lowland Delta',
       coords:'31.5204°N, 74.3587°E', elev:'210m', risk:'Moderate', riskClr:'#06b6d4',
       catchment:'3,800 km²', rainfall:'900 mm', bankCap:'4.8 m' },
};

const StationsPage = ({ fogStatusA, fogStatusB, metricsHistory, cloudSummaryA, cloudSummaryB, autoRefresh, setAutoRefresh, refresh }) => {
  const rows = [
    { label:'Status', a: fogStatusA ? '🟢 Online' : '🔴 Offline', b: fogStatusB ? '🟢 Online' : '🔴 Offline' },
    { label:'Station', a: META.A.name, b: META.B.name },
    { label:'River', a: META.A.river, b: META.B.river },
    { label:'Location', a: META.A.loc, b: META.B.loc },
    { label:'Coordinates', a: META.A.coords, b: META.B.coords, mono: true },
    { label:'Elevation', a: META.A.elev, b: META.B.elev },
    { label:'Risk Zone', a: META.A.risk, b: META.B.risk, colorA: META.A.riskClr, colorB: META.B.riskClr },
    { label:'Catchment', a: META.A.catchment, b: META.B.catchment },
    { label:'Avg Rainfall', a: META.A.rainfall, b: META.B.rainfall },
    { label:'Bank Capacity', a: META.A.bankCap, b: META.B.bankCap },
    { label:'Events/sec', a: fogStatusA ? (fogStatusA.rates_10s?.incoming_eps||0).toFixed(1) : '—', b: fogStatusB ? (fogStatusB.rates_10s?.incoming_eps||0).toFixed(1) : '—' },
    { label:'Bandwidth Reduction', a: fogStatusA ? `${(fogStatusA.rates_10s?.reduction_pct||0).toFixed(0)}%` : '—', b: fogStatusB ? `${(fogStatusB.rates_10s?.reduction_pct||0).toFixed(0)}%` : '—' },
    { label:'Spool Pending', a: fogStatusA?.spool?.pending_count ?? '—', b: fogStatusB?.spool?.pending_count ?? '—' },
    { label:'Water Level', a: fmtAgg(cloudSummaryA, 'max_water_level', 'm'), b: fmtAgg(cloudSummaryB, 'max_water_level', 'm') },
    { label:'Flow Rate', a: fmtAgg(cloudSummaryA, 'avg_flow_rate', ' m³/s'), b: fmtAgg(cloudSummaryB, 'avg_flow_rate', ' m³/s') },
    { label:'Flood Risk', a: fmtAgg(cloudSummaryA, 'flood_risk_index', ''), b: fmtAgg(cloudSummaryB, 'flood_risk_index', ''),
      colorA: riskClr(cloudSummaryA), colorB: riskClr(cloudSummaryB) },
  ];

  return (
    <div className="sp">
      <header className="sp-top">
        <h1 className="sp-h1">Station Comparison</h1>
        <div className="sp-actions">
          <label className="dp-toggle">
            <input type="checkbox" checked={autoRefresh} onChange={()=>setAutoRefresh(!autoRefresh)} />
            Live
          </label>
          <button className="dp-refresh" onClick={refresh}>↻</button>
        </div>
      </header>

      {/* Comparison Table */}
      <div className="comp-table-wrap">
        <table className="comp-table">
          <thead>
            <tr>
              <th className="ct-label-col"></th>
              <th className="ct-station-col">
                <span className="ct-dot" style={{background: fogStatusA ? '#22c55e' : '#ef4444'}}/>
                Station A
              </th>
              <th className="ct-station-col">
                <span className="ct-dot" style={{background: fogStatusB ? '#22c55e' : '#ef4444'}}/>
                Station B
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r,i) => (
              <tr key={i} className={i%2===0 ? 'ct-even' : ''}>
                <td className="ct-label">{r.label}</td>
                <td className="ct-val" style={r.colorA?{color:r.colorA}:r.mono?{fontFamily:'monospace',fontSize:11}:{}}>
                  {r.a}
                </td>
                <td className="ct-val" style={r.colorB?{color:r.colorB}:r.mono?{fontFamily:'monospace',fontSize:11}:{}}>
                  {r.b}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Live Ingestion Chart */}
      <div className="sp-chart">
        <h3 className="sp-chart-title">Fog Node Ingestion Rate</h3>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={metricsHistory}>
            <defs>
              <linearGradient id="epsG" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#0ea5e9" stopOpacity={0.3}/>
                <stop offset="100%" stopColor="#0ea5e9" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <XAxis dataKey="time" tick={{fill:'#555',fontSize:10}} axisLine={false} tickLine={false}/>
            <YAxis tick={{fill:'#555',fontSize:10}} axisLine={false} tickLine={false}/>
            <Tooltip contentStyle={{background:'#142338',border:'1px solid #1a3350',borderRadius:8,color:'#ccc',fontSize:11}} />
            <Legend wrapperStyle={{fontSize:11,color:'#666'}}/>
            <Area type="monotone" dataKey="incoming_eps" fill="url(#epsG)" stroke="#0ea5e9" strokeWidth={2} name="Events/sec" dot={false}/>
            <Area type="monotone" dataKey="alerts_total" fill="none" stroke="#ef4444" strokeWidth={1} strokeDasharray="4 3" name="Alerts (cum)" dot={false}/>
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

function fmtAgg(summary, key, unit) {
  const agg = summary?.aggregates;
  if (!agg?.length) return '—';
  const v = agg[agg.length-1][key];
  return v !== undefined ? `${Number(v).toFixed(1)}${unit}` : '—';
}
function riskClr(summary) {
  const agg = summary?.aggregates;
  if (!agg?.length) return undefined;
  const v = agg[agg.length-1].flood_risk_index || 0;
  return v > 2 ? '#ef4444' : v > 1 ? '#0ea5e9' : '#22c55e';
}

export default StationsPage;
