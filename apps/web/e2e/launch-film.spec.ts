import { expect, test } from "@playwright/test";

/* ── Landing page — official VeriBridge AI launch film ── */

const FILM = "/media/veribridge-ai-launch-film.mp4";

test.describe("Launch film section", () => {
  test("sits directly below the hero and keeps the hero intact", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/Prove them/i);

    const order = await page.evaluate(() => {
      const sections = Array.from(document.querySelectorAll("main > section, main > *"));
      return sections.map((el) => el.className || el.tagName);
    });
    const hero = order.findIndex((c) => String(c).includes("lv-hero"));
    const film = order.findIndex((c) => String(c).includes("lv-film"));
    const fair = order.findIndex((c) => String(c).includes("lv-fair"));
    const states = order.findIndex((c) => String(c).includes("lv-states"));
    expect(hero).toBeGreaterThanOrEqual(0);
    expect(film).toBe(hero + 1);
    expect(fair).toBe(film + 1);
    expect(states).toBe(fair + 1);
  });

  test("costs zero film bytes until the visitor presses Play", async ({ page }) => {
    const filmRequests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("launch-film.mp4")) filmRequests.push(r.url());
    });
    await page.goto("/", { waitUntil: "load" });
    await page.getByTestId("launch-film-video").scrollIntoViewIfNeeded();
    await page.waitForTimeout(1500);
    expect(filmRequests).toHaveLength(0);
  });

  test("poster is the approved 16:9 thumbnail and loads", async ({ page }) => {
    await page.goto("/");
    const video = page.getByTestId("launch-film-video");
    await expect(video).toHaveAttribute("poster", /launch-film-poster\.jpg$/);
    const res = await page.request.get(
      "/media/veribridge-ai-launch-film-poster.jpg",
    );
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("image/jpeg");
  });

  test("plays the real 1920x1080 film with an audio track, uncropped", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("launch-film-play").click();

    const state = await page.evaluate(async () => {
      const v = document.querySelector<HTMLVideoElement>('[data-testid="launch-film-video"]')!;
      const deadline = Date.now() + 25000;
      while (Date.now() < deadline && v.currentTime < 1.5) {
        await new Promise((r) => setTimeout(r, 200));
      }
      return {
        currentTime: v.currentTime,
        paused: v.paused,
        muted: v.muted,
        volume: v.volume,
        videoWidth: v.videoWidth,
        videoHeight: v.videoHeight,
        duration: Math.round(v.duration),
        objectFit: getComputedStyle(v).objectFit,
        // Chromium-only: proof the decoder is consuming a real audio stream.
        audioBytes:
          (v as unknown as { webkitAudioDecodedByteCount?: number })
            .webkitAudioDecodedByteCount ?? -1,
      };
    });

    expect(state.currentTime).toBeGreaterThan(1);
    expect(state.paused).toBe(false);
    expect(state.muted).toBe(false);
    expect(state.volume).toBe(1);
    expect(state.videoWidth).toBe(1920);
    expect(state.videoHeight).toBe(1080);
    expect(state.duration).toBe(98);
    expect(state.objectFit).toBe("contain");
    if (state.audioBytes !== -1) expect(state.audioBytes).toBeGreaterThan(0);
  });

  test("the film is never upscaled past its native resolution", async ({ page }) => {
    await page.goto("/");
    const box = await page.getByTestId("launch-film-video").boundingBox();
    expect(box!.width).toBeLessThanOrEqual(1920);
    // 16:9 within a pixel of rounding
    expect(Math.abs(box!.width / box!.height - 16 / 9)).toBeLessThan(0.02);
  });

  test("native controls, inline playback and keyboard focus are present", async ({ page }) => {
    await page.goto("/");
    const video = page.getByTestId("launch-film-video");
    const play = page.getByTestId("launch-film-play");

    // ── Poster state: one labelled, keyboard-reachable play affordance ──
    await expect(video).toHaveAttribute("playsinline", "");
    await expect(video).toHaveAttribute("preload", "none");
    await expect(video).not.toHaveAttribute("controls", "");
    await expect(play).toHaveAttribute("aria-label", /Play the VeriBridge AI launch film/i);
    await play.focus();
    await expect(play).toBeFocused();

    // ── Playing state: the overlay yields to the browser's own controls ──
    await play.click();
    await expect(video).toHaveAttribute("controls", "");
    await expect(play).toHaveCount(0);

    // Fullscreen is reachable. Safari/WebKit exposes webkitEnterFullscreen on
    // the media element instead of the standard requestFullscreen; the native
    // control bar's fullscreen button uses whichever the engine provides.
    expect(
      await page.evaluate(() => {
        const v = document.querySelector<HTMLVideoElement>('[data-testid="launch-film-video"]')!;
        const el = v as unknown as Record<string, unknown>;
        return (
          typeof el.requestFullscreen === "function" ||
          typeof el.webkitEnterFullscreen === "function" ||
          typeof el.webkitRequestFullscreen === "function"
        );
      }),
    ).toBe(true);
  });

  test("section copy is crawlable HTML", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("SEE VERIBRIDGE AI IN ACTION")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Your résumé starts the conversation/i }),
    ).toBeVisible();
    await expect(
      page.getByText(/carry that proof into career fairs, interviews, networking events/i),
    ).toBeVisible();
  });

  test("CTAs route into the existing student and recruiter flows", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.locator(".lv-film").getByRole("link", { name: /Build your Work Passport/i }),
    ).toHaveAttribute("href", "/login?next=/dashboard");
    await expect(
      page.locator(".lv-film").getByRole("link", { name: /For Recruiters/i }),
    ).toHaveAttribute("href", "/recruiters");
    await expect(
      page.getByRole("link", { name: /Get Career-Fair Ready/i }),
    ).toHaveAttribute("href", "/login?next=/dashboard");
  });

  test("Career Fair callout renders and does not read as career-fair-only", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Going to a Fall Career Fair\?/i }),
    ).toBeVisible();
    await expect(page.getByText(/What did you actually build\?/i)).toBeVisible();
    await expect(
      page.getByText(/interviews, networking events, conferences, hackathons/i),
    ).toBeVisible();
  });

  test("no horizontal overflow and no console errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto("/");
    await page.getByTestId("launch-film-video").scrollIntoViewIfNeeded();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    expect(errors).toEqual([]);
  });

  test("analytics fire once per event", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => {
      (window as unknown as { __evts: string[] }).__evts = [];
      window.addEventListener("veribridge:landing-analytics", (e) => {
        (window as unknown as { __evts: string[] }).__evts.push(
          (e as CustomEvent).detail.event,
        );
      });
    });
    await page.getByTestId("launch-film-video").scrollIntoViewIfNeeded();
    await page.getByTestId("launch-film-play").click();
    await page.waitForTimeout(2500);
    const evts = await page.evaluate(
      () => (window as unknown as { __evts: string[] }).__evts,
    );
    expect(evts).toContain("landing_launch_video_play");
    expect(evts.filter((e) => e === "landing_launch_video_play")).toHaveLength(1);
  });

  test("the film asset is served with byte-range support", async ({ page }) => {
    const res = await page.request.get(FILM, { headers: { Range: "bytes=0-1023" } });
    expect(res.status()).toBe(206);
    expect(res.headers()["content-type"]).toBe("video/mp4");
  });
});
