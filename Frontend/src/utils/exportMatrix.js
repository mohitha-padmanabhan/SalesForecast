// Capture displayed values before the asynchronous Excel library is loaded.
// First-column labels always remain text, including numeric-looking years/IDs.
export function captureMatrix(table) {
  if (!table || !table.tBodies[0]?.rows.length) throw new Error('There are no matrix rows to export.');
  const headers = Array.from(table.tHead.rows[0].cells, cell => cell.textContent.trim());
  const rows = Array.from(table.tBodies[0].rows, row => Array.from(row.cells, (cell, index) => {
    if (index === 0) return {value: cell.textContent.trim()};
    const input = cell.querySelector('input');
    const tag = cell.querySelector('.cell-tag, small')?.textContent.trim();
    let text;
    if (input) text = input.value.trim();
    else {
      const copy = cell.cloneNode(true);
      copy.querySelectorAll('.cell-tag, small').forEach(el => el.remove());
      // Total cells contain a value followed by a descriptive caption.
      if (cell.classList.contains('year-total')) text = copy.querySelector('strong')?.textContent || copy.textContent;
      else text = copy.textContent;
      text = text.trim();
    }
    if (!text) return {value: null, note: tag};
    const normalized = text.replace(/,/g, '').replace(/\u2212/g, '-');
    const isPercent = /^[-+]?\d+(?:\.\d+)?%$/.test(normalized);
    const isNumber = /^[-+]?\d+(?:\.\d+)?$/.test(normalized);
    return {
      value: isPercent ? Number(normalized.slice(0, -1)) / 100 : isNumber ? Number(normalized) : text,
      format: isPercent ? '0%' : input ? '#,##0.##' : '#,##0',
      note: tag
    };
  }));
  return {headers, rows};
}

export async function buildMatrixWorkbook(snapshot, {title, metadata = {}}) {
  // Lazy-loaded so Excel export does not increase the initial dashboard bundle.
  const {default: ExcelJS} = await import('exceljs');
  const workbook = new ExcelJS.Workbook();
  workbook.creator = 'Infinium Spirits Demand Planning';
  workbook.created = new Date();
  const sheet = workbook.addWorksheet('Forecast Matrix');
  sheet.columns = snapshot.headers.map((_, i) => ({width: i === 0 ? 36 : 16}));
  sheet.mergeCells(1, 1, 1, snapshot.headers.length);
  sheet.getCell('A1').value = title;
  sheet.getCell('A1').font = {name: 'Calibri', size: 18, bold: true, color: {argb: 'FF082744'}};
  sheet.getRow(1).height = 32;
  for (const [label, value] of Object.entries(metadata)) {
    const row = sheet.addRow([label, String(value ?? 'All')]);
    row.getCell(1).font = {bold: true};
    row.getCell(2).alignment = {wrapText: true};
    sheet.mergeCells(row.number, 2, row.number, snapshot.headers.length);
  }
  sheet.addRow([]);
  const header = sheet.addRow(snapshot.headers);
  header.height = 28;
  header.eachCell(cell => {
    cell.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: 'FF082744'}};
    cell.font = {name: 'Calibri', bold: true, color: {argb: 'FFFFFFFF'}};
    cell.alignment = {vertical: 'middle', horizontal: 'center'};
  });
  snapshot.rows.forEach((values, rowIndex) => {
    const row = sheet.addRow(values.map(cell => cell.value));
    row.height = 30;
    values.forEach((source, index) => {
      const cell = row.getCell(index + 1);
      cell.font = {name: 'Calibri', size: 11, bold: index === 0 || index === values.length - 1};
      cell.alignment = {vertical: 'middle', horizontal: index === 0 ? 'left' : 'right', wrapText: true};
      cell.border = {bottom: {style: 'thin', color: {argb: 'FFD9E3EB'}}};
      if (source.format) cell.numFmt = source.format;
      if (source.note) cell.note = source.note;
      if (rowIndex % 2 === 0 || index === values.length - 1) cell.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: 'FFEAF2F8'}};
    });
  });
  if (metadata['Planning ID']) {
    // Keep the original displayed cells so unchanged rounded values are not imported as edits.
    const baseline = workbook.addWorksheet('Export Baseline', {state: 'veryHidden'});
    snapshot.rows.forEach(row => baseline.addRow(row.map(cell => cell.value)));
  }
  sheet.views = [{state: 'frozen', xSplit: 1, ySplit: header.number, showGridLines: false}];
  sheet.pageSetup = {orientation: 'landscape', paperSize: 9, fitToPage: true, fitToWidth: 1, fitToHeight: 0, printTitlesRow: `${header.number}:${header.number}`};
  return workbook;
}

export async function downloadMatrix(snapshot, options) {
  const workbook = await buildMatrixWorkbook(snapshot, options);
  const buffer = await workbook.xlsx.writeBuffer();
  const url = URL.createObjectURL(new Blob([buffer], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
  const anchor = document.createElement('a');
  anchor.href = url;
  const name = options.filename.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').slice(0, 150);
  anchor.download = `${name}_${new Date().toISOString().replace(/[:.]/g, '-')}.xlsx`;
  document.body.appendChild(anchor);
  try { anchor.click(); } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000); }
}
