import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import App from './App'
import { ThemeProvider } from './context/ThemeContext'

// ── Self-hosted assets ───────────────────────────────────────
//
// These three groups of imports used to be <link> tags in index.html pointing
// at fonts.googleapis.com and unpkg.com. Every page load therefore contacted
// two third parties before rendering, which contradicts the "100% Air-gapped"
// claim on the login page and stalls first paint on a host with no egress.
// The rationale is written out in index.html; this is the replacement half.
//
// Weights are imported individually and match exactly what the old CDN URL
// asked for: Inter 300/400/500/600/700 and JetBrains Mono 400/500. Importing
// the packages wholesale would ship every weight and both italics - roughly
// 4x the font payload for faces nothing on screen uses.
import '@fontsource/inter/300.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'

// Leaflet's stylesheet, from the `leaflet` package that was already a
// dependency. Only GeoMapPage used Leaflet and that route is now retired
// (see constants/hiddenRoutes.js), so this import is only kept because the
// package is still a declared dependency and a re-enable should not require
// re-deriving the correct import path. It costs one stylesheet, it contacts
// nobody, and dropping it means a future re-enable renders an unstyled map
// with no error - which is a worse failure than a kilobyte of CSS.
import 'leaflet/dist/leaflet.css'

import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <ThemeProvider>
      <App />
      <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: '#1e2035',
          color: '#e2e8f0',
          border: '1px solid #2d3154'
        }
      }}
    />
    </ThemeProvider>
  </BrowserRouter>
)
