const addArrays = (items, key) => Array.from({length: 12}, (_, month) =>
  items.reduce((total, item) => total + (Number(item[key]?.[month]) || 0), 0));

export function buildSummaryMatrix(items, selectedYear, varianceMode) {
  const prev1 = selectedYear - 2;
  const prev2 = selectedYear - 1;
  const previousActuals = addArrays(items, 'actuals2024');
  const priorActuals = addArrays(items, 'actuals2025');
  const actuals = addArrays(items, 'actuals2026');
  const actualCount = Math.max(0, ...items.map(item => (item.actuals2026 || []).length));
  const forecast = Array(12).fill(0);
  items.forEach(item => (item.forecasts2026 || []).forEach((value, index) => {
    const month = (item.actuals2026 || []).length + index;
    if (month < 12) forecast[month] += Number(value) || 0;
  }));
  const consensus = actuals.map((value, index) => value + forecast[index]);
  const budget = addArrays(items, `budget${selectedYear}`);
  const reference = varianceMode === 'budget' ? budget : priorActuals;
  const nextYear = selectedYear + 1;
  // The API uses budget[nextYear] for the next-year Statistical Forecast,
  // matching the existing Dashboard row.
  const nextStatistical = addArrays(items, `budget${nextYear}`);
  return [
    {label: String(prev1), year: prev1, type: 'actual', vals: previousActuals},
    {label: String(prev2), year: prev2, type: 'actual', vals: priorActuals},
    {label: `Consensus (${selectedYear})`, year: selectedYear, type: 'consensus', vals: consensus, actualCount},
    {label: `Statistical Forecast (${selectedYear})`, year: selectedYear, type: 'stat', vals: addArrays(items, 'prevForecasts2026')},
    {label: `Budget (${selectedYear})`, year: selectedYear, type: 'budget', vals: budget},
    {label: `${varianceMode === 'budget' ? 'vBUD' : 'vPY'} (${selectedYear})`, year: selectedYear, type: 'variance', vals: consensus.map((value, i) => value - reference[i])},
    {label: `${varianceMode === 'budget' ? 'vBUD' : 'vPY'} % (${selectedYear})`, year: selectedYear, type: 'percent', vals: consensus.map((value, i) => reference[i] ? (value - reference[i]) / reference[i] * 100 : null)},
    {label: `Consensus (${nextYear})`, year: nextYear, type: 'consensus', vals: addArrays(items, 'forecasts2027'), actualCount: 0},
    {label: `Statistical Forecast (${nextYear})`, year: nextYear, type: 'stat', vals: nextStatistical},
    {label: `Budget (${nextYear})`, year: nextYear, type: 'budget', vals: nextStatistical}
  ];
}
