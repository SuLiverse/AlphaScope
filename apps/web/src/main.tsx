import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
// 字体本地化（@fontsource，latin 子集；中文走系统回退）：
// 导入项目实际使用的字重——Inter/JetBrains Mono 400/500/600/700（font-normal/medium/semibold/bold 均有使用），
// Space Grotesk 用 variable 包覆盖 500/600/700。
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/inter/latin-700.css';
import '@fontsource/jetbrains-mono/latin-400.css';
import '@fontsource/jetbrains-mono/latin-500.css';
import '@fontsource/jetbrains-mono/latin-600.css';
import '@fontsource/jetbrains-mono/latin-700.css';
import '@fontsource-variable/space-grotesk';
import App from './App.tsx';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
