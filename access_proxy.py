"""校内访问代理模块 — EZproxy URL 重写 + CARSI Shibboleth 认证

支持两种校内访问方式：
1. EZproxy：URL 重写，将付费数据库域名通过学校代理访问
2. CARSI：Shibboleth/SAML 联邦认证，通过学校统一身份认证访问数据库
"""

import re
import sys
from urllib.parse import urlparse, urlunparse, quote_plus


# 需要通过校内代理访问的付费数据库域名
PROXIED_DOMAINS = {
    "kns.cnki.net",
    "s.wanfangdata.com.cn",
    "wanfangdata.com.cn",
    "www.cqvip.com",
    "cqvip.com",
    "scholar.google.com",
    "scholar.google.com.hk",
}

# 免费 API，不走代理
FREE_DOMAINS = {
    "eutils.ncbi.nlm.nih.gov",
    "api.openalex.org",
    "api.semanticscholar.org",
    "cn.bing.com",
    "api.zotero.org",
}


class EZproxyRewriter:
    """EZproxy URL 重写器

    支持两种格式：
    - 后缀模式（默认）：domain/path → domain.ezproxy_host/path
    - 前缀模式：domain/path → ezproxy_host/login?url=https://domain/path
    """

    def __init__(self, ezproxy_host: str, mode: str = "suffix"):
        """
        Args:
            ezproxy_host: EZproxy 域名，如 ezproxy.xxx.edu.cn
            mode: "suffix"（后缀模式）或 "prefix"（前缀模式）
        """
        self.ezproxy_host = ezproxy_host.rstrip("/")
        self.mode = mode

    def rewrite(self, url: str) -> str:
        """重写 URL 以通过 EZproxy 访问

        Args:
            url: 原始 URL

        Returns:
            重写后的 URL，如果不是付费数据库则返回原 URL
        """
        if not self.ezproxy_host:
            return url

        parsed = urlparse(url)
        domain = parsed.hostname or ""

        # 检查是否是需要代理的域名
        if not self._should_proxy(domain):
            return url

        if self.mode == "prefix":
            # 前缀模式：ezproxy_host/login?url=original_url
            return f"https://{self.ezproxy_host}/login?url={quote_plus(url)}"
        else:
            # 后缀模式（默认）：domain.ezproxy_host/path
            new_netloc = f"{domain}.{self.ezproxy_host}"
            if parsed.port:
                new_netloc = f"{new_netloc}:{parsed.port}"
            new_parsed = parsed._replace(netloc=new_netloc, scheme="https")
            return urlunparse(new_parsed)

    def _should_proxy(self, domain: str) -> bool:
        """判断域名是否需要通过代理访问"""
        if not domain:
            return False
        # 精确匹配
        if domain in PROXIED_DOMAINS:
            return True
        # 子域名匹配（如 kns.cnki.net 匹配 cnki.net）
        for d in PROXIED_DOMAINS:
            if domain.endswith("." + d) or domain == d:
                return True
        return False


