import { useState } from 'react';

export default function ForecastNumberInput({label, value, onChange}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  return (
    <input
      aria-label={label}
      type="number"
      step="0.01"
      min="0"
      value={editing ? draft : value}
      onFocus={() => { setDraft(String(value)); setEditing(true); }}
      onChange={event => {
        setDraft(event.target.value);
        onChange(event.target.value);
      }}
      onBlur={() => {
        if (draft === '') onChange(0);
        setEditing(false);
      }}
    />
  );
}
