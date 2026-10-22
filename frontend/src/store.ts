import { create } from "zustand";
import { api, claimReloadReset, saveImage, setToken } from "./api";
import type { Capabilities, Frame, Item, Job, SearchResult, SessionDetail, SessionSummary, Version } from "./types";

const TOKEN_KEY = "framefit-token";
const SESSION_KEY = "framefit-session";

type Store = {
  booted: boolean;
  capabilities: Capabilities | null;
  sessions: SessionSummary[];
  session: SessionDetail | null;
  frame: Frame | null;
  previewVersionId: string | null;
  selectedItemId: string | null;
  job: Job | null;
  results: SearchResult[];
  productsOpen: boolean;
  notice: string | null;
  error: string | null;
  busy: string | null;
  gender: "female" | "male";
  style: string;
  keepOutfit: boolean;
  changeShoes: boolean;
  filterPeople: "off" | "normal" | "strict";
  referenceKind: "crop" | "frame";
  sourceUrl: string;
  historyOpen: boolean;
  boot: () => Promise<void>;
  setNotice: (notice: string | null) => void;
  setGender: (gender: "female" | "male") => void;
  setStyle: (style: string) => void;
  setKeepOutfit: (value: boolean) => void;
  setChangeShoes: (value: boolean) => void;
  setFilterPeople: (value: "off" | "normal" | "strict") => void;
  setReferenceKind: (value: "crop" | "frame") => void;
  setSourceUrl: (value: string) => void;
  setHistoryOpen: (value: boolean) => void;
  setProductsOpen: (value: boolean) => void;
  selectItem: (id: string | null) => void;
  previewVersion: (id: string) => void;
  uploadPhoto: (file: Blob, name?: string) => Promise<void>;
  useSamplePhoto: () => Promise<void>;
  importInspiration: (file: Blob, kind: string) => Promise<void>;
  useSampleInspiration: () => Promise<void>;
  detect: () => Promise<void>;
  addItem: (box: { category: string; x: number; y: number; width: number; height: number }) => Promise<void>;
  updateItem: (itemId: string, payload: Record<string, string | number>) => Promise<void>;
  tryInspiration: () => Promise<void>;
  tryProduct: (product: SearchResult) => Promise<void>;
  search: () => Promise<void>;
  continueFrom: (versionId: string) => Promise<void>;
  undo: () => Promise<void>;
  resetLook: () => Promise<void>;
  removeVersion: (versionId: string, subtree: boolean) => Promise<void>;
  removeSession: (sessionId: string) => Promise<void>;
  openSession: (sessionId: string) => Promise<void>;
  downloadVersion: (version: Version) => Promise<void>;
  acknowledge: () => Promise<void>;
  refreshLists: (session: SessionDetail) => Promise<SessionDetail>;
  generationOptions: (category: string) => Record<string, unknown>;
  startJob: (payload: Record<string, unknown>) => Promise<void>;
  watch: (jobId: string) => Promise<void>;
};

let bootPromise: Promise<void> | null = null;
let watchToken = 0;

function remember(session: SessionDetail | null) {
  if (session) localStorage.setItem(SESSION_KEY, session.id);
}

async function ensureToken() {
  let stored = localStorage.getItem(TOKEN_KEY);
  if (!stored) {
    const created = await api.createWorkspace();
    stored = created.token;
    localStorage.setItem(TOKEN_KEY, stored);
  }
  setToken(stored);
}

