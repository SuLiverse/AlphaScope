// Vitest 全局 setup：注册 jest-dom 匹配器（toBeInTheDocument 等）。
// 组件测试通过文件首行 `// @vitest-environment jsdom` 单独启用 jsdom，
// 全局 environment 保持 node，不影响 src/lib 下的纯逻辑测试。
// vitest 未开 globals，RTL 自动 cleanup 不生效，这里显式挂上；
// node 环境下没有已挂载组件，cleanup 是 no-op，不影响 lib 测试。
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
