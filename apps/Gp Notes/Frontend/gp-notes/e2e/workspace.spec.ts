import { test, expect } from "@playwright/test";
import { SAMPLE_NOTE, SAMPLE_TEXT } from "../lib/notes";

test("sample, review, edit, export and clear work without persistence", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "considered draft",
  );
  await page.screenshot({
    path: testInfo.outputPath("workspace.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Explore sample draft" }).click();
  await expect(page.getByLabel(/^subjective$/i)).toHaveValue(
    SAMPLE_NOTE.subjective,
  );
  await page.screenshot({
    path: testInfo.outputPath("draft.png"),
    fullPage: true,
  });
  const downloadButton = page.getByRole("button", { name: "Download .txt" });
  await expect(downloadButton).toBeDisabled();
  const review = page.getByRole("checkbox", { name: /compared this draft/ });
  await review.check();
  await expect(downloadButton).toBeEnabled();
  await page.getByLabel(/^plan$/i).fill("Reviewed synthetic plan.");
  await expect(review).not.toBeChecked();
  await expect(downloadButton).toBeDisabled();
  await review.check();
  const downloadPromise = page.waitForEvent("download");
  await downloadButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("gp-notes-reviewed-draft.txt");
  expect(
    await page.evaluate(() => ({
      local: localStorage.length,
      session: sessionStorage.length,
    })),
  ).toEqual({ local: 0, session: 0 });
  await page.getByRole("button", { name: /Clear session/ }).click();
  await expect(page.getByLabel(/^subjective$/i)).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("live mode requires token and consent; server auth remains enforced", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Live workspace", exact: true })
    .click();
  await page.getByLabel("Source consultation").fill(SAMPLE_TEXT);
  const generate = page.getByRole("button", { name: "Create SOAP draft" });
  await expect(generate).toBeDisabled();
  await page
    .getByLabel("Workspace access token")
    .fill("wrong-token-but-longer-than-32-characters");
  await expect(generate).toBeDisabled();
  await page.getByRole("checkbox", { name: /synthetic content/ }).check();
  await generate.click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Enter a valid workspace access token." }),
  ).toHaveText("Enter a valid workspace access token.");
});
test("live response can be reviewed; source edits invalidate generated results", async ({
  page,
}) => {
  await page.route("**/api/normalize-note", (route) =>
    route.fulfill({
      json: { note: SAMPLE_NOTE, transcription: SAMPLE_TEXT, source: "live" },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Live workspace", exact: true })
    .click();
  await page
    .getByLabel("Workspace access token")
    .fill("e2e-synthetic-workspace-token-32-characters");
  await page.getByRole("checkbox", { name: /synthetic content/ }).check();
  await page.getByLabel("Source consultation").fill(SAMPLE_TEXT);
  await page.getByRole("button", { name: "Create SOAP draft" }).click();
  await expect(page.getByLabel(/^subjective$/i)).toHaveValue(
    SAMPLE_NOTE.subjective,
  );
  await page.getByLabel("Source consultation").fill("Changed source.");
  await expect(page.getByLabel(/^subjective$/i)).toHaveCount(0);
});
test("cancelled requests cannot repopulate cleared session", async ({
  page,
}) => {
  await page.route("**/api/normalize-note", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700));
    await route
      .fulfill({
        json: {
          note: SAMPLE_NOTE,
          transcription: SAMPLE_TEXT,
          source: "sample",
        },
      })
      .catch(() => {});
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Explore sample draft" }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Cancelled");
  await expect(page.getByLabel(/^subjective$/i)).toHaveCount(0);
});
test("refresh drops draft; legacy storage is cleared", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.setItem("clinicApiKey", "old-key");
    localStorage.setItem("consultationData", "old synthetic data");
  });
  await page.reload();
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await page.getByRole("button", { name: "Explore sample draft" }).click();
  await expect(page.getByLabel(/^plan$/i)).toBeVisible();
  await page.reload();
  await expect(page.getByLabel(/^plan$/i)).toHaveCount(0);
});

test("audio upload uses the live workflow and displays the returned transcript", async ({
  page,
}) => {
  let uploaded = false;
  await page.route("**/api/transcribe", (route) => {
    uploaded = route
      .request()
      .headers()
      ["content-type"].includes("multipart/form-data");
    return route.fulfill({
      json: { note: SAMPLE_NOTE, transcription: SAMPLE_TEXT, source: "live" },
    });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Live workspace", exact: true })
    .click();
  await page
    .getByLabel("Workspace access token")
    .fill("e2e-synthetic-workspace-token-32-characters");
  await page.getByRole("checkbox", { name: /synthetic content/ }).check();
  await page.getByRole("button", { name: "Voice & audio" }).click();
  await page.getByLabel("Upload audio").setInputFiles({
    name: "synthetic.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("mock audio only"),
  });
  await expect(page.getByLabel(/^subjective$/i)).toBeVisible();
  expect(uploaded).toBe(true);
  await page.getByRole("button", { name: "Written notes" }).click();
  await expect(page.getByLabel("Source consultation")).toHaveValue(SAMPLE_TEXT);
});

test("microphone streams stop when recording is cancelled", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const state = { stops: 0 };
    Object.defineProperty(window, "microphoneTest", { value: state });
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      value: async () => ({ getTracks: () => [{ stop: () => state.stops++ }] }),
    });
    class Recorder {
      static isTypeSupported() {
        return true;
      }
      state = "inactive";
      mimeType = "audio/webm";
      onstop: (() => void) | null = null;
      ondataavailable = null;
      start() {
        this.state = "recording";
      }
      stop() {
        this.state = "inactive";
        this.onstop?.();
      }
    }
    Object.defineProperty(window, "MediaRecorder", { value: Recorder });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Live workspace", exact: true })
    .click();
  await page
    .getByLabel("Workspace access token")
    .fill("e2e-synthetic-workspace-token-32-characters");
  await page.getByRole("checkbox", { name: /synthetic content/ }).check();
  await page.getByRole("button", { name: "Voice & audio" }).click();
  await page.getByRole("button", { name: "Start recording" }).click();
  await expect(
    page.getByRole("button", { name: "Stop & create draft" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { microphoneTest: { stops: number } })
          .microphoneTest.stops,
    ),
  ).toBe(1);
  await expect(
    page.getByRole("button", { name: "Start recording" }),
  ).toBeEnabled();
});
