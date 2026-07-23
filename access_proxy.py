"""校内访问代理模块 — EZproxy URL 重写 + CARSI Shibboleth 认证

支持两种校内访问方式：
1. EZproxy：URL 重写，将付费数据库域名通过学校代理访问
2. CARSI：Shibboleth/SAML 联邦认证，通过学校统一身份认证访问数据库
"""

import sys
import os
from urllib.parse import urlparse, urlunparse, quote
from core.config import load_config


def _find_chromium_executable(cache_dir):
    """在 Playwright 缓存目录中查找 chromium 可执行文件

    在 chromium-* 目录内递归搜索 chrome.exe / chrome 可执行文件，
    而不是硬编码特定子路径（不同 Playwright 版本目录结构可能不同）。

    Args:
        cache_dir: ms-playwright 缓存目录路径

    Returns:
        str: 可执行文件路径，找不到返回 None
    """
    import glob as _glob

    chromium_dirs = sorted(
        _glob.glob(os.path.join(cache_dir, "chromium-*")), reverse=True
    )
    if not chromium_dirs:
        return None

    # 平台特定的可执行文件名
    if sys.platform == "win32":
        target_exe = "chrome.exe"
    elif sys.platform == "darwin":
        target_exe = "Chromium"  # 实际在 .app bundle 中，文件名不含扩展
    else:
        target_exe = "chrome"

    for d in chromium_dirs:
        # 递归搜索 chromium 目录，优先匹配浅层路径
        for root, _dirs, files in os.walk(d):
            if target_exe in files:
                return os.path.join(root, target_exe)
    return None


