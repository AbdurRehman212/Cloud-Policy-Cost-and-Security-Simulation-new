import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';
import { BellIcon } from '@heroicons/react/24/outline';

import apiClient, { createSocket } from '../../services/api';

const DOT = { critical: 'bg-red-500', high: 'bg-red-500', medium: 'bg-amber-500', low: 'bg-gray-400' };

/** In-app alerts filtered by the user's alert preferences (Settings → Alerts). */
const AlertBell = () => {
  const { currentOrganization } = useSelector((state) => state.organization);
  const prefsVersion = useSelector((state) => state.settings.data?.updated_at);
  const orgId = currentOrganization?.id;
  const [alerts, setAlerts] = useState([]);
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const ref = useRef(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    try {
      const response = await apiClient.get('/settings/alerts', { params: { organization_id: orgId } });
      setAlerts(response.data.data.alerts);
      setFailed(false);
    } catch (_error) {
      setFailed(true);
    }
  }, [orgId]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 60000);
    return () => window.clearInterval(timer);
  }, [load, prefsVersion]);

  useEffect(() => {
    if (!orgId) return undefined;
    const socket = createSocket('/metrics');
    if (!socket) return undefined;
    const join = () => socket.emit('join_room', { org_id: orgId });
    socket.on('connect', join);
    socket.on('threats:update', load);
    if (socket.connected) join();
    return () => {
      socket.off('connect', join);
      socket.off('threats:update', load);
    };
  }, [orgId, load]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const escape = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  if (!orgId) return null;
  const count = alerts.length;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`Alerts: ${count} open`}
        data-tour="alerts"
        className="relative rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
      >
        <BellIcon className="h-6 w-6" aria-hidden="true" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2 dark:border-gray-700">
            <p className="text-sm font-semibold text-gray-900 dark:text-white">Alerts</p>
            <Link to="/settings" onClick={() => setOpen(false)} className="text-xs text-primary-600 hover:underline dark:text-primary-400">Preferences</Link>
          </div>
          <ul className="max-h-80 overflow-y-auto py-1">
            {failed && <li className="px-4 py-3 text-sm text-red-600 dark:text-red-400">Alerts could not be loaded.</li>}
            {!failed && count === 0 && <li className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">No alerts for your current preferences.</li>}
            {alerts.map((alert, index) => (
              <li key={`${alert.type}-${index}`}>
                <Link to={alert.link} onClick={() => setOpen(false)} className="flex gap-3 px-4 py-2 hover:bg-gray-50 dark:hover:bg-gray-700/50">
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[alert.severity] || DOT.low}`} aria-hidden="true" />
                  <span>
                    <span className="block text-sm text-gray-900 dark:text-white">{alert.title}</span>
                    {alert.detail && <span className="block text-xs text-gray-500 dark:text-gray-400">{alert.detail}</span>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default AlertBell;
