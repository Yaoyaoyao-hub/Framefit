export type NormBox = { x: number; y: number; width: number; height: number };
export type Size = { width: number; height: number };
export type DisplayRect = { left: number; top: number; width: number; height: number };

export function containedRect(container: Size, natural: Size) {
  const scale = Math.min(container.width / natural.width, container.height / natural.height);
  const width = natural.width * scale;
  const height = natural.height * scale;
  return {
    offsetX: (container.width - width) / 2,
    offsetY: (container.height - height) / 2,
    width,
    height,
    scale,
  };
}

export function normBoxToDisplay(box: NormBox, container: Size, natural: Size): DisplayRect {
  const fit = containedRect(container, natural);
  return {
    left: fit.offsetX + box.x * fit.width,
    top: fit.offsetY + box.y * fit.height,
    width: box.width * fit.width,
    height: box.height * fit.height,
  };
}

export function displayPointToNorm(px: number, py: number, container: Size, natural: Size) {
  const fit = containedRect(container, natural);
  return {
    x: (px - fit.offsetX) / fit.width,
    y: (py - fit.offsetY) / fit.height,
  };
}

export function pointInsideImage(px: number, py: number, container: Size, natural: Size) {
  const fit = containedRect(container, natural);
  return px >= fit.offsetX && py >= fit.offsetY && px <= fit.offsetX + fit.width && py <= fit.offsetY + fit.height;
}

export function boxesAtPoint<T extends NormBox>(items: T[], px: number, py: number, container: Size, natural: Size): T[] {
  if (!pointInsideImage(px, py, container, natural)) return [];
  const point = displayPointToNorm(px, py, container, natural);
  return items.filter(
    (item) => point.x >= item.x && point.y >= item.y && point.x <= item.x + item.width && point.y <= item.y + item.height,
  );
}

export function clampBox(box: NormBox): NormBox {
  const x = Math.min(Math.max(box.x, 0), 0.98);
  const y = Math.min(Math.max(box.y, 0), 0.98);
  const width = Math.min(Math.max(box.width, 0.02), 1 - x);
  const height = Math.min(Math.max(box.height, 0.02), 1 - y);
  return { x, y, width, height };
}
