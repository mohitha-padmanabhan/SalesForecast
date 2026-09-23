import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  fetchFilterOptions, 
  fetchGridData, 
  submitForecastAdjustments, 
  fetchItemMasterData,
  fetchExistingDemandPlanIds,
  createNewPlanningItem
} from '../../api/forecastApi';
import './Dashboard.css';

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

const COMBINATION_OPTIONS = [
  { value: 'actual_forecast', label: 'Actuals + Forecasts' },
  { value: 'actual_only', label: 'Actuals Only' },
  { value: 'forecast_only', label: 'Forecasts Only' },
  { value: 'pre_forecast_only', label: 'Statistical Forecasts Only' },
  { value: 'budget_only', label: 'Budget Only' }
];

function makeDynamicRows(plan) {
  if (!plan) return [];

  const extractedYears = new Set();
  Object.keys(plan).forEach(key => {
    const match = key.match(/(?:actuals|forecasts|prevForecasts|budget)(\d{4})/);
    if (match) {
      extractedYears.add(parseInt(match[1], 10));
    }
  });

  const currentYear = new Date().getFullYear();
  const yearsList = extractedYears.size > 0 
    ? Array.from(extractedYears).sort((a, b) => a - b)
    : [currentYear - 2, currentYear - 1, currentYear, currentYear + 1];

  const rows = [];

  yearsList.forEach((year) => {
    const actualsArr = plan[`actuals${year}`] || [];
    const forecastsArr = plan[`forecasts${year}`] || [];
    const prevForecastsArr = plan[`prevForecasts${year}`] || [];
    const budgetArr = plan[`budget${year}`] || [];
    const idsArr = plan[`ids${year}`] || [];

    MONTHS.forEach((month, idx) => {
      let kind = 'Actual';
      let value = 0;
      let budgetVal = budgetArr[idx] !== undefined && budgetArr[idx] !== null ? Number(budgetArr[idx]) : null;
      
      let previouslyForecasted = prevForecastsArr[idx] !== undefined && prevForecastsArr[idx] !== null 
        ? Number(prevForecastsArr[idx]) 
        : null;

      if (year < currentYear) {
        kind = 'Actual';
        value = actualsArr[idx] ?? 0;
      } else if (year > currentYear) {
        kind = 'Forecast';
        value = forecastsArr[idx] ?? 0;
      } else {
        // Current Year Logic: completed months are Actuals; current/future months are Forecasts
        const currentMonthIndex = new Date().getMonth(); // Jan=0, Sep=8
        if (idx < currentMonthIndex) {
          kind = 'Actual';
          value = actualsArr[idx] ?? 0;
        } else {
          kind = 'Forecast';
          value = forecastsArr[idx - currentMonthIndex] ?? 0;
        }
      }

      rows.push({
        id: idsArr[idx] || 0,
        key: `${year}-${idx + 1}`,
        year: year,
        month: month,
        monthIndex: idx,
        kind: kind,
        value: Number(value) || 0,
        previouslyForecasted: previouslyForecasted,
        budgetVal: budgetVal
      });
    });
  });

  return rows;
}

