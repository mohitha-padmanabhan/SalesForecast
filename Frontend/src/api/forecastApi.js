import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

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

  // Use apiClient instead of naked fetch
  const response = await apiClient.get(`/filters/?${queryParams.toString()}`);
  return response.data;
};
// 2. Fetch grid data matching backend FilterParams schema
export const fetchGridData = async (filterPayload) => {
  const response = await apiClient.post('/forecast/query-base', {
    state: filterPayload.state || "All",
    chain_status: filterPayload.chain_status || filterPayload.chainStatus || "All",
    premise_type: filterPayload.premise_type || filterPayload.premiseType || "All",
    brand: filterPayload.brand || filterPayload.brandType || "All",
    top_chain: filterPayload.top_chain || filterPayload.topChain || "All",
    date_version: filterPayload.date_version || filterPayload.dateVersion || null
  });
  return response.data;
};

// 3. Submit grid edits, append lock snapshot, and write changelog
export const submitForecastAdjustments = async (submitPayload) => {
  const response = await apiClient.post('/forecast/submit', submitPayload);
  return response.data;
};

// 4. Fetch Item Master Data 
export const fetchItemMasterData = async () => {
  const response = await apiClient.get('/forecast/items');
  return response.data;
};

// 5. Fetch existing Demand Plan IDs based on modal filters
// forecastApi.js
export const fetchExistingDemandPlanIds = async (modalFilters = {}) => {
  const response = await apiClient.post('/forecast/query-base', {
    brand: modalFilters.brand || "All",
    state: modalFilters.state || "All",
    date_version: "All" // Explicitly request all versions instead of letting the backend default to Latest
  });
  
  const items = response.data?.grid_data || [];
  return Array.from(
    new Set(items.map(i => i.planning_id).filter(Boolean))
  ).sort();
};

export async function createNewPlanningItem(payload) {
  const response = await fetch(`${API_BASE_URL}/forecast/add-item`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      demand_plan_id: payload.demandPlanId,
      state: payload.state,
      brand: payload.brand,
      template_choice: payload.templateChoice,
      existing_demand_plan_id: payload.existingDemandPlanId || null,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to create new planning item.');
  }

  return await response.json();
}