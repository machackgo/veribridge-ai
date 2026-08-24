import { expect, test } from "@playwright/test";

/**
 * Production smoke test — official VeriBridge AI launch film on the live
 * public homepage (https://veribridgeai.com).
 *
 * Runs against the real deployment across Chromium, WebKit/Safari and a
 * phone viewport. Covers the full definition-of-done: the hero and every
 * existing section survive, the film sits directly below the hero, the
 * poster loads, playback starts with real audio, the frame stays sharp and
 * uncropped, controls and fullscreen work, both CTAs route correctly, mobile
 * has no overflow, and nothing throws.
 */

const FILM = "/media/veribridge-ai-launch-film.mp4";
const POSTER = "/media/veribridge-ai-launch-film-poster.jpg";

test.describe("PROD — launch film", () => {
  test("1. existing hero, navigation and brand remain intact", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/VeriBridge/i);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/Prove them/i);
    await expect(page.getByRole("link", { name: /VeriBridge home/i })).toBeVisible();
    await expect(
      page.getByText(/Don't just claim your skills|Don’t just claim your skills/i).first(),
    ).toBeVisible();
  });

  test("2. film section sits directly below the hero, callout directly after", async ({ page }) => {
    await page.goto("/");
    const order = await page.evaluate(() =>
      Array.from(document.querySelectorAll("main > *")).map((el) => el.className || el.tagName),
    );
    const idx = (needle: string) => order.findIndex((c) => String(c).includes(needle));
    expect(idx("lv-film")).toBe(idx("lv-hero") + 1);
    expect(idx("lv-fair")).toBe(idx("lv-film") + 1);
  });

  test("3. poster loads and 4/6/7. film plays sharp, uncropped, with audio", async ({ page }) => {
    await page.goto("/");
    const posterRes = await page.request.get(POSTER);
    expect(posterRes.status()).toBe(200);

    await page.getByTestId("launch-film-play").click();
    const state = await page.evaluate(async () => {
      const v = document.querySelector<HTMLVideoElement>('[data-testid="launch-film-video"]')!;
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline && v.currentTime < 2) {
        await new Promise((r) => setTimeout(r, 250));
      }
      const box = v.getBoundingClientRect();
      return {
        currentTime: v.currentTime,
        paused: v.paused,
        muted: v.muted,
        volume: v.volume,
        videoWidth: v.videoWidth,
        videoHeight: v.videoHeight,
        duration: Math.round(v.duration),
        objectFit: getComputedStyle(v).objectFit,
        renderedWidth: box.width,
        renderedRatio: box.width / box.height,
        audioBytes:
          (v as unknown as { webkitAudioDecodedByteCount?: number })
            .webkitAudioDecodedByteCount ?? -1,
      };
    });

    // 4. plays
    expect(state.currentTime).toBeGreaterThan(1.5);
    expect(state.paused).toBe(false);
    // 5. audio is audible after Play — not muted, full volume, real audio stream
    expect(state.muted).toBe(false);
    expect(state.volume).toBe(1);
    if (state.audioBytes !== -1) expect(state.audioBytes).toBeGreaterThan(0);
    // 6. sharp — native 1920x1080 decoded, never upscaled past it
    expect(state.videoWidth).toBe(1920);
    expect(state.videoHeight).toBe(1080);
    expect(state.renderedWidth).toBeLessThanOrEqual(1920);
    // 7. uncropped, true 16:9
    expect(state.objectFit).toBe("contain");
    expect(Math.abs(state.renderedRatio - 16 / 9)).toBeLessThan(0.02);
    expect(state.duration).toBe(98);
  });

  test("8/9. timeline controls and fullscreen are available once playing", async ({ page }) => {
    await page.goto("/");
    const video = page.getByTestId("launch-film-video");
    await expect(video).not.toHaveAttribute("controls", "");
    await page.getByTestId("launch-film-play").click();
    await expect(video).toHaveAttribute("controls", "");

    const caps = await page.evaluate(async () => {
      const v = document.querySelector<HTMLVideoElement>('[data-testid="launch-film-video"]')!;
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline && !Number.isFinite(v.duration)) {
        await new Promise((r) => setTimeout(r, 250));
      }
      const el = v as unknown as Record<string, unknown>;
      return {
        seekable: v.seekable.length > 0,
        duration: v.duration,
        fullscreen:
          typeof el.requestFullscreen === "function" ||
          typeof el.webkitEnterFullscreen === "function" ||
          typeof el.webkitRequestFullscreen === "function",
      };
    });
    expect(caps.seekable).toBe(true); // scrubbing works (byte-range backed)
    expect(caps.fullscreen).toBe(true);
  });

  test("10/11. student and Career Fair CTAs route into the real onboarding flow", async ({ page }) => {
    await page.goto("/");
    const film = page.locator(".lv-film");
    await expect(film.getByRole("link", { name: /Build your Work Passport/i })).toHaveAttribute(
      "href",
      "/login?next=/dashboard",
    );
    await expect(film.getByRole("link", { name: /For Recruiters/i })).toHaveAttribute(
      "href",
      "/recruiters",
    );
    await expect(page.getByRole("link", { name: /Get Career-Fair Ready/i })).toHaveAttribute(
      "href",
      "/login?next=/dashboard",
    );
    // Actually navigate — the route must resolve, not 404/redirect-loop.
    await page.getByRole("link", { name: /Get Career-Fair Ready/i }).click();
    await page.waitForURL(/\/login/);
    expect(page.url()).toContain("/login");
  });

  test("12. mobile/tablet layout has no horizontal overflow", async ({ page }) => {
    await page.goto("/");
    await page.locator(".lv-film").scrollIntoViewIfNeeded();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    const box = await page.getByTestId("launch-film-video").boundingBox();
    const vw = page.viewportSize()!.width;
    expect(box!.width).toBeLessThanOrEqual(vw);
  });

  test("13. every existing homepage section below still renders", async ({ page }) => {
    await page.goto("/");
    for (const cls of [
      "lv-states",
      "lv-problem",
      "lv-how",
      "lv-passport-section",
      "lv-recruiter",
      "lv-honest",
      "lv-cta2",
      "lv-final",
    ]) {
      await expect(page.locator(`.${cls}`)).toHaveCount(1);
    }
    await expect(page.locator(".lv-footer")).toBeVisible();
  });

  test("14. no console or runtime errors on the homepage", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/", { waitUntil: "load" });
    await page.locator(".lv-fair").scrollIntoViewIfNeeded();
    await page.waitForTimeout(2000);
    expect(errors).toEqual([]);
  });

  test("15. analytics events fire once per interaction", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      (window as unknown as { __e: string[] }).__e = [];
      window.addEventListener("veribridge:landing-analytics", (ev) =>
        (window as unknown as { __e: string[] }).__e.push((ev as CustomEvent).detail.event),
      );
    });
    await page.locator(".lv-film").scrollIntoViewIfNeeded();
    await page.getByTestId("launch-film-play").click();
    await page.waitForTimeout(4000);
    const evts = await page.evaluate(() => (window as unknown as { __e: string[] }).__e);
    expect(evts).toContain("landing_launch_video_play");
    expect(evts.filter((e) => e === "landing_launch_video_play")).toHaveLength(1);
  });

  test("PERF. the film costs zero bytes until Play is pressed", async ({ page }) => {
    const hits: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("launch-film.mp4")) hits.push(r.url());
    });
    await page.goto("/", { waitUntil: "load" });
    await page.locator(".lv-film").scrollIntoViewIfNeeded();
    await page.waitForTimeout(3000);
    expect(hits).toHaveLength(0);
  });

  test("ASSET. production serves the film immutably with range support", async ({ page }) => {
    const res = await page.request.get(FILM, { headers: { Range: "bytes=0-2047" } });
    expect(res.status()).toBe(206);
    expect(res.headers()["content-type"]).toBe("video/mp4");
    expect(res.headers()["cache-control"]).toContain("immutable");
  });
});
