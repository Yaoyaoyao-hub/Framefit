import { boxesAtPoint, containedRect, displayPointToNorm, normBoxToDisplay } from "./geometry";

const box = { x: 0.25, y: 0.25, width: 0.5, height: 0.5 };

describe("letterboxed bounding boxes", () => {
  it("offsets boxes when the image is letterboxed horizontally", () => {
    const container = { width: 200, height: 100 };
    const natural = { width: 100, height: 100 };
    const fit = containedRect(container, natural);
    expect(fit.offsetX).toBe(50);
    expect(fit.offsetY).toBe(0);
    expect(fit.width).toBe(100);
    const display = normBoxToDisplay({ x: 0, y: 0, width: 1, height: 1 }, container, natural);
    expect(display).toEqual({ left: 50, top: 0, width: 100, height: 100 });
  });

  it("offsets boxes when the image is letterboxed vertically", () => {
    const container = { width: 100, height: 200 };
    const natural = { width: 100, height: 100 };
    expect(containedRect(container, natural).offsetY).toBe(50);
    const display = normBoxToDisplay(box, container, natural);
    expect(display.top).toBe(75);
    expect(display.left).toBe(25);
    expect(display.width).toBe(50);
    expect(display.height).toBe(50);
  });

  it("scales boxes when the container grows", () => {
    const display = normBoxToDisplay(
      { x: 0.5, y: 0.5, width: 0.25, height: 0.25 },
      { width: 400, height: 200 },
      { width: 100, height: 100 },
    );
    expect(display).toEqual({ left: 200, top: 100, width: 50, height: 50 });
  });

  it("round-trips a displayed point back to image coordinates", () => {
    const container = { width: 300, height: 120 };
    const natural = { width: 150, height: 100 };
    const display = normBoxToDisplay(box, container, natural);
    const point = displayPointToNorm(display.left + display.width / 2, display.top + display.height / 2, container, natural);
    expect(point.x).toBeCloseTo(0.5);
    expect(point.y).toBeCloseTo(0.5);
  });

  it("returns every overlapping box under a click and ignores the matte", () => {
    const items = [
      { id: "hat", x: 0.2, y: 0.1, width: 0.4, height: 0.4 },
      { id: "jacket", x: 0.3, y: 0.2, width: 0.4, height: 0.4 },
    ];
    const container = { width: 200, height: 100 };
    const natural = { width: 100, height: 100 };
    const hit = normBoxToDisplay({ x: 0.35, y: 0.25, width: 0.01, height: 0.01 }, container, natural);
    const found = boxesAtPoint(items, hit.left, hit.top, container, natural);
    expect(found.map((item) => item.id)).toEqual(["hat", "jacket"]);
    expect(boxesAtPoint(items, 2, 2, container, natural)).toEqual([]);
  });
});
