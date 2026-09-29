/** Thin fetch wrapper for the backend API (ARCHITECTURE_v1 §2.2 services/api.ts). */
import type { Book, ChapterMeta, ChapterText, Progress } from "../types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, init);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return resp.json();
}

export const api = {
  listBooks: () => request<Book[]>("/books"),

  getBook: (id: number) => request<Book>(`/books/${id}`),

  importBook: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<Book>("/books", { method: "POST", body: form });
  },

  deleteBook: (id: number) => request<{ ok: boolean }>(`/books/${id}`, { method: "DELETE" }),

  coverUrl: (id: number) => `${BASE}/books/${id}/cover`,

  listChapters: (bookId: number) => request<ChapterMeta[]>(`/books/${bookId}/chapters`),

  getChapter: (bookId: number, index: number) =>
    request<ChapterText>(`/books/${bookId}/chapters/${index}`),

  getProgress: (bookId: number) => request<Progress>(`/books/${bookId}/progress`),

  setProgress: (bookId: number, progress: Progress) =>
    request<Progress>(`/books/${bookId}/progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(progress),
    }),
};
