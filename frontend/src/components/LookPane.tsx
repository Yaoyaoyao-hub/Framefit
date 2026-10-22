import { Download, History, RotateCcw, Undo2, Upload } from "lucide-react";
import { mediaUrl } from "../api";
import { useStore, versionById } from "../store";

export function LookPane() {
  const session = useStore((state) => state.session);
  const capabilities = useStore((state) => state.capabilities);
  const previewVersionId = useStore((state) => state.previewVersionId);
  const frame = useStore((state) => state.frame);
  const selectedItemId = useStore((state) => state.selectedItemId);
  const gender = useStore((state) => state.gender);
  const style = useStore((state) => state.style);
  const keepOutfit = useStore((state) => state.keepOutfit);
  const changeShoes = useStore((state) => state.changeShoes);
  const filterPeople = useStore((state) => state.filterPeople);
  const referenceKind = useStore((state) => state.referenceKind);
  const busy = useStore((state) => state.busy);
  const job = useStore((state) => state.job);
  const uploadPhoto = useStore((state) => state.uploadPhoto);
  const useSamplePhoto = useStore((state) => state.useSamplePhoto);
  const undo = useStore((state) => state.undo);
  const resetLook = useStore((state) => state.resetLook);
  const continueFrom = useStore((state) => state.continueFrom);
  const downloadVersion = useStore((state) => state.downloadVersion);
  const setHistoryOpen = useStore((state) => state.setHistoryOpen);
  const setGender = useStore((state) => state.setGender);
  const setStyle = useStore((state) => state.setStyle);
  const setKeepOutfit = useStore((state) => state.setKeepOutfit);
  const setChangeShoes = useStore((state) => state.setChangeShoes);
  const setFilterPeople = useStore((state) => state.setFilterPeople);
  const setReferenceKind = useStore((state) => state.setReferenceKind);

  const active = versionById(session, session?.active_version_id ?? null);
  const preview = versionById(session, previewVersionId) ?? active;
  const selected = frame?.items.find((item) => item.id === selectedItemId);
  const category = capabilities?.categories[selected?.category || ""];
  const viewingSaved = preview && active && preview.id !== active.id;

  return (
    <section className="flex min-h-[70vh] flex-col gap-4" aria-label="Your photo">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Your photo</p>
          <h2 className="font-display text-3xl">The look so far</h2>
        </div>
        {capabilities?.mode !== "real" && (
          <button className="btn" type="button" onClick={() => void useSamplePhoto()} disabled={!!busy}>
            Use sample photo
          </button>
        )}
      </div>
      <div className="relative flex-1 overflow-hidden rounded-[28px] border border-line bg-[#fbf7f2]">
        {!preview && (
          <div className="flex h-full min-h-[420px] flex-col items-center justify-center gap-4 px-8 text-center">
            <p className="max-w-sm text-lg">Start with a photo of yourself. It stays saved, and every try-on is kept as its own version.</p>
            <label className="btn btn-primary">
              <Upload size={16} aria-hidden /> Upload photo
              <input
                data-testid="personal-photo-input"
                className="sr-only"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void uploadPhoto(file, file.name);
                  event.target.value = "";
                }}
              />
            </label>
          </div>
        )}
        {preview && (
          <img src={mediaUrl(preview.image_url)} alt={preview.label} className="h-[56vh] min-h-[420px] w-full object-contain" />
        )}
        {job && (job.status === "queued" || job.status === "running") && (
          <p className="absolute bottom-4 left-4 rounded-full bg-white px-3 py-1 text-sm shadow" data-testid="job-status">
            Trying this on…
          </p>
        )}
      </div>
      <p data-testid="active-label" className="text-sm text-stone-600">
        Next try-on uses {active?.label ?? "your photo"}
        {active?.origin === "product" ? " · from a product" : ""}
        {active && active.origin === "inspiration" ? " · from inspiration" : ""}
      </p>
      {viewingSaved && (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-white px-4 py-3 text-sm">
          <span>Viewing {preview?.label}. Later versions stay saved.</span>
          <button data-testid="continue-from-here" className="btn btn-primary" type="button" onClick={() => preview && void continueFrom(preview.id)}>
            Continue from here
          </button>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button data-testid="undo" className="btn" type="button" onClick={() => void undo()} disabled={!session}>
          <Undo2 size={16} aria-hidden /> Undo
        </button>
        <button data-testid="reset" className="btn" type="button" onClick={() => void resetLook()} disabled={!session}>
          <RotateCcw size={16} aria-hidden /> Reset look
        </button>
        <label className="btn">
          Change photo
          <input
            className="sr-only"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void uploadPhoto(file, file.name);
              event.target.value = "";
            }}
          />
        </label>
        <button className="btn" type="button" disabled={!preview} onClick={() => preview && void downloadVersion(preview)}>
          <Download size={16} aria-hidden /> Download
        </button>
        <button data-testid="history" className="btn" type="button" onClick={() => setHistoryOpen(true)} disabled={!session}>
          <History size={16} aria-hidden /> History
        </button>
      </div>
      {category?.gender_required && (
        <div className="flex flex-wrap gap-3 text-sm">
          <label>
            Presentation
            <select className="ml-2 rounded-full border border-line bg-white px-2 py-1" value={gender} onChange={(event) => setGender(event.target.value as "female" | "male")}>
              <option value="female">Female</option>
              <option value="male">Male</option>
            </select>
          </label>
          {category.adapter === "hat" && (
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={keepOutfit} onChange={(event) => setKeepOutfit(event.target.checked)} />
              Only change the hat
            </label>
          )}
          {!(category.adapter === "hat" && keepOutfit) && (
            <label>
              Outfit and background
              <select className="ml-2 rounded-full border border-line bg-white px-2 py-1" value={style} onChange={(event) => setStyle(event.target.value)}>
                {(category.styles.length ? category.styles : ["random"]).map((value) => (
                  <option key={value} value={value}>{value === "random" ? "Surprise me" : value.replace("style_", "").replaceAll("_", " ")}</option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
      {category?.change_shoes && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={changeShoes} onChange={(event) => setChangeShoes(event.target.checked)} />
          Also replace shoes when the reference shows a full outfit
        </label>
      )}
      <div className="flex flex-wrap gap-3 text-sm">
        <label>
          Reference
          <select className="ml-2 rounded-full border border-line bg-white px-2 py-1" value={referenceKind} onChange={(event) => setReferenceKind(event.target.value as "crop" | "frame")}>
            <option value="crop">Item crop</option>
            <option value="frame">Full inspiration image</option>
          </select>
        </label>
        <label>
          People in the photo
          <select className="ml-2 rounded-full border border-line bg-white px-2 py-1" value={filterPeople} onChange={(event) => setFilterPeople(event.target.value as "off" | "normal" | "strict")}>
            <option value="off">Keep the main person</option>
            <option value="normal">Skip typical group photos</option>
            <option value="strict">Skip any extra person</option>
          </select>
        </label>
      </div>
      {!capabilities?.try_on.available && <p className="text-sm text-stone-600">{capabilities?.try_on.reason}</p>}
      <p className="text-sm text-stone-500">{capabilities?.external_processing}</p>
    </section>
  );
}
