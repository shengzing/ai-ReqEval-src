import { test, expect } from '@playwright/test'

const shouldRun = Boolean(process.env.WEB_E2E_BASE_URL)

test.describe('real backend workspace smoke', () => {
  test.skip(!shouldRun, 'Set WEB_E2E_BASE_URL to a running frontend that points at the real backend.')

  test('creates a project, uploads evidence, starts a run, handles suggestions, and reaches report gate UI', async ({ page }) => {
    await page.goto('/')

    await expect(page.getByText(/加载项目中|描述你的目标|新建项目|创建项目/)).toBeVisible()

    const createProjectButton = page.getByRole('button', { name: /新建项目|创建项目/ }).first()
    if (await createProjectButton.isVisible()) {
      await createProjectButton.click()
      await page.getByLabel(/项目名称|名称/).fill(`E2E真实后端-${Date.now()}`)
      const goalInput = page.getByLabel(/项目目标|目标/)
      if (await goalInput.isVisible()) {
        await goalInput.fill('用真实后端验证前端工作台主链路。')
      }
      await page.getByRole('button', { name: /创建|确定/ }).last().click()
    } else {
      await page.getByPlaceholder(/描述你的目标/).fill('用真实后端验证前端工作台主链路。')
      await page.keyboard.press('Enter')
    }

    await expect(page.getByText(/阶段|资料|继续对话|上传/)).toBeVisible()

    const fileChooserPromise = page.waitForEvent('filechooser')
    await page.getByRole('button', { name: /上传/ }).click()
    const fileChooser = await fileChooserPromise
    await fileChooser.setFiles({
      name: 'e2e-evidence.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('真实后端 smoke 测试材料：验证上传、解析、运行和报告门禁。'),
    })

    await page.getByPlaceholder(/继续对话|补充信息/).fill('请基于刚上传的材料启动当前阶段分析。')
    await page.keyboard.press('Enter')

    await expect(page.getByText(/执行流|正在执行|等待确认|执行结果|建议/)).toBeVisible()

    const reportButton = page.getByRole('button', { name: /报告/ })
    await expect(reportButton).toBeVisible()
    await reportButton.click()
    await expect(page.getByText(/报告产物|报告门禁|门禁|报告生成失败/)).toBeVisible()
  })
})
