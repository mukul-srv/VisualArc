import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

// Automated WCAG scan. Not proof of compliance: keyboard and snapshot checks stay manual.
// `known`: rule ids already failing on the untouched app (characterisation); each caller documents them.
export async function expectNoA11yViolations(page: Page, known: string[] = []) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
  expect(violations.filter((v) => !known.includes(v.id)).map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
}
