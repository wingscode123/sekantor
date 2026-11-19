// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
const mocks = vi.hoisted(() => ({ render: vi.fn(), App: () => null, MiniView: () => null }));
vi.mock("react-dom/client", () => ({ createRoot: () => ({ render: mocks.render }) }));
vi.mock("./App", () => ({ default: mocks.App }));
vi.mock("./office/MiniView", () => ({ MiniView: mocks.MiniView }));
afterEach(() => { mocks.render.mockClear(); window.history.replaceState(null, "", "/"); document.body.innerHTML = ""; });
it.each([["/?view=mini", true], ["/?other=1&view=mini", true], ["/", false], ["/?view=full", false]])("routes %s to the correct view", async (url, mini) => {
  vi.resetModules();
  window.history.replaceState(null, "", url);
  document.body.innerHTML = '<div id="root"></div>';
  await import("./main");
  const strict = mocks.render.mock.calls[0][0] as ReactElement<{ children: ReactElement }>;
  expect(strict.props.children.type).toBe(mini ? mocks.MiniView : mocks.App);
});