def _setup_playwright_browsers_path():
    """自动检测并设置 Playwright 浏览器路径

    优先级：
    1. 已设置 PLAYWRIGHT_BROWSERS_PATH → 不覆盖
    2. 检查默认平台路径是否包含可用的 chromium 可执行文件
    3. 检查常见自定义路径
    4. 都不满足 → 不设置环境变量，让 Playwright 自行检测
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return  # 用户已自定义，不覆盖

    # 平台默认路径
    candidates = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates.append(os.path.join(local, "ms-playwright"))
        # 也检查用户目录下的 .cache
        candidates.append(os.path.expanduser("~/.cache/ms-playwright"))
    elif sys.platform == "darwin":
        candidates.append(os.path.expanduser("~/Library/Caches/ms-playwright"))
        candidates.append(os.path.expanduser("~/.cache/ms-playwright"))
    else:
        candidates.append(os.path.expanduser("~/.cache/ms-playwright"))

    for path in candidates:
        if os.path.isdir(path) and _find_chromium_executable(path):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path
            return


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
            return f"https://{self.ezproxy_host}/login?url={quote(url, safe='')}"
        else:
            # 后缀模式（默认）：domain.ezproxy_host/path
            # EZproxy 不使用端口号，丢弃原端口
            new_netloc = f"{domain}.{self.ezproxy_host}"
            new_parsed = parsed._replace(netloc=new_netloc, scheme="https")
            return urlunparse(new_parsed)

    def _should_proxy(self, domain: str) -> bool:
        """判断域名是否需要通过代理访问"""
        if not domain:
            return False
        domain_lower = domain.lower()
        for d in PROXIED_DOMAINS:
            if domain_lower == d or domain_lower.endswith("." + d):
                return True
        return False


class CARSIAuth:
    """CARSI Shibboleth 认证

    实现 SAML SSO 流程：
    1. 请求数据库 CARSI 入口 → 重定向到学校 IdP
    2. 提交登录表单 → 获取 SAML Response
    3. 提交 SAML Response 到数据库 SP → 获取 session cookies
    """

    # 常见 CARSI 支持的数据库 SP Shibboleth 入口
    # entityID 通过 URL 参数传递给 SP
    SP_ENTRIES = {
        # 中文数据库
        "cnki": "https://fsso.cnki.net/Shibboleth.sso/Login?entityID={entity_id}",
        "wanfang": "https://s.wanfangdata.com.cn/carsi/login",
        "cqvip": "https://www.cqvip.com/carsi/login",
        # 国际出版商
        "elsevier": "https://www.sciencedirect.com/Shibboleth.sso/Login?entityID={entity_id}",
        "springer": "https://wayf.springernature.com/?redirect_uri=https://link.springer.com/",
        "wiley": "https://onlinelibrary.wiley.com/Shibboleth.sso/Login?entityID={entity_id}",
        "ieee": "https://ieeexplore.ieee.org/Shibboleth.sso/Login?entityID={entity_id}",
        "acs": "https://pubs.acs.org/Shibboleth.sso/Login?entityID={entity_id}",
        "rsc": "https://pubs.rsc.org/Shibboleth.sso/Login?entityID={entity_id}",
        "nature": "https://wayf.springernature.com/?redirect_uri=https://www.nature.com/",
        "tandfonline": "https://www.tandfonline.com/Shibboleth.sso/Login?entityID={entity_id}",
        "sage": "https://journals.sagepub.com/Shibboleth.sso/Login?entityID={entity_id}",
        "oup": "https://academic.oup.com/Shibboleth.sso/Login?entityID={entity_id}",
        "cambridge": "https://www.cambridge.org/core/Shibboleth.sso/Login?entityID={entity_id}",
        "jstor": "https://www.jstor.org/Shibboleth.sso/Login?entityID={entity_id}",
        "proquest": "https://www.proquest.com/Shibboleth.sso/Login?entityID={entity_id}",
        "ebsco": "https://search.ebscohost.com/Shibboleth.sso/Login?entityID={entity_id}",
        "webofscience": "https://www.webofscience.com/Shibboleth.sso/Login?entityID={entity_id}",
        "scopus": "https://www.scopus.com/Shibboleth.sso/Login?entityID={entity_id}",
    }

    # 常见高校 IdP Entity ID 映射（entity_id → 实际登录 URL）
    # CARSI 使用 Shibboleth entity ID 格式，实际登录由 IdP 自动处理
    IDP_ENTITY_MAP = {}

    # CARSI 联邦发现服务（学校列表）
    DISCOVERY_SERVICE = "https://ds.carsi.edu.cn/ds/discotag"

    def __init__(self):
        self.session = None
        self.cookies = {}  # {domain: cookies_dict}
        self.authenticated = False

    def authenticate(
        self,
        idp_url: str,
        username: str,
        password: str,
        sp_domains: list = None,
        custom_urls: dict = None,
        existing_cookies: dict = None,
    ) -> dict:
        """执行 CARSI 认证

        Args:
            idp_url: 学校 IdP URL（如 https://idp.xxx.edu.cn/idp/shibboleth）
            username: 校园账号
            password: 校园密码
            sp_domains: 要认证的数据库域名列表，默认全部
            custom_urls: 自定义 SP URL 字典，如 {"mydb": "https://example.com/Shibboleth.sso/Login?entityID={entity_id}"}
            existing_cookies: 已有的 CARSI cookies（用于 re-auth 时保留之前有效的 cookies）

        Returns:
            dict: {"ok": bool, "cookies": {domain: {...}}, "error": str}
        """
        import requests

        # 合并自定义 URL
        sp_entries = dict(self.SP_ENTRIES)
        if custom_urls:
            sp_entries.update(custom_urls)

        if sp_domains is None:
            sp_domains = list(sp_entries.keys())

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
        )
        # 保留已有的 cookies（re-auth 时不丢失之前有效的 SP cookies）
        self.cookies = dict(existing_cookies) if existing_cookies else {}
        errors = []
        any_success = False  # 跟踪本次是否有 SP 认证成功

        for sp_key in sp_domains:
            sp_url = sp_entries.get(sp_key)
            if not sp_url:
                continue

            try:
                # 每个 SP 独立的 cookie jar，避免跨域污染
                sp_session = requests.Session()
                sp_session.headers.update(self.session.headers)
                sp_session.cookies.update(self.session.cookies)

                result = self._authenticate_sp(
                    sp_session, sp_url, idp_url, username, password
                )
                if result.get("ok"):
                    domain = urlparse(sp_url).hostname
                    # 只保存该 SP 域名相关的 cookies（处理前导点号）
                    sp_cookies = {
                        c.name: c.value
                        for c in sp_session.cookies
                        if domain
                        and (
                            c.domain == domain
                            or c.domain == "." + domain
                            or c.domain.endswith("." + domain)
                        )
                    }
                    # 合并新 cookies 到已有 cookies，保留之前有效的 cookies
                    if domain in self.cookies:
                        self.cookies[domain].update(sp_cookies)
                    else:
                        self.cookies[domain] = sp_cookies
                    # 合并到主 session
                    self.session.cookies.update(sp_session.cookies)
                    any_success = True
                else:
                    errors.append(f"{sp_key}: {result.get('error', 'unknown')}")
            except Exception as e:
                errors.append(f"{sp_key}: {e}")

        self.authenticated = any_success
        if any_success:
            return {"ok": True, "cookies": self.cookies, "error": ""}
        return {
            "ok": False,
            "cookies": self.cookies,
            "error": "; ".join(errors) if errors else "No cookies obtained",
        }

    def _authenticate_sp(
        self, session, sp_url: str, idp_url: str, username: str, password: str
    ) -> dict:
        """对单个 SP 执行 CARSI/Shibboleth 认证（使用 Playwright 处理 JS 渲染和验证码）

        Args:
            session: requests.Session 实例（用于获取 cookies）
            sp_url: SP 入口 URL（可能含 {entity_id} 占位符）
            idp_url: 学校 IdP URL（entity ID）
            username: 校园账号
            password: 校园密码

        Returns:
            dict: {"ok": bool, "error": str}
        """
        # 构造 SP 入口 URL（替换 entity_id 占位符）
        entity_id = idp_url
        url = sp_url.replace("{entity_id}", entity_id)

        # 使用 Playwright 处理 JS 渲染和验证码
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {
                "ok": False,
                "error": "Playwright 未安装，请在设置中安装 Playwright",
            }

        # 自动检测 Playwright 浏览器路径
        import os

        _setup_playwright_browsers_path()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # HTTPS 证书验证：默认启用，仅当用户明确配置时才跳过
                # （某些学校 CARSI IdP 使用自签名证书）
                cfg = load_config()
                verify_ssl = cfg.get("access_proxy", {}).get("verify_ssl", True)
                context = browser.new_context(ignore_https_errors=not verify_ssl)

                # 注入已有的 cookies（re-auth 时保留之前有效的 SP cookies）
                if self.cookies:
                    pw_cookies = []
                    for domain, domain_cookies in self.cookies.items():
                        if isinstance(domain_cookies, dict):
                            for name, value in domain_cookies.items():
                                pw_cookies.append(
                                    {
                                        "name": name,
                                        "value": value,
                                        "domain": domain,
                                        "path": "/",
                                    }
                                )
                    if pw_cookies:
                        context.add_cookies(pw_cookies)

                page = context.new_page()

                # Step 1: 访问 SP 入口
                page.goto(url, wait_until="networkidle", timeout=30000)

                # Step 2: 处理中间页面（Continue 按钮等）
                for step in range(5):
                    # 检查是否已跳转回 SP（认证成功）
                    current_url = page.url
                    sp_domain = urlparse(sp_url).hostname
                    if sp_domain and sp_domain in current_url:
                        # 提取 cookies 并返回
                        cookies = context.cookies()
                        for c in cookies:
                            session.cookies.set(
                                c["name"], c["value"], domain=c.get("domain", "")
                            )
                        browser.close()
                        return {"ok": True, "error": ""}

                    # 检查是否有 SAML Response
                    saml_input = page.query_selector('input[name="SAMLResponse"]')
                    if saml_input:
                        # 提取表单数据并提交
                        form_data = page.evaluate("""() => {
                            const form = document.querySelector('form');
                            if (!form) return null;
                            const data = {};
                            new FormData(form).forEach((v, k) => data[k] = v);
                            return {action: form.action, data: data};
                        }""")
                        if form_data:
                            page.evaluate("""() => {
                                const form = document.querySelector('form');
                                if (form) form.submit();
                            }""")
                            page.wait_for_load_state("networkidle", timeout=15000)
                            # 检查是否跳转回 SP
                            if sp_domain and sp_domain in page.url:
                                cookies = context.cookies()
                                for c in cookies:
                                    session.cookies.set(
                                        c["name"],
                                        c["value"],
                                        domain=c.get("domain", ""),
                                    )
                                browser.close()
                                return {"ok": True, "error": ""}

                    # 检查是否有登录表单
                    pwd_field = page.query_selector('input[type="password"]')
                    if pwd_field:
                        # 填写用户名和密码
                        username_input = page.query_selector(
                            # --- 标准英文字段名（含大小写变体） ---
                            'input#username, input[name="username"], input[name="Username"], input[name="USERNAME"], '
                            'input#un, input[name="un"], '
                            'input[name="userName"], input[name="user_name"], '
                            'input#userid, input[name="userid"], input[name="userId"], input[name="user_id"], '
                            'input#account, input[name="account"], '
                            'input[name="loginAccount"], input[name="LoginAccount"], input[name="login_account"], '
                            'input[name="j_username"], '
                            'input#eduPersonPrincipalName, input[name="eduPersonPrincipalName"], '
                            'input#loginName, input[name="loginName"], input[name="loginname"], '
                            'input[name="LoginName"], input[name="LOGINNAME"], '
                            'input#login_username, input[name="login_username"], '
                            'input#user, input[name="user"], '
                            'input#uid, input[name="uid"], '
                            'input#login_id, input[name="login_id"], input[name="LOGIN_ID"], '
                            'input#email, input[name="email"], input[name="e-mail"], '
                            'input#txtUserName, input[name="txtUserName"], '
                            'input#txtUid, input[name="txtUid"], '
                            'input#txtAccount, input[name="txtAccount"], '
                            'input#txtLoginName, input[name="txtLoginName"], '
                            'input#cardNo, input[name="cardNo"], input[name="cardno"], '
                            'input#employeeId, input[name="employeeId"], input[name="employee_id"], '
                            'input#studentId, input[name="studentId"], input[name="student_id"], '
                            # --- CAS 5+ / Shibboleth / 中国高校常见字段名 ---
                            'input[name="loginId"], input[name="loginid"], input[name="LoginId"], '
                            'input[name="userNo"], input[name="UserNo"], '
                            'input[name="stuNo"], input[name="StuNo"], input[name="stu_no"], '
                            'input[name="empNo"], input[name="EmpNo"], input[name="emp_no"], '
                            'input[name="sno"], input[name="tno"], '
                            'input[name="netid"], input[name="netId"], input[name="NetId"], '
                            'input[name="personalId"], input[name="personal_id"], '
                            'input[name="credential_0"], '
                            'input[name="identifier"], input[name="principal"], '
                            'input[name="wmUserID"], '
                            'input[name="memberNo"], input[name="member_no"], '
                            'input[name="cardNum"], input[name="cardnum"], '
                            # --- 中文拼音缩写字段名（中国高校自研 CAS 常见） ---
                            'input[name="xh"], '  # 学号
                            'input[name="gh"], '  # 工号
                            'input[name="yhm"], '  # 用户名
                            'input[name="sfzh"], '  # 身份证号
                            'input[name="zjhm"], '  # 证件号码
                            'input[name="sjhm"], '  # 手机号码
                            'input[name="kh"], '  # 卡号
                            # --- 子串匹配：覆盖未列出的字段名变体 ---
                            'input[name*="login" i], input[name*="user" i], '
                            'input[name*="account" i], '
                            'input[id*="login" i], input[id*="user" i], input[id*="account" i], '
                            # --- placeholder 匹配 ---
                            'input[placeholder*="用户名"], input[placeholder*="账号"], '
                            'input[placeholder*="学号"], input[placeholder*="工号"], '
                            'input[placeholder*="校园卡"], input[placeholder*="身份"], '
                            'input[placeholder*="username"], input[placeholder*="user name"], '
                            'input[placeholder*="请输入"], input[placeholder*="一卡通"], '
                            'input[placeholder*="NetID"], input[placeholder*="netid"], '
                            'input[placeholder*="手机号"], input[placeholder*="邮箱"], '
                            'input[placeholder*="证件"], input[placeholder*="手机"], '
                            'input[placeholder*="Phone"], input[placeholder*="Email"], '
                            'input[placeholder*="card"], input[placeholder*="Card"], '
                            # --- aria-label 匹配 ---
                            'input[aria-label*="用户"], input[aria-label*="账号"], '
                            'input[aria-label*="学号"], input[aria-label*="工号"], '
                            'input[aria-label*="username"], input[aria-label*="登录"], '
                            'input[aria-label*="请输入"], input[aria-label*="手机"], '
                            'input[aria-label*="邮箱"], input[aria-label*="证件"]'
                        )
                        # 回退：label[for] 关联匹配（中文高校 CAS 表单常见）
                        if not username_input:
                            username_input = page.evaluate("""() => {
                                const labels = document.querySelectorAll('label');
                                const keywords = ['用户', '账号', '学号', '工号', '卡号', '登录',
                                    'username', 'user name', 'account', 'login', 'netid',
                                    '手机', '邮箱', '证件', '校园卡', '一卡通'];
                                for (const label of labels) {
                                    const text = (label.textContent || '').trim().toLowerCase();
                                    if (!keywords.some(k => text.includes(k))) continue;
                                    // 优先用 for 属性
                                    if (label.htmlFor) {
                                        const el = document.getElementById(label.htmlFor);
                                        if (el && el.tagName === 'INPUT') return el;
                                    }
                                    // 回退：label 内嵌的 input
                                    const inner = label.querySelector('input');
                                    if (inner) return inner;
                                }
                                return null;
                            }""")
                        # 回退：已知选择器未命中时，遍历 DOM 查找密码字段之前的文本输入框
                        if not username_input:
                            username_input = page.evaluate(
                                """(pwdEl) => {
                                const pwd = pwdEl;
                                if (!pwd) return null;
                                const isValid = (el) => el && el.tagName === 'INPUT'
                                    && el.type !== 'hidden' && el.type !== 'password'
                                    && el.type !== 'submit' && el.type !== 'checkbox'
                                    && el.type !== 'radio' && el.offsetParent !== null;
                                // 策略1：从密码字段向前遍历兄弟元素
                                let el = pwd;
                                while (el && el.previousElementSibling) {
                                    el = el.previousElementSibling;
                                    if (isValid(el)) return el;
                                }
                                // 策略2：向上遍历祖先容器（最多5层），在每个容器内查找密码字段之前的输入框
                                let ancestor = pwd.parentElement;
                                for (let depth = 0; depth < 5 && ancestor; depth++, ancestor = ancestor.parentElement) {
                                    const inputs = ancestor.querySelectorAll('input');
                                    for (let i = 0; i < inputs.length; i++) {
                                        if (inputs[i] === pwd) break;
                                        if (isValid(inputs[i])) return inputs[i];
                                    }
                                }
                                return null;
                            }""",
                                pwd_field,
                            )
                        if not username_input:
                            # 无法识别用户名输入框，无法自动填写
                            browser.close()
                            return {
                                "ok": False,
                                "error": "无法识别用户名输入框，请在浏览器中手动完成 CARSI 认证",
                            }
                        username_input.fill(username)
                        pwd_field.fill(password)

                        # 提交表单（不等待导航，因为可能有验证码）
                        submit_btn = page.query_selector(
                            'button[type="submit"], input[type="submit"]'
                        )
                        if submit_btn:
                            submit_btn.click()
                            page.wait_for_timeout(2000)

                            # 检查是否有验证码要求
                            captcha = page.query_selector(
                                'img[src*="captcha"], img[src*="code"], input[name*="code"]'
                            )
                            if captcha:
                                browser.close()
                                return {
                                    "ok": False,
                                    "error": "CAS 需要验证码，请在浏览器中手动完成 CARSI 认证",
                                }

                            # 检查是否登录成功
                            if sp_domain and sp_domain in page.url:
                                cookies = context.cookies()
                                for c in cookies:
                                    session.cookies.set(
                                        c["name"],
                                        c["value"],
                                        domain=c.get("domain", ""),
                                    )
                                browser.close()
                                return {"ok": True, "error": ""}

                    # 尝试点击 Continue 按钮
                    submit_btn = page.query_selector('input[type="submit"]')
                    if submit_btn:
                        submit_btn.click()
                        page.wait_for_load_state("networkidle", timeout=15000)
                    else:
                        break

                browser.close()
                return {"ok": False, "error": "CARSI 认证流程未完成"}

        except Exception as e:
            err_msg = str(e)
            # 检测浏览器未安装/版本不匹配的错误，提供可操作的指导
            if (
                "Executable doesn't exist" in err_msg
                or "Looks like Playwright" in err_msg
            ):
                detail = err_msg.splitlines()[0] if err_msg else "unknown"
                # 获取诊断信息
                cache_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
                if not cache_path:
                    if sys.platform == "win32":
                        cache_path = os.path.join(
                            os.environ.get("LOCALAPPDATA", ""), "ms-playwright"
                        )
                    else:
                        cache_path = os.path.expanduser("~/.cache/ms-playwright")
                return {
                    "ok": False,
                    "error": f"Playwright 浏览器未安装或版本不匹配。请运行: python -m playwright install chromium\n"
                    f"浏览器缓存路径: {cache_path}\n"
                    f"详细信息: {detail}",
                }
            return {"ok": False, "error": f"CARSI 认证失败: {err_msg}"}

    def get_cookies_for_domain(self, domain: str) -> dict:
        """获取指定域名的认证 cookies"""
        return self.cookies.get(domain, {})

    def is_authenticated(self) -> bool:
        return self.authenticated


def get_supported_institutions() -> list:
    """获取 CARSI 支持的学校列表

    优先从 CARSI 官网获取全量列表（1000+ 所高校），
    失败时回退到本地硬编码列表。

    Returns:
        list: [{"id": "xxx", "name": "XXX 大学", "idp_url": "https://..."}]
    """
    # 尝试从 CARSI 官网获取全量列表
    try:
        import requests
        import re
        import json as _json

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        resp = requests.get(
            "https://www.carsi.edu.cn/IdPlist.html", headers=headers, timeout=15
        )
        resp.encoding = "utf-8"  # 强制 UTF-8，避免 ISO-8859-1 误判导致中文乱码
        if resp.ok:
            # 页面中嵌入了 JSON 数组：var IdPList1 = [{...}, ...]
            match = re.search(r"var\s+\w+\s*=\s*(\[.*?\]);", resp.text, re.DOTALL)
            if match:
                raw_list = _json.loads(match.group(1))
                institutions = []
                for i, item in enumerate(raw_list):
                    if item.get("status") == "3" and item.get("url"):
                        institutions.append(
                            {
                                "id": f"carsi_{i}",
                                "name": item.get("name", ""),
                                "idp_url": item.get("url", ""),
                            }
                        )
                if institutions:
                    return institutions
    except Exception:
        pass

    # 回退：本地硬编码列表
    return [
        {
            "id": "tsinghua",
            "name": "清华大学",
            "idp_url": "https://id.tsinghua.edu.cn/idp/shibboleth",
        },
        {
            "id": "pku",
            "name": "北京大学",
            "idp_url": "https://iaaa.pku.edu.cn/idp/shibboleth",
        },
        {
            "id": "zju",
            "name": "浙江大学",
            "idp_url": "https://zjuam.zju.edu.cn/idp/shibboleth",
        },
        {
            "id": "sjtu",
            "name": "上海交通大学",
            "idp_url": "https://jaccount.sjtu.edu.cn/idp/shibboleth",
        },
        {
            "id": "fudan",
            "name": "复旦大学",
            "idp_url": "https://uis.fudan.edu.cn/idp/shibboleth",
        },
        {
            "id": "ustc",
            "name": "中国科学技术大学",
            "idp_url": "https://passport.ustc.edu.cn/idp/shibboleth",
        },
        {
            "id": "nju",
            "name": "南京大学",
            "idp_url": "https://authserver.nju.edu.cn/idp/shibboleth",
        },
        {
            "id": "whu",
            "name": "武汉大学",
            "idp_url": "https://sso.whu.edu.cn/idp/shibboleth",
        },
        {
            "id": "hust",
            "name": "华中科技大学",
            "idp_url": "https://idp.hust.edu.cn/idp/shibboleth",
        },
        {
            "id": "sysu",
            "name": "中山大学",
            "idp_url": "https://cas.sysu.edu.cn/idp/shibboleth",
        },
        {
            "id": "hit",
            "name": "哈尔滨工业大学",
            "idp_url": "https://ids.hit.edu.cn/idp/shibboleth",
        },
        {
            "id": "xjtu",
            "name": "西安交通大学",
            "idp_url": "https://cas.xjtu.edu.cn/idp/shibboleth",
        },
        {
            "id": "buaa",
            "name": "北京航空航天大学",
            "idp_url": "https://sso.buaa.edu.cn/idp/shibboleth",
        },
        {
            "id": "scu",
            "name": "四川大学",
            "idp_url": "https://id.scu.edu.cn/idp/shibboleth",
        },
        {
            "id": "tongji",
            "name": "同济大学",
            "idp_url": "https://ids.tongji.edu.cn/idp/shibboleth",
        },
        {
            "id": "nankai",
            "name": "南开大学",
            "idp_url": "https://cas.nankai.edu.cn/idp/shibboleth",
        },
        {
            "id": "tju",
            "name": "天津大学",
            "idp_url": "https://sso.tju.edu.cn/idp/shibboleth",
        },
        {
            "id": "bit",
            "name": "北京理工大学",
            "idp_url": "https://login.bit.edu.cn/idp/shibboleth",
        },
        {
            "id": "seu",
            "name": "东南大学",
            "idp_url": "https://auth.seu.edu.cn/idp/shibboleth",
        },
        {
            "id": "sdu",
            "name": "山东大学",
            "idp_url": "https://pass.sdu.edu.cn/idp/shibboleth",
        },
        {
            "id": "bnu",
            "name": "北京师范大学",
            "idp_url": "https://cas.bnu.edu.cn/idp/shibboleth",
        },
        {
            "id": "csu",
            "name": "中南大学",
            "idp_url": "https://ca.csu.edu.cn/idp/shibboleth",
        },
        {
            "id": "jlu",
            "name": "吉林大学",
            "idp_url": "https://cas.jlu.edu.cn/idp/shibboleth",
        },
        {
            "id": "dlut",
            "name": "大连理工大学",
            "idp_url": "https://sso.dlut.edu.cn/idp/shibboleth",
        },
        {
            "id": "ahmu",
            "name": "安徽医科大学",
            "idp_url": "https://idp.ahmu.edu.cn/idp/shibboleth",
        },
    ]

    def search_wos(self, query="", year_from=0, year_to=0, max_results=30):
        """Web of Science 搜索（通过 CARSI Playwright 浏览器）"""
        try:

            self._ensure_browser()
            if not self._browser:
                return []
            page = self._browser.new_page()
            try:
                # 注入 CARSI cookies
                page.goto(
                    "https://www.webofscience.com",
                    wait_until="domcontentloaded",
                    timeout=15,
                )
                for name, value in self.get_cookies_for_domain(
                    "webofscience.com"
                ).items():
                    page.context.add_cookies(
                        [
                            {
                                "name": name,
                                "value": value,
                                "domain": ".webofscience.com",
                                "path": "/",
                            }
                        ]
                    )
                # 搜索
                search_url = "https://www.webofscience.com/wos/woscc/basic-search"
                page.goto(search_url, wait_until="domcontentloaded", timeout=15)
                page.fill('input[data-id="search-field-input"]', query)
                page.click('button[data-id="search-button"]')
                page.wait_for_timeout(5000)
                # 解析结果 — 简单提取可见文本
                results = page.query_selector_all("app-record-item")
                papers = []
                for el in results[:max_results]:
                    try:
                        title_el = el.query_selector(".title-link, a.summary-title")
                        title = title_el.inner_text().strip() if title_el else ""
                        if not title:
                            continue
                        p = Paper(source="wos")
                        p.title = title
                        doi_el = el.query_selector("[data-ta='DOI']")
                        if doi_el:
                            p.doi = doi_el.inner_text().strip()
                        papers.append(p)
                    except Exception:
                        continue
                return papers
            finally:
                page.close()
        except Exception as e:
            print(f"[WoS] Search failed: {e}")
            return []

    def search_proquest(self, query="", year_from=0, year_to=0, max_results=20):
        """ProQuest 搜索（通过 CARSI Playwright 浏览器）"""
        try:

            self._ensure_browser()
            if not self._browser:
                return []
            page = self._browser.new_page()
            try:
                page.goto(
                    "https://www.proquest.com",
                    wait_until="domcontentloaded",
                    timeout=15,
                )
                for name, value in self.get_cookies_for_domain("proquest.com").items():
                    page.context.add_cookies(
                        [
                            {
                                "name": name,
                                "value": value,
                                "domain": ".proquest.com",
                                "path": "/",
                            }
                        ]
                    )
                search_url = (
                    f"https://www.proquest.com/resultsol/advanced?query={query}"
                )
                page.goto(search_url, wait_until="domcontentloaded", timeout=15)
                page.wait_for_timeout(5000)
                results = page.query_selector_all(
                    ".resultItem, [data-testid='result-item']"
                )
                papers = []
                for el in results[:max_results]:
                    try:
                        title_el = el.query_selector("h3 a, .title a")
                        title = title_el.inner_text().strip() if title_el else ""
                        if not title:
                            continue
                        p = Paper(source="proquest")
                        p.title = title
                        papers.append(p)
                    except Exception:
                        continue
                return papers
            finally:
                page.close()
        except Exception as e:
            print(f"[ProQuest] Search failed: {e}")
            return []
