import { mediaUrl } from "../api";
import { useStore } from "../store";
import type { Version } from "../types";

export function HistoryBar() {
  const session = useStore((state) => state.session);
  const previewVersionId = useStore((state) => state.previewVersionId);
  const previewVersion = useStore((state) => state.previewVersion);
  const historyOpen = useStore((state) => state.historyOpen);
  const setHistoryOpen = useStore((state) => state.setHistoryOpen);
  const removeVersion = useStore((state) => state.removeVersion);
  const continueFrom = useStore((state) => state.continueFrom);
  const downloadVersion = useStore((state) => state.downloadVersion);
  const versions = session?.versions ?? [];

  return (
    <>
      <section className="mt-6" aria-label="Saved versions">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-display text-2xl">History</h2>
          <p className="text-sm text-stone-500">Branches stay saved when you go back.</p>
        </div>
        <div data-testid="history-strip" className="flex gap-3 overflow-x-auto pb-2">
          {versions.map((version) => {
            const active = version.id === session?.active_version_id;
            const viewing = version.id === previewVersionId;
            return (
              <button
                key={version.id}
                type="button"
                data-testid={`version-${version.id}`}
                data-active={active ? "true" : "false"}
                aria-label={`Saved version: ${version.label}`}
                className={`w-28 shrink-0 rounded-2xl border bg-white p-2 text-left ${active ? "border-clay" : "border-line"} ${viewing ? "ring-2 ring-clay/40" : ""}`}
                onClick={() => previewVersion(version.id)}
              >
                <img src={mediaUrl(version.image_url)} alt="" className="h-24 w-full rounded-xl object-cover" />
                <span className="mt-2 block text-xs">{version.label}</span>
              </button>
            );
          })}
          {versions.length === 0 && <p className="text-sm text-stone-500">Saved try-ons will line up here.</p>}
        </div>
      </section>
      {historyOpen && session && (
        <div className="fixed inset-0 z-30 flex items-end justify-center bg-ink/30 p-4 sm:items-center" role="presentation">
          <div role="dialog" aria-label="All generations" className="max-h-[80vh] w-full max-w-lg overflow-auto rounded-[28px] bg-paper p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-display text-3xl">All generations</h2>
              <button className="btn" type="button" onClick={() => setHistoryOpen(false)}>Close</button>
            </div>
            <VersionTree
              versions={versions}
              parentId={null}
              depth={0}
              activeId={session.active_version_id}
              onOpen={(version) => {
                previewVersion(version.id);
              }}
              onContinue={(version) => void continueFrom(version.id)}
              onDownload={(version) => void downloadVersion(version)}
              onDelete={(version) => {
                const kids = countDescendants(versions, version.id);
                const accepted = window.confirm(
                  kids
                    ? `Deleting ${version.label} also deletes ${kids} later saved version${kids === 1 ? "" : "s"}. Other branches stay.`
                    : `Delete ${version.label}? Other saved versions stay.`,
                );
                if (accepted) void removeVersion(version.id, kids > 0);
              }}
            />
          </div>
        </div>
      )}
    </>
  );
}

function VersionTree({
  versions,
  parentId,
  depth,
  activeId,
  onOpen,
  onContinue,
  onDownload,
  onDelete,
}: {
  versions: Version[];
  parentId: string | null;
  depth: number;
  activeId: string;
  onOpen: (version: Version) => void;
  onContinue: (version: Version) => void;
  onDownload: (version: Version) => void;
  onDelete: (version: Version) => void;
}) {
  const nodes = versions.filter((version) => version.parent_version_id === parentId);
  return (
    <ul className="grid gap-2">
      {nodes.map((version) => (
        <li key={version.id} style={{ marginLeft: depth * 16 }}>
          <div className="rounded-2xl border border-line bg-white p-3">
            <button type="button" className="text-left font-medium" onClick={() => onOpen(version)}>
              {version.label}
              {version.id === activeId ? " · current source" : ""}
              {version.origin === "product" ? " · product" : ""}
            </button>
            <div className="mt-2 flex flex-wrap gap-2">
              <button className="btn" type="button" onClick={() => onContinue(version)}>Continue from here</button>
              <button className="btn" type="button" onClick={() => onDownload(version)}>Download</button>
              {!version.is_root && (
                <button className="btn" type="button" onClick={() => onDelete(version)}>Delete</button>
              )}
            </div>
          </div>
          <VersionTree versions={versions} parentId={version.id} depth={depth + 1} activeId={activeId} onOpen={onOpen} onContinue={onContinue} onDownload={onDownload} onDelete={onDelete} />
        </li>
      ))}
    </ul>
  );
}

function countDescendants(versions: Version[], id: string): number {
  const children = versions.filter((version) => version.parent_version_id === id);
  return children.reduce((sum, child) => sum + 1 + countDescendants(versions, child.id), 0);
}
