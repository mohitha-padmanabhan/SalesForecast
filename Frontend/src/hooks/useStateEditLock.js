import {useEffect, useRef, useState} from 'react';
import {acquireStateEdit, releaseStateEdit, fetchStateEditStatus, setEditLease} from '../api/forecastApi';

export default function useStateEditLock(state, saving = false) {
  const contextRef = useRef(null);
  const savingRef = useRef(saving);
  const refreshRef = useRef(null);
  savingRef.current = saving;
  const [status, setStatus] = useState({owner: null, blocked: false});
  const [heldState, setHeldState] = useState(null);
  const [message, setMessage] = useState('');
  const unrestricted = state === 'All';

  useEffect(() => {
    const context = {state, lease: crypto.randomUUID(), held: false, active: true, refreshing: false};
    contextRef.current = context;
    setHeldState(null);
    setStatus({owner: null, blocked: false});
    setMessage('');
    const refresh = async () => {
      if (!context.active || context.refreshing || savingRef.current) return;
      context.refreshing = true;
      const lease = context.lease;
      try {
        const renewing = context.held;
        const result = renewing
          ? await acquireStateEdit(state, lease)
          : await fetchStateEditStatus(state);
        if (renewing && (!context.active || !context.held || context.lease !== lease)) {
          await releaseStateEdit(state, lease);
          return;
        }
        if (!context.active || context.lease !== lease) return;
        if (renewing) {
          setHeldState(state);
          setStatus({owner: result.owner, blocked: false});
        } else setStatus(result);
        setMessage('');
      } catch (error) {
        if (!context.active || context.lease !== lease || savingRef.current) return;
        const code = error.response?.status;
        // A temporary failure does not prove the server lease was lost.
        // Disable editing until renewal succeeds, while retaining the lease to retry.
        if ([400, 401, 403, 409].includes(code)) context.held = false;
        setHeldState(null);
        setMessage(error.response?.data?.detail || 'Editing availability could not be checked. Retrying automatically.');
      } finally {
        context.refreshing = false;
      }
    };
    refreshRef.current = refresh;
    if (!unrestricted) refresh();
    const timer = unrestricted ? null : setInterval(refresh, 10000);
    const leave = () => {
      if (context.held) releaseStateEdit(state, context.lease, true).catch(() => {});
    };
    window.addEventListener('pagehide', leave);
    return () => {
      context.active = false;
      clearInterval(timer);
      window.removeEventListener('pagehide', leave);
      if (context.held) releaseStateEdit(state, context.lease, true).catch(() => {});
    };
  }, [state, unrestricted]);

  useEffect(() => {
    if (!saving && !unrestricted) refreshRef.current?.();
  }, [saving, unrestricted]);

  const ensureEdit = async () => {
    if (unrestricted) return true;
    const context = contextRef.current;
    if (!context?.active || context.state !== state) return false;
    const lease = context.lease;
    try {
      const result = await acquireStateEdit(state, lease);
      if (!context.active || context.lease !== lease) {
        await releaseStateEdit(state, lease);
        return false;
      }
      context.held = true;
      setEditLease(context.lease);
      setHeldState(state);
      setStatus({owner: result.owner, blocked: false});
      setMessage('');
      return true;
    } catch (error) {
      if (context.active) {
        context.held = false;
        setHeldState(null);
        const detail = error.response?.data?.detail || 'Unable to start editing this state.';
        setMessage(detail);
        alert(detail);
      }
      return false;
    }
  };

  const release = () => {
    const context = contextRef.current;
    if (!context) return;
    const lease = context.lease;
    const wasHeld = context.held;
    context.held = false;
    context.lease = crypto.randomUUID();
    setHeldState(null);
    if (wasHeld) releaseStateEdit(context.state, lease).catch(() => {});
  };

  return {
    canEdit: unrestricted || heldState === state,
    message: message || (status.blocked ? `${status.owner} is currently editing ${state}. You can view this state and edit after they finish.` : ''),
    ensureEdit,
    release
  };
}
