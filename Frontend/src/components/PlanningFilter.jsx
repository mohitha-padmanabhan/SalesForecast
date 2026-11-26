import {useId} from 'react';
import './PlanningFilter.css';

export function ClearFilterButton({label, onClear, disabled}) {
  return <button type="button" className="filter-eraser" aria-label={`Clear ${label}`} title={`Clear ${label}`} disabled={disabled} onClick={onClear}>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m14 3 7 7-11 11H6l-5-5L14 3Z M6 11l7 7 M10 21h12"/></svg>
    <span>Clear</span>
  </button>;
}

export default function PlanningFilter({label, value, options = [], onChange, required, disabled, clearValue = 'All', allValue = 'All'}) {
  const id = useId();
  const values = [...new Set([...(required ? [] : [allValue]), ...options, ...(value ? [value] : [])])];
  return <div className="filter-field">
    <div className="filter-heading"><label htmlFor={id}>{label}{required && <b> *</b>}</label><ClearFilterButton label={label} disabled={disabled || value === clearValue} onClear={() => onChange(clearValue)}/></div>
    <select id={id} value={value} onChange={event => onChange(event.target.value)} disabled={disabled}>
      {values.map(option => <option key={option} value={option}>{option}</option>)}
    </select>
  </div>;
}
