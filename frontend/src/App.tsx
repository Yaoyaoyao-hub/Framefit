import { useEffect } from "react";
import { HistoryBar } from "./components/HistoryBar";
import { InspirationPane } from "./components/InspirationPane";
import { LookPane } from "./components/LookPane";
import { ProductDrawer } from "./components/ProductDrawer";
import { useStore } from "./store";

export function App() {
  const boot = useStore((state) => state.boot);
  const booted = useStore((state) => state.booted);
  const capabilities = useStore((state) => state.capabilities);
  const sessions = useStore((state) => state.sessions);
  const session = useStore((state) => state.session);
  const notice = useStore((state) => state.notice);
  const error = useStore((state) => state.error);
  const openSession = useStore((state) => state.openSession);
  const removeSession = useStore((state) => state.removeSession);
  const acknowledge = useStore((state) => state.acknowledge);
  const setNotice = useStore((state) => state.setNotice);

  useEffect(() => {
    void boot();
  }, [boot]);

  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-6">
        <div>
          <p className="font-display text-4xl tracking-tight">FrameFit</p>
          <p className="text-sm text-stone-600">Try pieces from a frame, then look for something to buy.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {capabilities?.demo_data && (
            <span data-testid="demo-badge" className="rounded-full bg-clay px-3 py-1 text-sm text-white">
              Demo data
            </span>
          )}
          {sessions.length > 0 && (
            <label className="text-sm">
              Photos
              <select
                className="ml-2 rounded-full border border-line bg-white px-3 py-2"
                value={session?.id ?? ""}
                onChange={(event) => void openSession(event.target.value)}
              >
                {sessions.map((item, index) => (
                  <option key={item.id} value={item.id}>
                    Photo {sessions.length - index}
                  </option>
                ))}
              </select>
            </label>
          )}
          {session && (
            <button
              className="btn"
              type="button"
              onClick={() => {
                const accepted = window.confirm("Delete this photo and its saved try-ons?");
                if (accepted) void removeSession(session.id);
              }}
            >
              Delete photo
            </button>
          )}
        </div>
      </header>
      {capabilities?.disclosure && <p className="mx-auto max-w-7xl px-5 text-sm text-stone-600">{capabilities.disclosure}</p>}
      <div aria-live="polite" className="mx-auto max-w-7xl px-5">
        {notice && (
          <p data-testid="notice" className="mt-3 flex items-center justify-between rounded-2xl bg-white px-4 py-3 text-sm">
            {notice}
            <button className="btn" type="button" onClick={() => { setNotice(null); void acknowledge(); }}>
              Dismiss
            </button>
          </p>
        )}
        {error && (
          <p data-testid="error" className="mt-3 rounded-2xl border border-clay/30 bg-white px-4 py-3 text-sm">
            {error}
          </p>
        )}
      </div>
      <main className="mx-auto grid max-w-7xl gap-8 px-5 py-6 lg:grid-cols-2">
        {booted ? (
          <>
            <InspirationPane />
            <LookPane />
          </>
        ) : (
          <p className="text-sm text-stone-600">Opening FrameFit…</p>
        )}
      </main>
      <div className="mx-auto max-w-7xl px-5 pb-28">
        <HistoryBar />
      </div>
      <ProductDrawer />
    </div>
  );
}
