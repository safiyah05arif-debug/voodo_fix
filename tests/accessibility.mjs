import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const baseUrl = process.env.CIVIX_BASE_URL || 'http://127.0.0.1:8000/';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
const results = await page.goto(baseUrl, { waitUntil: 'networkidle' }).then(() => new AxeBuilder({ page }).analyze());

if (results.violations.length) {
    for (const violation of results.violations) {
        console.error(`${violation.id}: ${violation.help}`);
        for (const node of violation.nodes) console.error(`  ${node.html}`);
    }
    await browser.close();
    process.exit(1);
}

console.log(`Accessibility audit passed: ${results.passes.length} rules passed.`);
await browser.close();
