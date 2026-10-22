import { expect, test, type Page } from "@playwright/test";

test("demo journey keeps branches through reload and product try-on", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("demo-badge")).toBeVisible();
  await page.getByTestId("personal-photo-input").setInputFiles({
    name: "person.jpg",
    mimeType: "image/jpeg",
    buffer: await jpeg(page, 720, 960, "#c9b2a2"),
  });
  await expect(page.getByTestId("active-label")).toContainText("Original");
  await page.getByTestId("inspiration-input").setInputFiles({
    name: "look.jpg",
    mimeType: "image/jpeg",
    buffer: await jpeg(page, 640, 860, "#2f3b4a"),
  });
  await page.getByRole("button", { name: "Hat 91%" }).click();
  await page.getByTestId("try-on").click();
  await expect(page.getByRole("button", { name: "Saved version: Hat", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Outerwear 86%" }).click();
  await page.getByTestId("try-on").click();
  await expect(page.getByRole("button", { name: "Saved version: Outerwear", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Saved version: Hat", exact: true }).click();
  await page.getByTestId("continue-from-here").click();
  await expect(page.getByTestId("active-label")).toContainText("Hat");
  await page.getByRole("button", { name: "Shoes 84%" }).click();
  await page.getByTestId("try-on").click();
  await expect(page.getByRole("button", { name: "Saved version: Shoes", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Saved version: Outerwear", exact: true })).toBeVisible();
  await page.getByTestId("undo").click();
  await expect(page.getByTestId("active-label")).toContainText("Hat");
  await page.getByTestId("reset").click();
  await expect(page.getByTestId("active-label")).toContainText("Original");
  await page.reload();
  await expect(page.getByTestId("demo-badge")).toBeVisible();
  await expect(page.getByTestId("active-label")).toContainText("Original");
  await expect(page.getByRole("button", { name: "Saved version: Hat", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Saved version: Outerwear", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Saved version: Shoes", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Hat 91%" }).click();
  await page.getByTestId("search").click();
  await expect(page.getByTestId("product-card").first()).toBeVisible();
  await expect(page.getByText("Check price").first()).toBeVisible();
  await expect(page.getByText("Similar style").first()).toBeVisible();
  const productLink = page.getByTestId("open-product").first();
  await expect(productLink).toHaveAttribute("href", /^https:\/\/example.com\/products\//);
  await page.getByTestId("try-product").first().click();
  await expect(page.getByRole("button", { name: "Saved version: Hat · product" })).toBeVisible();
});

test("shared tab capture can be cropped and cancelled tracks stop", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getDisplayMedia = async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 320;
      canvas.height = 180;
      const context = canvas.getContext("2d");
      context?.fillRect(0, 0, 320, 180);
      const stream = canvas.captureStream(8);
      (window as unknown as { __tracks?: MediaStreamTrack[] }).__tracks = stream.getTracks();
      return stream;
    };
  });
  await page.goto("/");
  await page.getByTestId("personal-photo-input").setInputFiles({
    name: "person.jpg",
    mimeType: "image/jpeg",
    buffer: await jpeg(page, 480, 640, "#eadfce"),
  });
  await expect(page.getByText("Pause the video")).toBeVisible();
  await page.getByTestId("share-tab").click();
  await expect(page.getByTestId("tab-preview")).toBeVisible();
  await page.getByTestId("confirm-tab").click();
  await expect(page.getByRole("img", { name: "Inspiration" })).toBeVisible();
  const stopped = await page.evaluate(() => {
    const tracks = (window as unknown as { __tracks?: MediaStreamTrack[] }).__tracks ?? [];
    return tracks.every((track) => track.readyState === "ended");
  });
  expect(stopped).toBe(true);
});

async function jpeg(page: Page, width: number, height: number, color: string) {
  const bytes = await page.evaluate(
    async ({ width, height, color }) => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("canvas");
      context.fillStyle = color;
      context.fillRect(0, 0, width, height);
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((value) => (value ? resolve(value) : reject(new Error("blob"))), "image/jpeg", 0.9);
      });
      return Array.from(new Uint8Array(await blob.arrayBuffer()));
    },
    { width, height, color },
  );
  return Buffer.from(bytes);
}
