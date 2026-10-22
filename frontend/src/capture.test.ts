import { captureVideoFrame, stopStream } from "./capture";

describe("video frame capture", () => {
  it("waits until seeking finishes, then draws the video's real dimensions", async () => {
    const listeners = new Map<string, () => void>();
    const video = {
      seeking: true,
      readyState: 1,
      videoWidth: 64,
      videoHeight: 40,
      addEventListener: (name: string, fn: () => void) => listeners.set(name, fn),
      removeEventListener: (name: string) => listeners.delete(name),
      requestVideoFrameCallback: (callback: () => void) => {
        callback();
        return 1;
      },
    } as unknown as HTMLVideoElement;
    const drawImage = vi.fn();
    const original = document.createElement.bind(document);
    const spy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "canvas") {
        return {
          width: 0,
          height: 0,
          getContext: () => ({ drawImage }),
        } as unknown as HTMLCanvasElement;
      }
      return original(tag);
    });
    const pending = captureVideoFrame(video);
    let settled = false;
    pending.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    Object.assign(video, { seeking: false, readyState: 2 });
    listeners.get("seeked")?.();
    const canvas = await pending;
    expect(canvas.width).toBe(64);
    expect(canvas.height).toBe(40);
    expect(drawImage).toHaveBeenCalledWith(video, 0, 0, 64, 40);
    spy.mockRestore();
  });

  it("stops every capture track", () => {
    const stop = vi.fn();
    stopStream({ getTracks: () => [{ stop }, { stop }] } as unknown as MediaStream);
    expect(stop).toHaveBeenCalledTimes(2);
    stopStream(null);
  });
});