export const useStore = create<Store>((set, get) => ({
  booted: false,
  capabilities: null,
  sessions: [],
  session: null,
  frame: null,
  previewVersionId: null,
  selectedItemId: null,
  job: null,
  results: [],
  productsOpen: false,
  notice: null,
  error: null,
  busy: null,
  gender: "female",
  style: "random",
  keepOutfit: true,
  changeShoes: false,
  filterPeople: "off",
  referenceKind: "crop",
  sourceUrl: "",
  historyOpen: false,
  setNotice: (notice) => set({ notice }),
  setGender: (gender) => set({ gender }),
  setStyle: (style) => set({ style }),
  setKeepOutfit: (keepOutfit) => set({ keepOutfit }),
  setChangeShoes: (changeShoes) => set({ changeShoes }),
  setFilterPeople: (filterPeople) => set({ filterPeople }),
  setReferenceKind: (referenceKind) => set({ referenceKind }),
  setSourceUrl: (sourceUrl) => set({ sourceUrl }),
  setHistoryOpen: (historyOpen) => set({ historyOpen }),
  setProductsOpen: (productsOpen) => set({ productsOpen }),
  selectItem: (selectedItemId) => set({ selectedItemId, results: [], productsOpen: false }),
  previewVersion: (previewVersionId) => set({ previewVersionId }),
  boot: () => {
    if (!bootPromise) {
      bootPromise = (async () => {
        try {
          await ensureToken();
          const capabilities = await api.capabilities();
          let sessions: SessionSummary[] = [];
          try {
            sessions = (await api.sessions()).sessions;
          } catch {
            const created = await api.createWorkspace();
            localStorage.setItem(TOKEN_KEY, created.token);
            setToken(created.token);
            sessions = [];
          }
          const saved = localStorage.getItem(SESSION_KEY);
          let session: SessionDetail | null = null;
          if (saved && sessions.some((item) => item.id === saved)) {
            session = await api.session(saved);
            if (claimReloadReset()) session = await api.reload(saved);
          }
          const frame = session?.frames?.[0] ?? null;
          set({
            booted: true,
            capabilities,
            sessions,
            session,
            frame,
            previewVersionId: session?.active_version_id ?? null,
            referenceKind: capabilities.reference_kind,
            notice: session?.unseen_result_version_id ? "A result is available in history." : null,
          });
          if (session?.active_job_id) void get().watch(session.active_job_id);
        } catch (error) {
          set({ booted: true, error: messageOf(error) });
        }
      })();
    }
    return bootPromise;
  },
  uploadPhoto: async (file, name) => {
    set({ busy: "Saving your photo", error: null });
    try {
      const session = await useStore.getState().refreshLists(await api.uploadPhoto(file, name));
      set({
        session,
        frame: null,
        previewVersionId: session.active_version_id,
        selectedItemId: null,
        results: [],
        job: null,
        busy: null,
        notice: "Photo saved. Add something to try on.",
      });
    } catch (error) {
      set({ busy: null, error: messageOf(error) });
    }
  },
  useSamplePhoto: async () => {
    const blob = await api.sample("person");
    await get().uploadPhoto(blob, "sample-person.jpg");
  },
  importInspiration: async (file, kind) => {
    const session = get().session;
    if (!session) {
      set({ error: "Add your photo first." });
      return;
    }
    set({ busy: "Reading inspiration", error: null });
    try {
      const frame = await api.uploadFrame(session.id, file, kind, get().sourceUrl.trim());
      const detected = await api.detect(frame.id).catch(() => frame);
      set({
        frame: detected,
        selectedItemId: detected.items[0]?.id ?? null,
        busy: null,
        notice: detected.items.length ? "Select an item to try it on." : "Nothing was marked automatically. Draw a box around an item.",
      });
    } catch (error) {
      set({ busy: null, error: messageOf(error) });
    }
  },
  useSampleInspiration: async () => {
    const blob = await api.sample("inspiration");
    await get().importInspiration(blob, "upload");
  },
  detect: async () => {
    const frame = get().frame;
    if (!frame) return;
    set({ busy: "Looking for items", error: null });
    try {
      const detected = await api.detect(frame.id);
      set({ frame: detected, busy: null, selectedItemId: detected.items[0]?.id ?? get().selectedItemId });
    } catch (error) {
      set({ busy: null, error: messageOf(error) });
    }
  },
  addItem: async (box) => {
    const frame = get().frame;
    if (!frame) return;
    set({ busy: "Saving item", error: null });
    try {
      const updated = await api.createItem(frame.id, box);
      const created = updated.items[updated.items.length - 1];
      set({ frame: updated, selectedItemId: created?.id ?? null, busy: null });
    } catch (error) {
      set({ busy: null, error: messageOf(error) });
    }
  },
  updateItem: async (itemId, payload) => {
    const frame = get().frame;
    if (!frame) return;
    try {
      const updated = await api.updateItem(itemId, payload);
      set({ frame: updated, error: null });
    } catch (error) {
      set({ error: messageOf(error) });
    }
  },
  tryInspiration: async () => {
    const { session, frame, selectedItemId } = get();
    const item = frame?.items.find((entry) => entry.id === selectedItemId);
    if (!session || !item) return;
    await get().startJob({
      origin: "inspiration",
      item_id: item.id,
      reference_kind: get().referenceKind,
      ...get().generationOptions(item.category),
    });
  },
  tryProduct: async (product) => {
    const { session, selectedItemId } = get();
    if (!session || !selectedItemId || !product.image) return;
    await get().startJob({
      origin: "product",
      item_id: selectedItemId,
      product,
      ...get().generationOptions(get().frame?.items.find((item) => item.id === selectedItemId)?.category || ""),
    });
  },
  search: async () => {
    const item = get().frame?.items.find((entry) => entry.id === get().selectedItemId);
    if (!item) return;
    set({ busy: "Searching for similar products", error: null, productsOpen: true });
    try {
      const found = await api.search(item.id);
      set({
        results: found.results,
        busy: null,
        notice: found.demo_data ? "These product results are demo data." : "Product results are ready.",
      });
    } catch (error) {
      set({ busy: null, error: messageOf(error), productsOpen: true });
    }
  },
  continueFrom: async (versionId) => {
    const session = get().session;
    if (!session) return;
    set({ busy: "Switching version", error: null });
    try {
      const updated = await api.activate(session.id, versionId);
      set({ session: updated, previewVersionId: versionId, busy: null });
    } catch (error) {
      set({ busy: null, error: messageOf(error) });
    }
  },
  undo: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const updated = await api.undo(session.id);
      set({ session: updated, previewVersionId: updated.active_version_id, error: null });
    } catch (error) {
      set({ error: messageOf(error) });
    }
  },
  resetLook: async () => {
    const session = get().session;
    if (!session) return;
    try {
      const updated = await api.reset(session.id);
      set({ session: updated, previewVersionId: updated.active_version_id, error: null });
    } catch (error) {
      set({ error: messageOf(error) });
    }
  },
  removeVersion: async (versionId, subtree) => {
    try {
      const updated = await api.removeVersion(versionId, subtree);
      set({ session: updated, previewVersionId: updated.active_version_id, error: null, historyOpen: true });
    } catch (error) {
      set({ error: messageOf(error) });
    }
  },
  removeSession: async (sessionId) => {
    try {
      await api.removeSession(sessionId);
      const sessions = (await api.sessions()).sessions;
      const next = sessions[0] ? await api.session(sessions[0].id) : null;
      remember(next);
      set({
        sessions,
        session: next,
        frame: next?.frames?.[0] ?? null,
        previewVersionId: next?.active_version_id ?? null,
        selectedItemId: null,
        error: null,
      });
    } catch (error) {
      set({ error: messageOf(error) });
    }
  },
  openSession: async (sessionId) => {
    set({ busy: "Opening photo", error: null });
    try {
      const session = await api.session(sessionId);
      remember(session);
      set({
        session,
        frame: session.frames?.[0] ?? null,
        previewVersionId: session.active_version_id,
        selectedItemId: null,
        results: [],
        busy: null,
        notice: session.unseen_result_version_id ? "A result is available in history." : null,
      });
      if (session.active_job_id) void get().watch(session.active_job_id);
    } catch (error) {
      set({ busy: null, error: messageOf(error) });
    }
  },
  downloadVersion: async (version) => {
    try {
      await saveImage(version.image_url, `framefit-${version.label.replace(/\s+/g, "-").toLowerCase()}.jpg`);
    } catch (error) {
      set({ error: messageOf(error) });
    }
  },
  acknowledge: async () => {
    const session = get().session;
    if (!session) return;
    const updated = await api.acknowledge(session.id);
    set({ session: updated, notice: null });
  },
  refreshLists: async (session: SessionDetail) => {
    remember(session);
    const sessions = (await api.sessions()).sessions;
    set({ sessions });
    return session;
  },
  generationOptions: (category: string) => {
    const spec = get().capabilities?.categories[category];
    const options: Record<string, unknown> = {
      change_shoes: spec?.change_shoes ? get().changeShoes : false,
      filter_multi_person: get().filterPeople,
    };
    if (spec?.gender_required) {
      options.gender = get().gender;
      if (category === "hat" && get().keepOutfit) {
        options.keep_outfit = true;
      } else {
        options.style = get().style || "random";
        if (category === "hat") options.keep_outfit = false;
      }
    }
    return options;
  },
  startJob: async (payload: Record<string, unknown>) => {
    const session = get().session;
    if (!session) return;
    set({ busy: "Trying this on", error: null });
    try {
      const job = await api.tryOn(session.id, {
        expected_revision: session.revision,
        idempotency_key: crypto.randomUUID(),
        ...payload,
      });
      set({ job, session: { ...session, active_job_id: job.id } });
      await get().watch(job.id);
    } catch (error) {
      set({ busy: null, error: messageOf(error) });
    }
  },
  watch: async (jobId: string) => {
    const tokenId = ++watchToken;
    let job = get().job;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      if (tokenId !== watchToken) return;
      job = await api.job(jobId);
      set({ job });
      if (job.status !== "queued" && job.status !== "running") break;
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
    if (!job || tokenId !== watchToken) return;
    const current = get().session;
    if (!current || current.id !== job.session_id) {
      if (job.status === "succeeded") set({ notice: "A result was saved in another photo's history.", busy: null });
      return;
    }
    const session = await api.session(job.session_id);
    if (job.status === "succeeded" && job.applied_to_active) {
      set({
        session,
        previewVersionId: job.result_version_id,
        busy: null,
        notice: job.origin === "product" ? "Product try-on saved." : "Saved to history.",
      });
    } else if (job.status === "succeeded") {
      set({ session, busy: null, notice: "A result is available in history." });
    } else {
      set({ session, busy: null, error: job.error_message || "The try-on did not finish. You can try again." });
    }
  },
}));

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Try again.";
}

export function selectedItem(frame: Frame | null, id: string | null): Item | null {
  return frame?.items.find((item) => item.id === id) ?? null;
}

export function versionById(session: SessionDetail | null, id: string | null): Version | null {
  return session?.versions.find((version) => version.id === id) ?? null;
}
