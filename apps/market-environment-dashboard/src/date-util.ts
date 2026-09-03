const DEFAULT_DATE_CUTOFF_HOUR = 15

export function formatLocalDate(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function getDefaultMarketDate(now: Date) {
  const selectedDate = new Date(now)
  if (selectedDate.getHours() < DEFAULT_DATE_CUTOFF_HOUR) {
    selectedDate.setDate(selectedDate.getDate() - 1)
  }
  return formatLocalDate(selectedDate)
}
