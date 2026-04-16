import { useState, useEffect, useCallback, useRef } from 'react';

const CLOUD_API = process.env.REACT_APP_API_ENDPOINT;
const POLL_MS = parseInt(process.env.REACT_APP_POLL_INTERVAL_MS || '5000', 10);
const MAX_HISTORY = 60;

export default function useFloodData() {
  const [stationId, setStationId] = useState('River-Station-A');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Fog
  const [fogStatusA, setFogStatusA] = useState(null);
  const [fogStatusB, setFogStatusB] = useState(null);
  const [metricsHistory, setMetricsHistory] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [unseenCount, setUnseenCount] = useState(0);

  // Cloud
  const [cloudHealth, setCloudHealth] = useState(null);
  const [cloudSummaryA, setCloudSummaryA] = useState(null);
  const [cloudSummaryB, setCloudSummaryB] = useState(null);

  const [loading, setLoading] = useState(false);
  const [fogOnline, setFogOnline] = useState(false);
  const [cloudConnected, setCloudConnected] = useState(false);

  const seenAlertIds = useRef(new Set());

  const fetchAll = useCallback(async () => {
    if (!CLOUD_API) return;
    setLoading(true);
    try {
      // Fetch everything from API Gateway Lambda in parallel
      const [healthRes, sumARes, sumBRes, fogARes, fogBRes, fogNotifsARes, fogNotifsBRes] = await Promise.all([
        fetch(`${CLOUD_API}/health`).catch(() => null),
        fetch(`${CLOUD_API}/summary?stationId=River-Station-A&minutes=10`).catch(() => null),
        fetch(`${CLOUD_API}/summary?stationId=River-Station-B&minutes=10`).catch(() => null),
        fetch(`${CLOUD_API}/fog-status?nodeId=fog-a`).catch(() => null),
        fetch(`${CLOUD_API}/fog-status?nodeId=fog-b`).catch(() => null),
        fetch(`${CLOUD_API}/fog-notifications?nodeId=fog-a&limit=50`).catch(() => null),
        fetch(`${CLOUD_API}/fog-notifications?nodeId=fog-b&limit=50`).catch(() => null),
      ]);

      // Cloud health
      if (healthRes?.ok) {
        setCloudHealth(await healthRes.json());
        setCloudConnected(true);
      } else {
        setCloudConnected(false);
      }

      // Cloud summaries
      if (sumARes?.ok) setCloudSummaryA(await sumARes.json());
      if (sumBRes?.ok) setCloudSummaryB(await sumBRes.json());

      // Fog status (from DynamoDB via Lambda)
      let fogA = null, fogB = null;
      if (fogARes?.ok) fogA = await fogARes.json();
      if (fogBRes?.ok) fogB = await fogBRes.json();
      setFogStatusA(fogA);
      setFogStatusB(fogB);
      setFogOnline(!!(fogA?.nodeId || fogB?.nodeId));

      // Fog notifications (from events table via Lambda)
      let notifsA = [], notifsB = [];
      if (fogNotifsARes?.ok) {
        const d = await fogNotifsARes.json();
        notifsA = d.notifications || [];
      }
      if (fogNotifsBRes?.ok) {
        const d = await fogNotifsBRes.json();
        notifsB = d.notifications || [];
      }
      const allNotifs = [...notifsA, ...notifsB]
        .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

      const newUnseen = allNotifs.filter(n => !seenAlertIds.current.has(n.alert_id || n.id));
      newUnseen.forEach(n => seenAlertIds.current.add(n.alert_id || n.id));
      if (newUnseen.length > 0) setUnseenCount(c => c + newUnseen.length);
      setNotifications(allNotifs);

      // Metrics history from selected station
      const activeFog = stationId === 'River-Station-A' ? fogA : fogB;
      if (activeFog) {
        setMetricsHistory(prev => {
          const point = {
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            ts: Date.now(),
            incoming_eps: activeFog.rates_10s?.incoming_eps || 0,
            outgoing_mps: activeFog.rates_10s?.outgoing_mps || 0,
            reduction_pct: activeFog.rates_10s?.reduction_pct || 0,
            spool_pending: activeFog.spool?.pending_count || 0,
            alerts_total: activeFog.counters?.alerts_total || 0,
          };
          return [...prev, point].slice(-MAX_HISTORY);
        });
      }
    } catch (e) {
      console.error('Poll error:', e);
    }
    setLoading(false);
    setLastUpdated(new Date());
  }, [stationId]);

  useEffect(() => {
    fetchAll();
    if (!autoRefresh) return;
    const iv = setInterval(fetchAll, POLL_MS);
    return () => clearInterval(iv);
  }, [fetchAll, autoRefresh]);

  const clearUnseen = () => setUnseenCount(0);

  return {
    stationId, setStationId,
    autoRefresh, setAutoRefresh,
    lastUpdated,
    fogStatusA, fogStatusB,
    metricsHistory,
    notifications, unseenCount, clearUnseen,
    cloudHealth, cloudSummaryA, cloudSummaryB,
    loading, fogOnline, cloudConnected,
    refresh: fetchAll,
  };
}
