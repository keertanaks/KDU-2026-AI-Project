export default function MaskingIndicator({ text }) {
  if (!text || !text.includes('_REDACTED>')) return null;
  return (
    <span className="mt-3 inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800">
      PHI masked
    </span>
  );
}
