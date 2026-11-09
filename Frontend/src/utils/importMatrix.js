const fields = ['State', 'Chain Status', 'Premise Type', 'Top Chain', 'Date Version', 'Brand', 'Planning ID'];
const columns = ['Year / Type', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Total'];

export function allocateYearTotal(rows, baseline, year, total) {
  const actuals = rows.filter(row => row.year === year && row.kind === 'Actual')
    .reduce((sum, row) => sum + row.value, 0);
  const remaining = Math.max(0, total - actuals);
  const forecast = baseline.filter(row => row.year === year && row.kind === 'Forecast');
  if (!forecast.length) return rows;
  const weightTotal = forecast.reduce((sum, row) => sum + row.value, 0);
  const cents = Math.round(remaining * 100);
  const allocations = forecast.map(row => {
    const share = weightTotal > 0 ? row.value / weightTotal : 1 / forecast.length;
    const exact = cents * share;
    return {key: row.key, cents: Math.floor(exact), remainder: exact - Math.floor(exact)};
  });
  // Allocate leftover cents to the largest fractions so the displayed total ties out.
  const leftover = cents - allocations.reduce((sum, row) => sum + row.cents, 0);
  allocations.sort((a, b) => b.remainder - a.remainder);
  const values = new Map(allocations.map((row, index) => [row.key, (row.cents + (index < leftover ? 1 : 0)) / 100]));
  return rows.map(row => row.year === year && row.kind === 'Forecast' && values.has(row.key)
    ? {...row, value: values.get(row.key)}
    : row);
}

export async function readImportWorkbook(file) {
  if (!/\.xlsx$/i.test(file.name) || file.size > 5 * 1024 * 1024) {
    throw new Error('Choose an .xlsx workbook of 5 MB or less.');
  }
  const {default: ExcelJS} = await import('exceljs');
  const workbook = new ExcelJS.Workbook();
  try {
    await workbook.xlsx.load(await file.arrayBuffer());
  } catch {
    throw new Error('This file could not be read as an Excel workbook.');
  }
  return workbook;
}

export function applyMatrixWorkbook(workbook, metadata, rows, baseline, visibleYears) {
  const sheet = workbook.getWorksheet('Forecast Matrix');
  const original = workbook.getWorksheet('Export Baseline');
  if (!sheet || !original) throw new Error('Export a fresh workbook from the Dashboard, then edit and import that copy.');

  const header = Array.from({length: sheet.rowCount}, (_, i) => i + 1)
    .find(i => sheet.getCell(i, 1).value === columns[0]);
  if (!header || columns.some((label, i) => sheet.getCell(header, i + 1).value !== label)) {
    throw new Error('The matrix columns have changed. Keep the original Jan–Dec and Total columns.');
  }
  const mismatches = [];
  for (const field of fields) {
    const matches = [];
    for (let i = 2; i < header; i++) {
      if (sheet.getCell(i, 1).value === field) matches.push(sheet.getCell(i, 2).value);
    }
    if (matches.length !== 1 || matches[0] !== metadata[field] || !matches[0]) {
      mismatches.push(`${field} — Excel: ${matches.length === 1 ? matches[0] ?? '(blank)' : '(missing or repeated)'}; Dashboard: ${metadata[field]}`);
    }
  }
  if (mismatches.length) throw new Error(`Workbook filters do not match the dashboard.\n\n${mismatches.join('\n')}`);
  if (sheet.rowCount - header !== original.rowCount) {
    throw new Error('The matrix rows have changed. Keep the original rows and edit their values.');
  }

  const updates = new Map();
  const totals = new Map();
  let ignoredActuals = 0;
  const changedValue = (value, year, label) => {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > Number.MAX_SAFE_INTEGER / 100) {
      throw new Error(`${year} ${label} must be a non-negative number. Enter a value or leave the cell blank.`);
    }
    return value;
  };
  for (let i = 1; i <= original.rowCount; i++) {
    const row = sheet.getRow(header + i);
    const exported = original.getRow(i);
    const label = exported.getCell(1).value;
    if (row.getCell(1).value !== label) throw new Error('The matrix row labels or order have changed.');
    const yearMatch = /^(?:Consensus \()?([0-9]{4})\)?$/.exec(String(label));
    if (!yearMatch) continue;
    const year = Number(yearMatch[1]);
    const yearRows = rows.filter(row => row.year === year);
    const forecast = yearRows.filter(row => row.kind === 'Forecast');
    for (const month of yearRows) {
      const col = month.monthIndex + 2;
      const value = row.getCell(col).value;
      const before = exported.getCell(col).value;
      if (value == null || value === '' || value === before || before == null || before === '—') continue;
      if (month.kind === 'Actual') {
        ignoredActuals++;
      } else if (month.kind === 'Forecast') {
        if (!visibleYears.includes(year)) throw new Error(`Select ${year} in the dashboard Year filter before importing its forecast edits.`);
        updates.set(month.key, changedValue(value, year, columns[col - 1]));
      }
    }
    const total = row.getCell(14).value;
    if (!forecast.length || total == null || total === '' || total === exported.getCell(14).value) continue;
    if (!visibleYears.includes(year)) throw new Error(`Select ${year} in the dashboard Year filter before importing its total.`);
    if (yearRows.some(month => typeof exported.getCell(month.monthIndex + 2).value !== 'number')) {
      throw new Error(`Export the full Actuals + Forecast row for ${year} before editing its Total.`);
    }
    const target = changedValue(total, year, 'Total');
    const actuals = yearRows.filter(month => month.kind === 'Actual').reduce((sum, month) => sum + month.value, 0);
    if (target < actuals) throw new Error(`${year} Total cannot be lower than its actuals (${actuals}).`);
    totals.set(year, target);
  }
  let nextRows = rows.map(row => updates.has(row.key) ? {...row, value: updates.get(row.key)} : row);
  for (const [year, target] of totals) nextRows = allocateYearTotal(nextRows, baseline, year, target);
  const changedMonths = nextRows.filter((row, i) => row.kind === 'Forecast' && row.value !== rows[i].value).length;
  return {nextRows, changedMonths, ignoredActuals, totalYears: totals.size};
}
