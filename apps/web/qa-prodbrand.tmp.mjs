import { chromium, devices } from "@playwright/test";
const OUT = "/private/tmp/claude-501/-Users-mohammedmubashiruddinfaraz-veribridge-landing/05155df8-7ef5-4e8f-992f-c60a84066cc9/scratchpad";
const B = "https://veribridgeai.com";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", e => errors.push(String(e)));
for (const [name, path] of [["login", "/login"], ["passport", "/p/ZwC_0l8HutI"], ["rtoken", "/r/qa-brand-check"], ["extension", "/extension"]]) {
  await page.goto(B + path, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${OUT}/prodbrand-${name}.png` });
  console.log("ok", name);
}
console.log("pageerrors:", errors.length ? errors : "none");
await ctx.close(); await browser.close();
