import { useState } from 'react';
import { searchAPI, authAPI } from '../services/api.js';
import SearchBar from '../components/SearchBar';
import ResultsList from '../components/ResultsList';
import AuditDashboard from '../components/AuditDashboard';

export default function SearchPage({ user, onLogout }) {
  const [searchData, setSearchData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [uploadSuccess, setUploadSuccess] = useState('');
  const [uploadLoading, setUploadLoading] = useState(false);

  const handleSearch = async (query) => {
    setLoading(true);
    setError('');
    try {
      const response = await searchAPI.search(query);
      setSearchData(response.data);
    } catch (err) {
      if (err.response?.status === 403) {
        setError('Administrator accounts cannot perform searches.');
      } else {
        setError('Search failed. Please try again.');
        console.error('Search failed', err);
      }
      setSearchData(null);
    } finally {
      setLoading(false);
    }
  };

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
            Signed in as <span className="font-semibold text-slate-800">{user?.username}</span>
            {searchData?.user_role && (
              <span className="ml-2 inline-flex rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700">
                {searchData.user_role.replace(/_/g, ' ')}
              </span>
            )}
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
        <div className="mb-6">
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Healthcare Semantic Search</h1>
        </div>

        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <SearchBar onSearch={handleSearch} />
        </section>

        <section className="mt-5 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
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

        {loading && (
          <div className="mt-5 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="h-4 w-36 animate-pulse rounded bg-slate-200" />
            <div className="mt-4 h-16 animate-pulse rounded bg-slate-100" />
          </div>
        )}

        {error && (
          <div className="mt-5 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">
            {error}
          </div>
        )}

        {searchData && !loading && (
          <div className="mt-5 space-y-5">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              {searchData.search_latency_ms > 0 ? (
                <>
                  <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 shadow-sm">Search: {searchData.search_latency_ms}ms</span>
                  {searchData.answer_latency_ms > 0 && (
                    <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 shadow-sm">Answer: {searchData.answer_latency_ms}ms</span>
                  )}
                  <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 shadow-sm">Total: {searchData.latency_ms}ms</span>
                </>
              ) : (
                <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 shadow-sm">{searchData.latency_ms}ms</span>
              )}
              {searchData.sources?.length > 0 && (
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 font-medium text-emerald-700">
                  {searchData.sources.length} source{searchData.sources.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>

            {searchData.answer_generation_status === 'success' && searchData.generated_answer && (
              <section className="rounded-lg border border-sky-200 bg-sky-50 p-5 shadow-sm">
                <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-sky-800">Generated Answer</h2>
                <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{searchData.generated_answer}</p>
                {searchData.sources?.length > 0 && (
                  <div className="mt-4 border-t border-sky-100 pt-3">
                    <span className="text-xs font-semibold text-sky-700">Sources: </span>
                    <span className="text-xs text-sky-700">{searchData.sources.join(', ')}</span>
                  </div>
                )}
              </section>
            )}

            {searchData.answer_generation_status === 'skipped' && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
                Answer generation unavailable. Showing retrieved chunks only.
              </div>
            )}

            {searchData.answer_generation_status === 'failed' && (
              <div className="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm font-medium text-orange-800">
                Answer generation failed. Showing retrieved chunks only.
              </div>
            )}

            <ResultsList results={searchData.masked_chunks || []} />
          </div>
        )}

        {user?.role === 'ADMINISTRATOR' && (
          <div className="mt-8">
            <AuditDashboard />
          </div>
        )}
      </main>
    </div>
  );
}
