import { describe, expect, it } from "vitest";
import {
  isLivePriceFeed,
  isSyntheticPriceFeed,
  priceFeedKindLabel,
  resolvePriceFeed,
  type PriceFeed,
} from "./priceFeed";

describe("resolvePriceFeed (shipped priceFeed)", () => {
  it("returns synthetic when failed or no bars", () => {
    expect(resolvePriceFeed({ hasBars: false })).toBe("synthetic");
    expect(resolvePriceFeed({ hasBars: true, failed: true })).toBe("synthetic");
    expect(resolvePriceFeed({ hasBars: false, backendDegraded: true })).toBe("synthetic");
  });

  it("returns live when bars present and not degraded", () => {
    expect(resolvePriceFeed({ hasBars: true, backendDegraded: false })).toBe("live");
    expect(resolvePriceFeed({ hasBars: true })).toBe("live");
  });

  it("returns live_degraded when bars present and backend degraded", () => {
    expect(resolvePriceFeed({ hasBars: true, backendDegraded: true })).toBe("live_degraded");
  });
});

describe("price feed predicates and labels (shipped priceFeed)", () => {
  it("classifies synthetic vs live feeds", () => {
    expect(isSyntheticPriceFeed("synthetic")).toBe(true);
    expect(isSyntheticPriceFeed("live")).toBe(false);
    expect(isLivePriceFeed("live")).toBe(true);
    expect(isLivePriceFeed("live_degraded")).toBe(true);
    expect(isLivePriceFeed("synthetic")).toBe(false);
    expect(isLivePriceFeed("loading")).toBe(false);
  });

  it("returns stable Chinese labels for UI", () => {
    const labels: Record<PriceFeed, string> = {
      live: priceFeedKindLabel("live"),
      live_degraded: priceFeedKindLabel("live_degraded"),
      synthetic: priceFeedKindLabel("synthetic"),
      loading: priceFeedKindLabel("loading"),
    };
    expect(labels.live).toContain("真实");
    expect(labels.live_degraded).toContain("降级");
    expect(labels.synthetic).toContain("预览");
    expect(labels.loading).toContain("同步");
  });
});
