export default function MaskingIndicator({ text }) {
  if (!text || !text.includes('_REDACTED>')) return null;
  return (
    <span className="inline-block mt-2 text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded">
      PHI masked
    </span>
  );
}
