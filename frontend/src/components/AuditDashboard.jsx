import { useEffect, useState } from 'react';
import { auditAPI } from '../services/api.js';

export default function AuditDashboard() {
  const [auditEntries, setAuditEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const loadAuditLogs = async () => {
      setLoading(true);
      setError('');
      try {
        const response = await auditAPI.list();
        setAuditEntries(response.data);
      } catch (err) {
        setError('Unable to load audit logs.');
        console.error('Audit log fetch error', err);
      } finally {
        setLoading(false);
      }
    };

    loadAuditLogs();
  }, []);

  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Audit Dashboard</h2>
            <p className="mt-1 text-sm text-slate-500">Review recent query audit events and PHI-safe access patterns.</p>
          </div>
          <span className="w-fit rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
            {auditEntries.length} entries
          </span>
        </div>
      </div>

      {loading && (
        <div className="space-y-3 p-5">
          <div className="h-4 w-44 animate-pulse rounded bg-slate-200" />
          <div className="h-10 animate-pulse rounded bg-slate-100" />
          <div className="h-10 animate-pulse rounded bg-slate-100" />
        </div>
      )}

      {error && (
        <div className="m-5 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">
          {error}
        </div>
      )}

      {!loading && !error && auditEntries.length === 0 && (
        <div className="px-5 py-8 text-center text-sm text-slate-500">No audit log entries are available yet.</div>
      )}

      {!loading && !error && auditEntries.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm text-slate-600">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="whitespace-nowrap px-5 py-3 font-semibold">Timestamp</th>
                <th className="whitespace-nowrap px-5 py-3 font-semibold">User</th>
                <th className="whitespace-nowrap px-5 py-3 font-semibold">Role</th>
                <th className="whitespace-nowrap px-5 py-3 font-semibold">Query Hash</th>
                <th className="whitespace-nowrap px-5 py-3 font-semibold">Results</th>
                <th className="whitespace-nowrap px-5 py-3 font-semibold">Masking</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {auditEntries.map((entry) => (
                <tr key={entry.audit_id} className="transition hover:bg-slate-50">
                  <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">{new Date(entry.timestamp).toLocaleString()}</td>
                  <td className="max-w-48 truncate px-5 py-3 font-medium text-slate-700">{entry.user_id}</td>
                  <td className="whitespace-nowrap px-5 py-3 capitalize">{entry.role.replace(/_/g, ' ')}</td>
                  <td className="max-w-64 truncate px-5 py-3 font-mono text-xs text-slate-600">{entry.query_hash}</td>
                  <td className="px-5 py-3">
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">{entry.result_count}</span>
                  </td>
                  <td className="px-5 py-3">
                    <span className={entry.masking_applied ? 'rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800' : 'rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600'}>
                      {entry.masking_applied ? 'Yes' : 'No'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
