export {};

declare global {
  interface Window {
    uzkad?: {
      getBackendUrl: () => Promise<string>;
      openExternal: (url: string) => Promise<void>;
      openPath: (target: string) => Promise<string>;
      openLogin: (loginUrl: string) => Promise<void>;
      importSession: () => Promise<unknown>;
      logoutSession: () => Promise<unknown>;
    };
  }
}
