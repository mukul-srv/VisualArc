import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

// Automated WCAG scan. Not proof of compliance: keyboard and snapshot checks stay manual.
export async function expectNoA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}
