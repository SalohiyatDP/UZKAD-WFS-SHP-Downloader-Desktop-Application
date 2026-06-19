import { useState } from "react";
import { Api } from "../api";
import type { SessionStatus } from "../types";

interface Props {
  session: SessionStatus | null;
  onSessionChange: () => void;
}

/**
 * Session setup. The user pastes the authenticated request credentials copied
 * from their logged-in mulk.kadastr.uz browser tab (DevTools → Network):
 *   - the full Cookie header value (at least JSESSIONID), and
 *   - the Authorization bearer token if the WFS calls use one (required when
 *     the cookie alone returns HTTP 401/403).
 * These are POSTed to the backend and reused for every WFS request.
 *
 * "Ulanishni tekshirish" sends one real request and shows the server's reply.
 */
export function LoginPanel({ session, onSessionChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [cookieText, setCookieText] = useState("");
  const [tokenText, setTokenText] = useState("");
  const [curlText, setCurlText] = useState("");
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<Record<string, unknown> | null>(null);

  const authed = session?.authenticated ?? false;

  // Parse a raw "Cookie:" header value ("a=1; b=2; ...") into {name: value}.
  const parseCookieHeader = (raw: string): Record<string, string> => {
    const out: Record<string, string> = {};
    raw
      .replace(/^cookie:\s*/i, "")
      .split(/;\s*/)
      .forEach((pair) => {
        const i = pair.indexOf("=");
        if (i > 0) {
          const name = pair.slice(0, i).trim();
          const value = pair.slice(i + 1).trim();
          if (name && value) out[name] = value;
        }
      });
    return out;
  };

  const importSession = async () => {
    setError(null);
    setInfo(null);
    const cookies = parseCookieHeader(cookieText);
    const headers: Record<string, string> = {};
    const token = tokenText.trim();
    if (token) {
      headers["Authorization"] = /^bearer\s+/i.test(token)
        ? token
        : `Bearer ${token}`;
    }
    if (Object.keys(cookies).length === 0 && !token) {
      setError("Hech bo‘lmasa Cookie qatori (JSESSIONID=...) yoki token kiriting.");
      return;
    }
    setBusy(true);
    try {
      const status = await Api.setSession(cookies, headers, "manual");
      if (status.authenticated) {
        setInfo(
          `Import qilindi: ${status.cookie_count} cookie` +
            (status.has_token ? " + token" : "") +
            ". Endi \"Ulanishni tekshirish\"ni bosing."
        );
      } else {
        setError("Import bo‘ldi, lekin sessiya bo‘sh ko‘rinmoqda.");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      onSessionChange();
    }
  };

  const logout = async () => {
    setBusy(true);
    try {
      await Api.clearSession();
    } finally {
      setBusy(false);
      onSessionChange();
    }
  };

  // Parse a full "Copy as cURL" command and extract cookies + auth headers.
  const importFromCurl = async () => {
    setError(null);
    setInfo(null);
    const curl = curlText;
    let cookieStr = "";
    const authHeaders: Record<string, string> = {};
    const allow = ["authorization", "x-api-key", "x-auth-token", "x-csrf-token", "x-xsrf-token"];

    const headerRe = /(?:-H|--header)\s+('([^']*)'|"([^"]*)")/g;
    let m: RegExpExecArray | null;
    while ((m = headerRe.exec(curl))) {
      const h = m[2] ?? m[3] ?? "";
      const idx = h.indexOf(":");
      if (idx > 0) {
        const name = h.slice(0, idx).trim();
        const value = h.slice(idx + 1).trim();
        if (name.toLowerCase() === "cookie") cookieStr = value;
        else if (allow.includes(name.toLowerCase())) authHeaders[name] = value;
      }
    }
    const cookieFlag = /(?:-b|--cookie)\s+('([^']*)'|"([^"]*)")/.exec(curl);
    if (cookieFlag) cookieStr = cookieFlag[2] ?? cookieFlag[3] ?? cookieStr;

    const cookies = parseCookieHeader(cookieStr);
    if (Object.keys(cookies).length === 0 && Object.keys(authHeaders).length === 0) {
      setError("cURL ichidan Cookie yoki Authorization topilmadi. To‘liq buyruqni qo‘ying.");
      return;
    }
    // Reflect what was extracted in the fields, then import.
    setCookieText(cookieStr);
    if (authHeaders["Authorization"]) setTokenText(authHeaders["Authorization"]);
    setBusy(true);
    try {
      const status = await Api.setSession(cookies, authHeaders, "curl");
      setInfo(
        `cURL'dan import: ${status.cookie_count} cookie` +
          (status.has_token ? " + token" : "") +
          `. Headerlar: ${Object.keys(authHeaders).join(", ") || "—"}.`
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      onSessionChange();
    }
  };

  const runProbe = async () => {
    setProbing(true);
    setProbe(null);
    try {
      setProbe(await Api.probe());
    } catch (e) {
      setProbe({ ok: false, error: String(e) });
    } finally {
      setProbing(false);
    }
  };

  const probeStatus = probe ? Number(probe.status) : null;
  const needsToken = probeStatus === 401 || probeStatus === 403;

  return (
    <section className="login-panel">
      <div className="login-head">
        <h3>1. Tizimga kirish / sessiya</h3>
        {authed && (
          <button className="link-btn" onClick={logout} disabled={busy}>
            Chiqish
          </button>
        )}
      </div>

      {authed && <p className="hint ok-text">{session?.message}</p>}

      <div className="manual-body">
        <p className="hint">
          Brauzerda <strong>mulk.kadastr.uz</strong> ochiq va login qilingan
          holda: <strong>F12 → Network</strong> → ma’lumot qaytaradigan (status
          200) WFS so‘rovini toping → unга <strong>o‘ng tugma → Copy → Copy as
          cURL</strong> → quyiga joylashtiring:
        </p>
        <label className="field-label">cURL buyrug‘i (eng oson usul)</label>
        <textarea
          className="manual-text"
          rows={3}
          spellCheck={false}
          placeholder="curl 'https://mulk.kadastr.uz/gis/wfs?...' -H 'Cookie: ...' -H 'Authorization: Bearer ...'"
          value={curlText}
          onChange={(e) => setCurlText(e.target.value)}
        />
        <div className="manual-actions">
          <button className="btn primary small" onClick={importFromCurl} disabled={busy}>
            {busy ? "Import qilinmoqda..." : "cURL'dan import qilish"}
          </button>
          <button
            className="btn secondary small"
            onClick={runProbe}
            disabled={probing}
          >
            {probing ? "Tekshirilmoqda..." : "Ulanishni tekshirish"}
          </button>
        </div>

        <hr className="manual-sep" />
        <p className="hint">Yoki qo‘lda kiriting:</p>

        <label className="field-label">Cookie qatori (JSESSIONID=...)</label>
        <textarea
          className="manual-text"
          rows={2}
          spellCheck={false}
          placeholder="JSESSIONID=90FF5C461EFF7C43CD03CB2F8D81131A"
          value={cookieText}
          onChange={(e) => setCookieText(e.target.value)}
        />

        <label className="field-label">Authorization token (ixtiyoriy)</label>
        <input
          className="url-input"
          spellCheck={false}
          placeholder="Bearer eyJhbGciOi... (yoki tokenning o‘zi)"
          value={tokenText}
          onChange={(e) => setTokenText(e.target.value)}
        />

        <div className="manual-actions">
          <button className="btn secondary small" onClick={importSession} disabled={busy}>
            {busy ? "Import qilinmoqda..." : "Qo‘lda import qilish"}
          </button>
        </div>
      </div>

      {probe && (
        <div className={`alert ${probe.ok ? "success" : "error"} error-small`}>
          <div>
            <strong>Status:</strong> {String(probe.status ?? probe.error ?? "—")}
            {probe.feature_count !== undefined && (
              <>
                {" · "}
                <strong>features:</strong> {String(probe.feature_count)}
              </>
            )}
          </div>
          {Array.isArray(probe.property_keys) && (
            <div>
              <strong>Atributlar:</strong>{" "}
              {(probe.property_keys as string[]).join(", ")}
            </div>
          )}
          {needsToken && (
            <div className="warn-text">
              HTTP {probeStatus}: faqat JSESSIONID yetarli emas. DevTools’dan WFS
              so‘rovining <code>Authorization: Bearer ...</code> tokenini topib,
              yuqoridagi token maydoniga qo‘ying va qayta import qiling.
            </div>
          )}
          {probe.snippet !== undefined && (
            <pre className="probe-snippet">{String(probe.snippet)}</pre>
          )}
        </div>
      )}

      {info && <div className="alert info">{info}</div>}
      {error && <div className="alert error">{error}</div>}
    </section>
  );
}