function Dashboard() {
  const navigate = useNavigate();
  const [tempTotalInputs, setTempTotalInputs] = useState({});
  const [filters, setFilters] = useState({ 
    state: 'All', 
    chainStatus: 'All', 
    premiseType: 'All', 
    topChain: 'All', 
    dateVersion: '', 
    brandType: 'All' 
  });
  
  const [filterOptions, setFilterOptions] = useState({
    states: [],
    chainStatuses: [],
    premiseTypes: [],
    topChains: [],
    brands: [],
    versions: []
  });

  const [gridData, setGridData] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const selectedIdRef = useRef('');
  const [planType, setPlanType] = useState(null);
  const [annualTarget, setAnnualTarget] = useState(0);
  const [rows, setRows] = useState([]);
  const [saved, setSaved] = useState(false);
  const [latestLoadTimestamp, setLatestLoadTimestamp] = useState('');
  
  const [initialLoading, setInitialLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  
  const [tableFilters, setTableFilters] = useState({ 
    years: [], 
    dataCombinations: COMBINATION_OPTIONS.map(c => c.value) 
  });

  const [isYearDropdownOpen, setIsYearDropdownOpen] = useState(false);
  const [isComboDropdownOpen, setIsComboDropdownOpen] = useState(false);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [submittingModal, setSubmittingModal] = useState(false);
  const [newItemForm, setNewItemForm] = useState({
    demandPlanId: '',
    brand: '',
    state: '',
    templateChoice: 'existing',
    existingDemandPlanId: ''
  });

  const [demandPlanOptions, setDemandPlanOptions] = useState([]);
  const [existingForecastPlanIds, setExistingForecastPlanIds] = useState([]);
  const [loadingModalIds, setLoadingModalIds] = useState(false);

  const yearDropdownRef = useRef(null);
  const comboDropdownRef = useRef(null);

  const isIdAlreadyExisting = useMemo(() => {
    if (!newItemForm.demandPlanId) return false;
    return existingForecastPlanIds.includes(newItemForm.demandPlanId);
  }, [newItemForm.demandPlanId, existingForecastPlanIds]);

  const isAnyFilterSelected = useMemo(() => {
    return (
      filters.state !== 'All' ||
      filters.chainStatus !== 'All' ||
      filters.premiseType !== 'All' ||
      filters.topChain !== 'All' ||
      filters.brandType !== 'All'
    );
  }, [filters]);

  // Initial Load: Fetch master filter options once
  useEffect(() => {
    if (localStorage.getItem('isLoggedIn') !== 'true') {
      navigate('/login');
      return;
    }

    const fetchInitialData = async () => {
      setInitialLoading(true);
      try {
        const data = await fetchFilterOptions();
        
        setFilterOptions({
          states: data.states || [],
          chainStatuses: data.chain_statuses || ["CHAIN", "INDEPENDENT"],
          premiseTypes: data.premise_types || [],
          topChains: data.top_chains || [],
          brands: data.brands || [],
          versions: data.date_versions || []
        });

        const defaultVersion = data.default_date_version || (data.date_versions && data.date_versions[0]) || '';
        
        setFilters(prev => ({ 
          ...prev, 
          dateVersion: defaultVersion 
        }));

        const itemMasterRecords = await fetchItemMasterData();
        const uniqueDemandPlanIds = Array.from(
          new Set(
            (Array.isArray(itemMasterRecords) ? itemMasterRecords : [])
              .map(item => typeof item === 'string' ? item : item?.demand_plan_id)
              .filter(Boolean)
          )
        ).sort();
        setDemandPlanOptions(uniqueDemandPlanIds);

      } catch (err) {
        console.error('Failed to load initial dataset:', err);
      } finally {
        setInitialLoading(false);
      }
    };

    fetchInitialData();
  }, [navigate]);

  // Cascading Filter Logic: Updates downstream choices safely
  useEffect(() => {
    if (initialLoading) return;

    const updateCascadingFilters = async () => {
      try {
        const data = await fetchFilterOptions({
          state: filters.state,
          chainStatus: filters.chainStatus,
          premiseType: filters.premiseType
        });

        setFilterOptions(prev => {
          const updatedTopChains = data.top_chains || [];
          const updatedPremiseTypes = data.premise_types || [];

          return {
            ...prev,
            states: data.states && data.states.length > 0 ? data.states : prev.states,
            chainStatuses: data.chain_statuses && data.chain_statuses.length > 0 ? data.chain_statuses : prev.chainStatuses,
            premiseTypes: updatedPremiseTypes.length > 0 ? updatedPremiseTypes : prev.premiseTypes,
            topChains: updatedTopChains.length > 0 ? updatedTopChains : prev.topChains
          };
        });

        if (filters.chainStatus === 'INDEPENDENT' && filters.topChain !== 'Other') {
          setFilters(prev => ({ ...prev, topChain: 'Other' }));
        }
      } catch (err) {
        console.error('Failed to update cascading filters:', err);
      }
    };

    updateCascadingFilters();
  }, [filters.state, filters.chainStatus, filters.premiseType, initialLoading]);

  // Dynamic Fetching of Existing Plan IDs for Modal
  useEffect(() => {
    if (!isModalOpen) return;

    const updateModalExistingIds = async () => {
      setLoadingModalIds(true);
      try {
        const modalFilters = {
          brand: newItemForm.brand || "All",
          state: newItemForm.state || "All"
        };
        const filteredIds = await fetchExistingDemandPlanIds(modalFilters);
        setExistingForecastPlanIds(filteredIds);
      } catch (err) {
        console.error('Failed to load modal demand plan IDs:', err);
      } finally {
        setLoadingModalIds(false);
      }
    };

    updateModalExistingIds();
  }, [newItemForm.brand, newItemForm.state, isModalOpen]);

  useEffect(() => {
    function handleClickOutside(event) {
      if (yearDropdownRef.current && !yearDropdownRef.current.contains(event.target)) {
        setIsYearDropdownOpen(false);
      }
      if (comboDropdownRef.current && !comboDropdownRef.current.contains(event.target)) {
        setIsComboDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const loadForecastData = useCallback(async (activeVersion) => {
    if (!isAnyFilterSelected) {
      setGridData([]);
      setSelectedId('');
      setRows([]);
      setAnnualTarget(0);
      return;
    }

    setLoading(true);
    try {
      const payload = {
        state: filters.state || "All",
        chain_status: filters.chainStatus || "All",
        premise_type: filters.premiseType || "All",
        brand: filters.brandType || "All",
        top_chain: filters.topChain || "All",
        date_version: activeVersion || filters.dateVersion || "Latest"
      };

      const resData = await fetchGridData(payload);
      const items = resData.grid_data || [];
      setGridData(items);
      setLatestLoadTimestamp(resData?.statistics?.latest_load_timestamp || '');

      if (items.length > 0) {
        const currentSelection = items.find(i => i.planning_id === selectedIdRef.current) || items[0];
        selectedIdRef.current = currentSelection.planning_id;
        setSelectedId(currentSelection.planning_id);
        setAnnualTarget(currentSelection.annualTarget || 0);
        setRows(makeDynamicRows(currentSelection));
      } else {
        selectedIdRef.current = '';
        setSelectedId('');
        setRows([]);
        setAnnualTarget(0);
      }
    } catch (err) {
      console.error('Failed to fetch forecast grid:', err);
    } finally {
      setLoading(false);
    }
  }, [filters, isAnyFilterSelected]);

  useEffect(() => {
    if (!initialLoading) {
      loadForecastData(filters.dateVersion);
    }
  }, [filters.state, filters.chainStatus, filters.premiseType, filters.topChain, filters.dateVersion, filters.brandType, initialLoading, loadForecastData]);

  const dynamicYears = useMemo(() => {
    const set = new Set(rows.map(r => r.year));
    return Array.from(set).sort((a, b) => a - b);
  }, [rows]); 

  useEffect(() => {
    if (dynamicYears.length > 0 && tableFilters.years.length === 0) {
      setTableFilters(prev => ({ ...prev, years: dynamicYears }));
    }
  }, [dynamicYears, tableFilters.years.length]);

  const currentDynamicYear = useMemo(() => {
    const now = new Date().getFullYear();
    return dynamicYears.includes(now) ? now : dynamicYears[0] || now;
  }, [dynamicYears]);

  const selectedPlan = useMemo(() => {
    return gridData.find(p => p.planning_id === selectedId) || gridData[0] || null;
  }, [gridData, selectedId]);

  const choosePlan = (plan) => {
    selectedIdRef.current = plan.planning_id;
    setSelectedId(plan.planning_id);
    setAnnualTarget(plan.annualTarget || 0);
    setRows(makeDynamicRows(plan));
    setPlanType(null);
    setSaved(false);
  };

  const actualCurrentYear = useMemo(() => {
    return rows.filter(r => r.kind === 'Actual' && r.year === currentDynamicYear).reduce((s,r) => s + r.value, 0);
  }, [rows, currentDynamicYear]);

  const forecastCurrentYear = useMemo(() => {
    return rows.filter(r => r.kind === 'Forecast' && r.year === currentDynamicYear).reduce((s,r) => s + r.value, 0);
  }, [rows, currentDynamicYear]);

  const yearTotal = actualCurrentYear + forecastCurrentYear;

  const changeForecast = (key, value) => {
    if (!planType) return;
    setRows(prev => prev.map(r => r.key === key && r.kind === 'Forecast' ? { ...r, value: Math.max(0, Number(value) || 0) } : r));
    setSaved(false);
  };

  const handleYearTotalChange = (year, rawVal) => {
    setTempTotalInputs(prev => ({ ...prev, [year]: rawVal }));

    const newTotal = Math.max(0, Number(rawVal) || 0);
    const originalRows = makeDynamicRows(selectedPlan);

    const yearActuals = rows
      .filter(r => r.year === year && r.kind === 'Actual')
      .reduce((s, r) => s + r.value, 0);

    const remainingForForecast = Math.max(0, newTotal - yearActuals);
    const baselineForecastRows = originalRows.filter(r => r.year === year && r.kind === 'Forecast');
    const baselineTotal = baselineForecastRows.reduce((s, r) => s + r.value, 0);

    setRows(prev => prev.map(r => {
      if (r.year === year && r.kind === 'Forecast') {
        const baseCell = baselineForecastRows.find(b => b.key === r.key);
        const baseVal = baseCell ? baseCell.value : r.value;
        const proportion = baselineTotal > 0 
          ? baseVal / baselineTotal 
          : 1 / baselineForecastRows.length;

        return { 
          ...r, 
          value: Number((remainingForForecast * proportion).toFixed(2)) 
        };
      }
      return r;
    }));

    if (year === currentDynamicYear) {
      setAnnualTarget(newTotal);
    }
    setSaved(false);
  };

  const switchPlanType = (type) => {
    setPlanType(type);
    if (selectedPlan) {
      setRows(makeDynamicRows(selectedPlan));
      setAnnualTarget(selectedPlan.annualTarget || 0);
    }
    setSaved(false);
  };

  const resetView = () => {
    if (selectedPlan) {
      setRows(makeDynamicRows(selectedPlan));
      setAnnualTarget(selectedPlan.annualTarget || 0);
    }
    setPlanType(null);
    setSaved(false);
  };

  const submitPlan = async () => {
    if (!planType || !selectedPlan) return;

    const userEmail = localStorage.getItem('user_email') || 
                      localStorage.getItem('userEmail') || 
                      localStorage.getItem('user') || 
                      'user@company.com';

    const initialRows = makeDynamicRows(selectedPlan);

    const forecastUpdates = rows
      .filter(r => r.kind === 'Forecast')
      .filter(r => {
        const initialCell = initialRows.find(orig => orig.key === r.key);
        const oldVal = initialCell ? Number(initialCell.value) : Number(r.value);
        return Math.abs(oldVal - Number(r.value)) > 0.000001;
      })
      .map((r) => ({
        id: r.id || 0,
        planning_id: selectedPlan.planning_id,
        state: selectedPlan.state,
        chain_status: selectedPlan.chain_status,
        date: `${r.year}-${String(r.monthIndex + 1).padStart(2, '0')}-01`,
        forecast_qty_9l: r.value,
        date_version: filters.dateVersion,
        premise_type: selectedPlan.premise_type,
        brand: selectedPlan.brand,
        top_chain: selectedPlan.top_chain,
        adjustment_factor: 1.0
      }));
    const changelogEntries = rows
      .filter(r => r.kind === 'Forecast')
      .map(r => {
        const initialCell = initialRows.find(orig => orig.key === r.key);
        const oldVal = initialCell ? initialCell.value : r.value;
        const fcstDate = `${r.year}-${String(r.monthIndex + 1).padStart(2, '0')}-01`;

        return {
          user: userEmail,
          item: selectedPlan.planning_id,
          old_value: oldVal,
          new_value: r.value,
          fcst_date: fcstDate,
          state: selectedPlan.state,
          chain_status: selectedPlan.chain_status,
          date_version: filters.dateVersion,
          premise_type: selectedPlan.premise_type,
          top_chain: selectedPlan.top_chain
        };
      })
      .filter(entry => entry.old_value !== entry.new_value);

    if (changelogEntries.length === 0) {
      changelogEntries.push({
        user: userEmail,
        item: selectedPlan.planning_id,
        old_value: selectedPlan.annualTarget || 0,
        new_value: annualTarget,
        fcst_date: new Date().toISOString().split('T')[0],
        state: selectedPlan.state,
        chain_status: selectedPlan.chain_status,
        date_version: filters.dateVersion,
        premise_type: selectedPlan.premise_type,
        top_chain: selectedPlan.top_chain
      });
    }

    const payload = {
      plan_by: planType,
      plan_by_month: planType === 'month',
      selected_state: filters.state,
      plan_type: planType,
      brand: filters.brandType,
      premise_type: filters.premiseType,
      chain_status: filters.chainStatus,
      top_chain: filters.topChain,
      adjustments: changelogEntries,
      items_to_update: forecastUpdates
    };

    try {
      const submitResponse = await submitForecastAdjustments(payload);
      const savedVersion = submitResponse?.details?.date_version;
      const savedLoadTimestamp = submitResponse?.details?.load_timestamp;

      setSaved(true);
      if (savedLoadTimestamp) {
        setLatestLoadTimestamp(savedLoadTimestamp);
      }

      if (savedVersion) {
        setFilterOptions(prev => ({
          ...prev,
          versions: Array.from(new Set([savedVersion, ...(prev.versions || [])])).sort().reverse()
        }));
        setFilters(prev => ({ ...prev, dateVersion: savedVersion }));
        await loadForecastData(savedVersion);
      } else {
        await loadForecastData(filters.dateVersion);
      }
    } catch (error) {
      const detailMessage = error?.response?.data?.detail 
        ? JSON.stringify(error.response.data.detail) 
        : error.message;
      console.error("Submission failed:", detailMessage);
      alert(`Submission failed: ${detailMessage}`);
    }
  };

  const toggleYearSelection = (year) => {
    setTableFilters(prev => {
      const exists = prev.years.includes(year);
      return {
        ...prev,
        years: exists ? prev.years.filter(y => y !== year) : [...prev.years, year].sort((a, b) => a - b)
      };
    });
  };

  const toggleAllYears = () => {
    setTableFilters(prev => ({
      ...prev,
      years: prev.years.length === dynamicYears.length ? [] : [...dynamicYears]
    }));
  };

  const toggleComboSelection = (val) => {
    setTableFilters(prev => {
      const exists = prev.dataCombinations.includes(val);
      return {
        ...prev,
        dataCombinations: exists 
          ? prev.dataCombinations.filter(c => c !== val) 
          : [...prev.dataCombinations, val]
      };
    });
  };

  const toggleAllCombos = () => {
    setTableFilters(prev => ({
      ...prev,
      dataCombinations: prev.dataCombinations.length === COMBINATION_OPTIONS.length 
        ? [] 
        : COMBINATION_OPTIONS.map(c => c.value)
    }));
  };

  const handleOpenModal = () => {
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setNewItemForm({
      demandPlanId: '',
      brand: '',
      state: '',
      templateChoice: 'existing',
      existingDemandPlanId: ''
    });
  };

  const handleCreateNewItem = async (e) => {
    e.preventDefault();

    if (!newItemForm.demandPlanId || !newItemForm.brand || !newItemForm.state) {
      alert("Please fill in all required fields.");
      return;
    }

    if (newItemForm.templateChoice === 'existing' && !newItemForm.existingDemandPlanId) {
      alert("Please select an Existing Demand Plan ID.");
      return;
    }

    setSubmittingModal(true);
    try {
      await createNewPlanningItem(newItemForm);
      alert(`Successfully created demand plan ID: ${newItemForm.demandPlanId}`);
      handleCloseModal();

      setFilters(prev => ({
        ...prev,
        state: newItemForm.state,
        brandType: newItemForm.brand
      }));
    } catch (err) {
      console.error("Failed to create new item:", err);
      alert(`Error creating item: ${err.message}`);
    } finally {
      setSubmittingModal(false);
    }
  };

  const visibleYears = dynamicYears.filter(year => tableFilters.years.includes(year));

  const isRowVisible = (rowKind, rowType) => {
    const selectedCombos = tableFilters.dataCombinations;
    if (selectedCombos.length === 0) return false;

    if (selectedCombos.includes('actual_forecast') && rowType === 'main') return true;
    if (selectedCombos.includes('actual_only') && rowKind === 'Actual' && rowType === 'main') return true;
    if (selectedCombos.includes('forecast_only') && rowKind === 'Forecast' && rowType === 'main') return true;
    if (selectedCombos.includes('pre_forecast_only') && rowType === 'pre_forecast') return true;
    if (selectedCombos.includes('budget_only') && rowType === 'budget') return true;

    return false;
  };

  return (
    <main className="forecast-dashboard" style={{ position: 'relative' }}>
      
      {initialLoading && (
        <div className="full-loader-overlay">
          <div className="spinner-lg"></div>
          <h2>Loading Demand Forecast Engine...</h2>
          <p>Fetching initial filters and forecast matrices from database.</p>
        </div>
      )}

      {!initialLoading && loading && (
        <div className="loader-overlay">
          <div className="spinner"></div>
          <p>Updating dataset...</p>
        </div>
      )}

      <header className="page-heading">
        <div>
          <span className="eyebrow">Commercial Planning</span>
          <h1>Forecast Planning</h1>
          <p>Review actuals and forecasts dynamically fed from your database.</p>
        </div>
        <div className="mode-area">
          <span className={`view-badge ${!planType ? 'active' : ''}`}>{!planType ? 'View Mode' : 'Edit Mode'}</span>
          <div className="mode-switch" aria-label="Planning mode">
            <button className={planType === 'month' ? 'active' : ''} onClick={() => switchPlanType('month')}>Plan by Month</button>
            <button className={planType === 'year' ? 'active' : ''} onClick={() => switchPlanType('year')}>Plan by Year</button>
          </div>
        </div>
      </header>

      <section className="filter-card">
        <div className="filter-title">
          <span>Filters</span>
          <small>{loading || initialLoading ? 'Connecting...' : 'Synced to Database'}</small>
        </div>
        <div className="filter-grid">
          <Filter label="State" value={filters.state} options={filterOptions.states} onChange={v => setFilters(prev => ({ ...prev, state: v }))} disabled={loading || initialLoading} />
          <Filter label="Chain Status" value={filters.chainStatus} options={filterOptions.chainStatuses} onChange={v => setFilters(prev => ({ ...prev, chainStatus: v }))} disabled={loading || initialLoading} />
          <Filter label="Premise Type" value={filters.premiseType} options={filterOptions.premiseTypes} onChange={v => setFilters(prev => ({ ...prev, premiseType: v }))} disabled={loading || initialLoading} />
          <Filter label="Top Chain" value={filters.topChain} options={filterOptions.topChains} onChange={v => setFilters(prev => ({ ...prev, topChain: v }))} disabled={loading || initialLoading} />
          <Filter label="Date Version" value={filters.dateVersion} options={filterOptions.versions} onChange={v => setFilters(prev => ({ ...prev, dateVersion: v }))} required disabled={loading || initialLoading} />
          <Filter label="Brand Type (optional)" value={filters.brandType} options={filterOptions.brands} onChange={v => setFilters(prev => ({ ...prev, brandType: v }))} disabled={loading || initialLoading} />
        </div>
      </section>

      <section className="workspace">
        <aside className="planning-sidebar">
          <div className="panel-heading">
            <div>
              <span>Planning IDs</span>
              <small>{gridData.length} total</small>
            </div>
            <button className="new-item-btn" onClick={handleOpenModal}>
              + New Item
            </button>
          </div>
          <div className="planning-list">
            {gridData.map(plan => (
              <button 
                key={plan.planning_id} 
                onClick={() => choosePlan(plan)} 
                className={`plan-card ${selectedId === plan.planning_id ? 'selected' : ''}`}
              >
                <div className="plan-id-tag">ID: {plan.planning_id}</div>
                <strong>{plan.brand}</strong>
                <span>{plan.state} · {plan.premise_type}</span>
              </button>
            ))}
            {(!gridData.length || !isAnyFilterSelected) && !initialLoading && (
              <div className="empty-state">
                {!isAnyFilterSelected 
                  ? "Select top filter(s) to view planning IDs." 
                  : "No planning IDs match the selected filters."}
              </div>
            )}
          </div>
        </aside>

        {isAnyFilterSelected && selectedPlan ? (
          <section className="planning-main">
            <div className="selection-header">
              <div>
                <span className="eyebrow">Selected Planning ID</span>
                <h2>{selectedPlan.planning_id}</h2>
                <p>{selectedPlan.brand} · {selectedPlan.state} · {selectedPlan.premise_type}</p>
              </div>
              <div className="version-chip">
                <span>Version</span>
                <strong>{filters.dateVersion}</strong>
                {latestLoadTimestamp && <small>Loaded {latestLoadTimestamp}</small>}
              </div>
            </div>

            <div className="summary-strip">
              <Metric label={`Actuals ${currentDynamicYear}`} value={actualCurrentYear.toFixed(1)} suffix="9L" />
              <Metric label={`Forecast ${currentDynamicYear}`} value={forecastCurrentYear.toFixed(1)} suffix="9L" />
              <Metric label={`${currentDynamicYear} Total`} value={yearTotal.toFixed(1)} suffix="9L" emphasize />
              <Metric label="Annual Target" value={annualTarget.toFixed(1)} suffix="9L" />
            </div>

            <div className="forecast-view-controls">
              <div>
                <span className="eyebrow">Forecast Matrix Filters</span>
                <strong>Filter Matrix by Year and Data Combinations</strong>
              </div>
              <div className="table-filter-group flex-row">
                
                <div className="custom-multiselect-container" ref={yearDropdownRef}>
                  <span className="filter-label-title">Year Filter</span>
                  <div 
                    className="multiselect-trigger" 
                    onClick={() => {
                      setIsYearDropdownOpen(!isYearDropdownOpen);
                      setIsComboDropdownOpen(false);
                    }}
                  >
                    <span>
                      {tableFilters.years.length === 0 
                        ? 'Select Years' 
                        : tableFilters.years.length === dynamicYears.length 
                          ? 'All Years' 
                          : `${tableFilters.years.length} Selected`}
                    </span>
                    <span className="arrow">{isYearDropdownOpen ? '▲' : '▼'}</span>
                  </div>

                  {isYearDropdownOpen && (
                    <div className="multiselect-dropdown">
                      <label className="multiselect-option header-option">
                        <input 
                          type="checkbox" 
                          checked={tableFilters.years.length === dynamicYears.length && dynamicYears.length > 0} 
                          onChange={toggleAllYears} 
                        />
                        <span><strong>(Select All)</strong></span>
                      </label>
                      <hr style={{ margin: '4px 0', border: 'none', borderTop: '1px solid #e2e8f0' }} />
                      {dynamicYears.map(year => (
                        <label key={year} className="multiselect-option">
                          <input 
                            type="checkbox" 
                            checked={tableFilters.years.includes(year)} 
                            onChange={() => toggleYearSelection(year)} 
                          />
                          <span>{year}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>

                <div className="custom-multiselect-container" ref={comboDropdownRef}>
                  <span className="filter-label-title">View Combination Filter</span>
                  <div 
                    className="multiselect-trigger" 
                    onClick={() => {
                      setIsComboDropdownOpen(!isComboDropdownOpen);
                      setIsYearDropdownOpen(false);
                    }}
                  >
                    <span>
                      {tableFilters.dataCombinations.length === 0 
                        ? 'Select Combinations' 
                        : tableFilters.dataCombinations.length === COMBINATION_OPTIONS.length 
                          ? 'All Combinations' 
                          : `${tableFilters.dataCombinations.length} Selected`}
                    </span>
                    <span className="arrow">{isComboDropdownOpen ? '▲' : '▼'}</span>
                  </div>

                  {isComboDropdownOpen && (
                    <div className="multiselect-dropdown">
                      <label className="multiselect-option header-option">
                        <input 
                          type="checkbox" 
                          checked={tableFilters.dataCombinations.length === COMBINATION_OPTIONS.length} 
                          onChange={toggleAllCombos} 
                        />
                        <span><strong>(Select All)</strong></span>
                      </label>
                      <hr style={{ margin: '4px 0', border: 'none', borderTop: '1px solid #e2e8f0' }} />
                      {COMBINATION_OPTIONS.map(opt => (
                        <label key={opt.value} className="multiselect-option">
                          <input 
                            type="checkbox" 
                            checked={tableFilters.dataCombinations.includes(opt.value)} 
                            onChange={() => toggleComboSelection(opt.value)} 
                          />
                          <span>{opt.label}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>

              </div>
            </div>

            <div className="matrix-note">
              <div><strong>{planType ? 'Editing enabled' : 'Normal view mode'}</strong><span>{planType === 'year' ? ' Inline total editing enabled.' : planType === 'month' ? ' Monthly forecast input enabled.' : ' Select a planning mode to edit.'}</span></div>
              <div className="legend">
                <span><i className="dot actual"></i>Actuals</span>
                <span><i className="dot forecast"></i>Forecast</span>
                <span><i className="dot previous"></i>Statistical Forecast</span> 
                <span><i className="dot budget"></i>Budget</span>
              </div>
            </div>

            <div className="forecast-matrix-wrap">
              <table className="forecast-matrix">
                <thead>
                  <tr>
                    <th className="year-col">Year / Type</th>
                    {MONTHS.map(m => <th key={m}>{m}</th>)}
                    <th className="year-total">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleYears.map(year => {
                    const yearRows = rows.filter(r => r.year === year);
                    
                    const isEditableYear = planType === 'year' && year >= currentDynamicYear;
                    const prevForecastRows = yearRows.filter(r => r.previouslyForecasted !== null);
                    const prevTotal = prevForecastRows.reduce((s, r) => s + (r.previouslyForecasted || 0), 0);

                    const budgetRows = yearRows.filter(r => r.budgetVal !== null);
                    const budgetTotal = budgetRows.reduce((s, r) => s + (r.budgetVal || 0), 0);

                    const showMainRow = isRowVisible('Actual', 'main') || isRowVisible('Forecast', 'main');
                    const showPrevRow = isRowVisible('', 'pre_forecast') && prevForecastRows.length > 0;
                    const showBudgetRow = isRowVisible('', 'budget') && budgetRows.length > 0;

                    const mainTotal = yearRows
                      .filter(r => {
                        const combos = tableFilters.dataCombinations;
                        if (combos.includes('actual_only') && !combos.includes('forecast_only')) return r.kind === 'Actual';
                        if (combos.includes('forecast_only') && !combos.includes('actual_only')) return r.kind === 'Forecast';
                        return true;
                      })
                      .reduce((s, r) => s + r.value, 0);

                    return (
                      <React.Fragment key={year}>
                        {showMainRow && (
                          <tr>
                            <th className="year-cell">
                              {year === currentDynamicYear ? `Consensus (${year})` : year}
                            </th>
                            {MONTHS.map((month, idx) => {
                              const row = yearRows.find(r => r.monthIndex === idx);
                              if (!row || !isRowVisible(row.kind, 'main')) {
                                return <td key={`${year}-${month}`} className="filtered-cell"><span>—</span></td>;
                              }
                              return (
                                <td key={`${year}-${month}`} className={row.kind === 'Actual' ? 'actual-cell' : 'forecast-cell'}>
                                  <span className={`cell-tag ${row.kind.toLowerCase()}`}>{row.kind === 'Actual' ? 'Actuals' : 'Forecast'}</span>
                                  {row.kind === 'Forecast' && planType === 'month' ?
                                    <input aria-label={`${month} ${year} Forecast`} type="number" step="0.01" min="0" value={row.value} onChange={e => changeForecast(row.key, e.target.value)} />
                                    : <strong>{row.value.toFixed(2)}</strong>}
                                </td>
                              );
                            })}
                            <td className="year-total">
                              {isEditableYear ? (
                                <input
                                  type="number"
                                  step="0.01"
                                  min="0"
                                  className="inline-total-input"
                                  aria-label={`Total ${year}`}
                                  value={tempTotalInputs[year] !== undefined ? tempTotalInputs[year] : mainTotal.toFixed(2)}
                                  onChange={e => handleYearTotalChange(year, e.target.value)}
                                  onBlur={() => {
                                    setTempTotalInputs(prev => {
                                      const next = { ...prev };
                                      delete next[year];
                                      return next;
                                    });
                                  }}
                                />
                              ) : (
                                <strong>{mainTotal.toFixed(2)}</strong>
                              )}
                              <span>Total 9L</span>
                            </td>
                          </tr>
                        )}

                        {showPrevRow && (
                          <tr className="prev-forecast-row">
                            <th className="year-cell prev-label">Statistical Forecast ({year})</th>
                            {MONTHS.map((month, idx) => {
                              const row = yearRows.find(r => r.monthIndex === idx);
                              const prevVal = row ? row.previouslyForecasted : null;
                              return (
                                <td key={`prev-${year}-${month}`} className="prev-forecast-cell">
                                  {prevVal !== null ? (
                                    <>
                                      <span className="cell-tag previous">Stat-Fcst</span>
                                      <span className="prev-value">{prevVal.toFixed(2)}</span>
                                    </>
                                  ) : <span>—</span>}
                                </td>
                              );
                            })}
                            <td className="year-total prev-total">
                              <strong>{prevTotal.toFixed(2)}</strong>
                              <span>Statistical Forecast</span>
                            </td>
                          </tr>
                        )}

                        {showBudgetRow && (
                          <tr className="budget-row">
                            <th className="year-cell budget-label">Budget ({year})</th>
                            {MONTHS.map((month, idx) => {
                              const row = yearRows.find(r => r.monthIndex === idx);
                              const bVal = row ? row.budgetVal : null;
                              return (
                                <td key={`budget-${year}-${month}`} className="budget-cell">
                                  {bVal !== null ? (
                                    <>
                                      <span className="cell-tag budget">Budget</span>
                                      <span className="budget-value">{bVal.toFixed(2)}</span>
                                    </>
                                  ) : <span>—</span>}
                                </td>
                              );
                            })}
                            <td className="year-total budget-total">
                              <strong>{budgetTotal.toFixed(2)}</strong>
                              <span>Budget</span>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <footer className="action-bar">
              <div className="save-note">{saved ? '✓ Submitted successfully to backend.' : planType ? 'Editing active. Submit when finished.' : 'View Mode.'}</div>
              <div className="actions">
                <button className="secondary" onClick={resetView}>Reset / View Mode</button>
                <button className="primary" disabled={!planType} onClick={submitPlan}>Submit Forecast</button>
              </div>
            </footer>
          </section>
        ) : (
          <section className="planning-main flex-center">
            <div className="empty-state-card">
              <h3>No Filters Selected</h3>
              <p>Please select at least one top filter (State, Chain Status, Premise Type, Top Chain, or Brand) to view demand forecast records.</p>
            </div>
          </section>
        )}
      </section>

      {/* NEW ITEM MODAL */}
      {isModalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3>Add New Planning Item</h3>
              <button className="close-btn" onClick={handleCloseModal}>&times;</button>
            </div>
            
            <form onSubmit={handleCreateNewItem} className="modal-body">
              <div className="form-group">
                <label>Item Master Demand Plan ID</label>
                <select 
                  value={newItemForm.demandPlanId}
                  onChange={e => setNewItemForm({ ...newItemForm, demandPlanId: e.target.value })}
                  required
                >
                  <option value="">Select Demand Plan ID</option>
                  {demandPlanOptions.map(id => (
                    <option key={id} value={id}>{id}</option>
                  ))}
                </select>
                {isIdAlreadyExisting && (
                  <p style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px', fontWeight: '500' }}>
                    ⚠️ Warning: The item already exists for the selected brand and state filters.
                  </p>
                )}
              </div>

              <div className="form-group">
                <label>Brand</label>
                <select 
                  value={newItemForm.brand}
                  onChange={e => setNewItemForm({ ...newItemForm, brand: e.target.value })}
                  required
                >
                  <option value="">Select Brand</option>
                  {filterOptions.brands.map(b => (
                    <option key={b} value={b}>{b}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>State</label>
                <select 
                  value={newItemForm.state}
                  onChange={e => setNewItemForm({ ...newItemForm, state: e.target.value })}
                  required
                >
                  <option value="">Select State</option>
                  {filterOptions.states.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Template Choice</label>
                <div className="radio-group">
                  <label className="radio-label">
                    <input 
                      type="radio" 
                      name="templateChoice" 
                      value="new" 
                      checked={newItemForm.templateChoice === 'new'}
                      onChange={e => setNewItemForm({ ...newItemForm, templateChoice: e.target.value })}
                    />
                    <span>New Template Choice</span>
                  </label>
                  
                  <label className="radio-label">
                    <input 
                      type="radio" 
                      name="templateChoice" 
                      value="existing" 
                      checked={newItemForm.templateChoice === 'existing'}
                      onChange={e => setNewItemForm({ ...newItemForm, templateChoice: e.target.value })}
                    />
                    <span>Existing Template Choice</span>
                  </label>
                </div>
              </div>

              {newItemForm.templateChoice === 'existing' && (
                <div className="form-group conditional-group">
                  <label>Existing Demand Plan ID (from 24monforecast)</label>
                  <select 
                    value={newItemForm.existingDemandPlanId}
                    onChange={e => setNewItemForm({ ...newItemForm, existingDemandPlanId: e.target.value })}
                    required
                    disabled={loadingModalIds}
                  >
                    <option value="">
                      {loadingModalIds ? "Loading matching IDs..." : "Select Existing Demand Plan ID"}
                    </option>
                    {existingForecastPlanIds.map(id => (
                    <option key={id} value={id}>{id}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className="modal-footer">
                <button type="button" className="secondary" onClick={handleCloseModal} disabled={submittingModal}>
                  Cancel
                </button>
                <button type="submit" className="primary" disabled={submittingModal}>
                  {submittingModal ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </main>
  );
}

function Filter({ label, value, options, onChange, required, disabled }) {
  return (
    <label className="filter-field">
      <span>{label}{required && <b> •</b>}</span>
      <select value={value} onChange={e => onChange(e.target.value)} disabled={disabled}>
        {!required && <option value="All">All</option>}
        {(options || []).map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

function Metric({ label, value, suffix, emphasize }) { 
  return (
    <div className={`metric ${emphasize ? 'emphasize' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{suffix}</small>
    </div>
  ); 
}

export default Dashboard;