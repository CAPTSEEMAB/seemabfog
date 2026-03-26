/**
 * Mock API Server for local dashboard development
 * Serves sample data for /api/* endpoints
 */

const http = require('http');
const url = require('url');

const PORT = 8000;

// Sample data
const sampleAggregates = [
  { timestamp: new Date(Date.now() - 60000).toISOString(), vehicle_count_sum: 120, avg_speed: 45.5, congestion_index: 2.64 },
  { timestamp: new Date(Date.now() - 50000).toISOString(), vehicle_count_sum: 95, avg_speed: 52.3, congestion_index: 1.82 },
  { timestamp: new Date(Date.now() - 40000).toISOString(), vehicle_count_sum: 150, avg_speed: 38.2, congestion_index: 3.93 },
  { timestamp: new Date(Date.now() - 30000).toISOString(), vehicle_count_sum: 80, avg_speed: 58.1, congestion_index: 1.38 },
  { timestamp: new Date(Date.now() - 20000).toISOString(), vehicle_count_sum: 110, avg_speed: 48.7, congestion_index: 2.26 },
  { timestamp: new Date(Date.now() - 10000).toISOString(), vehicle_count_sum: 130, avg_speed: 42.0, congestion_index: 3.10 },
];

const sampleEvents = [
  { timestamp: new Date(Date.now() - 5000).toISOString(), alertType: 'CONGESTION', severity: 'HIGH', description: 'Congestion index 3.10 exceeds threshold 2.0' },
  { timestamp: new Date(Date.now() - 15000).toISOString(), alertType: 'SPEEDING', severity: 'MEDIUM', description: 'Vehicle speed 92 km/h exceeds limit 80 km/h' },
  { timestamp: new Date(Date.now() - 25000).toISOString(), alertType: 'CONGESTION', severity: 'HIGH', description: 'Congestion index 3.93 exceeds threshold 2.0' },
];

const sampleKpis = {
  avg_daily_vehicles: 15420,
  peak_hour_congestion: 4.2,
  total_alerts_24h: 28,
  avg_speed_24h: 47.3,
};

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const path = parsedUrl.pathname;
  
  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  console.log(`${new Date().toISOString()} ${req.method} ${path}`);

  if (path === '/api/summary') {
    res.writeHead(200);
    res.end(JSON.stringify({
      junctionId: parsedUrl.query.junctionId || 'Junction-A',
      aggregates: sampleAggregates,
      events: sampleEvents,
      kpis: sampleKpis,
    }));
  } else if (path === '/api/aggregates') {
    res.writeHead(200);
    res.end(JSON.stringify({
      junctionId: parsedUrl.query.junctionId || 'Junction-A',
      aggregates: sampleAggregates,
      count: sampleAggregates.length,
    }));
  } else if (path === '/api/events') {
    res.writeHead(200);
    res.end(JSON.stringify({
      junctionId: parsedUrl.query.junctionId || 'Junction-A',
      events: sampleEvents,
      count: sampleEvents.length,
    }));
  } else if (path === '/api/kpis') {
    res.writeHead(200);
    res.end(JSON.stringify({
      junctionId: parsedUrl.query.junctionId || 'Junction-A',
      kpis: sampleKpis,
    }));
  } else if (path === '/health') {
    res.writeHead(200);
    res.end(JSON.stringify({ status: 'healthy' }));
  } else {
    res.writeHead(404);
    res.end(JSON.stringify({ error: 'Not found' }));
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Mock API server running on http://0.0.0.0:${PORT}`);
  console.log('Endpoints: /api/summary, /api/aggregates, /api/events, /api/kpis, /health');
});
