import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { InfiniteGrid } from './components/ui/the-infinite-grid';
import { GlassFilter } from './components/ui/liquid-glass-button';
import './styles.css';

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('Root element was not found.');
}

createRoot(rootElement).render(
  <StrictMode>
    <InfiniteGrid>
      <GlassFilter />
      <App />
    </InfiniteGrid>
  </StrictMode>,
);
