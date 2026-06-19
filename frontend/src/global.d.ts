export {};

declare global {
  interface Window {
    uzkad?: {
      getBackendUrl: () => Promise<string>;
      openExternal: (url: string) => Promise<void>;
    };
  }
}
