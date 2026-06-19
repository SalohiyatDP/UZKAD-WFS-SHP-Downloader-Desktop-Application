import { useState } from "react";
import { Api } from "../api";
import type { SessionStatus } from "../types";

interface Props {
  session: SessionStatus | null;
  onSessionChange: () => void;
}

/**
 * Guided login flow:
 *   1) Open the sap.kadastr.uz portal login window (OneID / ERI)
 *   2) Sign in and open the map section
 *   3) Import the session (cookies + auth token) into the app
 *
 * Steps 1 & 3 require the Electron bridge; in a plain browser they are no-ops
 * with an explanatory message.
 */
export function LoginPanel({ session, onSessionChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const electron = typeof window !== "undefined" && !!window.uzkad?.openLogin;
  const authed = session?.authenticated ?? false;

  const openLogin = async () => {
    setError(null);
    setInfo(null);
    try {
      const { url } = await Api.loginUrl();
      if (window.uzkad?.openLogin) {
        await window.uzkad.openLogin(url);
        setInfo(
          "Login oynasi ochildi. OneID / ERI bilan kiring va xarita bo‘limini oching, " +
            "so‘ng \"Sessiyani import qilish\" tugmasini bosing."
        );
      } else if (window.uzkad?.openExternal) {
        await window.uzkad.openExternal(url);
      } else {
        window.open(url, "_blank");
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
            "Sessiya topilmadi. Avval login oynasida tizimga kirib, xaritani oching."
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
        <h3>1. Tizimga kirish</h3>
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
              <span className="step-no">1</span> Portalga kiring (OneID / ERI)
              <button className="btn primary small" onClick={openLogin}>
                Tizimga kirish (sap.kadastr.uz)
              </button>
            </li>
            <li>
              <span className="step-no">2</span> Login qiling va{" "}
              <strong>xarita</strong> bo‘limini oching
            </li>
            <li>
              <span className="step-no">3</span> Sessiyani ilovaga oling
              <button
                className="btn secondary small"
                onClick={importSession}
                disabled={busy}
              >
                {busy ? "Import qilinmoqda..." : "Sessiyani import qilish"}
              </button>
            </li>
          </ol>
          {!electron && (
            <p className="hint warn-text">
              Eslatma: ushbu bosqich faqat desktop (Electron) ilovasida to‘liq
              ishlaydi.
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
