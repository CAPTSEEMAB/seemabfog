import React from 'react';
import { NavLink } from 'react-router-dom';
import './Sidebar.css';

const Sidebar = ({ fogOnline, cloudConnected, unseenAlerts }) => (
  <aside className="rail">
    <div className="rail-logo">
      <svg viewBox="0 0 32 32" fill="none">
        <rect width="32" height="32" rx="8" fill="url(#rl)"/>
        <path d="M16 8l-6 12h4l-2 6 8-10h-5l3-8z" fill="#fff" opacity=".9"/>
        <defs><linearGradient id="rl" x1="0" y1="0" x2="32" y2="32">
          <stop stopColor="#0ea5e9"/><stop offset="1" stopColor="#0c4a6e"/>
        </linearGradient></defs>
      </svg>
    </div>

    <nav className="rail-nav">
      <NavLink to="/" end className={({isActive})=>`rail-btn ${isActive?'on':''}`} title="Dashboard">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1"/>
        </svg>
      </NavLink>
      <NavLink to="/alerts" className={({isActive})=>`rail-btn ${isActive?'on':''}`} title="Alerts">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
        </svg>
        {unseenAlerts > 0 && <span className="rail-badge">{unseenAlerts > 9 ? '9+' : unseenAlerts}</span>}
      </NavLink>
      <NavLink to="/stations" className={({isActive})=>`rail-btn ${isActive?'on':''}`} title="Stations">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/>
        </svg>
      </NavLink>
    </nav>

    <div className="rail-status">
      <div className="status-dot" title={`Fog: ${fogOnline?'Online':'Offline'}`}>
        <svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="none" stroke={fogOnline?'#22c55e':'#ef4444'} strokeWidth="1.5"/><circle cx="6" cy="6" r="2.5" fill={fogOnline?'#22c55e':'#ef4444'}/></svg>
      </div>
      <div className="status-dot" title={`Cloud: ${cloudConnected?'Connected':'Offline'}`}>
        <svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="none" stroke={cloudConnected?'#22c55e':'#ef4444'} strokeWidth="1.5"/><circle cx="6" cy="6" r="2.5" fill={cloudConnected?'#22c55e':'#ef4444'}/></svg>
      </div>
    </div>
  </aside>
);

export default Sidebar;