class CARSIAuth:
    """CARSI Shibboleth 认证

    实现 SAML SSO 流程：
    1. 请求数据库 CARSI 入口 → 重定向到学校 IdP
    2. 提交登录表单 → 获取 SAML Response
    3. 提交 SAML Response 到数据库 SP → 获取 session cookies
    """

    # 常见 CARSI 支持的数据库 SP 入口
    SP_ENTRIES = {
        "cnki": "https://www.cnki.net/carsi/",
        "wanfang": "https://s.wanfangdata.com.cn/carsi/",
        "cqvip": "https://www.cqvip.com/carsi/",
    }

    # CARSI 联邦发现服务（学校列表）
    DISCOVERY_SERVICE = "https://ds.carsi.edu.cn/ds/discotag"

    def __init__(self):
        self.session = None
        self.cookies = {}  # {domain: cookies_dict}
        self.authenticated = False

    def authenticate(self, idp_url: str, username: str, password: str,
                     sp_domains: list = None) -> dict:
        """执行 CARSI 认证

        Args:
            idp_url: 学校 IdP URL（如 https://idp.xxx.edu.cn/idp/profile/SAML2/Redirect/SSO）
            username: 校园账号
            password: 校园密码
            sp_domains: 要认证的数据库域名列表，默认全部

        Returns:
            dict: {"ok": bool, "cookies": {domain: {...}}, "error": str}
        """
        import requests
        from bs4 import BeautifulSoup

        if sp_domains is None:
            sp_domains = list(self.SP_ENTRIES.keys())

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
        self.cookies = {}

        for sp_key in sp_domains:
            sp_url = self.SP_ENTRIES.get(sp_key)
            if not sp_url:
                continue

            try:
                result = self._authenticate_sp(sp_url, idp_url, username, password)
                if result.get("ok"):
                    domain = urlparse(sp_url).hostname
                    self.cookies[domain] = dict(self.session.cookies)
                else:
                    return {"ok": False, "cookies": {}, "error": result.get("error", f"CARSI auth failed for {sp_key}")}
            except Exception as e:
                return {"ok": False, "cookies": {}, "error": f"CARSI auth error ({sp_key}): {e}"}

        self.authenticated = bool(self.cookies)
        return {"ok": self.authenticated, "cookies": self.cookies, "error": "" if self.authenticated else "No cookies obtained"}

    def _authenticate_sp(self, sp_url: str, idp_url: str, username: str, password: str) -> dict:
        """对单个 SP 执行 CARSI 认证

        Args:
            sp_url: SP 入口 URL
            idp_url: 学校 IdP URL
            username: 校园账号
            password: 校园密码

        Returns:
            dict: {"ok": bool, "error": str}
        """
        from bs4 import BeautifulSoup

        # Step 1: 请求 SP 入口，跟踪重定向到 IdP
        try:
            resp = self.session.get(sp_url, allow_redirects=True, timeout=30)
        except Exception as e:
            return {"ok": False, "error": f"Failed to reach SP: {e}"}

        # Step 2: 检查是否已重定向到 IdP 登录页
        if idp_url and not resp.url.startswith(idp_url.split("/idp")[0]):
            # 如果没有自动重定向到 IdP，手动构造 IdP 请求
            # 尝试从页面中提取 SAML AuthnRequest
            pass

        # Step 3: 在 IdP 登录页提交用户名密码
        login_url = resp.url
        try:
            # 解析登录表单
            soup = BeautifulSoup(resp.text, "html.parser")
            form = soup.find("form")
            if not form:
                # 可能已经是登录后的回调
                if "SAMLResponse" in resp.text:
                    return self._handle_saml_response(resp)
                return {"ok": False, "error": "No login form found on IdP page"}

            action = form.get("action", "")
            if action and not action.startswith("http"):
                # 相对路径，构造完整 URL
                from urllib.parse import urljoin
                action = urljoin(login_url, action)

            # 提取隐藏字段
            form_data = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                value = inp.get("value", "")
                if name:
                    form_data[name] = value

            # 填入用户名密码
            # 常见字段名：j_username, username, userid, loginName
            username_fields = ["j_username", "username", "userid", "loginName", "user", "account"]
            password_fields = ["j_password", "password", "passwd", "pass", "pwd"]

            for field in username_fields:
                if field in form_data:
                    form_data[field] = username
                    break

            for field in password_fields:
                if field in form_data:
                    form_data[field] = password
                    break

            # Step 4: 提交登录表单
            resp = self.session.post(action or login_url, data=form_data, allow_redirects=True, timeout=30)

        except Exception as e:
            return {"ok": False, "error": f"Login form submission failed: {e}"}

        # Step 5: 处理 SAML Response（如果有）
        if "SAMLResponse" in resp.text:
            return self._handle_saml_response(resp)

        # 检查是否认证成功（重定向回 SP 且带 cookies）
        if self.session.cookies:
            return {"ok": True, "error": ""}

        return {"ok": False, "error": "Authentication failed - no cookies obtained"}

    def _handle_saml_response(self, resp) -> dict:
        """处理 SAML Response，提交到 SP 的 ACS URL"""
        from bs4 import BeautifulSoup

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            # 找到 SAML Response 表单
            form = soup.find("form")
            if not form:
                return {"ok": False, "error": "No SAML response form found"}

            action = form.get("action", "")
            form_data = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                value = inp.get("value", "")
                if name:
                    form_data[name] = value

            if "SAMLResponse" not in form_data:
                return {"ok": False, "error": "SAMLResponse not found in form"}

            # 提交到 ACS URL
            if action:
                resp = self.session.post(action, data=form_data, allow_redirects=True, timeout=30)

            return {"ok": True, "error": ""}
        except Exception as e:
            return {"ok": False, "error": f"SAML response handling failed: {e}"}

    def get_cookies_for_domain(self, domain: str) -> dict:
        """获取指定域名的认证 cookies"""
        return self.cookies.get(domain, {})

    def is_authenticated(self) -> bool:
        return self.authenticated


def get_supported_institutions() -> list:
    """获取 CARSI 支持的学校列表

    Returns:
        list: [{"id": "xxx", "name": "XXX 大学", "idp_url": "https://..."}]
    """
    # 常见高校列表（实际应从 CARSI Discovery Service 动态获取）
    # 这里提供一个静态列表作为 fallback
    institutions = [
        {"id": "tsinghua", "name": "清华大学", "idp_url": "https://id.tsinghua.edu.cn/idp/profile/SAML2/Redirect/SSO"},
        {"id": "pku", "name": "北京大学", "idp_url": "https://iaaa.pku.edu.cn/"},
        {"id": "fudan", "name": "复旦大学", "idp_url": "https://uis.fudan.edu.cn/"},
        {"id": "sjtu", "name": "上海交通大学", "idp_url": "https://jaccount.sjtu.edu.cn/"},
        {"id": "zju", "name": "浙江大学", "idp_url": "https://zjuam.zju.edu.cn/"},
        {"id": "ustc", "name": "中国科学技术大学", "idp_url": "https://passport.ustc.edu.cn/"},
        {"id": "nju", "name": "南京大学", "idp_url": "https://authserver.nju.edu.cn/"},
        {"id": "whu", "name": "武汉大学", "idp_url": "https://sso.whu.edu.cn/"},
        {"id": "scu", "name": "四川大学", "idp_url": "https://id.scu.edu.cn/"},
        {"id": "hit", "name": "哈尔滨工业大学", "idp_url": "https://ids.hit.edu.cn/"},
        {"id": "sysu", "name": "中山大学", "idp_url": "https://cas.sysu.edu.cn/"},
        {"id": "xjtu", "name": "西安交通大学", "idp_url": "https://cas.xjtu.edu.cn/"},
        {"id": "tongji", "name": "同济大学", "idp_url": "https://ids.tongji.edu.cn/"},
        {"id": "nankai", "name": "南开大学", "idp_url": "https://cas.nankai.edu.cn/"},
        {"id": "buaa", "name": "北京航空航天大学", "idp_url": "https://sso.buaa.edu.cn/"},
    ]

    # 尝试从 CARSI Discovery Service 获取完整列表
    try:
        import requests
        resp = requests.get("https://ds.carsi.edu.cn/ds/discotag", timeout=10)
        if resp.ok:
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception:
        pass

    return institutions
