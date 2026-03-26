import React, { useState, useEffect, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, AreaChart, Area, BarChart, Bar } from 'recharts';
import './Dashboard.css';

// ─── Configuration (from environment or defaults) ───
const FOG_NODES = {
  'Junction-A': process.env.REACT_APP_FOG_A,
  'Junction-B': process.env.REACT_APP_FOG_B,
};
const CLOUD_API = process.env.REACT_APP_API_ENDPOINT;
const POLL_INTERVAL_MS = parseInt(process.env.REACT_APP_POLL_INTERVAL_MS || '5000', 10);
const MAX_HISTORY_POINTS = 60;

// ─── Theme Colors ───
const COLORS = {
  green: '#22c55e',
  blue: '#3b82f6',
  darkBlue: '#2563eb',
  yellow: '#eab308',
  red: '#ef4444',
  orange: '#f59e0b',
  darkOrange: '#d97706',
  purple: '#a855f7',
};

const SEVERITY_COLORS = {
  HIGH: COLORS.red,
  MEDIUM: COLORS.orange,
  LOW: COLORS.blue,
};

const Dashboard = () => {
  const [junctionId, setJunctionId] = useState('Junction-A');
  const [activeTab, setActiveTab] = useState('fog');   // 'fog' | 'cloud'
  
  // Fog-layer state
  const [fogStatus, setFogStatus] = useState(null);
  const [metricsHistory, setMetricsHistory] = useState([]);

  // Cloud-layer state
  const [cloudHealth, setCloudHealth] = useState(null);
  const [cloudSummary, setCloudSummary] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // ─── Fog Node Polling ───
  const fetchFogStatus = useCallback(async () => {
    try {
      const endpoint = FOG_NODES[junctionId];
      const response = await fetch(`${endpoint}/status`);
      if (response.ok) {
        const data = await response.json();
        setFogStatus(data);
        setMetricsHistory(prev => {
          const newPoint = {
            time: new Date().toLocaleTimeString(),
            timestamp: Date.now(),
            incoming_eps: data.rates_10s?.incoming_eps || 0,
            outgoing_mps: data.rates_10s?.outgoing_mps || 0,
            reduction_pct: data.rates_10s?.reduction_pct || 0,
            spool_pending: data.spool?.pending_count || 0,
            incoming_total: data.counters?.incoming_total || 0,
            outgoing_total: data.counters?.outgoing_total || 0,
            alerts_total: data.counters?.alerts_total || 0,
          };
          return [...prev, newPoint].slice(-MAX_HISTORY_POINTS);
        });
        setError('');
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      setError(`Fog node error: ${err.message}`);
    }
  }, [junctionId]);

  // ─── Cloud API Polling ───
  const fetchCloudData = useCallback(async () => {
    try {
      if (!CLOUD_API) {
        setCloudHealth(null);
        setCloudSummary(null);
        return;
      }

      const [healthRes, summaryRes] = await Promise.all([
        fetch(`${CLOUD_API}/health`),
        fetch(`${CLOUD_API}/summary?junctionId=${junctionId}&minutes=10`),
      ]);
      if (healthRes.ok) setCloudHealth(await healthRes.json());
      else setCloudHealth(null);
      if (summaryRes.ok) setCloudSummary(await summaryRes.json());
      else setCloudSummary(null);
    } catch (err) {
      // Cloud may not be ready yet — don't override fog errors
      if (!error) setError(`Cloud API: ${err.message}`);
    }
  }, [junctionId, error]);

  // ─── Effect: poll both layers ───
  useEffect(() => {
    setMetricsHistory([]);
    setCloudSummary(null);

    const poll = async () => {
      setLoading(true);
      await fetchFogStatus();
      await fetchCloudData();
      setLoading(false);
    };
    poll();

    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [junctionId, fetchFogStatus, fetchCloudData]);

  // ─── Helpers ───
  const getSqsHealthColor = (h) => (h === 'up' ? COLORS.green : COLORS.red);
  const getReductionColor = (pct) => {
    if (pct >= 90) return COLORS.green;
    if (pct >= 70) return COLORS.blue;
    if (pct >= 50) return COLORS.yellow;
    return COLORS.red;
  };
  const severityColor = (s) => SEVERITY_COLORS[s] || COLORS.blue;

  // ═══════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════
  return (
    <div className="dashboard">
      {/* ─── Header ─── */}
      <header className="header">
        <h1>🚦 Smart Traffic Analytics Platform</h1>
        <div className="controls">
          <label>Junction: </label>
          <select value={junctionId} onChange={(e) => setJunctionId(e.target.value)}>
            <option value="Junction-A">Junction-A (fog-a)</option>
            <option value="Junction-B">Junction-B (fog-b)</option>
          </select>

          <div className="tab-buttons">
            <button className={activeTab === 'fog' ? 'active' : ''} onClick={() => setActiveTab('fog')}>
              🌫️ Fog Layer
            </button>
            <button className={activeTab === 'cloud' ? 'active' : ''} onClick={() => setActiveTab('cloud')}>
              ☁️ Cloud Layer
            </button>
          </div>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {/* ─── Pipeline Health Bar ─── */}
      <div className="pipeline-bar">
        <div className={`pipeline-node ${fogStatus ? 'healthy' : 'unhealthy'}`}>
          📡 Sensors
        </div>
        <div className="pipeline-arrow">→</div>
        <div className={`pipeline-node ${fogStatus?.sqs_health === 'up' ? 'healthy' : 'unhealthy'}`}>
          🌫️ Fog ({fogStatus?.nodeId || '...'})
        </div>
        <div className="pipeline-arrow">→</div>
        <div className={`pipeline-node ${cloudHealth?.sqs === 'up' ? 'healthy' : 'unhealthy'}`}>
          📨 SQS
        </div>
        <div className="pipeline-arrow">→</div>
        <div className={`pipeline-node ${cloudHealth?.dynamodb === 'up' ? 'healthy' : 'unhealthy'}`}>
          ☁️ Consumer
        </div>
        <div className="pipeline-arrow">→</div>
        <div className={`pipeline-node ${cloudSummary ? 'healthy' : 'unhealthy'}`}>
          📊 DynamoDB
        </div>
      </div>

      {/* ════════════════════════════════════════════
           TAB: FOG LAYER
         ════════════════════════════════════════════ */}
      {activeTab === 'fog' && fogStatus && (
        <>
          <div className="metrics-grid">
            <div className="metric-card">
              <div className="metric-label">SQS Health</div>
              <div className="metric-value" style={{ color: getSqsHealthColor(fogStatus.sqs_health) }}>
                {fogStatus.sqs_health?.toUpperCase() || 'N/A'}
              </div>
              <div className="metric-unit">connection status</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Incoming Rate</div>
              <div className="metric-value">{(fogStatus.rates_10s?.incoming_eps || 0).toFixed(1)}</div>
              <div className="metric-unit">events/sec</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Outgoing Rate</div>
              <div className="metric-value">{(fogStatus.rates_10s?.outgoing_mps || 0).toFixed(2)}</div>
              <div className="metric-unit">msgs/sec</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Bandwidth Reduction</div>
              <div className="metric-value" style={{ color: getReductionColor(fogStatus.rates_10s?.reduction_pct || 0) }}>
                {(fogStatus.rates_10s?.reduction_pct || 0).toFixed(1)}%
              </div>
              <div className="metric-unit">fog efficiency</div>
            </div>
          </div>

          <div className="metrics-grid">
            <div className="metric-card">
              <div className="metric-label">Spool Pending</div>
              <div className={`metric-value ${(fogStatus.spool?.pending_count || 0) > 0 ? 'high' : ''}`}>
                {fogStatus.spool?.pending_count || 0}
              </div>
              <div className="metric-unit">messages queued</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Spool Size</div>
              <div className="metric-value">{((fogStatus.spool?.bytes || 0) / 1024).toFixed(1)} KB</div>
              <div className="metric-unit">disk usage</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Total Ingested</div>
              <div className="metric-value">{(fogStatus.counters?.incoming_total || 0).toLocaleString()}</div>
              <div className="metric-unit">events since start</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Total Dispatched</div>
              <div className="metric-value">{(fogStatus.counters?.outgoing_total || 0).toLocaleString()}</div>
              <div className="metric-unit">SQS messages</div>
            </div>
          </div>

          <div className="charts-container">
            <div className="chart">
              <h3>Incoming Events Rate (live)</h3>
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={metricsHistory}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Area type="monotone" dataKey="incoming_eps" fill={COLORS.blue} stroke={COLORS.darkBlue} name="events/sec" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="chart">
              <h3>Bandwidth Reduction % (live)</h3>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={metricsHistory}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="reduction_pct" stroke={COLORS.green} strokeWidth={2} dot={false} name="reduction %" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="chart">
              <h3>Spool Queue Depth (live)</h3>
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={metricsHistory}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Area type="monotone" dataKey="spool_pending" fill={COLORS.orange} stroke={COLORS.darkOrange} name="pending" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="kpi-section">
            <h3>Fog Node Status</h3>
            <div className="kpi-grid">
              <div className="kpi-item">
                <span className="kpi-label">Node ID:</span>
                <span className="kpi-value">{fogStatus.nodeId || 'N/A'}</span>
              </div>
              <div className="kpi-item">
                <span className="kpi-label">Alerts Generated:</span>
                <span className="kpi-value">{fogStatus.counters?.alerts_total || 0}</span>
              </div>
              <div className="kpi-item">
                <span className="kpi-label">Duplicates Dropped:</span>
                <span className="kpi-value">{fogStatus.counters?.duplicates_total || 0}</span>
              </div>
              <div className="kpi-item">
                <span className="kpi-label">Last Flush:</span>
                <span className="kpi-value">
                  {fogStatus.last_flush_time
                    ? new Date(fogStatus.last_flush_time).toLocaleTimeString()
                    : 'Never'}
                </span>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ════════════════════════════════════════════
           TAB: CLOUD LAYER
         ════════════════════════════════════════════ */}
      {activeTab === 'cloud' && (
        <>
          {/* Cloud Consumer Stats */}
          {cloudHealth && (
            <div className="metrics-grid">
              <div className="metric-card">
                <div className="metric-label">Aggregates Stored</div>
                <div className="metric-value">{cloudHealth.consumer?.aggregates_processed || 0}</div>
                <div className="metric-unit">in DynamoDB</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Events Stored</div>
                <div className="metric-value">{cloudHealth.consumer?.events_processed || 0}</div>
                <div className="metric-unit">in DynamoDB</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">KPIs Computed</div>
                <div className="metric-value">{cloudHealth.consumer?.kpis_computed || 0}</div>
                <div className="metric-unit">safety scores</div>
              </div>
              <div className="metric-card">
                <div className={`metric-value ${(cloudHealth.consumer?.errors || 0) > 0 ? 'high' : ''}`}>
                  {cloudHealth.consumer?.errors || 0}
                </div>
                <div className="metric-label">Consumer Errors</div>
                <div className="metric-unit">processing errors</div>
              </div>
            </div>
          )}

          {/* KPI Cards */}
          {cloudSummary?.kpis && Object.keys(cloudSummary.kpis).length > 0 && (
            <div className="kpi-section">
              <h3>🎯 Junction Safety KPIs (last 1 hour)</h3>
              <div className="metrics-grid">
                <div className="metric-card highlight">
                  <div className="metric-label">Safety Score</div>
                  <div className="metric-value" style={{
                    color: (cloudSummary.kpis.safety_score || 0) >= 70 ? COLORS.green :
                           (cloudSummary.kpis.safety_score || 0) >= 40 ? COLORS.yellow : COLORS.red,
                    fontSize: '2.5rem'
                  }}>
                    {cloudSummary.kpis.safety_score ?? '—'}/100
                  </div>
                  <div className="metric-unit">computed from events</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Speeding Events</div>
                  <div className="metric-value">{cloudSummary.kpis.speeding_events_1h || 0}</div>
                  <div className="metric-unit">last hour</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Congestion Events</div>
                  <div className="metric-value">{cloudSummary.kpis.congestion_events_1h || 0}</div>
                  <div className="metric-unit">last hour</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Incident Events</div>
                  <div className="metric-value">{cloudSummary.kpis.incident_events_1h || 0}</div>
                  <div className="metric-unit">last hour</div>
                </div>
              </div>
            </div>
          )}

          {/* Aggregates Chart (from DynamoDB) */}
          {cloudSummary?.aggregates?.length > 0 && (
            <div className="charts-container">
              <div className="chart">
                <h3>Congestion Index (from DynamoDB)</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <LineChart data={cloudSummary.aggregates.slice(-30)}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="SK" tickFormatter={(v) => v ? new Date(v).toLocaleTimeString() : ''} />
                    <YAxis domain={[0, 'auto']} />
                    <Tooltip labelFormatter={(v) => v ? new Date(v).toLocaleString() : ''} />
                    <Legend />
                    <Line type="monotone" dataKey="congestion_index" stroke={COLORS.red} strokeWidth={2} dot={false} name="congestion" />
                    <Line type="monotone" dataKey="avg_speed" stroke={COLORS.blue} strokeWidth={2} dot={false} name="avg speed (km/h)" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="chart">
                <h3>Vehicle Count & Pollution (from DynamoDB)</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={cloudSummary.aggregates.slice(-20)}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="SK" tickFormatter={(v) => v ? new Date(v).toLocaleTimeString() : ''} />
                    <YAxis />
                    <Tooltip labelFormatter={(v) => v ? new Date(v).toLocaleString() : ''} />
                    <Legend />
                    <Bar dataKey="vehicle_count_sum" fill={COLORS.blue} name="vehicle count" />
                    <Bar dataKey="avg_pollution" fill={COLORS.purple} name="PM2.5 µg/m³" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Recent Events Table */}
          {cloudSummary?.events?.length > 0 && (
            <div className="kpi-section">
              <h3>🚨 Recent Alert Events (from DynamoDB)</h3>
              <table className="events-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Type</th>
                    <th>Severity</th>
                    <th>Value</th>
                    <th>Threshold</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {cloudSummary.events.slice(0, 10).map((evt, i) => (
                    <tr key={i}>
                      <td>{evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : '—'}</td>
                      <td><span className="badge">{evt.alertType}</span></td>
                      <td style={{ color: SEVERITY_COLORS[evt.severity] || COLORS.blue }}>{evt.severity}</td>
                      <td>{typeof evt.triggered_value === 'number' ? evt.triggered_value.toFixed(1) : evt.triggered_value}</td>
                      <td>{typeof evt.threshold === 'number' ? evt.threshold.toFixed(1) : evt.threshold}</td>
                      <td>{evt.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Empty state */}
          {(!cloudSummary || (!cloudSummary.aggregates?.length && !cloudSummary.events?.length)) && !cloudHealth && (
            <div className="empty-state">
              <p>⏳ Waiting for cloud data... The consumer is polling SQS and storing data in DynamoDB.</p>
              <p>Aggregates and events will appear here once the full pipeline is flowing.</p>
            </div>
          )}
        </>
      )}

      {/* ─── Footer ─── */}
      {loading && <div className="loading">Updating...</div>}
      <footer className="footer">
        <small>
          Fog: {FOG_NODES[junctionId]} • Cloud API: {CLOUD_API} • Polling every {POLL_INTERVAL_MS / 1000}s
          {cloudHealth?.consumer?.started_at && (
            <> • Consumer up since: {new Date(cloudHealth.consumer.started_at).toLocaleTimeString()}</>
          )}
        </small>
      </footer>
    </div>
  );
};

export default Dashboard;
