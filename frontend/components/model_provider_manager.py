"""
模型服务商管理 UI 组件。

功能：
- 显示所有已配置的 LLM Provider
- 支持添加/编辑/删除自定义 Provider
- 测试连接功能
- API Key 脱敏显示与管理
"""

import streamlit as st
from typing import Dict, Any, List


def _get_providers() -> List[Dict[str, Any]]:
    """获取所有 Provider 配置"""
    try:
        from backend.models.provider_gateway import get_provider_list

        return get_provider_list()
    except Exception:
        return []


def _test_connection(vendor: str, api_key: str = "", base_url: str = "") -> Dict[str, Any]:
    """测试 Provider 连接"""
    try:
        from backend.models.provider_gateway import create_client

        client = create_client(vendor, api_key or None, base_url or None)
        # 尝试一个简单的 API 调用
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            temperature=0,
        )
        return {"ok": True, "message": "连接成功", "model": resp.model}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


def _mask_key(key: str) -> str:
    """脱敏显示 API Key"""
    if not key or len(key) < 12:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def render():
    """渲染模型服务商管理页面"""
    st.header("🔧 模型服务商管理")
    st.caption("管理 LLM API 连接配置，支持 OpenAI-compatible 接口")

    providers = _get_providers()

    # 现有 Provider 列表
    if providers:
        st.subheader("已配置的服务商")
        for prov in providers:
            with st.expander(f"**{prov['name']}** (`{prov['id']}`)", expanded=False):
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.text_input(
                        "Base URL",
                        value=prov.get("base_url", ""),
                        key=f"prov_url_{prov['id']}",
                        disabled=True,
                    )
                with col2:
                    status = "✅ 已配置" if prov.get("has_key") else "❌ 未配置"
                    st.metric("API Key", status)
                with col3:
                    if st.button("测试连接", key=f"test_{prov['id']}"):
                        with st.spinner("测试中..."):
                            result = _test_connection(prov["id"])
                        if result["ok"]:
                            st.success(result["message"])
                        else:
                            st.error(result["message"])

    # 添加新 Provider
    st.divider()
    st.subheader("添加自定义服务商")

    with st.form("add_provider"):
        col1, col2 = st.columns(2)
        with col1:
            provider_id = st.text_input("服务商 ID", placeholder="my-openai")
            provider_name = st.text_input("显示名称", placeholder="My OpenAI API")
        with col2:
            base_url = st.text_input("Base URL", placeholder="https://api.example.com/v1")
            api_key = st.text_input("API Key", type="password")

        model_name = st.text_input("默认模型", placeholder="gpt-4.1")
        capabilities = st.multiselect(
            "模型能力",
            ["text", "vision", "tool_call", "json_mode", "embedding"],
            default=["text"],
        )

        submitted = st.form_submit_button("添加服务商")
        if submitted:
            if provider_id and base_url and api_key:
                st.info("配置已记录。请将 API Key 添加到 .env 文件并在 config/providers.yaml 中配置。")
                st.code(
                    f"""
# .env
{provider_id.upper()}_API_KEY={api_key}
{provider_id.upper()}_BASE_URL={base_url}

# config/providers.yaml
providers:
  - id: {provider_id}
    name: {provider_name}
    apiHost: ${{{provider_id.upper()}_BASE_URL}}
    apiKey: ${{{provider_id.upper()}_API_KEY}}
    models:
      - id: {model_name}
        capabilities: {capabilities}
""",
                    language="yaml",
                )
            else:
                st.error("请填写服务商 ID、Base URL 和 API Key")

    # 使用说明
    st.divider()
    with st.expander("配置说明"):
        st.markdown("""
        ### 支持的 Provider 类型
        - **OpenAI-compatible** — 任何兼容 OpenAI API 的服务（DeepSeek、Claude 代理、本地模型等）
        - **环境变量注入** — 在 `config/providers.yaml` 中使用 `${VAR_NAME}` 引用环境变量
        - **安全限制** — 默认禁止连接 localhost/内网地址，设置 `ALLOW_LOCAL_LLM_BASE_URL=1` 可解除

        ### 配置文件位置
        - `.env` — API Key 存储
        - `config/providers.yaml` — Provider 配置
        - `config/models.yaml` — Agent 模式与模型分配
        """)
