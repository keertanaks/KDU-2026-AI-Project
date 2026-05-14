import { useState } from 'react';
import { searchAPI, authAPI } from '../services/api.js';
import AuditDashboard from '../components/AuditDashboard';

export default function AdminDashboard({ user, onLogout }) {
  const [uploadError, setUploadError] = useState('');
  const [uploadSuccess, setUploadSuccess] = useState('');
  const [uploadLoading, setUploadLoading] = useState(false);

  const handleUpload = async (file) => {
    if (!file) return;
    setUploadLoading(true);
    setUploadError('');
    setUploadSuccess('');
    try {
      await searchAPI.upload(file);
      setUploadSuccess('File uploaded successfully. It may take a moment before content is searchable.');
    } catch (err) {
      setUploadError('Upload failed. Please try again.');
      console.error('Upload failed', err);
    } finally {
      setUploadLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await authAPI.logout();
    } catch {
      // session already expired - proceed anyway
    }
    onLogout();
  };

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-4 py-3 shadow-sm backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-sm text-slate-500">
            Admin: <span className="font-semibold text-slate-800">{user?.username}</span>
          </span>
          <button
            onClick={handleLogout}
            className="w-fit rounded-lg border border-rose-200 px-3 py-1.5 text-sm font-semibold text-rose-700 transition hover:bg-rose-50 focus:outline-none focus:ring-4 focus:ring-rose-100"
          >
            Sign Out
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Admin Dashboard</h1>
          </div>
        </div>

        <section className="mb-5 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Upload Documents</h2>
              <p className="mt-1 text-sm text-slate-500">
                Add new PDFs for ingestion so they become searchable and available to the retrieval pipeline.
              </p>
            </div>
            {uploadLoading && (
              <span className="w-fit rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                Uploading...
              </span>
            )}
          </div>
          <input
            type="file"
            accept="application/pdf"
            onChange={(event) => handleUpload(event.target.files?.[0])}
            disabled={uploadLoading}
            className="block w-full rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3 text-sm text-slate-700 shadow-sm transition file:mr-4 file:rounded-lg file:border-0 file:bg-slate-800 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-60"
          />
          {uploadError && (
            <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">
              {uploadError}
            </div>
          )}
          {uploadSuccess && (
            <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-700">
              {uploadSuccess}
            </div>
          )}
        </section>

        <AuditDashboard />
      </main>
    </div>
  );
}
