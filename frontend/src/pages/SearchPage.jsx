import { useState } from 'react';
import { searchAPI, authAPI } from '../services/api.js';
import SearchBar from '../components/SearchBar';
import ResultsList from '../components/ResultsList';

export default function SearchPage({ user, onLogout }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  const handleSearch = async (query) => {
    setLoading(true);
    try {
      const response = await searchAPI.search(query);
      setResults(response.data.masked_results || []);
    } catch (error) {
      console.error('Search failed', error);
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
        </span>
        <button
          onClick={handleLogout}
          className="text-sm text-red-600 hover:text-red-800 font-medium"
        >
          Sign Out
        </button>
      </header>
      <div className="container mx-auto p-6">
        <h1 className="text-3xl font-bold mb-6">Healthcare Semantic Search</h1>
        <SearchBar onSearch={handleSearch} />
        {loading && <p className="text-gray-500">Loading…</p>}
        <ResultsList results={results} />
      </div>
    </div>
  );
}
