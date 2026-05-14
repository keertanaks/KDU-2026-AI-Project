import MaskingIndicator from './MaskingIndicator';

export default function ResultsList({ results }) {
  if (!results || results.length === 0) return null;

  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Retrieved Chunks ({results.length})
      </h2>
      <div className="space-y-3">
        {results.map((result, index) => (
          <article key={index} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-300 hover:shadow">
            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <span className="max-w-full truncate rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-600">
                {result.doc_id || '-'}
              </span>
              <span className="w-fit rounded-full border border-slate-200 px-2 py-1 text-xs font-medium text-slate-500">
                score {result.score != null ? result.score.toFixed(3) : '-'}
              </span>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{result.text}</p>
            <MaskingIndicator text={result.text} />
          </article>
        ))}
      </div>
    </section>
  );
}
