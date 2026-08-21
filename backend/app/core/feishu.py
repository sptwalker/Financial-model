import json
import time
import httpx
from typing import Optional, Dict, Any
from urllib.parse import quote
from app.core.config import get_settings

settings = get_settings()


class FeishuAPIError(Exception):
    """飞书 API 错误"""
    pass


class FeishuAuthError(FeishuAPIError):
    """飞书认证错误"""
    pass


class FeishuClient:
    """飞书 API 客户端（自 feishu_project_manager 移植，裁剪为 OAuth 登录 + 消息通知）"""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self):
        self._app_id_override: Optional[str] = None
        self._app_secret_override: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        # tenant_access_token 缓存（按凭证 key 失效）
        self._tenant_token: Optional[str] = None
        self._tenant_token_expire_at: float = 0.0
        self._tenant_cred_key: Optional[str] = None

    def _creds(self) -> tuple[str, str]:
        """解析当前应用凭证：显式 override > .env 默认。"""
        if self._app_id_override is not None:
            return self._app_id_override, (self._app_secret_override or "")
        return settings.FEISHU_APP_ID, settings.FEISHU_APP_SECRET

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_app_access_token(self) -> str:
        """获取应用 access token"""
        client = self._get_client()
        app_id, app_secret = self._creds()
        try:
            response = await client.post(
                f"{self.BASE_URL}/auth/v3/app_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAuthError(f"HTTP error getting app access token: {e}")
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error getting app access token: {e}")

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAuthError(f"Failed to get app access token: {data.get('msg')}")
        return data["app_access_token"]

    async def get_user_access_token(self, code: str) -> str:
        """通过 authorization code 获取用户 access token（返回令牌字符串）"""
        app_token = await self.get_app_access_token()

        client = self._get_client()
        try:
            response = await client.post(
                f"{self.BASE_URL}/authen/v1/access_token",
                headers={"Authorization": f"Bearer {app_token}"},
                json={"grant_type": "authorization_code", "code": code},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAuthError(f"HTTP error getting user access token: {e}")
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error getting user access token: {e}")

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAuthError(f"Failed to get user access token: {data.get('msg')}")
        return data["data"]["access_token"]

    async def get_user_info(self, user_access_token: str) -> Dict[str, Any]:
        """获取用户信息"""
        client = self._get_client()
        try:
            response = await client.get(
                f"{self.BASE_URL}/authen/v1/user_info",
                headers={"Authorization": f"Bearer {user_access_token}"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAuthError(f"HTTP error getting user info: {e}")
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error getting user info: {e}")

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAPIError(f"Failed to get user info: {data.get('msg')}")
        return data["data"]

    def get_oauth_url(self, state: Optional[str] = None) -> str:
        """生成飞书 OAuth 授权 URL"""
        app_id, _ = self._creds()
        redirect_uri = quote(settings.FEISHU_REDIRECT_URI)
        url = f"https://open.feishu.cn/open-apis/authen/v1/authorize?app_id={app_id}&redirect_uri={redirect_uri}"
        if state:
            url += f"&state={quote(state)}"
        return url

    async def get_tenant_access_token(self) -> str:
        """获取并缓存 tenant_access_token（发送消息使用）"""
        app_id, app_secret = self._creds()
        cred_key = f"{app_id}|{app_secret}"
        now = time.monotonic()
        if (self._tenant_token and self._tenant_cred_key == cred_key
                and now < self._tenant_token_expire_at):
            return self._tenant_token

        client = self._get_client()
        try:
            response = await client.post(
                f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAuthError(f"HTTP error getting tenant access token: {e}")
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error getting tenant access token: {e}")

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAuthError(f"Failed to get tenant access token: {data.get('msg')}")

        self._tenant_token = data["tenant_access_token"]
        self._tenant_token_expire_at = now + max(0, int(data.get("expire", 7200)) - 60)
        self._tenant_cred_key = cred_key
        return self._tenant_token

    async def _post_authed(self, path: str, json_body: Dict[str, Any],
                           params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """以 tenant_access_token 发送 POST 请求并解析飞书响应"""
        token = await self.get_tenant_access_token()
        client = self._get_client()
        try:
            response = await client.post(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json; charset=utf-8"},
                params=params,
                json=json_body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAPIError(f"HTTP error on POST {path}: {e}")
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error on POST {path}: {e}")

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAPIError(f"Feishu API error on POST {path}: {data.get('msg')}")
        return data.get("data", {})

    async def send_text(self, receive_id: str, text: str,
                        receive_id_type: str = "user_id") -> Dict[str, Any]:
        """发送纯文本消息"""
        return await self._post_authed(
            "/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json_body={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )


# 全局飞书客户端实例
feishu_client = FeishuClient()
