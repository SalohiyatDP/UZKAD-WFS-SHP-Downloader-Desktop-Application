import { useEffect, useState } from "react";
import { Api } from "../api";
import type { SessionStatus } from "../types";

interface Props {
  session: SessionStatus | null;
  onSessionChange: () => void;
}

/**
 * Session setup flow. The user is already signed in to the cadastre portal in
 * another (normal browser) window; here they:
 *   1) paste/confirm a ready portal link (e.g. a mulk.kadastr.uz transaction
 *      details URL) and open it in the app's portal window,
 *   2) once the page loads with their session, import it (cookies + token).
 *
 * If the user is signed in to mulk.kadastr.uz in a desktop browser, the app can
 * also auto-detect that session — just press "Sessiyani import qilish".
 *
 * The portal window + import require the Electron bridge; in a plain browser
 * they degrade gracefully with an explanatory message.
 */
export function LoginPanel({ session, onSessionChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const electron = typeof window !== "undefined" && !!window.uzkad?.openLogin;
  const authed = session?.authenticated ?? false;

  // Default the URL field to the backend-configured portal URL.
  useEffect(() => {
    Api.loginUrl()
      .then(({ url: u }) => setUrl((prev) => prev || u))
      .catch(() => setUrl((prev) => prev || "https://mulk.kadastr.uz/index.jsp"));
  }, []);

  const openPortal = async () => {
    setError(null);
    setInfo(null);
    const target = url.trim() || "https://mulk.kadastr.uz/index.jsp";
    try {
      if (window.uzkad?.openLogin) {
        await window.uzkad.openLogin(target);
        setInfo(
          "Portal oynasi ochildi. Agar so‘ralsa OneID / ERI bilan kiring " +
            "(boshqa oynada kirilgan bo‘lsa ham), sahifa to‘liq yuklanganidan " +
            "so‘ng \"Sessiyani import qilish\" tugmasini bosing."
        );
      } else if (window.uzkad?.openExternal) {
        await window.uzkad.openExternal(target);
      } else {
        window.open(target, "_blank");
      }
    } catch (e) {
      setError(String(e));
    }
  };

  const importSession = async () => {
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      if (window.uzkad?.importSession) {
        const status = (await window.uzkad.importSession()) as SessionStatus;
        if (status?.authenticated) {
          setInfo("Sessiya muvaffaqiyatli import qilindi.");
        } else {
          setError(
            "Sessiya topilmadi. Portal oynasida sahifa login qilingan holda " +
              "ochilganiga ishonch hosil qiling."
          );
        }
      } else {
        setError("Bu funksiya faqat desktop (Electron) ilovasida ishlaydi.");
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
      if (window.uzkad?.logoutSession) await window.uzkad.logoutSession();
      else await Api.clearSession();
    } finally {
      setBusy(false);
      onSessionChange();
    }
  };

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

      {!authed ? (
        <>
          <ol className="login-steps">
            <li>
              <span className="step-no">1</span>
              <div className="step-body">
                <span>Tayyor portal havolasini kiriting va oching:</span>
                <div className="url-row">
                  <input
                    type="text"
                    className="url-input"
                    value={url}
                    spellCheck={false}
                    placeholder="https://mulk.kadastr.uz/index.jsp#portal/details/transaction/..."
                    onChange={(e) => setUrl(e.target.value)}
                  />
                  <button className="btn primary small" onClick={openPortal}>
                    Portalni ochish
                  </button>
                </div>
              </div>
            </li>
            <li>
              <span className="step-no">2</span> Sahifa login qilingan holda
              yuklangach, sessiyani ilovaga oling
              <button
                className="btn secondary small"
                onClick={importSession}
                disabled={busy}
              >
                {busy ? "Import qilinmoqda..." : "Sessiyani import qilish"}
              </button>
            </li>
          </ol>
          <p className="hint">
            Agar <strong>mulk.kadastr.uz</strong> ga oddiy brauzerda kirgan
            bo‘lsangiz, ilova sessiyani avtomatik aniqlashga ham harakat qiladi —
            shunchaki “Sessiyani import qilish”ni bosing.
          </p>
          {!electron && (
            <p className="hint warn-text">
              Eslatma: portal oynasi va import faqat desktop (Electron) ilovasida
              to‘liq ishlaydi.
            </p>
          )}
        </>
      ) : (
        <p className="hint ok-text">{session?.message}</p>
      )}

      {info && <div className="alert info">{info}</div>}
      {error && <div className="alert error">{error}</div>}
    </section>
  );
}
