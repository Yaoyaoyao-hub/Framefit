export function supportsTabCapture() {
  return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getDisplayMedia;
}

export function stopStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => {
    track.stop();
  });
}

export function waitForSeek(video: HTMLVideoElement): Promise<void> {
  if (!video.seeking && video.readyState >= 2) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error("The video did not finish seeking."));
    }, 4000);
    const onReady = () => {
      if (video.seeking || video.readyState < 2) return;
      cleanup();
      resolve();
    };
    const cleanup = () => {
      window.clearTimeout(timer);
      video.removeEventListener("seeked", onReady);
      video.removeEventListener("loadeddata", onReady);
    };
    video.addEventListener("seeked", onReady);
    video.addEventListener("loadeddata", onReady);
  });
}

export function nextPresentedFrame(video: HTMLVideoElement): Promise<void> {
  const withCallback = video as HTMLVideoElement & {
    requestVideoFrameCallback?: (callback: () => void) => number;
  };
  if (typeof withCallback.requestVideoFrameCallback === "function") {
    return new Promise((resolve) => {
      const timer = window.setTimeout(resolve, 700);
      withCallback.requestVideoFrameCallback?.(() => {
        window.clearTimeout(timer);
        resolve();
      });
    });
  }
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

export async function captureVideoFrame(video: HTMLVideoElement): Promise<HTMLCanvasElement> {
  if (video.seeking || video.readyState < 2) {
    await waitForSeek(video);
  }
  await nextPresentedFrame(video);
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) {
    throw new Error("This frame is not ready yet.");
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Could not capture this frame.");
  context.drawImage(video, 0, 0, width, height);
  return canvas;
}

export function blobToCanvas(blob: Blob): Promise<HTMLCanvasElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext("2d");
      URL.revokeObjectURL(url);
      if (!context || canvas.width < 1 || canvas.height < 1) {
        reject(new Error("Could not read that image."));
        return;
      }
      context.drawImage(image, 0, 0);
      resolve(canvas);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read that image."));
    };
    image.src = url;
  });
}

export function canvasToBlob(canvas: HTMLCanvasElement, type = "image/jpeg"): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not prepare that image."))), type, 0.92);
  });
}

export function cropCanvas(source: HTMLCanvasElement, box: { x: number; y: number; width: number; height: number }) {
  const left = Math.max(0, Math.round(box.x * source.width));
  const top = Math.max(0, Math.round(box.y * source.height));
  const width = Math.max(1, Math.round(box.width * source.width));
  const height = Math.max(1, Math.round(box.height * source.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.min(width, source.width - left);
  canvas.height = Math.min(height, source.height - top);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Could not crop this image.");
  context.drawImage(source, left, top, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height);
  return canvas;
}
