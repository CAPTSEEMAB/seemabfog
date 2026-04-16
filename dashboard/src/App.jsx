import React from 'react';
import { Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import DashboardPage from './pages/DashboardPage';
import AlertsPage from './pages/AlertsPage';
import StationsPage from './pages/StationsPage';
import useFloodData from './hooks/useFloodData';
import './App.css';

const App = () => {
  const data = useFloodData();

  return (
    <div className="app-layout">
      <Sidebar
        fogOnline={data.fogOnline}
        cloudConnected={data.cloudConnected}
        unseenAlerts={data.unseenCount}
        stationId={data.stationId}
      />
      <main className="main-content">
        <Routes>
          <Route path="/" element={
            <DashboardPage
              cloudHealth={data.cloudHealth}
              cloudSummaryA={data.cloudSummaryA}
              cloudSummaryB={data.cloudSummaryB}
              fogStatusA={data.fogStatusA}
              fogStatusB={data.fogStatusB}
              notifications={data.notifications}
              metricsHistory={data.metricsHistory}
              lastUpdated={data.lastUpdated}
              autoRefresh={data.autoRefresh}
              setAutoRefresh={data.setAutoRefresh}
              refresh={data.refresh}
            />
          } />
          <Route path="/alerts" element={
            <AlertsPage
              notifications={data.notifications}
              cloudSummaryA={data.cloudSummaryA}
              cloudSummaryB={data.cloudSummaryB}
              autoRefresh={data.autoRefresh}
              setAutoRefresh={data.setAutoRefresh}
              refresh={data.refresh}
            />
          } />
          <Route path="/stations" element={
            <StationsPage
              fogStatusA={data.fogStatusA}
              fogStatusB={data.fogStatusB}
              metricsHistory={data.metricsHistory}
              cloudSummaryA={data.cloudSummaryA}
              cloudSummaryB={data.cloudSummaryB}
              autoRefresh={data.autoRefresh}
              setAutoRefresh={data.setAutoRefresh}
              refresh={data.refresh}
            />
          } />
        </Routes>
      </main>
    </div>
  );
};

export default App;
