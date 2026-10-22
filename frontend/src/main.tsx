import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/app.css';
import { App } from './App';
import { appStore } from './store/store';
import { startSession } from './api/session';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

startSession(appStore).catch((e: unknown) => {
  appStore.getState().setDatasetError(`Start-up failed: ${(e as Error).message}`);
});

// test / debugging hook (read-only use in Playwright)
(window as unknown as { __t2s?: unknown }).__t2s = { store: appStore };
