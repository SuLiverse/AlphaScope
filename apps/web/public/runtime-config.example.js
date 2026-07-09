// 复制为 runtime-config.js，或启动后端后由 ensure_local_api_token 自动生成。
// 勿提交含真实 token 的 runtime-config.js。
window.__ALPHASCOPE_CONFIG__ = window.__ALPHASCOPE_CONFIG__ || {
  apiBaseUrl: 'http://localhost:8000',
  apiKey: '',
  localApiToken: '',
  packaged: false,
};
