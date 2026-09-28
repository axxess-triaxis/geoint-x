import { expect, test } from '@playwright/test'

// The end-to-end demonstration: select area -> detect change on real Sentinel-2
// observations -> case created and prioritised -> AI brief (template mode, no key)
// -> reviewer confirms -> analytics update -> monitoring agent runs the next cycle.
test('detect, verify, confirm, monitor', async ({ page }) => {
  await page.goto('/map?aoi=deepor_beel')
  await expect(page.getByText('Ramsar-listed freshwater wetland')).toBeVisible()
  await page.getByRole('button', { name: 'Detect change' }).click()
  await expect(page.getByLabel('Analysis run')).toHaveValue('RUN-0001', { timeout: 120_000 })
  await expect(page.getByText(/regions · \d+ cases/)).toBeVisible()

  await page.goto('/cases')
  const firstRow = page.locator('table.data tbody tr').first()
  await expect(firstRow).toContainText('CASE-')
  const caseId = (await firstRow.locator('td.mono').textContent())!.trim()
  await firstRow.click()
  await expect(page).toHaveURL(new RegExp(`/cases/${caseId}$`))
  await expect(page.getByText('Why this priority')).toBeVisible()
  await expect(page.getByText('not a legal determination', { exact: false })).toBeVisible()

  await page.getByRole('button', { name: 'Generate' }).click()
  await expect(page.getByText('deterministic template')).toBeVisible()

  // Analyst cannot confirm; reviewer can.
  await expect(page.getByRole('button', { name: 'Confirm change' })).toHaveCount(0)
  await page.getByLabel('Demo role').selectOption('reviewer')
  await page.getByRole('button', { name: 'Start review' }).click()
  await expect(page.locator('.status', { hasText: 'Under review' }).first()).toBeVisible()
  await page.getByLabel('Note').fill('E2E: change visible in before/after crops.')
  await page.getByRole('button', { name: 'Confirm change' }).click()
  await expect(page.locator('.status', { hasText: 'Confirmed' }).first()).toBeVisible()
  await expect(page.getByText(/Hash chain intact · 3 events/)).toBeVisible()

  await page.goto('/analytics')
  const confirmed = page.locator('.kpi', { hasText: 'Confirmed' })
  await expect(confirmed.locator('.v')).toHaveText('1')

  await page.goto('/agent')
  await page.getByRole('button', { name: 'Run monitoring cycle' }).click()
  await expect(page.getByText(/Decision \(deterministic\)/)).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText(/Ran RUN-0002/)).toBeVisible()
})
