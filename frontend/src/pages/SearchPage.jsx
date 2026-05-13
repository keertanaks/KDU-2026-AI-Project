import { useState } from 'react';
import { searchAPI, authAPI } from '../services/api.js';
import SearchBar from '../components/SearchBar';
import ResultsList from '../components/ResultsList';

export default function SearchPage({ user, onLogout }) {
  const [searchData, setSearchData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

  const handleLogout = async () => {
    try {
      await authAPI.logout();
    } catch {
      // session already expired — proceed anyway
    }
    onLogout();
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex justify-between items-center">
        <span className="text-sm text-gray-500">
          Signed in as <span className="font-medium text-gray-700">{user?.username}</span>
          {searchData?.user_role && (
            <span className="ml-2 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
              {searchData.user_role.replace(/_/g, ' ')}
            </span>
          )}
        </span>
        <button
          onClick={handleLogout}
          className="text-sm text-red-600 hover:text-red-800 font-medium"
        >
          Sign Out
        </button>
      </header>

      <div className="container mx-auto p-6 max-w-4xl">
        <h1 className="text-3xl font-bold mb-6">Healthcare Semantic Search</h1>
        <SearchBar onSearch={handleSearch} />

        {loading && <p className="text-gray-500 mt-4">Searching…</p>}

        {error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
            {error}
          </div>
        )}

        {searchData && !loading && (
          <div className="mt-6 space-y-6">
            {/* Latency badge */}
            <div className="flex items-center gap-2 text-xs text-gray-400">
              {searchData.search_latency_ms > 0 ? (
                <span>
                  Search: {searchData.search_latency_ms}ms
                  {searchData.answer_latency_ms > 0 && (
                    <> · Answer: {searchData.answer_latency_ms}ms</>
                  )}
                  {' '}· Total: {searchData.latency_ms}ms
                </span>
              ) : (
                <span>{searchData.latency_ms}ms</span>
              )}
              {searchData.sources?.length > 0 && (
                <span>· {searchData.sources.length} source{searchData.sources.length !== 1 ? 's' : ''}</span>
              )}
            </div>

            {/* Generated answer */}
            {searchData.answer_generation_status === 'success' && searchData.generated_answer && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h2 className="text-sm font-semibold text-blue-800 mb-2">Generated Answer</h2>
                <p className="text-gray-800 text-sm whitespace-pre-wrap">{searchData.generated_answer}</p>
                {searchData.sources?.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-blue-100">
                    <span className="text-xs text-blue-600 font-medium">Sources: </span>
                    <span className="text-xs text-blue-500">{searchData.sources.join(', ')}</span>
                  </div>
                )}
              </div>
            )}

            {searchData.answer_generation_status === 'skipped' && (
              <div className="bg-yellow-50 border border-yellow-200 rounded text-yellow-700 text-sm px-4 py-2">
                Answer generation unavailable. Showing retrieved chunks only.
              </div>
            )}

            {searchData.answer_generation_status === 'failed' && (
              <div className="bg-orange-50 border border-orange-200 rounded text-orange-700 text-sm px-4 py-2">
                Answer generation failed. Showing retrieved chunks only.
              </div>
            )}

            {/* Retrieved chunks */}
            <ResultsList results={searchData.masked_chunks || []} />
          </div>
        )}
      </div>
    </div>
  );
}
