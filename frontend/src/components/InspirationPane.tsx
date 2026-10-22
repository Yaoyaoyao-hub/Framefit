import { ImagePlus, Share2, SquareDashed, Upload } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { mediaUrl } from "../api";
import { blobToCanvas, canvasToBlob, captureVideoFrame, cropCanvas, stopStream, supportsTabCapture } from "../capture";
import { boxesAtPoint, clampBox, normBoxToDisplay, pointInsideImage, displayPointToNorm } from "../geometry";
import { useStore } from "../store";
import type { Item, NormBox } from "../types";

export function InspirationPane() {
  const frame = useStore((state) => state.frame);
  const session = useStore((state) => state.session);
  const capabilities = useStore((state) => state.capabilities);
  const selectedItemId = useStore((state) => state.selectedItemId);
  const busy = useStore((state) => state.busy);
  const importInspiration = useStore((state) => state.importInspiration);
  const useSampleInspiration = useStore((state) => state.useSampleInspiration);
  const detect = useStore((state) => state.detect);
  const addItem = useStore((state) => state.addItem);
  const updateItem = useStore((state) => state.updateItem);
  const selectItem = useStore((state) => state.selectItem);
  const search = useStore((state) => state.search);
  const tryInspiration = useStore((state) => state.tryInspiration);
  const imageRef = useRef<HTMLImageElement>(null);
  const [size, setSize] = useState({ width: 1, height: 1 });
  const [drawing, setDrawing] = useState(false);
  const [draft, setDraft] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const [pendingCategory, setPendingCategory] = useState("jacket");
  const [chooser, setChooser] = useState<{ items: Item[]; left: number; top: number } | null>(null);
  const drag = useRef<{ id: string; handle: string; startX: number; startY: number; box: Item } | null>(null);
  const drawStart = useRef<{ x: number; y: number } | null>(null);
  const cropImageRef = useRef<HTMLImageElement>(null);
  const cropStart = useRef<{ x: number; y: number } | null>(null);
  const [pending, setPending] = useState<{ canvas: HTMLCanvasElement; url: string; kind: "upload" | "tab_capture" } | null>(null);
  const [shotCrop, setShotCrop] = useState<NormBox | null>(null);
  const [cropSize, setCropSize] = useState({ width: 1, height: 1 });
  const [tabMessage, setTabMessage] = useState<string | null>(null);
  const shown = keepBestItems(frame?.items ?? []);
  const selected = shown.find((item) => item.id === selectedItemId) ?? null;

  async function chooseTab() {
    setTabMessage(null);
    try {
      const options = {
        video: { displaySurface: "browser" },
        audio: false,
        preferCurrentTab: false,
        selfBrowserSurface: "exclude",
        monitorTypeSurfaces: "exclude",
      } as DisplayMediaStreamOptions;
      const next = await navigator.mediaDevices.getDisplayMedia(options);
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.srcObject = next;
      document.body.appendChild(video);
      let canvas: HTMLCanvasElement;
      try {
        await video.play();
        canvas = await captureVideoFrame(video);
      } finally {
        stopStream(next);
        video.remove();
      }
      await showPending(canvas, "tab_capture");
    } catch {
      setTabMessage("The browser did not share a tab. Pause the video, then choose that tab again, or upload a screenshot.");
    }
  }

  async function stageScreenshot(file: Blob) {
    setTabMessage(null);
    try {
      await showPending(await blobToCanvas(file), "upload");
    } catch {
      setTabMessage("That image could not be opened. Use a JPEG, PNG, or WebP.");
    }
  }

  async function showPending(canvas: HTMLCanvasElement, kind: "upload" | "tab_capture") {
    const url = URL.createObjectURL(await canvasToBlob(canvas));
    setPending((current) => {
      if (current) URL.revokeObjectURL(current.url);
      return { canvas, url, kind };
    });
    setShotCrop(null);
  }

  function clearPending() {
    setPending((current) => {
      if (current) URL.revokeObjectURL(current.url);
      return null;
    });
    setShotCrop(null);
    cropStart.current = null;
  }

  async function finishShot(useCrop: boolean) {
    if (!pending) return;
    const box = shotCrop;
    const cropped = useCrop && box && box.width > 0.02 && box.height > 0.02;
    const source = cropped && box ? cropCanvas(pending.canvas, box) : pending.canvas;
    const blob = await canvasToBlob(source);
    const kind = pending.kind;
    clearPending();
    await importInspiration(blob, kind);
  }

  function cropPoint(event: ReactPointerEvent) {
    const rect = cropImageRef.current!.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function onCropDown(event: ReactPointerEvent) {
    if (!pending || !cropImageRef.current) return;
    const point = cropPoint(event);
    const natural = { width: pending.canvas.width, height: pending.canvas.height };
    if (!pointInsideImage(point.x, point.y, cropSize, natural)) return;
    const norm = displayPointToNorm(point.x, point.y, cropSize, natural);
    cropStart.current = norm;
    setShotCrop({ x: norm.x, y: norm.y, width: 0.02, height: 0.02 });
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Dragging still updates the box when the browser will not capture the pointer.
    }
  }

  function onCropMove(event: ReactPointerEvent) {
    if (!pending || !cropStart.current) return;
    const point = cropPoint(event);
    const natural = { width: pending.canvas.width, height: pending.canvas.height };
    const norm = displayPointToNorm(point.x, point.y, cropSize, natural);
    const origin = cropStart.current;
    setShotCrop(clampBox({
      x: Math.min(origin.x, norm.x),
      y: Math.min(origin.y, norm.y),
      width: Math.abs(norm.x - origin.x),
      height: Math.abs(norm.y - origin.y),
    }));
  }

  function onCropUp() {
    cropStart.current = null;
  }

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const file = Array.from(event.clipboardData?.files ?? []).find((item) => /image\/(jpeg|png|webp)/.test(item.type));
      if (file) void stageScreenshot(file);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [importInspiration]);

  useEffect(() => {
    if (!frame || !selectedItemId) return;
    const visible = keepBestItems(frame.items);
    if (visible.some((item) => item.id === selectedItemId)) return;
    const hidden = frame.items.find((item) => item.id === selectedItemId);
    const replacement = visible.find((item) => item.label === hidden?.label) ?? visible[0];
    if (replacement) selectItem(replacement.id);
  }, [frame, selectedItemId, selectItem]);

  function measure() {
    const rect = imageRef.current?.getBoundingClientRect();
    if (rect) setSize({ width: rect.width, height: rect.height });
  }

  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [frame?.image_url]);

  const natural = { width: frame?.width || 1, height: frame?.height || 1 };
  const prompts = capabilities?.prompts ?? [];

  function localPoint(event: ReactPointerEvent) {
    const rect = imageRef.current!.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top, rect };
  }

  function onPointerDown(event: ReactPointerEvent) {
    if (!frame || !imageRef.current) return;
    const point = localPoint(event);
    if (!pointInsideImage(point.x, point.y, size, natural)) return;
    if (drawing) {
      const norm = displayPointToNorm(point.x, point.y, size, natural);
      drawStart.current = norm;
      setDraft({ x: norm.x, y: norm.y, width: 0.02, height: 0.02 });
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    const hits = boxesAtPoint(shown, point.x, point.y, size, natural);
    if (hits.length > 1) setChooser({ items: hits, left: point.x, top: point.y });
    else if (hits[0]) {
      selectItem(hits[0].id);
      setChooser(null);
    }
  }

  function onPointerMove(event: ReactPointerEvent) {
    if (!imageRef.current) return;
    const point = localPoint(event);
    if (drawing && drawStart.current) {
      const norm = displayPointToNorm(point.x, point.y, size, natural);
      const origin = drawStart.current;
      setDraft(clampBox({ x: Math.min(origin.x, norm.x), y: Math.min(origin.y, norm.y), width: Math.abs(norm.x - origin.x), height: Math.abs(norm.y - origin.y) }));
      return;
    }
    const active = drag.current;
    if (!active) return;
    const dx = (point.x - active.startX) / size.width;
    const dy = (point.y - active.startY) / size.height;
    const next = { ...active.box };
    if (active.handle.includes("e")) next.width = active.box.width + dx;
    if (active.handle.includes("s")) next.height = active.box.height + dy;
    if (active.handle.includes("w")) {
      next.x = active.box.x + dx;
      next.width = active.box.width - dx;
    }
    if (active.handle.includes("n")) {
      next.y = active.box.y + dy;
      next.height = active.box.height - dy;
    }
    if (active.handle === "move") {
      next.x = active.box.x + dx;
      next.y = active.box.y + dy;
    }
    const clamped = clampBox(next);
    useStore.setState({
      frame: frame && {
        ...frame,
        items: frame.items.map((item) => (item.id === active.id ? { ...item, ...clamped } : item)),
      },
    });
  }

  function onPointerUp() {
    if (drawing && draft && draft.width > 0.02 && draft.height > 0.02) return;
    const active = drag.current;
    drag.current = null;
    if (!active || !frame) return;
    const item = frame.items.find((entry) => entry.id === active.id);
    if (!item) return;
    void updateItem(item.id, { x: item.x, y: item.y, width: item.width, height: item.height });
  }

  return (
    <section className="flex min-h-[70vh] flex-col gap-4" aria-label="Inspiration">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Inspiration</p>
          <h2 className="font-display text-3xl">What caught your eye</h2>
        </div>
        {capabilities?.mode !== "real" && (
          <button className="btn" type="button" onClick={() => void useSampleInspiration()} disabled={!session || !!busy}>
            Use sample inspiration
          </button>
        )}
      </div>
      <div
        className="relative flex-1 rounded-[28px] border border-line bg-[#fbf7f2]"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          const file = event.dataTransfer.files?.[0];
          if (file) void stageScreenshot(file);
        }}
      >
        {pending && (
          <div className="flex h-full min-h-[420px] flex-col items-center justify-center gap-3 px-6 pb-4 text-center">
            <p className="max-w-md text-sm text-stone-600">Drag a box around the clothes. Crop before detection, or use the whole picture.</p>
            <div className="relative w-full" onPointerDown={onCropDown} onPointerMove={onCropMove} onPointerUp={onCropUp}>
              <img
                ref={cropImageRef}
                data-testid="tab-preview"
                src={pending.url}
                alt="Screenshot to crop"
                className="h-[56vh] min-h-[420px] w-full object-contain"
                onLoad={() => {
                  const rect = cropImageRef.current?.getBoundingClientRect();
                  if (rect) setCropSize({ width: rect.width, height: rect.height });
                }}
              />
              {shotCrop && (
                <div
                  className="pointer-events-none absolute border-2 border-dashed border-clay bg-clay/15"
                  style={normBoxToDisplay(shotCrop, cropSize, { width: pending.canvas.width, height: pending.canvas.height })}
                />
              )}
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              <button data-testid="confirm-tab" className="btn" type="button" onClick={() => void finishShot(false)}>
                Use the whole picture
              </button>
              <button
                data-testid="apply-crop"
                className="btn btn-primary"
                type="button"
                disabled={!shotCrop || shotCrop.width <= 0.02 || shotCrop.height <= 0.02}
                onClick={() => void finishShot(true)}
              >
                Crop and detect
              </button>
              <button className="btn" type="button" onClick={clearPending}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {!frame && !pending && (
          <div className="flex h-full min-h-[420px] flex-col items-center justify-center gap-4 px-6 text-center">
            <ImagePlus aria-hidden />
            <p className="max-w-sm text-lg">Drop a screenshot, paste one, or upload a JPEG, PNG, or WebP.</p>
            <p className="max-w-sm text-sm text-stone-600">Or pause the video on the clothes you want, then screenshot that browser tab.</p>
            <div className="flex flex-wrap justify-center gap-2">
              <label className="btn btn-primary">
                <Upload size={16} aria-hidden /> Upload screenshot
                <input
                  data-testid="inspiration-input"
                  className="hidden"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void stageScreenshot(file);
                    event.target.value = "";
                  }}
                />
              </label>
              <button data-testid="share-tab" className="btn" type="button" disabled={!supportsTabCapture()} onClick={() => void chooseTab()}>
                <Share2 size={16} aria-hidden /> Screenshot a browser tab
              </button>
            </div>
            {!supportsTabCapture() && <p className="text-sm">This browser cannot share a tab. You can upload a screenshot instead.</p>}
            {tabMessage && <p className="text-sm">{tabMessage}</p>}
          </div>
        )}
        {frame && !pending && (
          <div className="relative min-h-[420px]" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}>
            <img
              ref={imageRef}
              src={mediaUrl(frame.image_url)}
              alt="Inspiration"
              className="h-[56vh] min-h-[420px] w-full object-contain"
              onLoad={measure}
            />
            <div className="pointer-events-none absolute inset-0">
              {shown.map((item) => {
                const rect = normBoxToDisplay(item, size, natural);
                const active = item.id === selectedItemId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`pointer-events-auto absolute border-2 text-left text-xs ${active ? "z-10 border-clay bg-clay/10" : "border-white/90 bg-black/10"}`}
                    style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
                    aria-label={`Select ${item.label}`}
                    data-testid={`item-${item.category_prompt}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      selectItem(item.id);
                    }}
                    onPointerDown={(event) => {
                      if (!active) return;
                      event.stopPropagation();
                      drag.current = { id: item.id, handle: "move", startX: localPoint(event).x, startY: localPoint(event).y, box: item };
                    }}
                  >
                    <span className="absolute left-1 top-1 rounded-full bg-white/90 px-2 py-0.5">{item.label}</span>
                    {active &&
                      ["nw", "ne", "sw", "se"].map((handle) => (
                        <span
                          key={handle}
                          className="pointer-events-auto absolute h-3 w-3 rounded-full border border-clay bg-white"
                          style={{
                            left: handle.includes("w") ? -6 : undefined,
                            right: handle.includes("e") ? -6 : undefined,
                            top: handle.includes("n") ? -6 : undefined,
                            bottom: handle.includes("s") ? -6 : undefined,
                          }}
                          onPointerDown={(event) => {
                            event.stopPropagation();
                            drag.current = { id: item.id, handle, startX: localPoint(event).x, startY: localPoint(event).y, box: item };
                          }}
                        />
                      ))}
                  </button>
                );
              })}
              {draft && (
                <div
                  className="absolute border-2 border-dashed border-clay"
                  style={normBoxToDisplay(draft, size, natural)}
                />
              )}
            </div>
            {chooser && (
              <div role="dialog" aria-label="Choose an overlapping item" className="absolute z-10 rounded-2xl bg-white p-2 shadow-lg" style={{ left: chooser.left, top: chooser.top }}>
                {chooser.items.map((item) => (
                  <button key={item.id} className="btn mb-1 w-full" type="button" onClick={() => { selectItem(item.id); setChooser(null); }}>
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {busy && <p className="absolute bottom-4 left-4 rounded-full bg-white px-3 py-1 text-sm shadow">{busy}</p>}
      </div>
      {frame && tabMessage && <p className="text-sm">{tabMessage}</p>}
      {frame && !pending && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="w-full text-xs uppercase tracking-[0.16em] text-stone-500">Replace this picture</p>
          <label className="btn">
            <Upload size={16} aria-hidden /> Upload screenshot
            <input
              data-testid="inspiration-input"
              className="hidden"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void stageScreenshot(file);
                event.target.value = "";
              }}
            />
          </label>
          <button data-testid="share-tab" className="inline-flex items-center gap-2 rounded-full border border-dashed border-stone-400 bg-transparent px-4 py-2 text-sm text-stone-700 hover:border-ink hover:text-ink disabled:cursor-not-allowed disabled:opacity-45" type="button" disabled={!supportsTabCapture() || !!busy} onClick={() => void chooseTab()}>
            <Share2 size={16} aria-hidden /> Screenshot a browser tab
          </button>
        </div>
      )}
      {!pending && <div className="flex flex-wrap items-center gap-2">
        <button className="btn" type="button" onClick={() => void detect()} disabled={!frame || !capabilities?.detection.available || !!busy}>
          Find items
        </button>
        <button className={`btn ${drawing ? "btn-primary" : ""}`} type="button" onClick={() => { setDrawing((value) => !value); setDraft(null); }} disabled={!frame}>
          <SquareDashed size={16} aria-hidden /> {drawing ? "Drawing" : "Draw a box"}
        </button>
        {drawing && draft && (
          <>
            <label className="text-sm">
              Category
              <select className="ml-2 rounded-xl border border-line bg-white px-3 py-2" value={pendingCategory} onChange={(event) => setPendingCategory(event.target.value)}>
                {prompts.map((prompt) => (
                  <option key={prompt} value={prompt}>{promptName(prompt)}</option>
                ))}
              </select>
            </label>
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => {
                void addItem({ category: pendingCategory, ...clampBox(draft) });
                setDraft(null);
                setDrawing(false);
              }}
            >
              Save box
            </button>
          </>
        )}
      </div>}
      {selected && !pending && (
        <label className="grid w-full max-w-xs gap-1 text-xs uppercase tracking-[0.16em] text-stone-500">
          Correct category
          <select
            className="rounded-xl border border-line bg-white px-3 py-2 text-sm font-medium normal-case tracking-normal text-ink"
            value={selected.category_prompt}
            aria-label="Correct category"
            onChange={(event) => void updateItem(selected.id, { category: event.target.value })}
          >
            {prompts.map((prompt) => (
              <option key={prompt} value={prompt}>{promptName(prompt)}</option>
            ))}
          </select>
        </label>
      )}
      {frame && !pending && (
      <div className="grid gap-2">
        <p className="text-xs uppercase tracking-[0.16em] text-stone-500">Marked on the picture</p>
        <ul className="flex flex-wrap gap-2" aria-label="Detected items">
          {shown.map((item) => {
            const active = item.id === selectedItemId;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={`inline-flex items-center gap-2 rounded-2xl border px-3 py-2 text-sm ${active ? "border-clay bg-clay text-white" : "border-transparent bg-white text-ink shadow-sm hover:border-line"}`}
                  onClick={() => selectItem(item.id)}
                >
                  <span className="font-medium">{item.label}</span>
                  {item.confidence != null && (
                    <span className={`rounded-full px-2 py-0.5 text-xs ${active ? "bg-white/20" : "bg-paper text-stone-500"}`}>
                      {Math.round(item.confidence * 100)}%
                    </span>
                  )}
                  {item.manual && <span className={`text-xs ${active ? "text-white/80" : "text-stone-500"}`}>Drawn</span>}
                </button>
              </li>
            );
          })}
          {shown.length === 0 && <li className="text-sm text-stone-600">Nothing was marked automatically. Draw a box around an item.</li>}
        </ul>
      </div>
      )}
      {!pending && <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <button data-testid="try-on" className="btn btn-primary px-5" type="button" disabled={!selected || !capabilities?.try_on.available || !!busy} onClick={() => void tryInspiration()}>
          Try on
        </button>
        <button data-testid="search" className="btn bg-transparent" type="button" disabled={!selected || !capabilities?.search.available || !!busy} onClick={() => void search()}>
          Find similar products
        </button>
      </div>}
      {!capabilities?.detection.available && <p className="text-sm text-stone-600">{capabilities?.detection.detail}</p>}
      {frame?.source_url && (
        <a className="text-sm underline" href={frame.source_url} target="_blank" rel="noreferrer">
          Source link
        </a>
      )}
    </section>
  );
}

function keepBestItems(items: Item[]): Item[] {
  const manual: Item[] = [];
  const best = new Map<string, Item>();
  for (const item of items) {
    if (item.manual) {
      manual.push(item);
      continue;
    }
    const current = best.get(item.label);
    if (!current || (item.confidence ?? 0) > (current.confidence ?? 0)) best.set(item.label, item);
  }
  return [...best.values(), ...manual].sort((a, b) => (b.confidence ?? -1) - (a.confidence ?? -1));
}

function promptName(prompt: string) {
  return prompt.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase());
}
