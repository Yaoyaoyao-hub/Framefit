import { ExternalLink } from "lucide-react";
import { mediaUrl } from "../api";
import { useStore } from "../store";
import type { SearchResult } from "../types";

export function ProductDrawer() {
  const open = useStore((state) => state.productsOpen);
  const results = useStore((state) => state.results);
  const setProductsOpen = useStore((state) => state.setProductsOpen);
  const tryProduct = useStore((state) => state.tryProduct);
  const capabilities = useStore((state) => state.capabilities);
  if (!open) return null;
  return (
    <aside className="fixed inset-x-0 bottom-0 z-20 max-h-[70vh] overflow-auto rounded-t-[28px] border border-line bg-paper p-5 shadow-2xl" aria-label="Product results">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-3xl">Similar products</h2>
          <p className="text-sm text-stone-600">A visual match is not proof it is the same garment.</p>
        </div>
        <button className="btn" type="button" onClick={() => setProductsOpen(false)}>Close</button>
      </div>
      {capabilities?.search.source === "fixture" && <p className="mb-3 text-sm">Demo data</p>}
      {results.length === 0 && <p className="text-sm text-stone-600">No similar products came back. You can still try on the inspiration item.</p>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {results.map((result) => (
          <article key={result.url} data-testid="product-card" className="rounded-3xl border border-line bg-white p-3">
            {result.image ? (
              <img src={mediaUrl(result.image)} alt="" className="h-40 w-full rounded-2xl object-contain" />
            ) : (
              <div className="flex h-40 items-center justify-center rounded-2xl bg-paper text-sm text-stone-500">No image</div>
            )}
            <h3 className="mt-3 text-sm font-medium">{result.title}</h3>
            <p className="text-sm text-stone-500">{result.source || "Unknown source"}</p>
            <p className="mt-1 text-sm">{formatPrice(result)}</p>
            {result.result_type === "similar_style" && <p className="text-xs uppercase tracking-wide text-clay">Similar style</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              <a data-testid="open-product" className="btn" href={result.url} target="_blank" rel="noreferrer">
                <ExternalLink size={14} aria-hidden /> Open product
              </a>
              <button data-testid="try-product" className="btn btn-primary" type="button" disabled={!result.image || !capabilities?.try_on.available} onClick={() => void tryProduct(result)}>
                Try this product
              </button>
            </div>
          </article>
        ))}
      </div>
    </aside>
  );
}

function formatPrice(result: SearchResult) {
  if (result.price == null) return "Check price";
  if (!result.currency) return String(result.price);
  if (result.currency.length <= 2) return `${result.currency}${result.price}`;
  return `${result.price} ${result.currency}`;
}
