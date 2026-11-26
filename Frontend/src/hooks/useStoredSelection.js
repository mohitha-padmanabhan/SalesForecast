import {useCallback, useState} from 'react';

export function readSelection(key, fallback) {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key));
    if (saved === null || typeof saved !== typeof fallback) return fallback;
    if (typeof fallback !== 'object') return saved;
    if (Array.isArray(fallback)) return Array.isArray(saved) ? saved : fallback;
    return Object.fromEntries(Object.entries(fallback).map(([field, value]) => {
      const candidate = saved[field];
      const valid = Array.isArray(value) ? Array.isArray(candidate) : typeof candidate === typeof value;
      return [field, valid ? candidate : value];
    }));
  } catch { return fallback; }
}

export default function useStoredSelection(name, fallback) {
  const account = localStorage.getItem('user_email') || localStorage.getItem('userEmail') || 'anonymous';
  const key = `forecast-selections:${account}:${name}`;
  const [selection, setSelection] = useState(() => readSelection(key, fallback));
  const updateSelection = useCallback(update => {
    setSelection(previous => {
      const next = typeof update === 'function' ? update(previous) : update;
      try { sessionStorage.setItem(key, JSON.stringify(next)); } catch { /* In-memory selection still works. */ }
      return next;
    });
  }, [key]);
  return [selection, updateSelection];
}
