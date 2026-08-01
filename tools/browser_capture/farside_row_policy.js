function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isCompleteFarsideRow(row) {
  if (!row || !row.date_iso || !isFiniteNumber(row.total_usd_m)) return false;
  const fundValues = Object.values(row.funds || {});
  return fundValues.some(isFiniteNumber);
}

export function selectCompleteFarsideRows(rows) {
  const ordered = [...rows].sort((a, b) => (
    String(a.date_iso).localeCompare(String(b.date_iso))
  ));
  const completeRows = ordered.filter(isCompleteFarsideRow);
  return {
    orderedRows: ordered,
    completeRows,
    latestDisplayed: ordered.at(-1) || null,
    latest: completeRows.at(-1) || null,
    previous: completeRows.at(-2) || null,
  };
}
