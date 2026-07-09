import { describe, expect, it } from "vitest";
import { isPreviewResult, previewResultNote } from "./quantPreview";

describe("isPreviewResult (shipped quantPreview)", () => {
  it("returns false for null/undefined", () => {
    expect(isPreviewResult(null)).toBe(false);
    expect(isPreviewResult(undefined)).toBe(false);
  });

  it("prefers top-level is_preview boolean", () => {
    expect(isPreviewResult({ is_preview: true, data_source: "akshare" })).toBe(true);
    expect(isPreviewResult({ is_preview: false, data_source: "local_preview" })).toBe(false);
  });

  it("falls back to summary.is_preview", () => {
    expect(isPreviewResult({ summary: { is_preview: true } })).toBe(true);
    expect(isPreviewResult({ summary: { is_preview: false } })).toBe(false);
  });

  it("compat: treats data_source local_preview as preview when flags absent", () => {
    expect(isPreviewResult({ data_source: "local_preview" })).toBe(true);
    expect(isPreviewResult({ summary: { data_source: "local_preview" } })).toBe(true);
    expect(isPreviewResult({ data_source: "akshare" })).toBe(false);
  });
});

describe("previewResultNote (shipped quantPreview)", () => {
  it("returns warning note only for preview results", () => {
    const note = previewResultNote({ is_preview: true });
    expect(note).toContain("演示样例");
    expect(previewResultNote({ is_preview: false })).toBe("");
    expect(previewResultNote(null)).toBe("");
  });
});
