import axios from 'axios';

const API_BASE_URL =  import.meta.env.VITE_API_BASE_URL ||
                      'http://localhost:8000/api/v1';

const AUTH_BASE_URL = API_BASE_URL.replace(/\/api\/v1\/?$/, '');

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

let editLease = '';
export function setEditLease(lease) { editLease = lease; }
apiClient.interceptors.request.use(config => {
  if (editLease && !config.headers['X-Planning-Lease']) config.headers['X-Planning-Lease'] = editLease;
  return config;
});
export const fetchStateEditStatus = async state => (await apiClient.get('/state-locks/', {params: {state}})).data;
export const acquireStateEdit = async (state, lease) => (await apiClient.post('/state-locks/acquire', {state}, {headers: {'X-Planning-Lease': lease}})).data;
export const releaseStateEdit = (state, lease, keepalive = false) => fetch(`${API_BASE_URL}/state-locks/release`, {
  method: 'POST', credentials: 'include', keepalive,
  headers: {'Content-Type': 'application/json', 'X-Planning-Lease': lease},
  body: JSON.stringify({state})
});
export async function verifySession() {
  const response = await fetch('`${AUTH_BASE_URL}/auth/session', {credentials: 'include'});
  if (!response.ok) throw new Error('Please sign in again to edit forecasts.');
  return response.json();
}
export async function demoLogin(username, password) {
  const response = await fetch('`${AUTH_BASE_URL}/auth/demo-login', {
    method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username, password})
  });
  if (!response.ok) throw new Error('Invalid username or password');
  return response.json();
}
export async function endSession() {
  const response = await fetch('`${AUTH_BASE_URL}/auth/logout', {method: 'POST', credentials: 'include'});
  if (!response.ok) throw new Error('Sign out could not complete. Please try again.');
  clearForecastCache();
}

// Memory-only cache: bounded, shared across pages, never persisted in browser storage.
const responses = new Map();
const pending = new Map();
let cacheGeneration = 0;
export function clearForecastCache() {
  cacheGeneration += 1;
  responses.clear();
  pending.clear();
}
async function cachedRequest(key, ttl, request) {
  const cached = responses.get(key);
  if (cached && cached.expires > Date.now()) return structuredClone(cached.value);
  if (pending.has(key)) return structuredClone(await pending.get(key));
  const generation = cacheGeneration;
  const promise = request().then(response => {
    if (generation === cacheGeneration) {
      responses.delete(key);
      responses.set(key, {value: response.data, expires: Date.now() + ttl});
      while (responses.size > 24) responses.delete(responses.keys().next().value);
    }
    return response.data;
  });
  pending.set(key, promise);
  try { return structuredClone(await promise); }
  finally { if (pending.get(key) === promise) pending.delete(key); }
}
if (typeof window !== 'undefined') {
  window.addEventListener('storage', clearForecastCache);
  window.addEventListener('forecast-data-changed', clearForecastCache);
}
function invalidateAfterWrite() {
  clearForecastCache();
  // Notify other open tabs without storing forecast records.
  try { localStorage.setItem('forecastDataRevision', `${Date.now()}-${Math.random()}`); } catch { /* Memory cache is already cleared. */ }
}

// 1. Fetch dynamic filter dropdown options
export const fetchFilterOptions = async (params = {}) => {
  const queryParams = new URLSearchParams();
  
  if (params.state && params.state !== 'All') {
    queryParams.append('state', params.state);
  }
  if (params.chainStatus && params.chainStatus !== 'All') {
    queryParams.append('chain_status', params.chainStatus);
  }
  if (params.premiseType && params.premiseType !== 'All') {
    queryParams.append('premise_type', params.premiseType);
  }
  if (params.brandType && params.brandType !== 'All') {
    queryParams.append('brand', params.brandType);
  }
  if (params.dateVersion) {
    queryParams.append('date_version', params.dateVersion);
  }

  // Use apiClient instead of naked fetch
  const url = `/filters/?${queryParams.toString()}`;
  return cachedRequest(`filters:${url}`, 60000, () => apiClient.get(url));
};
// 2. Fetch grid data matching backend FilterParams schema
export const fetchGridData = async (filterPayload) => {
  const payload = {
    state: filterPayload.state || "All",
    chain_status: filterPayload.chain_status || filterPayload.chainStatus || "All",
    premise_type: filterPayload.premise_type || filterPayload.premiseType || "All",
    brand: filterPayload.brand || filterPayload.brandType || "All",
    top_chain: filterPayload.top_chain || filterPayload.topChain || "All",
    date_version: filterPayload.date_version || filterPayload.dateVersion || null
  };
  return cachedRequest(`grid:${JSON.stringify(payload)}`, 15000, () => apiClient.post('/forecast/query-base', payload));
};

// 3. Submit grid edits, append lock snapshot, and write changelog
export const submitForecastAdjustments = async (submitPayload) => {
  const response = await apiClient.post('/forecast/submit', submitPayload);
  invalidateAfterWrite();
  return response.data;
};

// 4. Fetch Item Master Data targeting localhost:8000
export const fetchItemMasterData = async (brand = 'All') => {
  return cachedRequest(`items:${brand}`, 60000, () => apiClient.get('/forecast/items', {params: {brand}}));
};

// 5. Fetch existing Demand Plan IDs based on modal filters
// forecastApi.js
export const fetchExistingDemandPlanIds = async (modalFilters = {}) => {
  // Always fresh: duplicate validation must not depend on a cached grid.
  const response = await apiClient.get('/forecast/existing-ids', {
    params: {brand: modalFilters.brand || 'All', state: modalFilters.state || 'All'}
  });
  return response.data;
};

export async function createNewPlanningItem(payload) {
  const response = await fetch(`${API_BASE_URL}/forecast/add-item`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-Planning-Lease': editLease,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      demand_plan_id: payload.demandPlanId,
      state: payload.state,
      brand: payload.brand,
      template_choice: payload.templateChoice,
      existing_demand_plan_id: payload.existingDemandPlanId || null,
      date_version: payload.dateVersion,
      edit_scope: payload.editScope,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to create new planning item.');
  }

  const result = await response.json();
  invalidateAfterWrite();
  return result;
}