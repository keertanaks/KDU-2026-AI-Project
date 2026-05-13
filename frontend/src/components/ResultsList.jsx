import MaskingIndicator from './MaskingIndicator';

export default function ResultsList({ results }) {
  if (!results || results.length === 0) return null;

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-600 mb-3">
        Retrieved Chunks ({results.length})
      </h2>
      <div className="space-y-4">
        {results.map((result, index) => (
          <div key={index} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs text-gray-500 font-mono">
                {result.doc_id || '—'}
              </span>
              <span className="text-xs text-gray-400">
                score {result.score != null ? result.score.toFixed(3) : '—'}
              </span>
            </div>
            <p className="text-gray-800 text-sm">{result.text}</p>
            <MaskingIndicator text={result.text} />
          </div>
        ))}
      </div>
    </div>
  );
}
