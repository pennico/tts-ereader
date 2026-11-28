/**
 * Pure pagination math for paginated mode (AC-110).
 *
 * Layout: the chapter content is laid out as CSS columns of the viewport
 * width inside a fixed-height viewport; one column = one page. Kept pure so
 * it is unit-testable without a DOM.
 */

export const COLUMN_GAP = 48; // px between pages

/** Total number of pages for a given laid-out content width. */
export function pageCount(contentWidth: number, viewportWidth: number): number {
  if (viewportWidth <= 0 || contentWidth <= 0) return 1;
  return Math.max(1, Math.ceil(contentWidth / (viewportWidth + COLUMN_GAP)));
}

/** The leftmost visible page for a scroll offset (used on mode switches). */
export function pageAtOffset(scrollLeft: number, viewportWidth: number): number {
  if (viewportWidth <= 0) return 0;
  return Math.max(0, Math.round(scrollLeft / (viewportWidth + COLUMN_GAP)));
}

/** Translate-x offset that shows the given page. */
export function pageOffset(page: number, viewportWidth: number): number {
  return page * (viewportWidth + COLUMN_GAP);
}

/** Clamp a page index into [0, pages-1]. */
export function clampPage(page: number, pages: number): number {
  if (pages <= 1) return 0;
  return Math.min(pages - 1, Math.max(0, page));
}

/** Fractional reading position (0..1) of a page within a chapter. */
export function pageToPosition(page: number, pages: number): number {
  if (pages <= 1) return 0;
  return page / (pages - 1);
}

/** Page index for a fractional position (inverse of pageToPosition). */
export function positionToPage(position: number, pages: number): number {
  if (pages <= 1) return 0;
  return clampPage(Math.round(position * (pages - 1)), pages);
}

/** Scroll-top for a fractional position in continuous mode. */
export function positionToScrollTop(position: number, scrollHeight: number, clientHeight: number): number {
  const max = scrollHeight - clientHeight;
  if (max <= 0) return 0;
  return Math.min(max, Math.max(0, position * max));
}

/** Fractional position for a scroll-top in continuous mode. */
export function scrollTopToPosition(scrollTop: number, scrollHeight: number, clientHeight: number): number {
  const max = scrollHeight - clientHeight;
  if (max <= 0) return 0;
  return Math.min(1, Math.max(0, scrollTop / max));
}

/** Next page, or null at the end of the chapter (caller advances chapters). */
export function nextPage(page: number, pages: number): number | null {
  if (page >= pages - 1) return null;
  return page + 1;
}
