import { useState } from 'react';
import { captureMatrix, downloadMatrix } from '../utils/exportMatrix';
import './ExportMatrixButton.css';

export default function ExportMatrixButton({tableRef, disabled, title, filename, metadata}) {
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const handleExport = async () => {
    if (exporting || disabled) return;
    setError('');
    setExporting(true);
    try {
      const snapshot = captureMatrix(tableRef.current);
      await downloadMatrix(snapshot, {title, filename, metadata});
    } catch (err) {
      console.error('Matrix export failed:', err);
      setError('Excel export failed. Please try again.');
    } finally { setExporting(false); }
  };
  return <div className="matrix-export-control">
    <button type="button" className="matrix-export-button" onClick={handleExport} disabled={disabled || exporting} aria-busy={exporting}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></svg>
      {exporting ? 'Exporting…' : 'Export Excel'}
    </button>
    {error && <span className="matrix-export-error" role="alert">{error}</span>}
  </div>;
}
