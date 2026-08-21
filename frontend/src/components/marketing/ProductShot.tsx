import Image, { type StaticImageData } from "next/image";

/**
 * A real screenshot framed as a dark "plate", the same treatment the homepage
 * product tour uses (see landing/home/ProductTour.tsx).
 *
 * Why this exists: until now every page except the homepage shipped with zero
 * product imagery. Someone landing on /products/tickets from a search never
 * saw the product before being asked to sign up — the page argued for itself
 * entirely in prose. A screenshot is the cheapest proof a product page has.
 *
 * Pass a **static import** of the WebP, never a string path: static imports
 * carry width/height/blurDataURL, so the frame reserves its space and the page
 * has no layout shift. Capture new plates with
 * e2e/tools/capture-marketing-shots.ts.
 *
 * `figure`/`caption` render the mono slug line the brand uses on product
 * imagery ("FIG. 01 — Service desk, email-intake"). `priority` opts into eager
 * loading for a shot that is the LCP element; note Next 16 deprecated the
 * `priority` prop on next/image itself in favour of `fetchPriority`.
 */
export function ProductShot({
  src,
  alt,
  figure,
  caption,
  priority = false,
  className = "",
}: {
  src: StaticImageData;
  alt: string;
  figure: string;
  caption: string;
  priority?: boolean;
  className?: string;
}) {
  return (
    <figure className={className}>
      <div className="overflow-hidden rounded-[4px] border border-ledger-ink/25 bg-ledger-pane text-[#E6EDE7]">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <span className="font-brand-mono text-[11px] uppercase tracking-[0.14em] text-white/55">
            {figure} — {caption}
          </span>
          <span className="font-brand-mono text-[11px] uppercase tracking-[0.14em] text-ledger-mint">Live</span>
        </div>
        <Image
          src={src}
          alt={alt}
          placeholder="blur"
          sizes="(min-width: 1024px) 60vw, 100vw"
          fetchPriority={priority ? "high" : undefined}
          loading={priority ? "eager" : "lazy"}
          className="w-full"
        />
      </div>
      <figcaption className="mt-2.5 font-brand-mono text-[11px] uppercase tracking-[0.14em] text-ledger-ink/45">
        {caption}
      </figcaption>
    </figure>
  );
}
